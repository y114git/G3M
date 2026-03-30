"""Used mods tracking and management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from app.window import AppWindow

from app.game_ui import update_chapter_tabs_style, update_steam_launch_checkbox_state
from models.app_state import AppState
from services.game_detection_service import get_chapter_id_for_game_mode
from services.localization_service import tr
from services.migration_service import migrate_legacy_chapter_id
from services.mod_service import ModManager
from services.settings_service import SettingsManager
from ui.common.feedback import FeedbackManager
from utils.file_utils import sanitize_filename
from utils.mod_utils import get_mod_id, get_mod_name


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
        mod_id = get_mod_id(mod_data) if mod_data else None
        current_mods = self.used_mods.get(chapter_id, [])
        if mod_data is None:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        elif mod_id:
            found_index = next(
                (i for i, m in enumerate(current_mods) if get_mod_id(m) == mod_id), None
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
        if not mod_data or not (mod_id := get_mod_id(mod_data)):
            return False
        return any(get_mod_id(m) == mod_id for m in self.used_mods.get(chapter_id, []))

    def remove_mod_from_all_chapters(self, mod_data):
        mod_id = get_mod_id(mod_data)
        if not mod_id:
            return
        chapters_changed = []
        for chapter_id, used_mods_list in list(self.used_mods.items()):
            updated_list = [m for m in used_mods_list if get_mod_id(m) != mod_id]
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
        self._cleanup_mod_from_all_config_entries(mod_id)

    def _cleanup_mod_from_all_config_entries(self, mod_id: str):
        if not mod_id:
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
                    if mod_data_raw == mod_id:
                        chapters_to_clear.append(chapter_id_str)
                elif isinstance(mod_data_raw, list) and mod_id in mod_data_raw:
                    updated_list = [k for k in mod_data_raw if k != mod_id]
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
        config_id = getattr(game_mode, "used_mods_config_key", "")
        if config_id:
            return config_id
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
            mod_ids = []
            for mod_data in mods_list:
                try:
                    mod_id = (
                        mod_data.get("id")
                        if isinstance(mod_data, dict)
                        else get_mod_id(mod_data)
                    )
                    mod_name = get_mod_name(mod_data, "")
                    if not mod_id or (mod_id == mod_name and mod_name):
                        if mod_name and isinstance(mod_name, str):
                            sanitized = sanitize_filename(mod_name)
                            if sanitized:
                                mod_id = f"local_{sanitized.lower().replace(' ', '_')}"
                            else:
                                mod_id = None
                        else:
                            mod_id = None
                    if mod_id:
                        mod_ids.append(mod_id)
                except Exception as e:
                    logging.error(
                        f"save_used_mods_state: Failed to extract mod id from {mod_data!r}: {e}",
                        exc_info=True,
                    )
                    continue
            if mod_ids:
                if len(mod_ids) == 1:
                    used_mods_data[str(chapter_id)] = mod_ids[0]
                else:
                    used_mods_data[str(chapter_id)] = mod_ids
        for ch_id, pending_mod_ids in getattr(self, "_pending_mod_ids", {}).items():
            ch_str = str(ch_id)
            if ch_id not in active_ids:
                continue
            if ch_str not in used_mods_data:
                used_mods_data[ch_str] = (
                    pending_mod_ids
                    if len(pending_mod_ids) > 1
                    else pending_mod_ids[0]
                )
            else:
                existing = used_mods_data[ch_str]
                merged = [existing] if isinstance(existing, str) else list(existing)
                for mod_id in pending_mod_ids:
                    if mod_id not in merged:
                        merged.append(mod_id)
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

            migrations_needed = []
            for chapter_id_str, mod_data_raw in list(used_mods_data.items()):
                chapter_id = migrate_legacy_chapter_id(chapter_id_str)
                if chapter_id != chapter_id_str:
                    migrations_needed.append((chapter_id_str, chapter_id, mod_data_raw))

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
                mod_ids = (
                    [mod_data_raw]
                    if isinstance(mod_data_raw, str)
                    else (mod_data_raw if isinstance(mod_data_raw, list) else [])
                )
                if isinstance(mod_data_raw, str):
                    needs_save = True
                if not mod_ids:
                    continue
                mods_list, missing_mod_ids = [], []
                for mod_id in mod_ids:
                    if not mod_id:
                        continue
                    if mod_data := self._find_mod_by_id(mod_id):
                        mods_list.append(mod_data)
                    else:
                        missing_mod_ids.append(mod_id)
                if mods_list:
                    self.used_mods[chapter_id] = mods_list
                if missing_mod_ids:
                    if not hasattr(self, "_pending_mod_ids"):
                        self._pending_mod_ids = {}
                    self._pending_mod_ids[chapter_id] = missing_mod_ids
                else:
                    if (
                        hasattr(self, "_pending_mod_ids")
                        and chapter_id in self._pending_mod_ids
                    ):
                        del self._pending_mod_ids[chapter_id]
                if (
                    not missing_mod_ids
                    and not mods_list
                    and chapter_id_str in used_mods_data
                    and not (
                        hasattr(self, "_pending_mod_ids")
                        and chapter_id in self._pending_mod_ids
                    )
                    ):
                    del used_mods_data[chapter_id_str]
                    needs_save = True
            if migrations_needed:
                current_keys = set(used_mods_data.keys())
                for old_chapter_id, new_chapter_id, mod_data in migrations_needed:
                    if old_chapter_id not in current_keys:
                        continue
                    used_mods_data[new_chapter_id] = mod_data
                    if old_chapter_id in used_mods_data:
                        del used_mods_data[old_chapter_id]
                self.app_state.local_config[config_key] = used_mods_data
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

    def _find_mod_by_id(self, mod_id: str):
        """Find mod by id from all_mods, installed mods, or config."""
        if hasattr(self.app_state, "all_mods") and self.app_state.all_mods:
            for mod in self.app_state.all_mods:
                if get_mod_id(mod) == mod_id:
                    return mod
        if self.parent_widget:
            for im in self.mod_service.get_installed_mods_list():
                installed_mod_id = im.get("id")
                if installed_mod_id == mod_id:
                    return self.mod_service.create_mod_object_from_info(
                        im, getattr(self.app_state, "all_mods", None)
                    )
            if mod_config := self.mod_service.get_mod_config(mod_id):
                return self.mod_service.create_mod_object_from_info(
                    mod_config, getattr(self.app_state, "all_mods", None)
                )
        return None

    def _is_local_mod(self, mod_data):
        mod_id = get_mod_id(mod_data)
        return mod_id and isinstance(mod_id, str) and mod_id.startswith("local_")

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
        if self.parent_widget:
            update_chapter_tabs_style(self.parent_widget)

    def _update_steam_checkbox_state(self):
        if not self.parent_widget:
            return
        update_steam_launch_checkbox_state(self.parent_widget)

    def record_session_playtime(self, seconds: float) -> None:
        if seconds <= 0:
            return
        mod_service = getattr(self.app_state, "mod_service", None)
        if not mod_service:
            return
        active_mod_ids = []
        seen = set()
        for mods in self.used_mods.values():
            for mod in mods:
                mod_id = get_mod_id(mod)
                if not mod_id or mod_id in seen or mod_id.startswith("local_"):
                    continue
                seen.add(mod_id)
                active_mod_ids.append(mod_id)
        if active_mod_ids:
            mod_service.add_playtime_hours(active_mod_ids, seconds / 3600.0)
