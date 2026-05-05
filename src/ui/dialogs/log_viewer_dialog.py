"""Non-modal live log viewer dialog."""

from __future__ import annotations

import logging
import os
from typing import override

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabBar,
    QVBoxLayout,
)

from services.localization_service import tr
from services.log_viewer_service import LogSnapshotState, LogViewerService
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_text_color,
    get_dialog_theme_values,
)
from ui.widgets.shared.custom_controls import NoScrollComboBox
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)

_TAB_KEYS = ("g3m", "patching", "conflicts")
_MONOSPACE_FONT_SIZE_PX = 12
_DEFAULT_MONOSPACE = "'Consolas', 'Monaco', 'Courier New', monospace"


def _get_app_font(app_state) -> str:
    """Return the current G3M font family."""
    ff = (app_state.local_config.get("custom_font_family") or "").strip()
    if not ff:
        parent = getattr(app_state, "_app_window", None)
        ff = (getattr(parent, "custom_font_family", None) or "").strip() if parent else ""
    return f"'{ff}', {_DEFAULT_MONOSPACE}" if ff else _DEFAULT_MONOSPACE


class LogViewerDialog(QDialog):
    """Window for viewing current application logs in real time."""

    def __init__(
        self,
        app_state,
        parent=None,
        user_data_root: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._service = LogViewerService(user_data_root=user_data_root)
        self._states: dict[str, LogSnapshotState | None] = dict.fromkeys(_TAB_KEYS)
        self._history_cache = {key: [] for key in _TAB_KEYS}
        self._paths: dict[str, str | None] = dict.fromkeys(_TAB_KEYS)
        self._selected_tokens: dict[str, str] = dict.fromkeys(_TAB_KEYS, "live")
        self._empty_keys: dict[str, str] = {
            "g3m": "log_viewer.empty.g3m",
            "patching": "log_viewer.empty.patching",
            "conflicts": "log_viewer.empty.conflicts",
        }
        self.setModal(False)
        self.setMinimumSize(760, 520)
        self.resize(980, 680)
        self._build_ui()
        self.relocalize_ui()
        self.refresh_theme()
        self._refresh_active_log(force=True)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._refresh_active_log)

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self._open_folder_button = QPushButton()
        self._open_folder_button.setObjectName("logViewerOpenFolderButton")
        self._open_folder_button.setFixedSize(34, 34)
        self._open_folder_button.clicked.connect(self._open_logs_folder)
        header.addWidget(self._open_folder_button, 0, Qt.AlignmentFlag.AlignLeft)
        header.addStretch(1)

        self._tabs = QTabBar()
        self._tabs.setObjectName("logViewerTabs")
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        for _ in _TAB_KEYS:
            self._tabs.addTab("")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        header.addWidget(self._tabs, 0, Qt.AlignmentFlag.AlignCenter)
        header.addStretch(1)

        self._close_button = QPushButton()
        self._close_button.setObjectName("logViewerCloseButton")
        self._close_button.clicked.connect(self.close)
        header.addWidget(self._close_button, 0, Qt.AlignmentFlag.AlignRight)
        main.addLayout(header)

        combo_row = QHBoxLayout()
        combo_row.setContentsMargins(0, 0, 0, 0)
        combo_row.addStretch(1)
        self._history_combo = NoScrollComboBox()
        self._history_combo.setObjectName("logViewerHistoryCombo")
        self._history_combo.setMinimumWidth(300)
        self._history_combo.setMaximumWidth(380)
        self._history_combo.currentIndexChanged.connect(self._on_history_combo_changed)
        combo_row.addWidget(self._history_combo, 0, Qt.AlignmentFlag.AlignCenter)
        combo_row.addStretch(1)
        main.addLayout(combo_row)

        self._source_label = QLabel()
        self._source_label.setObjectName("logViewerSourceLabel")
        self._source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source_label.setWordWrap(True)
        main.addWidget(self._source_label)

        viewer_frame = QFrame()
        viewer_frame.setObjectName("logViewerFrame")
        viewer_layout = QVBoxLayout(viewer_frame)
        viewer_layout.setContentsMargins(10, 10, 10, 10)
        viewer_layout.setSpacing(0)
        self._viewer = QPlainTextEdit()
        self._viewer.setObjectName("logViewerText")
        self._viewer.setReadOnly(True)
        self._viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._viewer.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        viewer_layout.addWidget(self._viewer)
        main.addWidget(viewer_frame, 1)

    def _current_key(self) -> str:
        index = max(0, self._tabs.currentIndex())
        return _TAB_KEYS[index]

    def _on_tab_changed(self, _index: int) -> None:
        self._refresh_history_combo()
        self._refresh_active_log(force=True)

    def _refresh_active_log(self, force: bool = False) -> None:
        key = self._current_key()
        self._history_cache = self._service.resolve_history()
        if force:
            self._refresh_history_combo()
        path = self._selected_path_for_key(key)
        path_changed = path != self._paths.get(key)
        if path_changed:
            self._states[key] = None
            self._paths[key] = path
        should_update = force or path_changed

        follow_output = self._is_at_bottom()
        scrollbar = self._viewer.verticalScrollBar()
        previous_value = scrollbar.value()

        snapshot = self._service.read_snapshot(path, self._states.get(key))
        self._states[key] = snapshot.state
        display_text = snapshot.full_text if path is not None else tr(self._empty_keys[key])
        if should_update or self._viewer.toPlainText() != display_text:
            self._viewer.setPlainText(display_text)
            if follow_output:
                self._scroll_to_bottom()
            else:
                scrollbar.setValue(min(previous_value, scrollbar.maximum()))

        self._update_source_label(path)

    def _refresh_history_combo(self) -> None:
        key = self._current_key()
        entries = self._history_cache.get(key) or []
        selected_token = self._selected_tokens.get(key, "live")

        self._history_combo.blockSignals(True)
        self._history_combo.clear()
        for entry in entries:
            text = (
                tr("log_viewer.latest_live")
                if entry.is_live
                else self._service.format_archive_label(entry.path)
            )
            self._history_combo.addItem(text, self._entry_token(entry))

        target_index = -1
        for index in range(self._history_combo.count()):
            if self._history_combo.itemData(index) == selected_token:
                target_index = index
                break
        if target_index < 0 and self._history_combo.count() > 0:
            target_index = 0
        if target_index >= 0:
            self._history_combo.setCurrentIndex(target_index)
        self._history_combo.blockSignals(False)

    @staticmethod
    def _entry_token(entry) -> str:
        return "live" if entry.is_live else (entry.path or "")

    def _selected_path_for_key(self, key: str) -> str | None:
        selected_token = self._selected_tokens.get(key, "live")
        for entry in self._history_cache.get(key, []):
            if self._entry_token(entry) == selected_token:
                return entry.path
        if self._history_cache.get(key):
            return self._history_cache[key][0].path
        return None

    def _on_history_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        key = self._current_key()
        self._selected_tokens[key] = self._history_combo.itemData(index) or "live"
        self._refresh_active_log(force=True)

    def _update_source_label(self, path: str | None) -> None:
        source_name = os.path.basename(path) if path else tr("log_viewer.no_source")
        self._source_label.setText(
            tr("log_viewer.current_source", file_name=source_name)
        )

    def _is_at_bottom(self) -> bool:
        scrollbar = self._viewer.verticalScrollBar()
        return scrollbar.value() >= max(0, scrollbar.maximum() - 2)

    def _scroll_to_bottom(self) -> None:
        self._viewer.moveCursor(QTextCursor.MoveOperation.End)
        scrollbar = self._viewer.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _open_logs_folder(self) -> None:
        logs_dir = self._service.logs_dir
        os.makedirs(logs_dir, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir)):
            logger.warning("Failed to open logs folder: %s", logs_dir)

    @override
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.relocalize_ui()
        self.refresh_theme()
        self._refresh_active_log(force=True)
        if hasattr(self, "_poll_timer") and self._poll_timer:
            self._poll_timer.start()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("log_viewer.title"))
        self._close_button.setText(tr("common.close"))
        self._open_folder_button.setToolTip(tr("log_viewer.open_folder"))
        tab_keys = (
            "log_viewer.tabs.g3m",
            "log_viewer.tabs.patching",
            "log_viewer.tabs.conflicts",
        )
        for index, key in enumerate(tab_keys):
            self._tabs.setTabText(index, tr(key))
        self._refresh_history_combo()
        self._update_source_label(self._paths.get(self._current_key()))
        if (not self._viewer.toPlainText()) and (
            self._selected_path_for_key(self._current_key()) is None
        ):
            self._viewer.setPlainText(tr(self._empty_keys[self._current_key()]))

    def refresh_theme(self) -> None:
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        font_family = _get_app_font(self._app_state)
        self._open_folder_button.setIcon(
            colored_icon("folder", get_dialog_text_color(self._app_state))
        )
        self._open_folder_button.setIconSize(QSize(17, 17))
        extra = f"""
            QFrame#logViewerFrame {{
                background-color: {theme["elements"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["field_radius"]}px;
            }}
            QPlainTextEdit#logViewerText {{
                background-color: {theme["background"]};
                border: none;
                color: {theme["main_text"]};
                font-family: {font_family};
                font-size: {_MONOSPACE_FONT_SIZE_PX}px;
                padding: 8px;
                selection-background-color: {theme["hover"]};
            }}
            QLabel#logViewerSourceLabel {{
                color: {theme["secondary_text"]};
                font-size: 12px;
            }}
            QComboBox#logViewerHistoryCombo {{
                min-height: 34px;
                padding-left: 10px;
                padding-right: 28px;
            }}
            QPushButton#logViewerOpenFolderButton {{
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
            }}
        """
        self.setStyleSheet(base + extra)

    def apply_styles(self) -> None:
        self.refresh_theme()

    @override
    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        self._states.clear()
        self._paths.clear()
        super().closeEvent(event)
