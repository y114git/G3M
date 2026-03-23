"""Used mods tracking and management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from core.app_window import AppWindow

from models.app_state import AppState
from services.game_detection_service import get_chapter_id_for_game_mode
from services.localization_service import tr
from services.mod_service import ModManager
from services.settings_service import SettingsManager
from ui.common.feedback import FeedbackManager
from utils.file_utils import sanitize_filename
from utils.mod_utils import get_mod_key, get_mod_name


class UsedModsManager(QObject):
    used_mods_updated, used_mod_changed = pyqtSignal(), pyqtSignal(str)
    action_button_update_needed, mod_widgets_update_needed = pyqtSignal(), pyqtSignal()

    def __init__(
        self,
        app_state: AppState,
        mod_service: ModManager,
        feedback_service: FeedbackManager,
        settings_service: SettingsManager,
        parent: AppWindow | None = None,
    ) -> None:
        super().__init__(parent)
        self.app_state, self.mod_service = app_state, mod_service
        self.feedback_service, self.settings_service = (
            feedback_service,
            settings_service,
        )
        self.parent_widget: AppWindow | None = parent
        self.used_mods: dict[str, list[Any]] = {}
        self._mods_state_loaded = False

    def get_used_mods_list(self, chapter_id: str) -> list[Any]:
        return self.used_mods.get(chapter_id, [])

    def set_used_mod(
        self, chapter_id: str, mod_data: Any | None, save_state: bool = True
    ) -> None:
        key = get_mod_key(mod_data) if mod_data else None
        current_mods = self.used_mods.get(chapter_id, [])
        if mod_data is None:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        elif key:
            found_index = next(
                (i for i, m in enumerate(current_mods) if get_mod_key(m) == key), None
            )
            if found_index is not None:
                current_mods.pop(found_index)
                if current_mods:
                    self.used_mods[chapter_id] = current_mods
                elif chapter_id in self.used_mods:
                    del self.used_mods[chapter_id]
            else:
                current_mods.insert(0, mod_data)
                self.used_mods[chapter_id] = current_mods
        self.used_mod_changed.emit(chapter_id)
        if save_state:
            try:
                self.save_used_mods_state()
            except Exception as e:
                logging.error(
                    f"set_used_mod: Failed to save used mods state: {e}", exc_info=True
                )

    def set_mods_list(
        self, chapter_id: str, mods_list: list[Any], save_state: bool = True
    ) -> None:
        if not mods_list:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        else:
            self.used_mods[chapter_id] = mods_list
        self.used_mod_changed.emit(chapter_id)
        if save_state:
            try:
                self.save_used_mods_state()
            except Exception as e:
                logging.error(
                    f"set_mods_list: Failed to save used mods state: {e}", exc_info=True
                )

    def is_mod_used_for_chapter(self, mod_data, chapter_id: str) -> bool:
        if not mod_data or not (key := get_mod_key(mod_data)):
            return False
        return any(get_mod_key(m) == key for m in self.used_mods.get(chapter_id, []))

    def remove_mod_from_all_chapters(self, mod_data):
        key = get_mod_key(mod_data)
        if not key:
            return
        chapters_changed = []
        for chapter_id, used_mods_list in list(self.used_mods.items()):
            updated_list = [m for m in used_mods_list if get_mod_key(m) != key]
            if len(updated_list) != len(used_mods_list):
                chapters_changed.append(chapter_id)
                if updated_list:
                    self.used_mods[chapter_id] = updated_list
                else:
                    del self.used_mods[chapter_id]
        if chapters_changed:
            self.save_used_mods_state()
            for chapter_id in chapters_changed:
                self.used_mod_changed.emit(chapter_id)
        self._cleanup_mod_from_all_config_keys(key)

    def _cleanup_mod_from_all_config_keys(self, mod_key: str):
        if not mod_key:
            return
        config_keys = [
            config_key
            for config_key in self.app_state.local_config
            if config_key.startswith("used_mods_")
        ]
        config_updated = False
        for config_key in config_keys:
            used_mods_data = self.app_state.local_config.get(config_key, {})
            if not used_mods_data:
                continue
            chapters_to_clear = []
            for chapter_id_str, mod_data_raw in list(used_mods_data.items()):
                if isinstance(mod_data_raw, str):
                    if mod_data_raw == mod_key:
                        chapters_to_clear.append(chapter_id_str)
                elif isinstance(mod_data_raw, list) and mod_key in mod_data_raw:
                    updated_list = [k for k in mod_data_raw if k != mod_key]
                    if updated_list:
                        used_mods_data[chapter_id_str] = updated_list
                        config_updated = True
                    else:
                        chapters_to_clear.append(chapter_id_str)
                        config_updated = True
            for chapter_id_str in chapters_to_clear:
                del used_mods_data[chapter_id_str]
                config_updated = True
            if config_updated:
                self.app_state.local_config[config_key] = used_mods_data
        if config_updated:
            self.settings_service.write_local_config()

    def get_used_mods_config_key(
        self, game_mode_instance=None, is_chapter_mode: bool | None = None
    ):
        game_mode = game_mode_instance or self.app_state.game_mode
        is_chapter = (
            is_chapter_mode
            if is_chapter_mode is not None
            else self.app_state.current_mode == "chapter"
        )
        key = getattr(game_mode, "used_mods_config_key", "")
        if key:
            return key
        return "used_mods_deltarune_chapter" if is_chapter else "used_mods_deltarune"

    def save_used_mods_state(self):
        if not self._mods_state_loaded:
            return
        is_chapter_mode = self.app_state.current_mode == "chapter"
        gm = self.app_state.game_mode
        active_ids = (
            {tab.tab_id for tab in gm.tabs}
            if is_chapter_mode
            else {get_chapter_id_for_game_mode(gm)}
        )
        config_key = self.get_used_mods_config_key(
            self.app_state.game_mode, is_chapter_mode
        )
        used_mods_data = {}
        for chapter_id, mods_list in self.used_mods.items():
            if chapter_id not in active_ids:
                continue
            mod_keys = []
            for mod_data in mods_list:
                try:
                    if isinstance(mod_data, dict):
                        key = mod_data.get("key") or mod_data.get("mod_key")
                    else:
                        key = get_mod_key(mod_data)
                    mod_name = get_mod_name(mod_data, "")
                    if not key or (key == mod_name and mod_name):
                        if mod_name and isinstance(mod_name, str):
                            sanitized = sanitize_filename(mod_name)
                            if sanitized:
                                key = f"local_{sanitized.lower().replace(' ', '_')}"
                            else:
                                key = None
                        else:
                            key = None
                    if key:
                        mod_keys.append(key)
                except Exception as e:
                    logging.error(
                        f"save_used_mods_state: Failed to extract mod key from {mod_data!r}: {e}",
                        exc_info=True,
                    )
                    continue
            if mod_keys:
                if len(mod_keys) == 1:
                    used_mods_data[str(chapter_id)] = mod_keys[0]
                else:
                    used_mods_data[str(chapter_id)] = mod_keys
        for ch_id, keys in getattr(self, "_pending_mod_keys", {}).items():
            ch_str = str(ch_id)
            if ch_id not in active_ids:
                continue
            if ch_str not in used_mods_data:
                used_mods_data[ch_str] = keys if len(keys) > 1 else keys[0]
            else:
                existing = used_mods_data[ch_str]
                merged = [existing] if isinstance(existing, str) else list(existing)
                for k in keys:
                    if k not in merged:
                        merged.append(k)
                used_mods_data[ch_str] = merged if len(merged) > 1 else merged[0]
        self.app_state.local_config[config_key] = {
            str(k): v
            for k, v in used_mods_data.items()
            if k in active_ids or str(k) in active_ids
        }
        self.settings_service.write_local_config()

    def load_used_mods_state(self):
        is_chapter_mode = self.app_state.current_mode == "chapter"
        gm = self.app_state.game_mode
        active_ids = (
            {tab.tab_id for tab in gm.tabs}
            if is_chapter_mode
            else {get_chapter_id_for_game_mode(gm)}
        )
        self.used_mods = {
            chapter_id: mods
            for chapter_id, mods in self.used_mods.items()
            if chapter_id in active_ids
        }

        modes_to_load = [is_chapter_mode]
        if len(self.used_mods) == 0:
            modes_to_load = [True, False]

        needs_save = False
        did_process = False
        for chapter_mode in modes_to_load:
            config_key = self.get_used_mods_config_key(
                self.app_state.game_mode, chapter_mode
            )
            used_mods_data = self.app_state.local_config.get(config_key, {})
            if not used_mods_data:
                continue
            did_process = True

            gm = self.app_state.game_mode
            valid_tab_ids = {tab.tab_id for tab in gm.tabs}
            expected_id = get_chapter_id_for_game_mode(gm)
            for chapter_id_str, mod_data_raw in list(used_mods_data.items()):
                chapter_id = self._migrate_legacy_id(chapter_id_str)
                if (
                    not chapter_mode
                    and expected_id != gm.game_id
                    and chapter_id != expected_id
                ):
                    continue
                if chapter_mode and chapter_id not in valid_tab_ids:
                    continue
                if (
                    not chapter_mode
                    and expected_id == gm.game_id
                    and chapter_id != expected_id
                ):
                    continue
                mod_keys = (
                    [mod_data_raw]
                    if isinstance(mod_data_raw, str)
                    else (mod_data_raw if isinstance(mod_data_raw, list) else [])
                )
                if isinstance(mod_data_raw, str):
                    needs_save = True
                if not mod_keys:
                    continue
                mods_list, missing_keys = [], []
                for key in mod_keys:
                    if not key:
                        continue
                    if mod_data := self._find_mod_by_key(key):
                        mods_list.append(mod_data)
                    else:
                        missing_keys.append(key)
                if mods_list:
                    self.used_mods[chapter_id] = mods_list
                if missing_keys:
                    if not hasattr(self, "_pending_mod_keys"):
                        self._pending_mod_keys = {}
                    self._pending_mod_keys[chapter_id] = missing_keys
                else:
                    if (
                        hasattr(self, "_pending_mod_keys")
                        and chapter_id in self._pending_mod_keys
                    ):
                        del self._pending_mod_keys[chapter_id]
                if (
                    not missing_keys
                    and not mods_list
                    and chapter_id_str in used_mods_data
                    and not (
                        hasattr(self, "_pending_mod_keys")
                        and chapter_id in self._pending_mod_keys
                    )
                ):
                    del used_mods_data[chapter_id_str]
                    needs_save = True
        if did_process or (
            hasattr(self.app_state, "all_mods") and self.app_state.all_mods
        ):
            self._mods_state_loaded = True
        if needs_save:
            self.save_used_mods_state()
        self.used_mods_updated.emit()
        self.mod_widgets_update_needed.emit()
        self.action_button_update_needed.emit()

    def _find_mod_by_key(self, key: str):
        """Find mod by key from all_mods, installed mods, or config."""
        if hasattr(self.app_state, "all_mods") and self.app_state.all_mods:
            for mod in self.app_state.all_mods:
                if get_mod_key(mod) == key:
                    return mod
        if self.parent_widget:
            for im in self.mod_service.get_installed_mods_list():
                im_key = im.get("mod_key") or im.get("key") or im.get("name")
                if im_key == key or (
                    key.startswith("gb_")
                    and (im.get("key") or im.get("mod_key")) == key
                ):
                    return self.mod_service.create_mod_object_from_info(
                        im, getattr(self.app_state, "all_mods", None)
                    )
            if mod_config := self.mod_service.get_mod_config(key):
                return self.mod_service.create_mod_object_from_info(
                    mod_config, getattr(self.app_state, "all_mods", None)
                )
        return None

    def _is_local_mod(self, mod_data):
        key = get_mod_key(mod_data)
        return key and isinstance(key, str) and key.startswith("local_")

    def check_used_mods_need_updates(self) -> bool:
        return any(
            self.mod_service.mod_has_update_available(m)
            for mods in self.used_mods.values()
            for m in mods
            if not self._is_local_mod(m)
        )

    def collect_mods_needing_update(self) -> list:
        if getattr(self.app_state, "is_installing", False):
            return []
        gm = self.app_state.game_mode
        is_chapter_mode = self.app_state.current_mode == "chapter"
        active_ids = (
            [tab.tab_id for tab in gm.tabs]
            if is_chapter_mode
            else [get_chapter_id_for_game_mode(gm)]
        )
        mods_to_update = []
        for cid in active_ids:
            for mod in self.used_mods.get(cid, []):
                if (
                    not self._is_local_mod(mod)
                    and self.mod_service.mod_has_update_available(mod)
                    and mod not in mods_to_update
                ):
                    mods_to_update.append(mod)
        return mods_to_update

    def get_active_mod_selections(self) -> dict[str, list[Any]]:
        gm = self.app_state.game_mode
        empty = {tab.tab_id: [] for tab in gm.tabs}
        if not self.used_mods:
            return empty
        default_id = get_chapter_id_for_game_mode(gm)
        if not gm.is_multi_tab:
            return {default_id: self.get_used_mods_list(default_id)}
        if self.app_state.current_mode == "chapter":
            return {
                tab.tab_id: self.get_used_mods_list(tab.tab_id) or [] for tab in gm.tabs
            }
        mods_list = self.get_used_mods_list(default_id)
        if not mods_list:
            return empty
        return {
            tab.tab_id: [
                m
                for m in mods_list
                if hasattr(m, "get_chapter_data") and m.get_chapter_data(tab.tab_id)
            ]
            for tab in gm.tabs
        }

    def toggle_direct_launch_for_chapter(self, chapter_id: str):
        if chapter_id.endswith("_0"):
            self.feedback_service.show_message(
                "info", "ui.direct_launch", tr("ui.direct_launch_menu_not_allowed")
            )
            return
        current_direct_launch = self.app_state.local_config.get(
            "direct_launch_chapter", ""
        )
        is_currently_enabled = current_direct_launch == chapter_id
        tab = self.app_state.game_mode.get_tab(chapter_id)
        chapter_name = tr(tab.name_key) if tab else chapter_id
        msg_key = (
            "ui.disable_direct_launch"
            if is_currently_enabled
            else "ui.enable_direct_launch"
        )
        if not self.feedback_service.ask_question(
            "ui.direct_launch",
            "ui.direct_launch",
            tr(msg_key, chapter=chapter_name),
            False,
        ):
            return
        self.app_state.local_config["direct_launch_chapter"] = (
            "" if is_currently_enabled else chapter_id
        )
        self.settings_service.write_local_config()
        self.action_button_update_needed.emit()
        if self.parent_widget and hasattr(
            self.parent_widget, "launch_via_steam_checkbox"
        ):
            self._update_steam_checkbox_state()
        if self.parent_widget and hasattr(
            self.parent_widget, "_update_chapter_tabs_style"
        ):
            self.parent_widget._update_chapter_tabs_style()

    def _update_steam_checkbox_state(self):
        if not self.parent_widget:
            return
        if hasattr(self.parent_widget, "_update_steam_launch_checkbox_state"):
            self.parent_widget._update_steam_launch_checkbox_state()

    @staticmethod
    def _migrate_legacy_id(chapter_id_str: str) -> str:
        """Convert old numeric chapter IDs to new string-based IDs."""
        legacy_map = {
            "-1": "deltarune",
            "0": "deltarune_0",
            "1": "deltarune_1",
            "2": "deltarune_2",
            "3": "deltarune_3",
            "4": "deltarune_4",
            "-10": "deltarunedemo",
            "-20": "undertale",
            "-30": "undertaleyellow",
            "-40": "pizzatower",
            "-50": "sugaryspire",
        }
        if chapter_id_str in legacy_map:
            return legacy_map[chapter_id_str]
        return chapter_id_str
