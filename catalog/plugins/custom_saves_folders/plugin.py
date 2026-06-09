"""Custom save folders plugin."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from adapters.g3mtool_adapter import G3MToolManager
from config.config import MOD_CONFIG_FILENAME
from models.game_modes import get_all_games, get_game
from services.backup_service import BackupManager
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values
from ui.common.styling import (
    apply_stylesheet_if_changed,
    clamp_border_radius,
    get_border_radius,
    get_theme_color,
    get_theme_colors,
    get_widget_border_radius,
)
from utils.mod.config_parser import normalize_mod_config_data
from utils.mod.utils import get_mod_id, get_mod_name
from utils.native_integration import open_path_native
from utils.path_utils import (
    colored_icon,
    find_chapter_resource_dir,
    find_supported_game_data_file,
    get_profile_mods_root,
    get_user_data_root,
)

logger = logging.getLogger(__name__)


def _show_translated_feedback_message(context, level: str, title_key: str, message: str) -> None:
    title = context.localization_service.get_text(title_key)
    feedback = getattr(context, "feedback_service", None)
    base_feedback = getattr(feedback, "_base_manager", None)
    if base_feedback is not None:
        icon_map = {
            "error": QMessageBox.Icon.Critical,
            "warning": QMessageBox.Icon.Warning,
            "info": QMessageBox.Icon.Information,
            "success": QMessageBox.Icon.Information,
        }
        msg_box = QMessageBox(getattr(base_feedback, "parent_widget", None))
        msg_box.setIcon(icon_map.get(level, QMessageBox.Icon.Information))
        msg_box.setWindowTitle(title)
        msg_box.setText(str(message))
        msg_box.exec()
        return
    if feedback is not None:
        feedback.show_message(level, title, message)

_SETTINGS_FOLDERS_KEY = "folders_by_game"
_SETTINGS_SELECTED_KEY = "selected_by_game"
_SETTINGS_NEW_FOLDERS_KEY = "folders"
_SETTINGS_RULES_KEY = "mod_rules"
_GLOBAL_PROFILE = ""
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
        radius = get_widget_border_radius(
            self,
            get_dialog_theme_values(self._app_state)["border_radius"],
            border_width=2,
        )
        border_color = colors["hover"] if (self._hovered or self._selected) else colors["border"]
        background = colors["elements"]
        apply_stylesheet_if_changed(
            self,
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
            """,
            cache_attr="_row_stylesheet_cache",
        )


class _FolderRow(_InteractiveRow):
    enabled_changed = pyqtSignal(bool)
    delete_requested = pyqtSignal()

    def __init__(self, app_state, title: str, subtitle: str, enabled: bool, tr_func, parent=None) -> None:
        super().__init__(app_state, compact=False, parent=parent)
        self._tr = tr_func
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._enabled_box = QCheckBox(self)
        self._enabled_box.setChecked(enabled)
        self._enabled_box.stateChanged.connect(
            lambda state: self.enabled_changed.emit(state == Qt.CheckState.Checked.value)
        )
        layout.addWidget(self._enabled_box, 0, Qt.AlignmentFlag.AlignVCenter)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)
        self._title = QLabel(title, self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 18px; font-weight: 800;")
        text_wrap.addWidget(self._title)
        self._subtitle = QLabel(subtitle, self)
        self._subtitle.setObjectName("customSavesFolderSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("font-size: 12px;")
        text_wrap.addWidget(self._subtitle)
        layout.addLayout(text_wrap, 1)

        self._subtitle_text = subtitle
        self._delete_button = QPushButton(self)
        self._delete_button.setObjectName("summaryActionButton")
        self._delete_button.setFixedSize(32, 32)
        self._delete_button.setIconSize(QSize(18, 18))
        self._delete_button.clicked.connect(lambda: self.delete_requested.emit())
        layout.addWidget(self._delete_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        super().refresh_theme()
        config = self._app_state.local_config
        colors = get_theme_colors(config)
        br = clamp_border_radius(
            get_widget_border_radius(self._delete_button, get_border_radius(config), border_width=2),
            width=38,
            height=38,
        )
        self._enabled_box.setText(self._tr("ui.rule_enabled"))
        self._delete_button.setIcon(colored_icon("delete", colors["main_text"]))
        self._delete_button.setToolTip(self._tr("ui.delete_tooltip"))
        self._subtitle.setText(self._subtitle_text)
        apply_stylesheet_if_changed(
            self._delete_button,
            f"""
            QPushButton#summaryActionButton {{
                background: transparent;
                border: 2px solid {colors["border"]};
                border-radius: {min(br, 10)}px;
                min-width: 32px;
                min-height: 32px;
                max-width: 32px;
                max-height: 32px;
                padding: 0;
            }}
            QPushButton#summaryActionButton:hover {{
                background: {colors["hover"]};
            }}
            """,
            cache_attr="_delete_btn_ss_cache",
        )

    def update_subtitle(self, subtitle: str) -> None:
        self._subtitle_text = subtitle
        self._subtitle.setText(subtitle)


class _RuleRow(_InteractiveRow):
    enabled_changed = pyqtSignal(bool)
    delete_requested = pyqtSignal()

    def __init__(
        self,
        app_state,
        title: str,
        subtitle: str,
        enabled: bool,
        tr_func,
        parent=None,
    ) -> None:
        super().__init__(app_state, compact=False, parent=parent)
        self._tr = tr_func
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self._enabled_box = QCheckBox(self)
        self._enabled_box.setChecked(enabled)
        self._enabled_box.stateChanged.connect(
            lambda state: self.enabled_changed.emit(state == Qt.CheckState.Checked.value)
        )
        layout.addWidget(self._enabled_box, 0, Qt.AlignmentFlag.AlignVCenter)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(2)
        self._title = QLabel(title, self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 16px; font-weight: 800;")
        text_wrap.addWidget(self._title)
        self._subtitle = QLabel(subtitle, self)
        self._subtitle.setObjectName("customSavesFolderSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("font-size: 12px;")
        text_wrap.addWidget(self._subtitle)
        layout.addLayout(text_wrap, 1)

        self._delete_button = QPushButton(self)
        self._delete_button.setObjectName("summaryActionButton")
        self._delete_button.setFixedSize(32, 32)
        self._delete_button.setIconSize(QSize(18, 18))
        self._delete_button.clicked.connect(lambda: self.delete_requested.emit())
        layout.addWidget(self._delete_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        super().refresh_theme()
        colors = get_theme_colors(self._app_state.local_config)
        br = clamp_border_radius(
            get_widget_border_radius(
                self._delete_button,
                get_border_radius(self._app_state.local_config),
                border_width=2,
            ),
            width=38,
            height=38,
        )
        self._enabled_box.setText(self._tr("ui.rule_enabled"))
        self._delete_button.setIcon(colored_icon("delete", colors["main_text"]))
        self._delete_button.setToolTip(self._tr("ui.delete_tooltip"))
        apply_stylesheet_if_changed(
            self._delete_button,
            f"""
            QPushButton#summaryActionButton {{
                background: transparent;
                border: 2px solid {colors["border"]};
                border-radius: {min(br, 10)}px;
                min-width: 32px;
                min-height: 32px;
                max-width: 32px;
                max-height: 32px;
                padding: 0;
            }}
            QPushButton#summaryActionButton:hover {{
                background: {colors["hover"]};
            }}
            """,
            cache_attr="_delete_btn_ss_cache",
        )


class _StateStore:
    def __init__(
        self,
        settings_accessor,
        game_registry_service,
        profile_service=None,
        app_state=None,
    ) -> None:
        self._settings = settings_accessor
        self._game_registry = game_registry_service
        self._profile_service = profile_service
        self._app_state = app_state
        self._migrate_legacy_settings()

    def list_games(self):
        if self._game_registry and hasattr(self._game_registry, "list_visible_games"):
            return self._game_registry.list_visible_games()
        return [
            type("Entry", (), {"id": game.game_id, "display_name": game.display_label})
            for game in get_all_games()
        ]

    def list_profiles(self) -> list[str]:
        active = self.active_profile()
        if self._profile_service and hasattr(self._profile_service, "list_profiles"):
            profiles = list(self._profile_service.list_profiles())
            if active and active not in profiles:
                profiles.insert(0, active)
            return profiles
        return [active] if active else []

    def active_profile(self) -> str:
        if self._profile_service and hasattr(self._profile_service, "active_name"):
            return str(self._profile_service.active_name or "Default")
        config = getattr(self._app_state, "local_config", {}) or {}
        return str(config.get("active_profile", "Default") or "Default")

    def profile_label(self, profile: str) -> str:
        return profile or "Global"

    def game_label(self, game_id: str) -> str:
        for entry in self.list_games():
            if getattr(entry, "id", "") == game_id:
                return getattr(entry, "display_name", game_id)
        game = get_game(game_id)
        return game.display_label if game else game_id

    def _migrate_legacy_settings(self) -> None:
        try:
            existing_folders = self._settings.get(_SETTINGS_NEW_FOLDERS_KEY, None)
            folders_map = self._read_legacy_folders_map()
            if isinstance(existing_folders, list) and (existing_folders or not folders_map):
                self.get_folders()
                self.get_rules()
                return
            selected_map = self._read_legacy_selected_map()
            folders: list[dict] = []
            for game_id, names in folders_map.items():
                ordered_names = list(names)
                selected = selected_map.get(game_id, "")
                if selected in ordered_names:
                    ordered_names.remove(selected)
                    ordered_names.insert(0, selected)
                elif selected:
                    ordered_names.insert(0, selected)
                for name in ordered_names:
                    folders.append(
                        {
                            "id": self._new_id("folder"),
                            "game_id": game_id,
                            "profile": _GLOBAL_PROFILE,
                            "name": name,
                        }
                    )
            rules = self._normalize_rules([])
        except Exception:
            logger.exception("Failed to migrate legacy custom save folder settings")
            return
        self._settings.set(_SETTINGS_NEW_FOLDERS_KEY, folders)
        self._settings.set(_SETTINGS_RULES_KEY, rules)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _read_legacy_folders_map(self) -> dict[str, list[str]]:
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

    def _read_legacy_selected_map(self) -> dict[str, str]:
        raw = self._settings.get(_SETTINGS_SELECTED_KEY, {})
        if not isinstance(raw, dict):
            return {}
        return {
            game_id: value.strip()
            for game_id, value in raw.items()
            if isinstance(game_id, str) and isinstance(value, str) and value.strip()
        }

    def _normalize_folders(self, raw) -> list[dict]:
        if not isinstance(raw, list):
            return []
        result = []
        seen_ids = set()
        seen_keys = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            game_id = str(item.get("game_id", "") or "").strip()
            name = str(item.get("name", "") or "").strip()
            profile = str(item.get("profile", "") or "").strip()
            if not game_id or not name:
                continue
            duplicate_key = (game_id, profile, name)
            if duplicate_key in seen_keys:
                continue
            folder_id = str(item.get("id", "") or "").strip()
            if not folder_id or folder_id in seen_ids:
                folder_id = self._new_id("folder")
            seen_ids.add(folder_id)
            seen_keys.add(duplicate_key)
            result.append(
                {
                    "id": folder_id,
                    "enabled": bool(item.get("enabled", True)),
                    "game_id": game_id,
                    "profile": profile,
                    "name": name,
                }
            )
        return result

    def _normalize_rules(self, raw) -> list[dict]:
        if not isinstance(raw, list):
            return []
        result = []
        seen_ids = set()
        seen_keys = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            profile = str(item.get("profile", "") or "").strip()
            game_id = str(item.get("game_id", "") or "").strip()
            mod_id = str(item.get("mod_id", "") or "").strip()
            folder_id = str(item.get("folder_id", "") or "").strip()
            if not profile or not game_id or not mod_id or not folder_id:
                continue
            duplicate_key = (profile, game_id, mod_id, folder_id)
            if duplicate_key in seen_keys:
                continue
            rule_id = str(item.get("id", "") or "").strip()
            if not rule_id or rule_id in seen_ids:
                rule_id = self._new_id("rule")
            seen_ids.add(rule_id)
            seen_keys.add(duplicate_key)
            result.append(
                {
                    "id": rule_id,
                    "enabled": bool(item.get("enabled", True)),
                    "profile": profile,
                    "game_id": game_id,
                    "mod_id": mod_id,
                    "mod_name": str(item.get("mod_name", "") or "").strip() or mod_id,
                    "folder_id": folder_id,
                }
            )
        return result

    def get_folders(self, game_id: str = "", *, active_profile_only: bool = False) -> list[dict]:
        folders = self._normalize_folders(self._settings.get(_SETTINGS_NEW_FOLDERS_KEY, []))
        self._settings.set(_SETTINGS_NEW_FOLDERS_KEY, folders)
        active_profile = self.active_profile()
        return [
            folder
            for folder in folders
            if (not game_id or folder["game_id"] == game_id)
            and (
                not active_profile_only
                or folder["profile"] in {_GLOBAL_PROFILE, active_profile}
            )
        ]

    def get_rules(self, game_id: str = "") -> list[dict]:
        rules = self._normalize_rules(self._settings.get(_SETTINGS_RULES_KEY, []))
        self._settings.set(_SETTINGS_RULES_KEY, rules)
        return [
            rule
            for rule in rules
            if not game_id or rule["game_id"] == game_id
        ]

    def get_folder(self, folder_id: str) -> dict | None:
        return next(
            (folder for folder in self.get_folders() if folder["id"] == folder_id),
            None,
        )

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

    def add_folder(self, game_id: str, profile: str, folder_name: str) -> str | None:
        cleaned = str(folder_name or "").strip()
        error_key = self.validate_name(cleaned)
        if error_key:
            return error_key
        profile = str(profile or "").strip()
        folders = self.get_folders()
        if any(
            folder["game_id"] == game_id
            and folder["profile"] == profile
            and folder["name"] == cleaned
            for folder in folders
        ):
            return "errors.folder_exists"
        folders.append(
            {
                "id": self._new_id("folder"),
                "enabled": True,
                "game_id": game_id,
                "profile": profile,
                "name": cleaned,
            }
        )
        self._settings.set(_SETTINGS_NEW_FOLDERS_KEY, folders)
        return None

    def remove_folder(self, folder_id: str) -> None:
        folders = [
            folder for folder in self.get_folders() if folder["id"] != folder_id
        ]
        self._settings.set(_SETTINGS_NEW_FOLDERS_KEY, folders)

    def reorder_folders(self, ordered_ids: list[str]) -> None:
        folders = self.get_folders()
        by_id = {folder["id"]: folder for folder in folders}
        ordered = [by_id[folder_id] for folder_id in ordered_ids if folder_id in by_id]
        ordered.extend(folder for folder in folders if folder["id"] not in ordered_ids)
        self._settings.set(_SETTINGS_NEW_FOLDERS_KEY, ordered)

    def set_folder_enabled(self, folder_id: str, enabled: bool) -> None:
        folders = self.get_folders()
        for folder in folders:
            if folder["id"] == folder_id:
                folder["enabled"] = bool(enabled)
                break
        self._settings.set(_SETTINGS_NEW_FOLDERS_KEY, folders)

    def add_rule(
        self,
        profile: str,
        game_id: str,
        mod_id: str,
        mod_name: str,
        folder_id: str,
    ) -> str | None:
        profile = str(profile or "").strip()
        game_id = str(game_id or "").strip()
        mod_id = str(mod_id or "").strip()
        folder_id = str(folder_id or "").strip()
        folder = self.get_folder(folder_id)
        if not profile or not game_id or not mod_id or not folder:
            return "errors.rule_selection_missing"
        if folder["game_id"] != game_id or folder["profile"] not in {
            _GLOBAL_PROFILE,
            profile,
        }:
            return "errors.folder_game_mismatch"
        rules = self.get_rules()
        if any(
            rule["profile"] == profile
            and rule["game_id"] == game_id
            and rule["mod_id"] == mod_id
            and rule["folder_id"] == folder_id
            for rule in rules
        ):
            return "errors.rule_exists"
        rules.append(
            {
                "id": self._new_id("rule"),
                "enabled": True,
                "profile": profile,
                "game_id": game_id,
                "mod_id": mod_id,
                "mod_name": str(mod_name or "").strip() or mod_id,
                "folder_id": folder_id,
            }
        )
        self._settings.set(_SETTINGS_RULES_KEY, rules)
        return None

    def remove_rule(self, rule_id: str) -> None:
        self._settings.set(
            _SETTINGS_RULES_KEY,
            [rule for rule in self.get_rules() if rule["id"] != rule_id],
        )

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> None:
        rules = self.get_rules()
        for rule in rules:
            if rule["id"] == rule_id:
                rule["enabled"] = bool(enabled)
                break
        self._settings.set(_SETTINGS_RULES_KEY, rules)

    def reorder_rules(self, ordered_ids: list[str]) -> None:
        rules = self.get_rules()
        by_id = {rule["id"]: rule for rule in rules}
        ordered = [by_id[rule_id] for rule_id in ordered_ids if rule_id in by_id]
        ordered.extend(rule for rule in rules if rule["id"] not in ordered_ids)
        self._settings.set(_SETTINGS_RULES_KEY, ordered)

    def list_profile_mods(self, profile: str, game_id: str) -> list[dict]:
        mods_root = get_profile_mods_root(profile)
        if not os.path.isdir(mods_root):
            return []
        mods = []
        seen_ids = set()
        for folder_name in sorted(os.listdir(mods_root), key=str.casefold):
            folder_path = os.path.join(mods_root, folder_name)
            config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
            if not os.path.isfile(config_path):
                continue
            try:
                with open(config_path, encoding="utf-8") as handle:
                    config_data = json.load(handle)
                normalize_mod_config_data(config_data, mod_root_path=folder_path)
            except Exception:
                logger.debug("Skipping unreadable mod config: %s", config_path)
                continue
            if str(config_data.get("game", "") or "").strip() != game_id:
                continue
            mod_id = get_mod_id(config_data) or folder_name
            if not mod_id or mod_id in seen_ids:
                continue
            seen_ids.add(mod_id)
            mods.append(
                {
                    "id": mod_id,
                    "name": get_mod_name(config_data, folder_name),
                    "game": game_id,
                }
            )
        return mods

    def rule_status(self, rule: dict) -> str:
        folder = self.get_folder(str(rule.get("folder_id", "")))
        if not folder:
            return "missing_folder"
        profile = str(rule.get("profile", "") or "")
        if (
            folder["game_id"] != rule.get("game_id")
            or folder["profile"] not in {_GLOBAL_PROFILE, profile}
        ):
            return "missing_folder"
        mod_id = str(rule.get("mod_id", "") or "")
        if not any(mod["id"] == mod_id for mod in self.list_profile_mods(profile, rule["game_id"])):
            return "missing_mod"
        return "ok"

    def _collect_selected_mod_ids(self, selections) -> set[str]:
        selected = set()
        if isinstance(selections, dict):
            values = selections.values()
        else:
            values = []
        for value in values:
            mods = value if isinstance(value, list) else [value]
            for mod in mods:
                mod_id = get_mod_id(mod)
                if mod_id:
                    selected.add(mod_id)
        return selected

    def _collect_config_mod_ids(self, game_id: str) -> set[str]:
        config = getattr(self._app_state, "local_config", {}) or {}
        selected = set()
        for key, value in config.items():
            if not key.startswith(f"used_mods_{game_id}") or not isinstance(value, dict):
                continue
            for raw in value.values():
                items = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
                selected.update(str(item) for item in items if item)
        return selected

    def resolve_launch_folder(
        self,
        game_id: str,
        profile: str | None = None,
        selections=None,
    ) -> dict | None:
        profile = str(profile or self.active_profile() or "Default")
        selected_mod_ids = self._collect_selected_mod_ids(selections)
        if not selected_mod_ids:
            selected_mod_ids = self._collect_config_mod_ids(game_id)
        folders_by_id = {folder["id"]: folder for folder in self.get_folders()}
        available_mod_ids = {
            mod["id"] for mod in self.list_profile_mods(profile, game_id)
        }
        for rule in self.get_rules(game_id):
            folder = folders_by_id.get(rule["folder_id"])
            if (
                rule["enabled"]
                and rule["profile"] == profile
                and rule["mod_id"] in selected_mod_ids
                and rule["mod_id"] in available_mod_ids
                and folder
                and folder["game_id"] == game_id
                and folder["profile"] in {_GLOBAL_PROFILE, profile}
            ):
                return folder
        for folder in self.get_folders(game_id):
            if folder.get("enabled", True) and folder["profile"] in {_GLOBAL_PROFILE, profile}:
                return folder
        return None


class _FolderDialog(QDialog):
    def __init__(self, app_state, state: _StateStore, tr_func, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._state = state
        self._tr = tr_func
        self.setWindowTitle(self._tr("ui.add_folder"))
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        game_label = QLabel(self._tr("ui.game_label"), self)
        layout.addWidget(game_label)
        self.game_combo = QComboBox(self)
        for entry in self._state.list_games():
            self.game_combo.addItem(entry.display_name, entry.id)
        layout.addWidget(self.game_combo)

        profile_label = QLabel(self._tr("ui.profile_label"), self)
        layout.addWidget(profile_label)
        self.profile_combo = QComboBox(self)
        self.profile_combo.addItem(self._tr("ui.global_profile"), _GLOBAL_PROFILE)
        for profile in self._state.list_profiles():
            self.profile_combo.addItem(profile, profile)
        layout.addWidget(self.profile_combo)

        name_label = QLabel(self._tr("ui.name_label"), self)
        layout.addWidget(name_label)
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText(self._tr("ui.name_placeholder"))
        self.name_edit.returnPressed.connect(self.accept)
        layout.addWidget(self.name_edit)

        hint = QLabel(self._tr("ui.name_hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self._tr("ui.create_button"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self._tr("ui.cancel_button"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_dialog_theme(self, self._app_state)

    def value(self) -> tuple[str, str, str]:
        return (
            str(self.game_combo.currentData() or ""),
            str(self.profile_combo.currentData() or ""),
            self.name_edit.text().strip(),
        )


class _RuleDialog(QDialog):
    def __init__(self, app_state, state: _StateStore, tr_func, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._state = state
        self._tr = tr_func
        self.setWindowTitle(self._tr("ui.add_rule"))
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        profile_box = QVBoxLayout()
        profile_box.addWidget(QLabel(self._tr("ui.profile_label"), self))
        self.profile_combo = QComboBox(self)
        for profile in self._state.list_profiles():
            self.profile_combo.addItem(profile, profile)
        profile_box.addWidget(self.profile_combo)
        top_row.addLayout(profile_box, 1)

        game_box = QVBoxLayout()
        game_box.addWidget(QLabel(self._tr("ui.game_label"), self))
        self.game_combo = QComboBox(self)
        for entry in self._state.list_games():
            self.game_combo.addItem(entry.display_name, entry.id)
        game_box.addWidget(self.game_combo)
        top_row.addLayout(game_box, 1)
        layout.addLayout(top_row)

        layout.addWidget(QLabel(self._tr("ui.mod_label"), self))
        self.mod_combo = QComboBox(self)
        layout.addWidget(self.mod_combo)

        layout.addWidget(QLabel(self._tr("ui.folder_label"), self))
        self.folder_combo = QComboBox(self)
        layout.addWidget(self.folder_combo)

        hint = QLabel(self._tr("ui.rule_dialog_hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self._tr("ui.create_button"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self._tr("ui.cancel_button"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.profile_combo.currentIndexChanged.connect(self._refresh_choices)
        self.game_combo.currentIndexChanged.connect(self._refresh_choices)
        self._refresh_choices()
        apply_dialog_theme(self, self._app_state)

    def _refresh_choices(self) -> None:
        profile = str(self.profile_combo.currentData() or "")
        game_id = str(self.game_combo.currentData() or "")

        self.mod_combo.clear()
        for mod in self._state.list_profile_mods(profile, game_id):
            self.mod_combo.addItem(mod["name"], mod)

        self.folder_combo.clear()
        for folder in self._state.get_folders(game_id):
            if folder["profile"] not in {_GLOBAL_PROFILE, profile}:
                continue
            label = f'{folder["name"]} ({self._state.profile_label(folder["profile"])})'
            self.folder_combo.addItem(label, folder["id"])

        has_choices = self.mod_combo.count() > 0 and self.folder_combo.count() > 0
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(has_choices)

    def value(self) -> tuple[str, str, str, str, str]:
        mod = self.mod_combo.currentData() or {}
        return (
            str(self.profile_combo.currentData() or ""),
            str(self.game_combo.currentData() or ""),
            str(mod.get("id", "")),
            str(mod.get("name", "")),
            str(self.folder_combo.currentData() or ""),
        )


class _HelpDialog(QDialog):
    def __init__(self, app_state, tr_func, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._tr = tr_func
        self.setWindowTitle(self._tr("ui.help_title"))
        self.setModal(True)
        self.setMinimumSize(1120, 630)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        body = QTextBrowser(self)
        body.setOpenExternalLinks(False)
        body.setPlainText(self._tr("ui.help_body"))
        layout.addWidget(body, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self._tr("ui.close_button"))
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        apply_dialog_theme(self, self._app_state)


class _CustomSavesFoldersWidget(QWidget):
    selection_changed = pyqtSignal()

    def __init__(self, ui_context, state: _StateStore, tr_func, parent=None) -> None:
        super().__init__(parent)
        self._ui_context = ui_context
        self._state = state
        self._tr = tr_func
        self._folder_rows: dict[str, _FolderRow] = {}
        self._rule_rows: dict[str, _RuleRow] = {}
        self._build_ui()
        self._apply_theme()
        self._refresh_game_filters()
        self._refresh_all()

        game_registry = getattr(self._ui_context.host_context, "game_registry_service", None)
        if game_registry and hasattr(game_registry, "games_changed"):
            game_registry.games_changed.connect(self._refresh_game_filters)
            game_registry.games_changed.connect(self._refresh_all)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addStretch(1)
        self._help_btn = QPushButton(self)
        self._help_btn.setObjectName("customSavesFoldersAppDataButton")
        self._help_btn.clicked.connect(self._show_help)
        header.addWidget(self._help_btn)
        self._appdata_btn = QPushButton(self)
        self._appdata_btn.setObjectName("customSavesFoldersAppDataButton")
        self._appdata_btn.clicked.connect(self._open_appdata_folder)
        header.addWidget(self._appdata_btn)
        header.addStretch(1)
        outer.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(14)
        outer.addLayout(content, 1)

        left = QFrame(self)
        left.setObjectName("customSavesFoldersPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)
        folder_header = QHBoxLayout()
        self._folder_filter = QComboBox(left)
        self._folder_filter.currentIndexChanged.connect(self._refresh_folders)
        folder_header.addWidget(self._folder_filter, 1)
        self.add_folder_btn = QPushButton(left)
        self.add_folder_btn.setObjectName("game_versions_add_btn")
        self.add_folder_btn.setFixedSize(38, 38)
        self.add_folder_btn.setIconSize(QSize(20, 20))
        self.add_folder_btn.clicked.connect(self._on_add_folder_clicked)
        folder_header.addWidget(self.add_folder_btn)
        left_layout.addLayout(folder_header)

        self.folders_list = QListWidget(left)
        self.folders_list.setSpacing(10)
        self.folders_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.folders_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.folders_list.model().rowsMoved.connect(lambda *_args: self._save_folder_order())
        left_layout.addWidget(self.folders_list, 1)
        self.folders_empty_label = QLabel(self._tr("ui.empty_folders"), left)
        self.folders_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.folders_empty_label.setWordWrap(True)
        left_layout.addWidget(self.folders_empty_label)
        content.addWidget(left, 1)

        right = QFrame(self)
        right.setObjectName("customSavesFoldersPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        rule_header = QHBoxLayout()
        self._rule_filter = QComboBox(right)
        self._rule_filter.currentIndexChanged.connect(self._refresh_rules)
        rule_header.addWidget(self._rule_filter, 1)
        self.add_rule_btn = QPushButton(right)
        self.add_rule_btn.setObjectName("game_versions_add_btn")
        self.add_rule_btn.setFixedSize(38, 38)
        self.add_rule_btn.setIconSize(QSize(20, 20))
        self.add_rule_btn.clicked.connect(self._on_add_rule_clicked)
        rule_header.addWidget(self.add_rule_btn)
        right_layout.addLayout(rule_header)

        self.rules_list = QListWidget(right)
        self.rules_list.setSpacing(10)
        self.rules_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.rules_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.rules_list.model().rowsMoved.connect(lambda *_args: self._save_rule_order())
        right_layout.addWidget(self.rules_list, 1)
        self.rules_empty_label = QLabel(self._tr("ui.empty_rules"), right)
        self.rules_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rules_empty_label.setWordWrap(True)
        right_layout.addWidget(self.rules_empty_label)
        content.addWidget(right, 1)

    def _apply_theme(self) -> None:
        colors = get_theme_colors(self._ui_context.app_state.local_config)
        theme = get_dialog_theme_values(self._ui_context.app_state)
        radius = theme["border_radius"]
        small_radius = max(0, min(radius, 16))
        self.setStyleSheet(
            f"""
            QWidget {{
                color: {colors["main_text"]};
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
            QComboBox {{
                background-color: {colors["background"]};
                border: 2px solid {colors["border"]};
                border-radius: {small_radius}px;
                padding: 6px 10px;
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
        self._help_btn.setText(self._tr("ui.help_button"))
        self._help_btn.setToolTip(self._tr("ui.help_tooltip"))
        self._appdata_btn.setIcon(colored_icon("folder", colors["main_text"]))
        self._appdata_btn.setText(self._tr("ui.open_appdata_button"))
        self._appdata_btn.setToolTip(self._tr("ui.open_appdata_tooltip"))
        self.add_folder_btn.setIcon(colored_icon("add", colors["main_text"]))
        self.add_folder_btn.setToolTip(self._tr("ui.add_folder_tooltip"))
        self.add_rule_btn.setIcon(colored_icon("add", colors["main_text"]))
        self.add_rule_btn.setToolTip(self._tr("ui.add_rule_tooltip"))
        for row in self._folder_rows.values():
            row.refresh_theme()
            row.updateGeometry()
            row.update()
        for row in self._rule_rows.values():
            row.refresh_theme()
            row.updateGeometry()
            row.update()
        self.folders_list.viewport().update()
        self.rules_list.viewport().update()
        self.folders_list.update()
        self.rules_list.update()
        self._refresh_all()

    def _open_appdata_folder(self) -> None:
        path = get_user_data_root()
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        open_path_native(path)

    def _show_help(self) -> None:
        _HelpDialog(self._ui_context.app_state, self._tr, self).exec()

    @staticmethod
    def _combo_value(combo: QComboBox) -> str:
        return str(combo.currentData() or "")

    def _refresh_game_filters(self) -> None:
        current_folder = self._combo_value(self._folder_filter)
        current_rule = self._combo_value(self._rule_filter)
        entries = self._state.list_games()
        for combo, current in (
            (self._folder_filter, current_folder),
            (self._rule_filter, current_rule),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self._tr("ui.all_games"), "")
            for entry in entries:
                combo.addItem(entry.display_name, entry.id)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _on_add_folder_clicked(self) -> None:
        dialog = _FolderDialog(self._ui_context.app_state, self._state, self._tr, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        game_id, profile, name = dialog.value()
        error_key = self._state.add_folder(game_id, profile, name)
        if error_key:
            QMessageBox.warning(self, self._tr("ui.title"), self._tr(error_key))
            return
        self._set_filter(self._folder_filter, game_id)
        self._refresh_folders()
        self.selection_changed.emit()

    def _on_add_rule_clicked(self) -> None:
        dialog = _RuleDialog(self._ui_context.app_state, self._state, self._tr, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile, game_id, mod_id, mod_name, folder_id = dialog.value()
        error_key = self._state.add_rule(profile, game_id, mod_id, mod_name, folder_id)
        if error_key:
            QMessageBox.warning(self, self._tr("ui.title"), self._tr(error_key))
            return
        self._set_filter(self._rule_filter, game_id)
        self._refresh_rules()
        self.selection_changed.emit()

    def _set_filter(self, combo: QComboBox, game_id: str) -> None:
        index = combo.findData(game_id)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _on_delete_folder(self, folder: dict) -> None:
        should_delete = QMessageBox.question(
            self,
            self._tr("dialogs.delete_title"),
            self._tr("dialogs.delete_body", name=folder["name"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if should_delete != QMessageBox.StandardButton.Yes:
            return
        self._state.remove_folder(folder["id"])
        self._refresh_all()
        self.selection_changed.emit()

    def _on_delete_rule(self, rule: dict) -> None:
        should_delete = QMessageBox.question(
            self,
            self._tr("dialogs.delete_rule_title"),
            self._tr("dialogs.delete_rule_body", name=rule["mod_name"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if should_delete != QMessageBox.StandardButton.Yes:
            return
        self._state.remove_rule(rule["id"])
        self._refresh_rules()
        self.selection_changed.emit()

    def _save_folder_order(self) -> None:
        ids = [
            self.folders_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.folders_list.count())
        ]
        self._state.reorder_folders([str(folder_id) for folder_id in ids if folder_id])

    def _save_rule_order(self) -> None:
        ids = [
            self.rules_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.rules_list.count())
        ]
        self._state.reorder_rules([str(rule_id) for rule_id in ids if rule_id])

    def _refresh_all(self) -> None:
        self._refresh_folders()
        self._refresh_rules()

    def _refresh_folders(self, *_args) -> None:
        game_id = self._combo_value(self._folder_filter)
        self.folders_list.clear()
        self._folder_rows.clear()
        folders = self._state.get_folders(game_id)
        self.folders_empty_label.setVisible(not folders)
        self.folders_empty_label.setText(self._tr("ui.empty_folders"))
        self.folders_list.setVisible(bool(folders))

        for folder in folders:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, folder["id"])
            item.setSizeHint(QSize(0, 84))
            self.folders_list.addItem(item)
            subtitle = self._tr(
                "ui.folder_scope",
                game=self._state.game_label(folder["game_id"]),
                profile=self._state.profile_label(folder["profile"]),
            )
            if not folder.get("enabled", True):
                subtitle = f"{subtitle} · {self._tr('ui.rule_disabled')}"
            row = _FolderRow(
                self._ui_context.app_state,
                folder["name"],
                subtitle,
                folder.get("enabled", True),
                self._tr,
                self.folders_list,
            )
            row.enabled_changed.connect(
                lambda enabled, folder_id=folder["id"]: self._set_folder_enabled(folder_id, enabled)
            )
            row.delete_requested.connect(lambda _=False, data=folder: self._on_delete_folder(data))
            self.folders_list.setItemWidget(item, row)
            self._folder_rows[folder["id"]] = row

    def _refresh_rules(self, *_args) -> None:
        game_id = self._combo_value(self._rule_filter)
        self.rules_list.clear()
        self._rule_rows.clear()
        rules = self._state.get_rules(game_id)
        self.rules_empty_label.setVisible(not rules)
        self.rules_empty_label.setText(self._tr("ui.empty_rules"))
        self.rules_list.setVisible(bool(rules))

        for rule in rules:
            folder = self._state.get_folder(rule["folder_id"])
            status = self._state.rule_status(rule)
            folder_name = folder["name"] if folder else self._tr("ui.rule_missing_folder")
            status_text = ""
            if not rule["enabled"]:
                status_text = self._tr("ui.rule_disabled")
            elif status == "missing_mod":
                status_text = self._tr("ui.rule_missing_mod")
            elif status == "missing_folder":
                status_text = self._tr("ui.rule_missing_folder")
            subtitle = self._tr(
                "ui.rule_scope",
                game=self._state.game_label(rule["game_id"]),
                profile=rule["profile"],
                folder=folder_name,
                status=status_text,
            ).strip()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, rule["id"])
            item.setSizeHint(QSize(0, 92))
            self.rules_list.addItem(item)
            row = _RuleRow(
                self._ui_context.app_state,
                rule["mod_name"],
                subtitle,
                rule["enabled"],
                self._tr,
                self.rules_list,
            )
            row.enabled_changed.connect(
                lambda enabled, rule_id=rule["id"]: self._set_rule_enabled(rule_id, enabled)
            )
            row.delete_requested.connect(lambda _=False, data=rule: self._on_delete_rule(data))
            self.rules_list.setItemWidget(item, row)
            self._rule_rows[rule["id"]] = row

    def _set_rule_enabled(self, rule_id: str, enabled: bool) -> None:
        self._state.set_rule_enabled(rule_id, enabled)
        self._refresh_rules()
        self.selection_changed.emit()

    def _set_folder_enabled(self, folder_id: str, enabled: bool) -> None:
        self._state.set_folder_enabled(folder_id, enabled)
        self._refresh_folders()
        self.selection_changed.emit()

    def refresh_language(self) -> None:
        self._help_btn.setText(self._tr("ui.help_button"))
        self._help_btn.setToolTip(self._tr("ui.help_tooltip"))
        self._appdata_btn.setText(self._tr("ui.open_appdata_button"))
        self._appdata_btn.setToolTip(self._tr("ui.open_appdata_tooltip"))
        self.add_folder_btn.setToolTip(self._tr("ui.add_folder_tooltip"))
        self.add_rule_btn.setToolTip(self._tr("ui.add_rule_tooltip"))
        self._refresh_game_filters()
        self._refresh_all()

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
            getattr(context, "profile_service", None),
            getattr(context, "app_state", None),
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
        folder = self._state.resolve_launch_folder(game_mode.game_id)
        if not folder:
            return []
        shortcut_context.set_plugin_state(
            "custom_saves_folders",
            {
                "game_id": game_mode.game_id,
                "folder_id": folder["id"],
                "folder_name": folder["name"],
            },
        )
        shortcut_context.add_summary_line(
            self._tr()("ui.shortcut_summary_label"),
            folder["name"],
        )
        return [
            {
                "plugin_id": "custom_saves_folders",
                "type": "text",
                "label": self._tr()("ui.shortcut_summary_label"),
                "value": folder["name"],
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

        g3mtool = G3MToolManager(self._context.app_state)
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
        selections = _args[0] if _args else None
        folder = self._state.resolve_launch_folder(
            game_mode.game_id,
            self._state.active_profile(),
            selections,
        )
        if not folder:
            return True
        task_runtime = getattr(context, "task_runtime", None)
        ok, error = self._apply_name_to_targets(game_mode.game_id, folder["name"], task_runtime)
        if ok:
            return True
        if error == "cancelled":
            return False
        message = self._tr()("errors.apply_failed", error=error)
        _show_translated_feedback_message(context, "error", "errors.error", message)
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
        _show_translated_feedback_message(context, "error", "errors.error", message)
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
            _show_translated_feedback_message(
                context,
                "error",
                "errors.error",
                self._tr()("errors.restore_failed", error=error),
            )
        return ok

    def on_before_restore_after_exit_shortcut(self, context, shortcut_context, *_args):
        return self.on_before_restore_after_exit(context)


def create_plugin():
    return CustomSavesFoldersPlugin()
