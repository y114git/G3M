"""Used mods tracking and slot management."""
import logging
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from typing import Dict, Optional, Any, List, TYPE_CHECKING
if TYPE_CHECKING:
    from core.app_window import AppWindow
from core.app_state import AppState
from ui.common.feedback import FeedbackManager
from services.mod_service import ModManager
from services.settings_service import SettingsManager
from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode, FullGameMode
from services.localization_service import tr
from config.constants import SLOT_ID_UNIVERSAL, SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
from utils.mod_utils import get_mod_key, get_mod_name
from services.game_detection_service import get_chapter_id_for_game_mode
from utils.file_utils import sanitize_filename


class UsedModsManager(QObject):
    used_mods_updated, used_mod_changed = pyqtSignal(), pyqtSignal(int)
    action_button_update_needed, mod_widgets_update_needed = pyqtSignal(), pyqtSignal()

    def __init__(self, app_state: AppState, mod_service: ModManager, feedback_service: FeedbackManager, settings_service: SettingsManager, parent: Optional['AppWindow'] = None):
        super().__init__(parent)
        self.app_state, self.mod_service = app_state, mod_service
        self.feedback_service, self.settings_service = feedback_service, settings_service
        self.parent_widget: Optional['AppWindow'] = parent
        self.used_mods: Dict[int, List[Any]] = {}

    def get_used_mod(self, chapter_id: int):
        mods_list = self.used_mods.get(chapter_id, [])
        return mods_list[0] if mods_list else None

    def get_used_mods_list(self, chapter_id: int) -> List[Any]:
        return self.used_mods.get(chapter_id, [])

    def set_used_mod(self, chapter_id: int, mod_data: Optional[Any], save_state: bool = True) -> None:
        key = get_mod_key(mod_data) if mod_data else None
        current_mods = self.used_mods.get(chapter_id, [])
        if mod_data is None:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        elif key:
            found_index = next((i for i, m in enumerate(current_mods) if get_mod_key(m) == key), None)
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
            except Exception:
                pass

    def set_mods_list(self, chapter_id: int, mods_list: List[Any], save_state: bool = True) -> None:
        if not mods_list:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        else:
            self.used_mods[chapter_id] = mods_list
        self.used_mod_changed.emit(chapter_id)
        if save_state:
            try:
                self.save_used_mods_state()
            except Exception:
                pass

    def is_mod_used_for_chapter(self, mod_data, chapter_id: int) -> bool:
        if not mod_data or not (key := get_mod_key(mod_data)):
            return False
        return any(get_mod_key(m) == key for m in self.used_mods.get(chapter_id, []))

    def is_mod_used_anywhere(self, mod_data) -> bool:
        if not mod_data or not (key := get_mod_key(mod_data)):
            return False
        return any(get_mod_key(m) == key for mods in self.used_mods.values() for m in mods)

    def remove_mod_from_all_chapters(self, mod_data):
        key = get_mod_key(mod_data)
        if not key:
            return
        chapters_changed = []
        for chapter_id, used_mods_list in list(self.used_mods.items()):
            updated_list = []
            for used_mod in used_mods_list:
                used_mod_key = get_mod_key(used_mod)
                if used_mod_key != key:
                    updated_list.append(used_mod)
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
        config_keys = ['used_mods_deltarune', 'used_mods_deltarune_chapter', 'used_mods_deltarunedemo', 'used_mods_undertale', 'used_mods_undertaleyellow', 'used_mods_pizzatower']
        for config_key in list(self.app_state.local_config.keys()):
            if config_key.startswith('used_mods_') and config_key not in config_keys:
                config_keys.append(config_key)
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
                elif isinstance(mod_data_raw, list):
                    if mod_key in mod_data_raw:
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
            logging.info(f'_cleanup_mod_from_all_config_keys: Removed mod {mod_key} from all config keys')

    _GAME_MODE_CONFIG_KEYS = {
        DemoGameMode: 'used_mods_deltarunedemo',
        UndertaleGameMode: 'used_mods_undertale',
        UndertaleYellowGameMode: 'used_mods_undertaleyellow',
        PizzaTowerGameMode: 'used_mods_pizzatower',
        SugarySpireGameMode: 'used_mods_sugaryspire',
    }

    def get_used_mods_config_key(self, game_mode_instance=None, is_chapter_mode: Optional[bool] = None):
        game_mode = game_mode_instance or self.app_state.game_mode
        is_chapter = is_chapter_mode if is_chapter_mode is not None else self.app_state.current_mode == 'chapter'
        key = self._GAME_MODE_CONFIG_KEYS.get(type(game_mode))
        if key:
            return key
        return 'used_mods_deltarune_chapter' if is_chapter else 'used_mods_deltarune'

    def save_used_mods_state(self):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_used_mods_config_key(self.app_state.game_mode, is_chapter_mode)
        used_mods_data = {}
        for chapter_id, mods_list in self.used_mods.items():
            mod_keys = []
            for mod_data in mods_list:
                try:
                    if isinstance(mod_data, dict):
                        key = mod_data.get('key') or mod_data.get('mod_key')
                    else:
                        key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                    mod_name = get_mod_name(mod_data, '')
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
                except Exception:
                    continue
            if mod_keys:
                if len(mod_keys) == 1:
                    used_mods_data[str(chapter_id)] = mod_keys[0]
                else:
                    used_mods_data[str(chapter_id)] = mod_keys
        self.app_state.local_config[config_key] = used_mods_data
        self.settings_service.write_local_config()
        logging.info(f'save_used_mods_state: Saved {len(used_mods_data)} chapter(s) with mods')

    def load_used_mods_state(self, mode=None):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_used_mods_config_key(self.app_state.game_mode, is_chapter_mode)
        used_mods_data = self.app_state.local_config.get(config_key, {})
        if not used_mods_data:
            self.used_mods.clear()
            self.used_mods_updated.emit()
            return
        if not (hasattr(self.app_state, 'all_mods') and self.app_state.all_mods):
            return
        self.used_mods.clear()
        needs_save = False
        valid_chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
        expected_chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
        for chapter_id_str, mod_data_raw in list(used_mods_data.items()):
            try:
                chapter_id = int(chapter_id_str)
            except ValueError:
                continue
            if not is_chapter_mode and expected_chapter_id != SLOT_ID_UNIVERSAL and chapter_id != expected_chapter_id:
                continue
            if is_chapter_mode and chapter_id not in valid_chapter_ids:
                continue
            if not is_chapter_mode and expected_chapter_id == SLOT_ID_UNIVERSAL and chapter_id != SLOT_ID_UNIVERSAL:
                continue
            mod_keys = [mod_data_raw] if isinstance(mod_data_raw, str) else (mod_data_raw if isinstance(mod_data_raw, list) else [])
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
                if not hasattr(self, '_pending_mod_keys'):
                    self._pending_mod_keys = {}
                self._pending_mod_keys[chapter_id] = missing_keys
            elif chapter_id_str in used_mods_data and not mods_list and not (hasattr(self, '_pending_mod_keys') and chapter_id in self._pending_mod_keys):
                del used_mods_data[chapter_id_str]
                needs_save = True
        if needs_save:
            self.save_used_mods_state()
        QTimer.singleShot(100, self.used_mods_updated.emit)
        QTimer.singleShot(200, self.mod_widgets_update_needed.emit)
        QTimer.singleShot(300, self.action_button_update_needed.emit)

    def _find_mod_by_key(self, key: str):
        """Find mod by key from all_mods, installed mods, or config."""
        if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
            for mod in self.app_state.all_mods:
                if get_mod_key(mod) == key:
                    return mod
                if key.startswith('gb_') and (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key:
                    return mod
        if self.parent_widget:
            for im in self.mod_service.get_installed_mods_list():
                im_key = im.get('mod_key') or im.get('key') or im.get('name')
                if im_key == key or (key.startswith('gb_') and (im.get('key') or im.get('mod_key')) == key):
                    return self.mod_service.create_mod_object_from_info(im, getattr(self.app_state, 'all_mods', None))
            if mod_config := self.mod_service.get_mod_config(key):
                return self.mod_service.create_mod_object_from_info(mod_config, getattr(self.app_state, 'all_mods', None))
        return None

    def _retry_load_missing_mods(self):
        if not getattr(self, '_pending_mod_keys', None):
            return
        needs_save = False
        for chapter_id, missing_keys in list(self._pending_mod_keys.items()):
            found_mods = [m for key in missing_keys if (m := self._find_mod_by_key(key))]
            if found_mods:
                existing_mods = self.used_mods.get(chapter_id, [])
                existing_keys = {get_mod_key(m) for m in existing_mods}
                for mod in found_mods:
                    if get_mod_key(mod) not in existing_keys:
                        existing_mods.append(mod)
                self.used_mods[chapter_id] = existing_mods
                needs_save = True
            remaining = [k for k in missing_keys if not any(get_mod_key(m) == k for m in found_mods)]
            if remaining:
                self._pending_mod_keys[chapter_id] = remaining
            else:
                del self._pending_mod_keys[chapter_id]
        if needs_save:
            self.save_used_mods_state()
            self.used_mods_updated.emit()
            self.mod_widgets_update_needed.emit()

    def _is_local_mod(self, mod_data):
        key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
        return key and isinstance(key, str) and key.startswith('local_')

    def check_used_mods_need_updates(self) -> bool:
        return any(self.mod_service.mod_has_update_available(m) for mods in self.used_mods.values() for m in mods if not self._is_local_mod(m))

    def collect_mods_needing_update(self) -> list:
        if getattr(self.app_state, 'is_installing', False):
            return []
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        active_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4] if is_chapter_mode else [get_chapter_id_for_game_mode(self.app_state.game_mode)]
        mods_to_update = []
        for cid in active_ids:
            for mod in self.used_mods.get(cid, []):
                if not self._is_local_mod(mod) and self.mod_service.mod_has_update_available(mod) and mod not in mods_to_update:
                    mods_to_update.append(mod)
        return mods_to_update

    def get_active_mod_selections(self) -> Dict[int, List[Any]]:
        selections = {}
        if not self.used_mods:
            for chapter_id in range(5):
                selections[chapter_id] = []
            return selections
        chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
        if chapter_id != SLOT_ID_UNIVERSAL:
            mods_list = self.get_used_mods_list(chapter_id)
            selections[-1] = mods_list if mods_list else []
        elif self.app_state.current_mode == 'normal':
            mods_list = self.get_used_mods_list(SLOT_ID_UNIVERSAL)
            if mods_list:
                for chapter_id in range(5):
                    chapter_mods = []
                    for mod in mods_list:
                        if hasattr(mod, 'get_chapter_data') and mod.get_chapter_data(chapter_id):
                            chapter_mods.append(mod)
                    selections[chapter_id] = chapter_mods
            else:
                used_mod = self.get_used_mod(SLOT_ID_UNIVERSAL)
                if used_mod:
                    for chapter_id in range(5):
                        if hasattr(used_mod, 'get_chapter_data') and used_mod.get_chapter_data(chapter_id):
                            selections[chapter_id] = [used_mod]
                        else:
                            selections[chapter_id] = []
                else:
                    for chapter_id in range(5):
                        selections[chapter_id] = []
        elif self.app_state.current_mode == 'chapter':
            for chapter_id in range(5):
                mods_list = self.get_used_mods_list(chapter_id)
                selections[chapter_id] = mods_list if mods_list else []
        return selections

    def toggle_direct_launch_for_chapter(self, chapter_id: int):
        if chapter_id == 0:
            self.feedback_service.show_message('info', 'ui.direct_launch', tr('ui.direct_launch_menu_not_allowed'))
            return
        current_direct_launch = self.app_state.local_config.get('direct_launch_slot_id', -1)
        is_currently_enabled = current_direct_launch == chapter_id
        chapter_names = {1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
        chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_n', chapter=str(chapter_id)))
        if is_currently_enabled:
            message = tr('ui.disable_direct_launch', chapter=chapter_name)
            if not self.feedback_service.ask_question('ui.direct_launch', 'ui.direct_launch', message, False):
                return
            self.app_state.local_config['direct_launch_slot_id'] = -1
        else:
            message = tr('ui.enable_direct_launch', chapter=chapter_name)
            if not self.feedback_service.ask_question('ui.direct_launch', 'ui.direct_launch', message, False):
                return
            self.app_state.local_config['direct_launch_slot_id'] = chapter_id
        self.settings_service.write_local_config()
        self.action_button_update_needed.emit()
        if self.parent_widget and hasattr(self.parent_widget, 'launch_via_steam_checkbox'):
            self._update_steam_checkbox_state()
        if self.parent_widget and hasattr(self.parent_widget, '_update_chapter_tabs_style'):
            self.parent_widget._update_chapter_tabs_style()

    def _update_steam_checkbox_state(self):
        if not self.parent_widget or not hasattr(self.parent_widget, 'launch_via_steam_checkbox'):
            return
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        is_deltarune = isinstance(self.app_state.game_mode, FullGameMode)
        should_block = is_deltarune and is_chapter_mode and (direct_launch_slot_id >= 0)
        self.parent_widget.launch_via_steam_checkbox.setEnabled(not should_block)
