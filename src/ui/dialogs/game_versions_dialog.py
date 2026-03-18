"""Non-modal Game Versions dialog with per-game filtering."""
import logging
import os
from typing import Dict

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QScrollArea, QWidget, QFrame, QComboBox, QSizePolicy, QMessageBox,
)

from config.constants import LIBRARY_GAME_OPTIONS
from models.game_version_models import GameVersionRecord
from services.localization_service import tr
from ui.common.dialog_theme import build_dialog_theme_stylesheet, get_dialog_theme_values, get_dialog_text_color
from ui.utils.ui_utils import format_size
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)


class _VersionRecordWidget(QFrame):
    """Single version item with progress bar and cancel support."""

    def __init__(self, record: GameVersionRecord, manager, app_state, parent=None):
        super().__init__(parent)
        self._record = record
        self._manager = manager
        self._app_state = app_state
        self.setObjectName('game_versions_record')
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
        self._name_label.setObjectName('game_versions_record_name')
        self._name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(self._name_label)
        self._status_label = QLabel()
        self._status_label.setObjectName('game_versions_record_status')
        top.addWidget(self._status_label)
        layout.addLayout(top)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._info_label = QLabel()
        self._info_label.setObjectName('game_versions_record_info')
        layout.addWidget(self._info_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch()
        tc = get_dialog_text_color(self._app_state)
        self._cancel_btn = QPushButton(tr('game_versions.action_cancel'))
        self._cancel_btn.setObjectName('game_versions_btn_cancel')
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setVisible(False)
        btn_row.addWidget(self._cancel_btn)
        self._export_btn = QPushButton()
        self._export_btn.setObjectName('game_versions_btn_export')
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setIcon(colored_icon('export', tc))
        self._export_btn.setIconSize(QSize(20, 20))
        self._export_btn.setContentsMargins(0, 0, 0, 0)
        self._export_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self._export_btn)
        self._apply_btn = QPushButton(tr('game_versions.action_apply'))
        self._apply_btn.setObjectName('game_versions_btn_apply')
        self._apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self._apply_btn)
        self._delete_btn = QPushButton(tr('game_versions.action_delete'))
        self._delete_btn.setObjectName('game_versions_btn_delete')
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)
        layout.addLayout(btn_row)

    def _refresh(self):
        r = self._record
        busy = self._manager.is_busy(r.archive_path)
        applying = busy and self._manager.is_applying(r.archive_path)
        self._name_label.setText(r.display_name or '—')
        if applying:
            self._status_label.setText(tr('game_versions.status_applying'))
        elif busy:
            self._status_label.setText(tr('game_versions.status_busy'))
        elif r.archive_exists:
            self._status_label.setText(tr('game_versions.status_ready'))
        else:
            self._status_label.setText(tr('game_versions.status_missing'))
        parts = []
        if r.created_at:
            parts.append(r.created_at[:10])
        if r.size_bytes:
            parts.append(format_size(r.size_bytes))
        if r.file_count:
            parts.append(tr('game_versions.file_count', count=r.file_count))
        self._info_label.setText(' · '.join(parts))
        self._info_label.setVisible(not busy)
        self._progress_bar.setVisible(busy)
        self._cancel_btn.setVisible(busy and not applying)
        self._apply_btn.setVisible(not busy and r.archive_exists)
        self._export_btn.setVisible(not busy and r.archive_exists)
        self._delete_btn.setVisible(not busy)

    def set_progress(self, value: int):
        self._progress_bar.setValue(value)

    def _on_cancel(self):
        self._manager.cancel_operation(self._record.archive_path)

    def _on_apply(self):
        reply = QMessageBox.question(
            self.window(), tr('game_versions.confirm_apply_title'),
            tr('game_versions.confirm_apply_text', name=self._record.display_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._manager.apply_version(self._record.archive_path)
            self._refresh()

    def _on_export(self):
        self._manager.export_game_version(self._record.archive_path, parent_widget=self.window())
        self._refresh()

    def _on_delete(self):
        reply = QMessageBox.question(
            self.window(), tr('game_versions.confirm_delete_title'),
            tr('game_versions.confirm_delete_text', name=self._record.display_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._manager.delete_version(self._record.archive_path)

    def update_record(self, record: GameVersionRecord):
        self._record = record
        self._refresh()

    def relocalize_ui(self):
        self._apply_btn.setText(tr('game_versions.action_apply'))
        self._export_btn.setIcon(colored_icon('export', get_dialog_text_color(self._app_state)))
        self._delete_btn.setText(tr('game_versions.action_delete'))
        self._cancel_btn.setText(tr('game_versions.action_cancel'))
        self._refresh()

    def refresh_theme(self):
        self._export_btn.setIcon(colored_icon('export', get_dialog_text_color(self._app_state)))


class GameVersionsDialog(QDialog):
    """Non-modal Game Versions dialog with per-game filtering."""

    def __init__(self, manager, app_state, initial_game: str = 'deltarune', parent=None):
        super().__init__(parent)
        self._manager = manager
        self._app_state = app_state
        self._record_widgets: Dict[str, _VersionRecordWidget] = {}
        self.setWindowTitle(tr('game_versions.title'))
        self.setMinimumSize(540, 420)
        self.resize(580, 500)
        self.setModal(False)
        self.setAcceptDrops(True)
        self._build_ui(initial_game)
        self._apply_theme()
        self._populate()
        self._connect_signals()

    def _build_ui(self, initial_game: str):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(4)

        header = QHBoxLayout()
        self._title_label = QLabel(tr('game_versions.title'))
        self._title_label.setObjectName('game_versions_title')
        font = self._title_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self._title_label.setFont(font)
        header.addWidget(self._title_label)
        header.addStretch()
        self._close_btn = QPushButton(tr('common.close'))
        self._close_btn.setObjectName('game_versions_close_btn')
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        main.addLayout(header)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 5, 0, 5)
        tc = get_dialog_text_color(self._app_state)
        self._add_btn = QPushButton()
        self._add_btn.setObjectName('game_versions_add_btn')
        self._add_btn.setToolTip(tr('game_versions.add_tooltip'))
        self._add_btn.setIcon(colored_icon('add', tc))
        self._add_btn.setIconSize(QSize(20, 20))
        self._add_btn.setContentsMargins(0, 0, 0, 0)
        self._add_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._game_combo = QComboBox()
        for name, data in LIBRARY_GAME_OPTIONS:
            self._game_combo.addItem(tr(f'ui.{name}') if isinstance(name, str) and not name.isupper() else name, data)
        idx = self._game_combo.findData(initial_game)
        self._game_combo.setCurrentIndex(max(idx, 0))
        self._game_combo.currentIndexChanged.connect(self._on_game_changed)
        combo_h = self._game_combo.sizeHint().height()
        self._add_btn.setFixedSize(combo_h, combo_h)
        actions.addStretch()
        actions.addWidget(self._add_btn)
        actions.addSpacing(20)
        actions.addWidget(self._game_combo)
        actions.addStretch()
        main.addLayout(actions)

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

        self._empty_label = QLabel(tr('game_versions.empty_list'))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName('game_versions_empty')
        main.addWidget(self._empty_label)

    def _apply_theme(self):
        base = build_dialog_theme_stylesheet(self._app_state)
        theme = get_dialog_theme_values(self._app_state)
        extra = f'''
            QFrame#game_versions_record {{
                background-color: {theme["button"]};
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
            }}
            QLabel#game_versions_record_name {{
                font-weight: bold;
                font-size: 13px;
            }}
            QLabel#game_versions_record_status {{
                font-size: 12px;
                color: {theme["secondary_text"]};
            }}
            QLabel#game_versions_record_info {{
                font-size: 11px;
                color: {theme["secondary_text"]};
            }}
            QLabel#game_versions_title {{
                font-size: 16px;
            }}
            QPushButton#game_versions_add_btn {{
                border: 2px solid {theme["border"]};
                border-radius: {theme["button_radius"]}px;
                background-color: {theme["button"]};
                margin: 0px;
                padding: 0px;
            }}
            QPushButton#game_versions_add_btn:hover {{
                background-color: {theme["button_hover"]};
            }}
            QLabel#game_versions_empty {{
                font-size: 13px;
                color: {theme["secondary_text"]};
            }}
            QProgressBar {{
                background-color: {theme["background"]};
                border: 2px solid {theme["border"]};
                border-radius: 4px;
                text-align: center;
                font-size: 10px;
                color: {theme["text"]};
            }}
            QProgressBar::chunk {{
                background-color: {theme["secondary_text"]};
                border-radius: 3px;
            }}
        '''
        self.setStyleSheet(base + extra)

    def _connect_signals(self):
        self._manager.record_added.connect(self._on_record_added)
        self._manager.record_removed.connect(self._on_record_removed)
        self._manager.record_updated.connect(self._on_record_updated)
        self._manager.progress_updated.connect(self._on_progress)
        self._manager.operation_error.connect(self._on_error)

    def closeEvent(self, event):
        self.hide()
        super().closeEvent(event)

    def _current_game(self) -> str:
        return self._game_combo.currentData() or 'deltarune'

    def _populate(self):
        self._clear_list()
        for record in self._manager.records_for_game(self._current_game()):
            self._add_record_widget(record)
        self._update_empty_visibility()

    def _clear_list(self):
        for w in self._record_widgets.values():
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._record_widgets.clear()

    def _add_record_widget(self, record: GameVersionRecord):
        w = _VersionRecordWidget(record, self._manager, self._app_state)
        self._record_widgets[record.archive_path] = w
        idx = max(0, self._list_layout.count() - 1)
        self._list_layout.insertWidget(idx, w)

    def _on_record_added(self, record: GameVersionRecord):
        if record.game == self._current_game() and record.archive_path not in self._record_widgets:
            self._add_record_widget(record)
        self._update_empty_visibility()

    def _on_record_removed(self, archive_path: str):
        w = self._record_widgets.pop(archive_path, None)
        if w:
            self._list_layout.removeWidget(w)
            w.deleteLater()
        self._update_empty_visibility()

    def _on_record_updated(self, record: GameVersionRecord):
        w = self._record_widgets.get(record.archive_path)
        if w:
            w.update_record(record)

    def _on_progress(self, archive_path: str, value: int):
        w = self._record_widgets.get(archive_path)
        if w:
            w.set_progress(value)

    def _on_error(self, msg: str):
        QMessageBox.warning(self, tr('errors.error'), msg)

    def _on_game_changed(self):
        self._populate()

    def _on_add_clicked(self):
        game = self._current_game()
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('game_versions.add_tooltip'))
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        btn_layout = QHBoxLayout()
        create_btn = QPushButton(tr('game_versions.action_create'))

        def on_create():
            dialog.accept()
            self._do_create(game)
        create_btn.clicked.connect(on_create)
        btn_layout.addWidget(create_btn)
        import_btn = QPushButton(tr('game_versions.action_import'))

        def on_import():
            dialog.accept()
            self._do_import(game)
        import_btn.clicked.connect(on_import)
        btn_layout.addWidget(import_btn)
        layout.addLayout(btn_layout)
        dialog.setStyleSheet(build_dialog_theme_stylesheet(self._app_state))
        dialog.exec()

    def _do_create(self, game_id: str):
        from models.game_modes import get_game
        game_def = get_game(game_id)
        game_name = game_def.display_name if game_def else game_id
        from ui.dialogs.create_game_version_dialog import CreateVersionDialog
        dialog = CreateVersionDialog(game_name, self._app_state, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.version_name:
            self._manager.create_version(game_id, dialog.version_name)

    def _do_import(self, game_id: str):
        from ui.dialogs.import_dialog import ImportDialog
        from ui.common.feedback import FeedbackManager
        parent_window = self.parent()
        feedback = getattr(parent_window, 'feedback_service', None)
        if not feedback:
            feedback = FeedbackManager(self)
        dialog = ImportDialog(self, feedback, 'game_versions', '*.zip')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._manager.import_game_version_from_file(game_id, dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._manager.import_game_version_from_url(game_id, dialog.selected_url)

    def _update_empty_visibility(self):
        has_items = bool(self._record_widgets)
        self._scroll.setVisible(has_items)
        self._empty_label.setVisible(not has_items)

    def relocalize_ui(self):
        self.setWindowTitle(tr('game_versions.title'))
        self._title_label.setText(tr('game_versions.title'))
        self._close_btn.setText(tr('common.close'))
        self._empty_label.setText(tr('game_versions.empty_list'))
        self._add_btn.setToolTip(tr('game_versions.add_tooltip'))
        self._add_btn.setIcon(colored_icon('add', get_dialog_text_color(self._app_state)))
        for w in self._record_widgets.values():
            w.relocalize_ui()

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        game = self._current_game()
        md = event.mimeData()
        if md.hasUrls():
            for u in md.urls():
                path = u.toLocalFile()
                if path and os.path.isfile(path):
                    event.acceptProposedAction()
                    self._manager.import_game_version_from_file(game, path)
                    return
                s = u.toString()
                if s.startswith(('http://', 'https://')):
                    event.acceptProposedAction()
                    self._manager.import_game_version_from_url(game, s)
                    return
        if md.hasText():
            text = md.text().strip()
            if text.startswith(('http://', 'https://')):
                event.acceptProposedAction()
                self._manager.import_game_version_from_url(game, text)

    def refresh_theme(self):
        self._apply_theme()
        self._add_btn.setIcon(colored_icon('add', get_dialog_text_color(self._app_state)))
        for w in self._record_widgets.values():
            w.refresh_theme()
