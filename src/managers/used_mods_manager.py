import logging
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from typing import Dict, Optional, Any, List, TYPE_CHECKING
if TYPE_CHECKING:
    from core.app_window import AppWindow
from core.app_state import AppState
from ui.common.feedback import FeedbackManager
from managers.mod_manager import ModManager
from managers.settings_manager import SettingsManager
from models.game_modes import DemoGameMode, UndertaleGameMode
from managers.localization_manager import tr
from config.constants import SLOT_ID_UNIVERSAL, SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
from utils.mod_utils import get_mod_key, get_mod_name
from utils.game_utils import is_demo_mode, is_undertale_mode


class UsedModsManager(QObject):
    used_mods_updated = pyqtSignal()
    used_mod_changed = pyqtSignal(int)
    action_button_update_needed = pyqtSignal()
    mod_widgets_update_needed = pyqtSignal()

    def __init__(self, app_state: AppState, mod_manager: ModManager, feedback_manager: FeedbackManager, settings_manager: SettingsManager, parent: Optional['AppWindow'] = None):
        super().__init__(parent)
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.feedback_manager = feedback_manager
        self.settings_manager = settings_manager
        self.parent_widget: Optional['AppWindow'] = parent
        self.used_mods: Dict[int, List[Any]] = {}

    def get_used_mod(self, chapter_id: int):
        mods_list = self.used_mods.get(chapter_id, [])
        return mods_list[0] if mods_list else None

    def get_used_mods_list(self, chapter_id: int) -> List[Any]:
        return self.used_mods.get(chapter_id, [])

    def set_used_mod(self, chapter_id: int, mod_data: Optional[Any], save_state: bool = True) -> None:
        import logging
        mod_key = get_mod_key(mod_data) if mod_data else None
        mod_name = get_mod_name(mod_data, 'None') if mod_data else 'None'
        logging.debug(f'set_used_mod: chapter_id={chapter_id}, mod={mod_name} (key={mod_key})')
        current_mods = self.used_mods.get(chapter_id, [])
        if mod_data is None:
            logging.info(f'Removing all mods from chapter {chapter_id}')
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        elif mod_key:
            found_index = None
            for i, existing_mod in enumerate(current_mods):
                existing_key = get_mod_key(existing_mod)
                if existing_key == mod_key:
                    found_index = i
                    break
            if found_index is not None:
                logging.info(f'Removing mod {mod_name} from chapter {chapter_id} (toggle off)')
                current_mods.pop(found_index)
                if not current_mods:
                    if chapter_id in self.used_mods:
                        del self.used_mods[chapter_id]
                    logging.info(f'No mods remaining for chapter {chapter_id}')
                else:
                    self.used_mods[chapter_id] = current_mods
                    logging.info(f'Chapter {chapter_id} now has {len(current_mods)} mod(s)')
            else:
                current_mods.insert(0, mod_data)
                self.used_mods[chapter_id] = current_mods
                logging.info(f'Chapter {chapter_id} now has {len(current_mods)} mod(s)')
        self.used_mod_changed.emit(chapter_id)
        if save_state:
            try:
                self.save_used_mods_state()
            except Exception as e:
                logging.warning(f'set_used_mod: save_state failed: {e}')

    def set_mods_list(self, chapter_id: int, mods_list: List[Any], save_state: bool = True) -> None:
        import logging
        mod_names = [get_mod_name(m, 'Unknown') for m in mods_list] if mods_list else []
        logging.info(f'set_mods_list: chapter_id={chapter_id}, mods={mod_names}, count={(len(mods_list) if mods_list else 0)}')
        if not mods_list:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
                logging.info(f'Removed all mods from chapter {chapter_id}')
        else:
            self.used_mods[chapter_id] = mods_list
            logging.info(f'Set mod list for chapter {chapter_id}: {len(mods_list)} mod(s)')
        self.used_mod_changed.emit(chapter_id)
        if save_state:
            try:
                self.save_used_mods_state()
                logging.debug('Saved mods state after set_mods_list')
            except Exception as e:
                logging.warning(f'set_mods_list: save_state failed: {e}')

    def is_mod_used_for_chapter(self, mod_data, chapter_id: int) -> bool:
        if not mod_data:
            return False
        mod_key = get_mod_key(mod_data)
        if not mod_key:
            return False
        used_mods_list = self.used_mods.get(chapter_id, [])
        if not used_mods_list:
            return False
        for used_mod in used_mods_list:
            used_mod_key = get_mod_key(used_mod)
            if used_mod_key == mod_key:
                return True
        return False

    def is_mod_used_anywhere(self, mod_data) -> bool:
        if not mod_data:
            return False
        mod_key = get_mod_key(mod_data)
        if not mod_key:
            return False
        for used_mods_list in self.used_mods.values():
            for used_mod in used_mods_list:
                used_mod_key = get_mod_key(used_mod)
                if used_mod_key == mod_key:
                    return True
        return False

    def remove_mod_from_all_chapters(self, mod_data):
        mod_key = get_mod_key(mod_data)
        if not mod_key:
            return
        chapters_changed = []
        for chapter_id, used_mods_list in list(self.used_mods.items()):
            updated_list = []
            for used_mod in used_mods_list:
                used_mod_key = get_mod_key(used_mod)
                if used_mod_key != mod_key:
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

    def get_used_mods_config_key(self, game_mode_instance=None, is_chapter_mode: Optional[bool] = None):
        if game_mode_instance is None:
            game_mode_instance = self.app_state.game_mode
        if is_chapter_mode is None:
            is_chapter_mode = self.app_state.current_mode == 'chapter'
        if isinstance(game_mode_instance, DemoGameMode):
            return 'used_mods_deltarunedemo'
        elif isinstance(game_mode_instance, UndertaleGameMode):
            return 'used_mods_undertale'
        else:
            return 'used_mods_deltarune_chapter' if is_chapter_mode else 'used_mods_deltarune'

    def save_used_mods_state(self):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_used_mods_config_key(self.app_state.game_mode, is_chapter_mode)
        used_mods_data = {}
        for chapter_id, mods_list in self.used_mods.items():
            mod_keys = []
            for mod_data in mods_list:
                mod_key = get_mod_key(mod_data)
                if mod_key:
                    mod_keys.append(mod_key)
            if mod_keys:
                if len(mod_keys) == 1:
                    used_mods_data[str(chapter_id)] = mod_keys[0]
                else:
                    used_mods_data[str(chapter_id)] = mod_keys
        self.app_state.local_config[config_key] = used_mods_data
        self.settings_manager.write_local_config()

    def load_used_mods_state(self, mode=None):
        import logging
        logging.info('Loading used mods state')
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_used_mods_config_key(self.app_state.game_mode, is_chapter_mode)
        used_mods_data = self.app_state.local_config.get(config_key, {})
        if not used_mods_data:
            logging.debug(f'No used mods data found for key: {config_key}')
            self.used_mods.clear()
            self.used_mods_updated.emit()
            return
        logging.info(f'Found used mods data for {len(used_mods_data)} chapter(s)')
        self.used_mods.clear()
        needs_save = False
        for chapter_id_str, mod_data_raw in list(used_mods_data.items()):
            try:
                chapter_id = int(chapter_id_str)
            except ValueError:
                continue
            is_chapter_mode = self.app_state.current_mode == 'chapter'
            if is_demo_mode(self.app_state.game_mode):
                if chapter_id != SLOT_ID_DEMO:
                    continue
            elif is_undertale_mode(self.app_state.game_mode):
                if chapter_id != SLOT_ID_UNDERTALE:
                    continue
            elif is_chapter_mode:
                if chapter_id not in [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]:
                    continue
            elif chapter_id != SLOT_ID_UNIVERSAL:
                continue
            mod_keys = []
            if isinstance(mod_data_raw, str):
                logging.info(f'Migrating chapter {chapter_id} from old format (string) to new format (list)')
                mod_keys = [mod_data_raw]
                needs_save = True
            elif isinstance(mod_data_raw, list):
                mod_keys = mod_data_raw
                logging.debug(f'Chapter {chapter_id} already in new format: {len(mod_keys)} mod(s)')
            else:
                logging.warning(f'Invalid mod data format for chapter {chapter_id}: {type(mod_data_raw)}')
                continue
            if not mod_keys:
                continue
            mods_list = []
            for mod_key in mod_keys:
                if not mod_key:
                    continue
                mod_data = None
                if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                    for mod in self.app_state.all_mods:
                        if getattr(mod, 'key', None) == mod_key:
                            mod_data = mod
                            break
                if not mod_data and self.parent_widget:
                    installed_mods = self.mod_manager.get_installed_mods_list()
                    for installed_mod in installed_mods:
                        installed_mod_key = installed_mod.get('mod_key') or installed_mod.get('key') or installed_mod.get('name')
                        if installed_mod_key == mod_key:
                            mod_data = self.mod_manager.create_mod_object_from_info(installed_mod, getattr(self.app_state, 'all_mods', None))
                            break
                if not mod_data and self.parent_widget:
                    mod_config = self.mod_manager.get_mod_config(mod_key)
                    if mod_config:
                        mod_data = self.mod_manager.create_mod_object_from_info(mod_config, getattr(self.app_state, 'all_mods', None))
                if mod_data:
                    mods_list.append(mod_data)
                else:
                    needs_save = True
            if mods_list:
                self.used_mods[chapter_id] = mods_list
                logging.info(f"Loaded {len(mods_list)} mod(s) for chapter {chapter_id}: {[get_mod_name(m, 'Unknown') for m in mods_list]}")
            elif chapter_id_str in used_mods_data:
                logging.warning(f'Removing invalid mod data for chapter {chapter_id} (mods not found)')
                del used_mods_data[chapter_id_str]
                needs_save = True
        if needs_save:
            logging.info('Saving used mods state after migration or cleanup')
            self.save_used_mods_state()
        logging.info(f'Loaded used mods for {len(self.used_mods)} chapter(s)')
        QTimer.singleShot(100, self.used_mods_updated.emit)
        QTimer.singleShot(200, self.mod_widgets_update_needed.emit)
        QTimer.singleShot(300, self.action_button_update_needed.emit)

    def check_used_mods_need_updates(self) -> bool:
        for mods_list in self.used_mods.values():
            for mod_data in mods_list:
                is_local_mod = getattr(mod_data, 'is_local_mod', False)
                if is_local_mod:
                    continue
                for i in range(5):
                    if self.mod_manager.mod_has_files_for_chapter(mod_data, i):
                        status = self.mod_manager.get_mod_status(mod_data, i)
                        if status == 'update':
                            return True
        return False

    def collect_mods_needing_update(self) -> list:
        if getattr(self.app_state, 'is_installing', False):
            return []
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        if is_demo_mode(self.app_state.game_mode):
            active_chapter_ids = [SLOT_ID_DEMO]
        elif is_undertale_mode(self.app_state.game_mode):
            active_chapter_ids = [SLOT_ID_UNDERTALE]
        elif is_chapter_mode:
            active_chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
        else:
            active_chapter_ids = [SLOT_ID_UNIVERSAL]
        mods_to_update = []
        for chapter_id in active_chapter_ids:
            mods_list = self.used_mods.get(chapter_id, [])
            for mod_data in mods_list:
                if getattr(mod_data, 'is_local_mod', False):
                    continue
                needs_update = self.mod_manager.mod_has_update_available(mod_data)
                if needs_update and mod_data not in mods_to_update:
                    mods_to_update.append(mod_data)
        return mods_to_update

    def get_active_mod_selections(self) -> Dict[int, List[Any]]:
        selections = {}
        if not self.used_mods:
            for chapter_id in range(5):
                selections[chapter_id] = []
            return selections
        if is_demo_mode(self.app_state.game_mode):
            mods_list = self.get_used_mods_list(SLOT_ID_DEMO)
            selections[-1] = mods_list if mods_list else []
        elif is_undertale_mode(self.app_state.game_mode):
            mods_list = self.get_used_mods_list(SLOT_ID_UNDERTALE)
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
            self.feedback_manager.show_message('info', 'ui.direct_launch', tr('ui.direct_launch_menu_not_allowed'))
            return
        current_direct_launch = self.app_state.local_config.get('direct_launch_slot_id', -1)
        is_currently_enabled = current_direct_launch == chapter_id
        if is_currently_enabled:
            chapter_names = {1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
            chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_n', chapter=str(chapter_id)))
            message = tr('ui.disable_direct_launch', chapter=chapter_name)
            if not self.feedback_manager.ask_question('ui.direct_launch', 'ui.direct_launch', message, False):
                return
            self.app_state.local_config['direct_launch_slot_id'] = -1
        else:
            chapter_names = {1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
            chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_n', chapter=str(chapter_id)))
            message = tr('ui.enable_direct_launch', chapter=chapter_name)
            if not self.feedback_manager.ask_question('ui.direct_launch', 'ui.direct_launch', message, False):
                return
            self.app_state.local_config['direct_launch_slot_id'] = chapter_id
        self.settings_manager.write_local_config()
        self.action_button_update_needed.emit()
        if self.parent_widget and hasattr(self.parent_widget, 'launch_via_steam_checkbox'):
            direct_launch_enabled = self.app_state.local_config.get('direct_launch_slot_id', -1) >= 0
            self.parent_widget.launch_via_steam_checkbox.setEnabled(not direct_launch_enabled)
        if self.parent_widget and hasattr(self.parent_widget, '_update_chapter_tabs_style'):
            self.parent_widget._update_chapter_tabs_style()
