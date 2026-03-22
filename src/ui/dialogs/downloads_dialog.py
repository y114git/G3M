"""Non-modal Downloads dialog showing download history with per-item actions."""

import logging
import os

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models.download_models import DownloadRecord, SourceKind, TargetKind
from services.localization_service import tr
from ui.common.dialog_theme import (
    build_dialog_theme_stylesheet,
    get_dialog_text_color,
    get_dialog_theme_values,
)
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)


class _RecordWidget(QFrame):
    _BUTTON_KEYS = [
        ("install", "downloads.action_install"),
        ("reinstall", "downloads.action_reinstall"),
        ("delete", "downloads.action_delete"),
        ("cancel", "downloads.action_cancel"),
        ("retry", "downloads.action_retry"),
        ("overwrite", "downloads.action_overwrite"),
        ("cancel_install", "downloads.action_cancel_install"),
        ("continue_setup", "downloads.action_continue_setup"),
    ]

    def __init__(self, record: DownloadRecord, manager, app_state, parent=None) -> None:
        super().__init__(parent)
        self._record = record
        self._manager = manager
        self._app_state = app_state
        self.setObjectName("downloads_record")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self._name_label = QLabel()
        self._name_label.setObjectName("downloads_record_name")
        self._name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        top.addWidget(self._name_label)
        self._status_label = QLabel()
        self._status_label.setObjectName("downloads_record_status")
        top.addWidget(self._status_label)
        layout.addLayout(top)
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setRange(0, 100)
        layout.addWidget(self._progress_bar)
        self._error_label = QLabel()
        self._error_label.setObjectName("downloads_record_error")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)
        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(6)
        self._btn_row.addStretch()
        self._buttons: dict[str, QPushButton] = {}
        for key, tr_key in self._BUTTON_KEYS:
            btn = QPushButton(tr(tr_key))
            btn.setObjectName(f"downloads_btn_{key}")
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._btn_row.addWidget(btn)
            self._buttons[key] = btn
        layout.addLayout(self._btn_row)
        self._buttons["install"].clicked.connect(
            lambda: self._manager.action_install(self._record.id)
        )
        self._buttons["reinstall"].clicked.connect(
            lambda: self._manager.action_install(self._record.id)
        )
        self._buttons["delete"].clicked.connect(self._on_delete)
        self._buttons["cancel"].clicked.connect(
            lambda: self._manager.action_cancel_download(self._record.id)
        )
        self._buttons["retry"].clicked.connect(
            lambda: self._manager.action_retry(self._record.id)
        )
        self._buttons["overwrite"].clicked.connect(
            lambda: self._manager.action_overwrite(self._record.id)
        )
        self._buttons["cancel_install"].clicked.connect(
            lambda: self._manager.action_cancel_install(self._record.id)
        )
        self._buttons["continue_setup"].clicked.connect(
            lambda: self._manager.action_continue_setup(
                self._record.id, parent_widget=self.window()
            )
        )

    def _refresh(self):
        """Update labels and button visibility from current record state."""
        r = self._record
        self._name_label.setText(r.display_name or r.id)
        status_key = r.effective_status_key
        status_tr_map = {
            "downloading": tr("downloads.status_downloading", progress=r.progress),
            "installing": tr("downloads.status_installing"),
            "overwrite_pending": tr("downloads.status_overwrite_pending"),
            "needs_manual": tr("downloads.status_needs_manual"),
            "ready": tr("downloads.status_ready"),
            "installed": tr("downloads.status_installed"),
            "cancelled": tr("downloads.status_cancelled"),
            "failed": tr("downloads.status_failed"),
        }
        self._status_label.setText(status_tr_map.get(status_key, status_key))
        self._progress_bar.setVisible(status_key == "downloading")
        self._progress_bar.setValue(r.progress)
        if r.error_message and status_key == "failed":
            self._error_label.setText(r.error_message)
            self._error_label.setVisible(True)
        else:
            self._error_label.setVisible(False)
        visible_map = {
            "downloading": ("cancel",),
            "installing": (),
            "overwrite_pending": ("overwrite", "cancel_install"),
            "needs_manual": ("continue_setup", "delete"),
            "ready": ("install", "delete"),
            "installed": ("reinstall", "delete"),
            "cancelled": ("retry", "delete"),
            "failed": ("retry", "delete"),
        }
        visible = set(visible_map.get(status_key, ()))
        for key, btn in self._buttons.items():
            btn.setVisible(key in visible)

    def _on_delete(self):
        reply = QMessageBox.question(
            self.window(),
            tr("downloads.confirm_delete_title"),
            tr("downloads.confirm_delete_text", name=self._record.display_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._manager.action_delete(self._record.id)

    def update_record(self, record: DownloadRecord):
        self._record = record
        self._refresh()

    def relocalize_ui(self):
        for key, tr_key in self._BUTTON_KEYS:
            self._buttons[key].setText(tr(tr_key))
        self._refresh()


class DownloadsDialog(QDialog):
    """Non-modal dialog listing all download records with actions."""

    def __init__(self, manager, app_state, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._app_state = app_state
        self._record_widgets: dict[str, _RecordWidget] = {}
        self.setWindowTitle(tr("downloads.title"))
        self.setMinimumSize(520, 400)
        self.resize(560, 480)
        self.setModal(False)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_theme()
        self._populate()
        self._connect_signals()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(8)
        header = QHBoxLayout()
        self._title_label = QLabel(tr("downloads.title"))
        self._title_label.setObjectName("downloads_title")
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        tc = get_dialog_text_color(self._app_state)
        self._folder_btn = QPushButton()
        self._folder_btn.setObjectName("downloads_folder_btn")
        self._folder_btn.setToolTip(tr("downloads.open_folder"))
        self._folder_btn.setIcon(colored_icon("folder", tc))
        self._folder_btn.setIconSize(QSize(16, 16))
        self._folder_btn.clicked.connect(self._on_open_folder)
        header.addWidget(self._folder_btn)
        self._clear_btn = QPushButton(tr("downloads.clear_downloads"))
        self._clear_btn.setObjectName("downloads_clear_btn")
        self._clear_btn.clicked.connect(self._on_clear)
        header.addWidget(self._clear_btn)
        self._close_btn = QPushButton(tr("common.close"))
        self._close_btn.setObjectName("downloads_close_btn")
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        main.addWidget(self._scroll)
        self._empty_label = QLabel(tr("downloads.empty_list"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("downloads_empty")
        main.addWidget(self._empty_label)

    def _apply_theme(self):
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        extra = f"""
            QFrame#downloads_record {{
                background-color: {theme["button"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
            }}
            QLabel#downloads_record_name {{
                font-weight: bold;
                font-size: 13px;
            }}
            QLabel#downloads_record_status {{
                font-size: 12px;
                color: {theme["secondary_text"]};
            }}
            QLabel#downloads_record_error {{
                font-size: 11px;
                color: #e05555;
            }}
            QLabel#downloads_title {{
                font-size: 16px;
            }}
            QLabel#downloads_empty {{
                font-size: 13px;
                color: {theme["secondary_text"]};
            }}
            QProgressBar {{
                background-color: {theme["background"]};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {theme["border"]};
                border-radius: 3px;
            }}
        """
        self.setStyleSheet(base + extra)

    def _connect_signals(self):
        self._manager.record_added.connect(self._on_record_added)
        self._manager.record_updated.connect(self._on_record_updated)
        self._manager.record_removed.connect(self._on_record_removed)

    def closeEvent(self, event):
        self._manager.record_added.disconnect(self._on_record_added)
        self._manager.record_updated.disconnect(self._on_record_updated)
        self._manager.record_removed.disconnect(self._on_record_removed)
        super().closeEvent(event)

    def _populate(self):
        for record in self._manager.records:
            self._add_record_widget(record)
        self._update_empty_visibility()

    def _add_record_widget(self, record: DownloadRecord):
        w = _RecordWidget(record, self._manager, self._app_state)
        self._record_widgets[record.id] = w
        idx = max(0, self._list_layout.count() - 1)
        self._list_layout.insertWidget(idx, w)

    def _on_record_added(self, record: DownloadRecord):
        if record.id not in self._record_widgets:
            self._add_record_widget(record)
        self._update_empty_visibility()

    def _on_record_updated(self, record: DownloadRecord):
        w = self._record_widgets.get(record.id)
        if w:
            w.update_record(record)

    def _on_record_removed(self, record_id: str):
        w = self._record_widgets.pop(record_id, None)
        if w:
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._update_empty_visibility()

    def _on_open_folder(self):
        downloads_dir = self._manager.store.downloads_dir
        if os.path.isdir(downloads_dir) and not QDesktopServices.openUrl(
            QUrl.fromLocalFile(downloads_dir)
        ):
            logger.warning(f"Failed to open downloads folder: {downloads_dir}")

    def _on_clear(self):
        self._manager.clear_downloads()

    def _update_empty_visibility(self):
        has_items = bool(self._record_widgets)
        self._scroll.setVisible(has_items)
        self._empty_label.setVisible(not has_items)

    def relocalize_ui(self):
        """Update all translatable texts when language changes."""
        self.setWindowTitle(tr("downloads.title"))
        self._title_label.setText(tr("downloads.title"))
        tc = get_dialog_text_color(self._app_state)
        self._folder_btn.setIcon(colored_icon("folder", tc))
        self._folder_btn.setToolTip(tr("downloads.open_folder"))
        self._clear_btn.setText(tr("downloads.clear_downloads"))
        self._close_btn.setText(tr("common.close"))
        self._empty_label.setText(tr("downloads.empty_list"))
        for w in self._record_widgets.values():
            w.relocalize_ui()

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        md = event.mimeData()
        accepted = False
        if md.hasUrls():
            for u in md.urls():
                path = u.toLocalFile()
                if path and os.path.isfile(path):
                    if not accepted:
                        event.acceptProposedAction()
                        accepted = True
                    name = os.path.basename(path)
                    self._manager.enqueue(
                        display_name=name,
                        source_kind=SourceKind.LOCAL_FILE,
                        target_kind=TargetKind.MOD,
                        source_file_path=path,
                    )
                else:
                    s = u.toString()
                    if s.startswith(("http://", "https://")):
                        if not accepted:
                            event.acceptProposedAction()
                            accepted = True
                        name = os.path.basename(s.split("?")[0]) or tr(
                            "downloads.external_download"
                        )
                        self._manager.enqueue(
                            display_name=name,
                            source_kind=SourceKind.EXTERNAL_URL,
                            target_kind=TargetKind.MOD,
                            source_url=s,
                        )
        if md.hasText():
            text = md.text().strip()
            if text.startswith(("http://", "https://")):
                event.acceptProposedAction()
                name = os.path.basename(text.split("?")[0]) or tr(
                    "downloads.external_download"
                )
                self._manager.enqueue(
                    display_name=name,
                    source_kind=SourceKind.EXTERNAL_URL,
                    target_kind=TargetKind.MOD,
                    source_url=text,
                )

    def refresh_theme(self):
        self._apply_theme()
        self._folder_btn.setIcon(
            colored_icon("folder", get_dialog_text_color(self._app_state))
        )
