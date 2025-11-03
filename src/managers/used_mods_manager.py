import logging
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from typing import Dict, Optional, Any, TYPE_CHECKING
if TYPE_CHECKING:
    from core.app_window import AppWindow
from core.app_state import AppState
from ui.common.feedback import FeedbackManager
from managers.mod_manager import ModManager
from managers.settings_manager import SettingsManager
from models.game_modes import DemoGameMode, UndertaleGameMode
from managers.localization_manager import tr
from config.constants import SLOT_ID_UNIVERSAL, SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4


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
        self.used_mods: Dict[int, Any] = {}

    def get_used_mod(self, chapter_id: int):
        return self.used_mods.get(chapter_id)

    def set_used_mod(self, chapter_id: int, mod_data: Optional[Any], save_state: bool = True) -> None:
        if mod_data is None:
            if chapter_id in self.used_mods:
                del self.used_mods[chapter_id]
        else:
            self.used_mods[chapter_id] = mod_data
        self.used_mod_changed.emit(chapter_id)
        if save_state:
            try:
                self.save_used_mods_state()
            except Exception as e:
                logging.warning(f'set_used_mod: save_state failed: {e}')

    def is_mod_used_for_chapter(self, mod_data, chapter_id: int) -> bool:
        if not mod_data:
            return False
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return False
        used_mod = self.used_mods.get(chapter_id)
        if not used_mod:
            return False
        used_mod_key = getattr(used_mod, 'key', None) or getattr(used_mod, 'mod_key', None) or getattr(used_mod, 'name', None)
        return used_mod_key == mod_key

    def is_mod_used_anywhere(self, mod_data) -> bool:
        if not mod_data:
            return False
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return False
        for used_mod in self.used_mods.values():
            used_mod_key = getattr(used_mod, 'key', None) or getattr(used_mod, 'mod_key', None) or getattr(used_mod, 'name', None)
            if used_mod_key == mod_key:
                return True
        return False

    def remove_mod_from_all_chapters(self, mod_data):
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return
        chapters_to_remove = []
        for chapter_id, used_mod in self.used_mods.items():
            used_mod_key = getattr(used_mod, 'key', None) or getattr(used_mod, 'mod_key', None) or getattr(used_mod, 'name', None)
            if used_mod_key == mod_key:
                chapters_to_remove.append(chapter_id)
        for chapter_id in chapters_to_remove:
            del self.used_mods[chapter_id]
        if chapters_to_remove:
            self.save_used_mods_state()
            for chapter_id in chapters_to_remove:
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
        for chapter_id, mod_data in self.used_mods.items():
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
            if mod_key:
                used_mods_data[str(chapter_id)] = mod_key
        self.app_state.local_config[config_key] = used_mods_data
        self.settings_manager.write_local_config()

    def load_used_mods_state(self, mode=None):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        config_key = self.get_used_mods_config_key(self.app_state.game_mode, is_chapter_mode)
        used_mods_data = self.app_state.local_config.get(config_key, {})
        if not used_mods_data:
            self.used_mods.clear()
            self.used_mods_updated.emit()
            return
        self.used_mods.clear()
        for chapter_id_str, mod_key in list(used_mods_data.items()):
            try:
                chapter_id = int(chapter_id_str)
            except ValueError:
                continue
            is_chapter_mode = self.app_state.current_mode == 'chapter'
            if isinstance(self.app_state.game_mode, DemoGameMode):
                if chapter_id != SLOT_ID_DEMO:
                    continue
            elif isinstance(self.app_state.game_mode, UndertaleGameMode):
                if chapter_id != SLOT_ID_UNDERTALE:
                    continue
            elif is_chapter_mode:
                if chapter_id not in [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]:
                    continue
            elif chapter_id != SLOT_ID_UNIVERSAL:
                continue
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
                self.used_mods[chapter_id] = mod_data
            elif chapter_id_str in used_mods_data:
                del used_mods_data[chapter_id_str]
        if used_mods_data != self.app_state.local_config.get(config_key, {}):
            self.app_state.local_config[config_key] = used_mods_data
            self.settings_manager.write_json(self.app_state.config_path, self.app_state.local_config)
        QTimer.singleShot(100, self.used_mods_updated.emit)
        QTimer.singleShot(200, self.mod_widgets_update_needed.emit)
        QTimer.singleShot(300, self.action_button_update_needed.emit)

    def check_used_mods_need_updates(self) -> bool:
        for mod_data in self.used_mods.values():
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
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        if is_demo_mode:
            active_chapter_ids = [SLOT_ID_DEMO]
        elif is_undertale_mode:
            active_chapter_ids = [SLOT_ID_UNDERTALE]
        elif is_chapter_mode:
            active_chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
        else:
            active_chapter_ids = [SLOT_ID_UNIVERSAL]
        mods_to_update = []
        for chapter_id in active_chapter_ids:
            mod_data = self.used_mods.get(chapter_id)
            if not mod_data:
                continue
            if getattr(mod_data, 'is_local_mod', False):
                continue
            needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
            if needs_update and mod_data not in mods_to_update:
                mods_to_update.append(mod_data)
        return mods_to_update

    def toggle_direct_launch_for_chapter(self, chapter_id: int):
        if chapter_id == 0:
            self.feedback_manager.show_info('ui.direct_launch', tr('ui.direct_launch_menu_not_allowed'))
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
