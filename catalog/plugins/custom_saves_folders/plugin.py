"""Custom save folders plugin."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from adapters.g3mtool_adapter import G3MToolManager
from models.game_modes import get_all_games, get_game
from services.backup_service import BackupManager
from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values
from ui.common.styling import (
    apply_stylesheet_if_changed,
    build_button_style,
    clamp_border_radius,
    get_border_radius,
    get_card_button_metrics,
    get_theme_color,
    get_theme_colors,
)
from utils.path_utils import (
    colored_icon,
    find_chapter_resource_dir,
    find_supported_game_data_file,
    get_user_data_root,
)

logger = logging.getLogger(__name__)

_SETTINGS_FOLDERS_KEY = "folders_by_game"
_SETTINGS_SELECTED_KEY = "selected_by_game"
_INVALID_NAME_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


@dataclass
class _ActiveSession:
    game_id: str
    work_dir: str
    backup_manager: BackupManager


class _InteractiveRow(QFrame):
    clicked = pyqtSignal()

    def __init__(self, app_state, *, compact: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._compact = compact
        self._hovered = False
        self._selected = False
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_state_style()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._apply_state_style()

    def refresh_theme(self) -> None:
        self._apply_state_style()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._apply_state_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_state_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _apply_state_style(self) -> None:
        colors = get_theme_colors(self._app_state.local_config)
        radius = get_dialog_theme_values(self._app_state)["border_radius"]
        border_color = colors["hover"] if (self._hovered or self._selected) else colors["border"]
        background = colors["elements"]
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {background};
                border: 2px solid {border_color};
                border-radius: {radius}px;
            }}
            QLabel {{
                color: {colors["main_text"]};
                background: transparent;
                border: none;
            }}
            QLabel#customSavesFolderSubtitle {{
                color: {colors["secondary_text"]};
            }}
            """
        )


class _GameRow(_InteractiveRow):
    def __init__(self, app_state, title: str, parent=None) -> None:
        super().__init__(app_state, compact=True, parent=parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self._title = QLabel(title, self)
        self._title.setWordWrap(True)
        self._title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(self._title, 1)
        self.refresh_theme()

    @property
    def title(self) -> str:
        return self._title.text()


class _FolderRow(_InteractiveRow):
    use_requested = pyqtSignal()
    unuse_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, app_state, title: str, tr_func, parent=None) -> None:
        super().__init__(app_state, compact=False, parent=parent)
        self._tr = tr_func
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)
        self._title = QLabel(title, self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 18px; font-weight: 800;")
        text_wrap.addWidget(self._title)
        self._subtitle = QLabel(self._tr("ui.folder_item_hint"), self)
        self._subtitle.setObjectName("customSavesFolderSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("font-size: 12px;")
        text_wrap.addWidget(self._subtitle)
        layout.addLayout(text_wrap, 1)

        self._checkmark = QPushButton(self)
        self._checkmark.setObjectName("profileCheckmark")
        self._checkmark.setFixedSize(36, 36)
        self._checkmark.setIconSize(QSize(22, 22))
        self._checkmark.setEnabled(False)
        layout.addWidget(self._checkmark)

        self._actions_widget = QWidget(self)
        actions = QHBoxLayout(self._actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self._use_button = QPushButton(self._tr("ui.use_button"), self._actions_widget)
        self._use_button.setObjectName("profileUseBtn")
        self._use_button.clicked.connect(lambda: self.use_requested.emit())
        actions.addWidget(self._use_button)
        self._unuse_button = QPushButton(tr("ui.remove_button"), self._actions_widget)
        self._unuse_button.setObjectName("profileUseBtn")
        self._unuse_button.clicked.connect(lambda: self.unuse_requested.emit())
        actions.addWidget(self._unuse_button)

        self._delete_button = QPushButton(self._actions_widget)
        self._delete_button.setObjectName("summaryActionButton")
        self._delete_button.setFixedSize(32, 32)
        self._delete_button.setIconSize(QSize(18, 18))
        self._delete_button.clicked.connect(lambda: self.delete_requested.emit())
        actions.addWidget(self._delete_button)
        layout.addWidget(self._actions_widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        super().refresh_theme()
        config = self._app_state.local_config
        colors = get_theme_colors(config)
        br = clamp_border_radius(
            get_border_radius(config),
            width=38,
            height=38,
            border_width=2,
        )
        bw, bh, bfs = get_card_button_metrics(config)
        self._delete_button.setIcon(colored_icon("delete", colors["main_text"]))
        self._checkmark.setIcon(colored_icon("checkmark", colors["main_text"]))
        self._delete_button.setToolTip(self._tr("ui.delete_tooltip"))
        self._use_button.setText(self._tr("ui.use_button"))
        self._unuse_button.setText(tr("ui.remove_button"))
        self._subtitle.setText(self._tr("ui.folder_item_hint"))
        apply_stylesheet_if_changed(
            self._use_button,
            build_button_style(
                "profileUseBtn",
                "#4CAF50",
                "#5cb85c",
                "#e8e9eb",
                colors["border"],
                width=bw,
                height=bh,
                font_size=bfs,
                border_radius=br,
            ),
            cache_attr="_use_btn_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._unuse_button,
            build_button_style(
                "profileUseBtn",
                "#FF9800",
                "#F57C00",
                "#e8e9eb",
                colors["border"],
                width=bw,
                height=bh,
                font_size=bfs,
                border_radius=br,
            ),
            cache_attr="_unuse_btn_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._checkmark,
            "QPushButton#profileCheckmark { background: transparent; border: none; padding: 0px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }",
            cache_attr="_checkmark_ss_cache",
        )
        apply_stylesheet_if_changed(
            self._delete_button,
            f"""
            QToolButton#summaryActionButton, QPushButton#summaryActionButton {{
                background: transparent;
                border: 2px solid {colors["border"]};
                border-radius: {min(br, 10)}px;
                min-width: 32px;
                min-height: 32px;
                max-width: 32px;
                max-height: 32px;
                padding: 0;
            }}
            QToolButton#summaryActionButton:hover, QPushButton#summaryActionButton:hover {{
                background: {colors["hover"]};
            }}
            """,
            cache_attr="_delete_btn_ss_cache",
        )
        self._update_actions_visibility()

    def set_active(self, active: bool) -> None:
        super().set_active(active)
        self._update_actions_visibility()

    def set_selected(self, selected: bool) -> None:
        super().set_selected(selected)
        self._update_actions_visibility()

    def _update_actions_visibility(self) -> None:
        self._actions_widget.setVisible(self._selected)
        self._checkmark.setVisible(self._active and not self._selected)
        self._use_button.setVisible(self._selected and not self._active)
        self._unuse_button.setVisible(self._selected and self._active)


class _StateStore:
    def __init__(self, settings_accessor, game_registry_service) -> None:
        self._settings = settings_accessor
        self._game_registry = game_registry_service

    def list_games(self):
        if self._game_registry and hasattr(self._game_registry, "list_visible_games"):
            return self._game_registry.list_visible_games()
        return [
            type("Entry", (), {"id": game.game_id, "display_name": game.display_label})
            for game in get_all_games()
        ]

    def get_folders_map(self) -> dict[str, list[str]]:
        raw = self._settings.get(_SETTINGS_FOLDERS_KEY, {})
        if not isinstance(raw, dict):
            return {}
        result: dict[str, list[str]] = {}
        for game_id, values in raw.items():
            if not isinstance(game_id, str) or not isinstance(values, list):
                continue
            cleaned = [
                str(value).strip()
                for value in values
                if isinstance(value, str) and str(value).strip()
            ]
            if cleaned:
                result[game_id] = list(dict.fromkeys(cleaned))
        return result

    def get_selected_map(self) -> dict[str, str]:
        raw = self._settings.get(_SETTINGS_SELECTED_KEY, {})
        if not isinstance(raw, dict):
            return {}
        result: dict[str, str] = {}
        for game_id, value in raw.items():
            if isinstance(game_id, str) and isinstance(value, str) and value.strip():
                result[game_id] = value.strip()
        return result

    def get_folders(self, game_id: str) -> list[str]:
        return self.get_folders_map().get(game_id, [])

    def get_selected(self, game_id: str) -> str:
        selected = self.get_selected_map().get(game_id, "")
        if selected and selected in self.get_folders(game_id):
            return selected
        return ""

    @staticmethod
    def validate_name(name: str) -> str | None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return "errors.name_required"
        if len(cleaned) > 80:
            return "errors.name_too_long"
        if cleaned[-1:] in {" ", "."}:
            return "errors.name_invalid_suffix"
        if any(ord(char) < 32 for char in cleaned):
            return "errors.name_invalid_chars"
        if any(char in _INVALID_NAME_CHARS for char in cleaned):
            return "errors.name_invalid_chars"
        if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
            return "errors.name_reserved"
        return None

    def add_folder(self, game_id: str, folder_name: str) -> str | None:
        cleaned = str(folder_name or "").strip()
        error_key = self.validate_name(cleaned)
        if error_key:
            return error_key
        folders_map = self.get_folders_map()
        folders = folders_map.setdefault(game_id, [])
        if cleaned in folders:
            return "errors.folder_exists"
        folders.append(cleaned)
        folders_map[game_id] = folders
        self._settings.set(_SETTINGS_FOLDERS_KEY, folders_map)
        selected_map = self.get_selected_map()
        selected_map[game_id] = cleaned
        self._settings.set(_SETTINGS_SELECTED_KEY, selected_map)
        return None

    def remove_folder(self, game_id: str, folder_name: str) -> None:
        folders_map = self.get_folders_map()
        selected_map = self.get_selected_map()
        folders = [value for value in folders_map.get(game_id, []) if value != folder_name]
        if folders:
            folders_map[game_id] = folders
        else:
            folders_map.pop(game_id, None)
        if selected_map.get(game_id) == folder_name:
            if folders:
                selected_map[game_id] = folders[0]
            else:
                selected_map.pop(game_id, None)
        self._settings.set(_SETTINGS_FOLDERS_KEY, folders_map)
        self._settings.set(_SETTINGS_SELECTED_KEY, selected_map)

    def select_folder(self, game_id: str, folder_name: str) -> None:
        if folder_name not in self.get_folders(game_id):
            return
        selected_map = self.get_selected_map()
        selected_map[game_id] = folder_name
        self._settings.set(_SETTINGS_SELECTED_KEY, selected_map)

    def clear_selected(self, game_id: str) -> None:
        selected_map = self.get_selected_map()
        if game_id in selected_map:
            selected_map.pop(game_id, None)
            self._settings.set(_SETTINGS_SELECTED_KEY, selected_map)


class _FolderNameDialog(QDialog):
    def __init__(self, app_state, tr_func, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._tr = tr_func
        self.setWindowTitle(self._tr("ui.add_folder"))
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel(self._tr("ui.name_label"), self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(self._tr("ui.name_placeholder"))
        self.edit.returnPressed.connect(self.accept)
        layout.addWidget(self.edit)

        hint = QLabel(self._tr("ui.name_hint"), self)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton(self._tr("ui.cancel_button"), self)
        cancel_btn.clicked.connect(self.reject)
        create_btn = QPushButton(self._tr("ui.create_button"), self)
        create_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(create_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        apply_dialog_theme(self, self._app_state)

    def value(self) -> str:
        return self.edit.text().strip()


class _CustomSavesFoldersWidget(QWidget):
    selection_changed = pyqtSignal()

    def __init__(self, ui_context, state: _StateStore, tr_func, parent=None) -> None:
        super().__init__(parent)
        self._ui_context = ui_context
        self._state = state
        self._tr = tr_func
        self._game_rows: dict[str, _GameRow] = {}
        self._folder_rows: dict[str, _FolderRow] = {}
        self._focused_folder_name = ""
        self._build_ui()
        self._apply_theme()
        self._refresh_games()

        game_registry = getattr(self._ui_context.host_context, "game_registry_service", None)
        if game_registry and hasattr(game_registry, "games_changed"):
            game_registry.games_changed.connect(self._refresh_games)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addStretch(1)
        self._title_label = QLabel(self._tr("ui.title"), self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setObjectName("customSavesFoldersTitle")
        header.addWidget(self._title_label)
        self._appdata_btn = QPushButton(self)
        self._appdata_btn.setObjectName("customSavesFoldersAppDataButton")
        self._appdata_btn.clicked.connect(self._open_appdata_folder)
        header.addWidget(self._appdata_btn)
        header.addStretch(1)
        outer.addLayout(header)

        self._hint_label = QLabel(self._tr("ui.current_game_hint"), self)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.setWordWrap(True)
        self._hint_label.setObjectName("customSavesFoldersHint")
        outer.addWidget(self._hint_label)

        content = QHBoxLayout()
        content.setSpacing(14)
        outer.addLayout(content, 1)

        left = QFrame(self)
        left.setObjectName("customSavesFoldersPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)
        self._games_title_label = QLabel(self._tr("ui.games_title"), left)
        self._games_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self._games_title_label)
        self.games_list = QListWidget(left)
        self.games_list.setSpacing(8)
        self.games_list.currentItemChanged.connect(self._refresh_folders)
        left_layout.addWidget(self.games_list, 1)
        content.addWidget(left, 1)

        right = QFrame(self)
        right.setObjectName("customSavesFoldersPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        header = QHBoxLayout()
        header.addStretch(1)
        self._folders_title_label = QLabel(self._tr("ui.folders_title"), right)
        self._folders_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._folders_title_label)
        header.addStretch(1)
        self.add_btn = QPushButton(right)
        self.add_btn.setObjectName("game_versions_add_btn")
        self.add_btn.setFixedSize(38, 38)
        self.add_btn.setIconSize(QSize(20, 20))
        self.add_btn.clicked.connect(self._on_add_clicked)
        header.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignRight)
        right_layout.addLayout(header)

        self.folders_list = QListWidget(right)
        self.folders_list.setSpacing(10)
        right_layout.addWidget(self.folders_list, 1)

        self.empty_label = QLabel(self._tr("ui.empty_selection"), right)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        right_layout.addWidget(self.empty_label)
        content.addWidget(right, 1)

    def _apply_theme(self) -> None:
        colors = get_theme_colors(self._ui_context.app_state.local_config)
        theme = get_dialog_theme_values(self._ui_context.app_state)
        radius = theme["border_radius"]
        small_radius = max(8, min(radius, 16))
        self.setStyleSheet(
            f"""
            QWidget {{
                color: {colors["main_text"]};
            }}
            QLabel#customSavesFoldersTitle {{
                font-size: 24px;
                font-weight: 800;
            }}
            QPushButton#customSavesFoldersAppDataButton {{
                background-color: {colors["background"]};
                border: 2px solid {colors["border"]};
                border-radius: {small_radius}px;
                padding: 6px 10px;
            }}
            QPushButton#customSavesFoldersAppDataButton:hover:enabled {{
                background-color: {colors["hover"]};
                border-color: {colors["select"]};
            }}
            QPushButton#customSavesFoldersAppDataButton:disabled {{
                background-color: {colors["background"]};
                border-color: #6f6f6f;
            }}
            QLabel#customSavesFoldersHint {{
                color: {colors["secondary_text"]};
                font-size: 13px;
            }}
            QFrame#customSavesFoldersPanel {{
                background-color: {colors["elements"]};
                border: 2px solid {colors["border"]};
                border-radius: {radius}px;
            }}
            QListWidget {{
                background: transparent;
                border: none;
                padding: 2px;
                outline: none;
            }}
            QListWidget::item {{
                border: none;
                background: transparent;
                padding: 0;
            }}
            QPushButton#game_versions_add_btn {{
                background-color: {colors["background"]};
                border: 2px solid {colors["border"]};
                border-radius: {small_radius}px;
                padding: 0;
            }}
            QPushButton#game_versions_add_btn:hover:enabled {{
                background-color: {colors["hover"]};
                border-color: {colors["select"]};
            }}
            QPushButton#game_versions_add_btn:disabled {{
                background-color: {colors["background"]};
                border-color: #6f6f6f;
            }}
            """
        )
        self._appdata_btn.setIcon(colored_icon("folder", colors["main_text"]))
        self._appdata_btn.setText(self._tr("ui.open_appdata_button"))
        self._appdata_btn.setToolTip(self._tr("ui.open_appdata_tooltip"))
        self.add_btn.setIcon(colored_icon("add", colors["main_text"]))
        self.add_btn.setToolTip(self._tr("ui.add_tooltip"))
        for row in self._game_rows.values():
            row.refresh_theme()
        for row in self._folder_rows.values():
            row.refresh_theme()
        self._refresh_folders()

    def _open_appdata_folder(self) -> None:
        path = get_user_data_root()
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _current_game_id(self) -> str:
        item = self.games_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _set_current_game(self, game_id: str) -> None:
        for index in range(self.games_list.count()):
            item = self.games_list.item(index)
            if item and item.data(Qt.ItemDataRole.UserRole) == game_id:
                self.games_list.setCurrentItem(item)
                return

    def _set_focused_folder(self, game_id: str, folder_name: str) -> None:
        self._set_current_game(game_id)
        self._focused_folder_name = folder_name
        self._refresh_folders()
        self.selection_changed.emit()

    def _select_folder(self, game_id: str, folder_name: str) -> None:
        self._state.select_folder(game_id, folder_name)
        self._focused_folder_name = folder_name
        self._set_current_game(game_id)
        self._refresh_folders()
        self.selection_changed.emit()

    def _clear_selected_folder(self, game_id: str) -> None:
        self._state.clear_selected(game_id)
        self._focused_folder_name = ""
        self._set_current_game(game_id)
        self._refresh_folders()
        self.selection_changed.emit()

    def _refresh_games(self) -> None:
        current_game_id = self._current_game_id()
        self.games_list.clear()
        self._game_rows.clear()
        self._focused_folder_name = ""
        entries = self._state.list_games()
        if not entries:
            item = QListWidgetItem(self._tr("ui.empty_games"))
            self.games_list.addItem(item)
            self.games_list.setEnabled(False)
            self._refresh_folders()
            return

        self.games_list.setEnabled(True)
        for entry in entries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, 58))
            self.games_list.addItem(item)
            row = _GameRow(self._ui_context.app_state, entry.display_name, self.games_list)
            row.clicked.connect(lambda gid=entry.id: self._set_current_game(gid))
            self.games_list.setItemWidget(item, row)
            self._game_rows[entry.id] = row

        if self.games_list.count():
            self._set_current_game(current_game_id or entries[0].id)
        self._refresh_folders()

    def _on_add_clicked(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            QMessageBox.warning(self, self._tr("ui.title"), self._tr("errors.selection_missing"))
            return
        dialog = _FolderNameDialog(self._ui_context.app_state, self._tr, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        error_key = self._state.add_folder(game_id, dialog.value())
        if error_key:
            QMessageBox.warning(self, self._tr("ui.title"), self._tr(error_key))
            return
        self._refresh_folders()
        self.selection_changed.emit()

    def _on_delete_folder(self, game_id: str, folder_name: str) -> None:
        should_delete = QMessageBox.question(
            self,
            self._tr("dialogs.delete_title"),
            self._tr("dialogs.delete_body", name=folder_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if should_delete != QMessageBox.StandardButton.Yes:
            return
        self._state.remove_folder(game_id, folder_name)
        self._refresh_folders()
        self.selection_changed.emit()

    def _refresh_folders(self, *_args) -> None:
        game_id = self._current_game_id()
        for row_game_id, row in self._game_rows.items():
            row.set_selected(row_game_id == game_id)

        self.folders_list.clear()
        self._folder_rows.clear()

        if not game_id:
            self.empty_label.setText(self._tr("ui.empty_selection"))
            self.empty_label.setVisible(True)
            self.folders_list.setVisible(False)
            self.add_btn.setEnabled(False)
            return

        folders = self._state.get_folders(game_id)
        selected = self._state.get_selected(game_id)
        focused = self._focused_folder_name if self._focused_folder_name in folders else ""
        self.add_btn.setEnabled(True)

        if not folders:
            self.empty_label.setText(self._tr("ui.empty_folders"))
            self.empty_label.setVisible(True)
            self.folders_list.setVisible(False)
            return

        self.empty_label.setVisible(False)
        self.folders_list.setVisible(True)
        for folder_name in folders:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, folder_name)
            item.setSizeHint(QSize(0, 84))
            self.folders_list.addItem(item)
            row = _FolderRow(self._ui_context.app_state, folder_name, self._tr, self.folders_list)
            row.clicked.connect(
                lambda gid=game_id, folder=folder_name: self._set_focused_folder(gid, folder)
            )
            row.use_requested.connect(
                lambda gid=game_id, folder=folder_name: self._select_folder(gid, folder)
            )
            row.unuse_requested.connect(lambda gid=game_id: self._clear_selected_folder(gid))
            row.delete_requested.connect(
                lambda gid=game_id, folder=folder_name: self._on_delete_folder(gid, folder)
            )
            row.set_selected(folder_name == focused)
            row.set_active(folder_name == selected)
            self.folders_list.setItemWidget(item, row)
            self._folder_rows[folder_name] = row

    def refresh_language(self) -> None:
        self._title_label.setText(self._tr("ui.title"))
        self._appdata_btn.setText(self._tr("ui.open_appdata_button"))
        self._appdata_btn.setToolTip(self._tr("ui.open_appdata_tooltip"))
        self._hint_label.setText(self._tr("ui.current_game_hint"))
        self._games_title_label.setText(self._tr("ui.games_title"))
        self._folders_title_label.setText(self._tr("ui.folders_title"))
        self.add_btn.setToolTip(self._tr("ui.add_tooltip"))
        self._refresh_games()

    def refresh_theme(self) -> None:
        self._apply_theme()


class CustomSavesFoldersPlugin:
    def __init__(self) -> None:
        self._context = None
        self._ui_widget: _CustomSavesFoldersWidget | None = None
        self._state: _StateStore | None = None
        self._active_session: _ActiveSession | None = None

    def on_load(self, context) -> None:
        self._context = context
        self._state = _StateStore(
            context.plugin_settings,
            getattr(context, "game_registry_service", None),
        )

    def _tr(self):
        return self._context.localization_service.get_plugin_tr("custom_saves_folders")

    def create_main_widget(self, ui_context, parent):
        widget = _CustomSavesFoldersWidget(ui_context, self._state, self._tr(), parent)
        self._ui_widget = widget
        return widget

    def on_language_changed(self, context, *_args):
        if self._ui_widget is not None:
            self._ui_widget.refresh_language()

    def on_theme_changed(self, context, *_args):
        if self._ui_widget is not None:
            self._ui_widget.refresh_theme()

    def on_profile_changed(self, context, *_args):
        if self._ui_widget is not None:
            self._ui_widget.refresh_language()

    def on_shortcut_dialog(self, context, shortcut_context, *_args):
        game_mode = getattr(context.app_state, "game_mode", None)
        if game_mode is None or self._state is None:
            return []
        selected_folder = self._state.get_selected(game_mode.game_id)
        if not selected_folder:
            return []
        shortcut_context.set_plugin_state(
            "custom_saves_folders",
            {
                "game_id": game_mode.game_id,
                "folder_name": selected_folder,
            },
        )
        shortcut_context.add_summary_line(
            self._tr()("ui.shortcut_summary_label"),
            selected_folder,
        )
        return [
            {
                "plugin_id": "custom_saves_folders",
                "type": "text",
                "label": self._tr()("ui.shortcut_summary_label"),
                "value": selected_folder,
            }
        ]

    def _script_path(self) -> str:
        return str(Path(__file__).with_name("scripts") / "set_general_info_name.csx")

    def _resolve_target_files(self, game_id: str) -> tuple[object, str, list[str]]:
        game = get_game(game_id)
        if game is None:
            return None, "", []
        game_path = game.get_game_path(self._context.app_state.local_config)
        if not game_path or not os.path.isdir(game_path):
            return game, game_path, []

        targets: list[str] = []
        for tab in game.tabs:
            resource_dir = find_chapter_resource_dir(
                game_path,
                tab.tab_id,
                getattr(game, "macos_app_names", ("DELTARUNE.app", "DELTARUNEdemo.app")),
            )
            if not resource_dir or not os.path.isdir(resource_dir):
                resource_dir = game_path
            if not resource_dir or not os.path.isdir(resource_dir):
                continue
            data_path = find_supported_game_data_file(
                resource_dir,
                preferred_name=getattr(game, "data_file_name", "") or "",
            )
            if data_path and data_path not in targets:
                targets.append(data_path)
        return game, game_path, targets

    def _apply_name_to_targets(self, game_id: str, folder_name: str, task_runtime=None) -> tuple[bool, str]:
        script_path = self._script_path()
        if not os.path.isfile(script_path):
            return False, self._tr()("errors.script_missing")

        g3mtool = G3MToolManager()
        if not g3mtool.is_available():
            return False, self._tr()("errors.g3mtool_missing")

        game, game_path, targets = self._resolve_target_files(game_id)
        game_label = game.display_label if game else game_id
        if not game_path:
            return False, self._tr()("errors.game_path_missing")
        if not targets:
            return False, self._tr()("errors.data_file_missing", game=game_label)

        runtime_root = os.path.join(get_user_data_root(), "plugin_runtime")
        os.makedirs(runtime_root, exist_ok=True)
        backup_dir = tempfile.mkdtemp(prefix="custom_saves_backup_", dir=runtime_root)
        work_dir = tempfile.mkdtemp(prefix="custom_saves_work_", dir=runtime_root)
        backup_manager = BackupManager(backup_dir, patching_logger=logger)

        try:
            if task_runtime:
                task_runtime.set_status(self._tr()("ui.applying_status"), "info")
            for index, target in enumerate(targets):
                if task_runtime:
                    task_runtime.raise_if_cancelled()
                    task_runtime.set_progress(
                        round((index / max(len(targets), 1)) * 100),
                        self._tr()("ui.applying_progress", current=index + 1, total=len(targets)),
                    )
                if not backup_manager.backup_file(game_id, target):
                    raise RuntimeError(f"Failed to backup {target}")
                temp_output = os.path.join(work_dir, f"{index}_{os.path.basename(target)}")
                rc, _stdout, stderr = g3mtool.execute(
                    script_path,
                    args=[folder_name],
                    data_file=target,
                    output_path=temp_output,
                )
                if rc != 0:
                    raise RuntimeError(stderr[:500] or target)
                if task_runtime:
                    task_runtime.raise_if_cancelled()
                if not os.path.exists(temp_output):
                    raise RuntimeError(temp_output)
                shutil.move(temp_output, target)

            self._active_session = _ActiveSession(
                game_id=game_id,
                work_dir=work_dir,
                backup_manager=backup_manager,
            )
            self._context.feedback_service.update_status(
                self._tr()("ui.applied_status", name=folder_name, game=game_label),
                get_theme_color(self._context.app_state.local_config, "select"),
            )
            if task_runtime:
                task_runtime.set_progress(100, self._tr()("ui.applied_status", name=folder_name, game=game_label))
            return True, ""
        except InterruptedError:
            logger.info("CustomSavesFoldersPlugin: apply cancelled, restoring backups")
            try:
                backup_manager.restore_backups(game_id)
            finally:
                backup_manager.clear_backup_dir()
                shutil.rmtree(work_dir, ignore_errors=True)
            return False, "cancelled"
        except Exception as error:
            logger.error(
                "CustomSavesFoldersPlugin: failed to apply custom save folder",
                exc_info=True,
            )
            try:
                backup_manager.restore_backups(game_id)
            finally:
                backup_manager.clear_backup_dir()
                shutil.rmtree(work_dir, ignore_errors=True)
            return False, str(error)

    def on_after_mod_apply_before_launch(self, context, *_args):
        game_mode = getattr(context.app_state, "game_mode", None)
        if game_mode is None or self._state is None:
            return True
        selected_folder = self._state.get_selected(game_mode.game_id)
        if not selected_folder:
            return True
        task_runtime = getattr(context, "task_runtime", None)
        ok, error = self._apply_name_to_targets(game_mode.game_id, selected_folder, task_runtime)
        if ok:
            return True
        if error == "cancelled":
            return False
        message = self._tr()("errors.apply_failed", error=error)
        context.feedback_service.show_message("error", "errors.error", message)
        return False

    def on_after_mod_apply_before_launch_shortcut(self, context, shortcut_context, *_args):
        payload = shortcut_context.get_plugin_state("custom_saves_folders")
        if not payload or not isinstance(payload, dict):
            return True
        folder_name = str(payload.get("folder_name", "")).strip()
        game_id = str(payload.get("game_id", "")).strip()
        if not folder_name or not game_id:
            return True
        task_runtime = getattr(context, "task_runtime", None)
        ok, error = self._apply_name_to_targets(game_id, folder_name, task_runtime)
        if ok:
            return True
        if error == "cancelled":
            return False
        message = self._tr()("errors.apply_failed", error=error)
        context.feedback_service.show_message("error", "errors.error", message)
        return False

    def on_mod_apply_cancelled(self, context, *_args):
        self._restore_session()
        return True

    def _restore_session(self) -> tuple[bool, str]:
        session = self._active_session
        if session is None:
            return True, ""
        try:
            session.backup_manager.restore_backups(session.game_id)
            session.backup_manager.clear_backup_dir()
            shutil.rmtree(session.work_dir, ignore_errors=True)
            self._context.feedback_service.update_status(
                self._tr()("ui.restored_status"),
                get_theme_color(self._context.app_state.local_config, "border"),
            )
            return True, ""
        except Exception as error:
            logger.error(
                "CustomSavesFoldersPlugin: failed to restore custom save folder session",
                exc_info=True,
            )
            return False, str(error)
        finally:
            self._active_session = None

    def on_before_restore_after_exit(self, context, *_args):
        ok, error = self._restore_session()
        if not ok:
            context.feedback_service.show_message(
                "error",
                "errors.error",
                self._tr()("errors.restore_failed", error=error),
            )
        return ok

    def on_before_restore_after_exit_shortcut(self, context, shortcut_context, *_args):
        return self.on_before_restore_after_exit(context)


def create_plugin():
    return CustomSavesFoldersPlugin()
