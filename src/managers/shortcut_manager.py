import os
import sys
import json
import base64
import platform
import logging
from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog
from core.app_state import AppState
from ui.common.feedback import FeedbackManager
from managers.mod_manager import ModManager
from models.game_modes import FullGameMode
from config.constants import LAUNCHER_VERSION, UI_COLORS, SLOT_ID_UNIVERSAL, SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
from managers.localization_manager import tr
from utils.path_utils import resource_path
from utils.mod_utils import get_mod_key
from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode


class ShortcutManager(QObject):
    shortcut_created = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)

    def __init__(self, app_state: AppState, feedback_manager: FeedbackManager, mod_manager: ModManager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.parent_widget = parent

    def create_shortcut_flow(self):
        settings = self._gather_shortcut_settings()
        if not settings:
            self.feedback_manager.show_message('warning', 'dialogs.cannot_create_shortcut_title', tr('dialogs.path_not_specified'))
            return
        description_lines = [tr('dialogs.shortcut_description'), '', tr('dialogs.current_shortcut_settings'), '']
        is_undertaleyellow = settings.get('is_undertaleyellow_mode', False)
        game_name = tr('ui.undertaleyellow') if is_undertaleyellow else tr('ui.undertale') if settings.get('is_undertale_mode', False) else tr('ui.deltarunedemo') if settings.get('is_demo_mode', False) else tr('ui.deltarune')
        description_lines.append(f"<b>{tr('ui.mod_type_label')}</b> {game_name}")
        if settings.get('is_demo_mode', False):
            mod_data = settings['mods'].get('demo')
            if mod_data:
                mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                mod_names = []
                for mod_key in mod_keys:
                    mod_config = self.mod_manager.get_mod_config(mod_key)
                    mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                    mod_names.append(mod_name)
                if len(mod_names) == 1:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_names[0]}")
                else:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {len(mod_names)} mod(s): {', '.join(mod_names)}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        elif settings.get('is_undertaleyellow_mode', False):
            mod_data = settings['mods'].get('undertaleyellow')
            if mod_data:
                mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                mod_names = []
                for mod_key in mod_keys:
                    mod_config = self.mod_manager.get_mod_config(mod_key)
                    mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                    mod_names.append(mod_name)
                if len(mod_names) == 1:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_names[0]}")
                else:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {len(mod_names)} mod(s): {', '.join(mod_names)}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        elif settings.get('is_undertale_mode', False):
            mod_data = settings['mods'].get('undertale')
            if mod_data:
                mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                mod_names = []
                for mod_key in mod_keys:
                    mod_config = self.mod_manager.get_mod_config(mod_key)
                    mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                    mod_names.append(mod_name)
                if len(mod_names) == 1:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_names[0]}")
                else:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {len(mod_names)} mod(s): {', '.join(mod_names)}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        else:
            is_chapter_mode = settings.get('is_chapter_mode', False)
            direct_launch_slot_id = settings.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
            if is_chapter_mode:
                if direct_launch_slot_id >= 0:
                    chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                    chapter_name = chapter_names.get(direct_launch_slot_id, tr('ui.chapter_tab_title', chapter_num=direct_launch_slot_id))
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {chapter_name}")
                else:
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {tr('status.disabled')}")
                for chapter_id in [0, 1, 2, 3, 4]:
                    mod_data = settings['mods'].get(str(chapter_id))
                    if mod_data:
                        mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                        mod_names = []
                        for mod_key in mod_keys:
                            mod_config = self.mod_manager.get_mod_config(mod_key)
                            mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                            mod_names.append(mod_name)
                        chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                        chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_tab_title', chapter_num=chapter_id))
                        if len(mod_names) == 1:
                            description_lines.append(f'<b>{chapter_name}:</b> {mod_names[0]}')
                        else:
                            description_lines.append(f"<b>{chapter_name}:</b> {len(mod_names)} mod(s): {', '.join(mod_names)}")
            else:
                uni_data = settings['mods'].get('universal')
                if uni_data:
                    mod_keys = uni_data if isinstance(uni_data, list) else [uni_data]
                    mod_names = []
                    for mod_key in mod_keys:
                        mod_config = self.mod_manager.get_mod_config(mod_key)
                        mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                        mod_names.append(mod_name)
                    if len(mod_names) == 1:
                        description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_names[0]}")
                    else:
                        description_lines.append(f"<b>{tr('status.mod_label')}</b> {len(mod_names)} mod(s): {', '.join(mod_names)}")
                else:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.no_mod')}</i>")
        description_lines.append('')
        if settings.get('launch_via_steam'):
            description_lines.append(f"✓ {tr('ui.steam_launch')}")
        elif settings.get('use_custom_executable'):
            custom_path = settings.get('custom_executable_path', '') or settings.get('demo_custom_executable_path', '') or settings.get('undertaleyellow_custom_executable_path', '')
            exe_name = os.path.basename(custom_path) if custom_path else '?'
            description_lines.append(f"✓ {tr('status.custom_executable_launch', exe_name=exe_name)}")
        else:
            description_lines.append(f"✓ {tr('status.normal_launch')}")
        description_text = '<br>'.join(description_lines) + f"<br><br><p>{tr('dialogs.shortcut_create_description')}</p>"
        if self.feedback_manager.ask_question('dialogs.create_shortcut_question', 'dialogs.shortcut_create_description', description_text):
            self._save_shortcut(settings)

    def _gather_shortcut_settings(self) -> Optional[Dict[str, Any]]:
        if not self.parent_widget:
            return None
        current_path = self.parent_widget._get_current_game_path()
        if not current_path:
            return None
        is_demo = isinstance(self.app_state.game_mode, DemoGameMode)
        is_chapter_mode = hasattr(self.parent_widget, 'chapter_mode_checkbox') and self.parent_widget.chapter_mode_checkbox.isChecked()
        is_undertale = isinstance(self.app_state.game_mode, UndertaleGameMode)
        is_undertaleyellow = isinstance(self.app_state.game_mode, UndertaleYellowGameMode)
        undertale_game_path = ''
        undertaleyellow_game_path = ''
        if is_undertale:
            undertale_game_path = self.app_state.game_mode.get_game_path(self.app_state.local_config) or ''
        elif is_undertaleyellow:
            undertaleyellow_game_path = self.app_state.game_mode.get_game_path(self.app_state.local_config) or ''
        settings = {'launcher_version': LAUNCHER_VERSION, 'game_path': self.app_state.game_path, 'demo_game_path': self.app_state.demo_game_path, 'undertale_game_path': undertale_game_path, 'undertaleyellow_game_path': undertaleyellow_game_path, 'is_demo_mode': is_demo, 'is_chapter_mode': is_chapter_mode, 'is_undertale_mode': is_undertale, 'is_undertaleyellow_mode': is_undertaleyellow, 'launch_via_steam': self.parent_widget.launch_via_steam_checkbox.isChecked(), 'use_custom_executable': self.parent_widget.use_custom_executable_checkbox.isChecked(), 'custom_executable_path': self.app_state.local_config.get(FullGameMode().get_custom_exec_config_key(), ''), 'demo_custom_executable_path': self.app_state.local_config.get(DemoGameMode().get_custom_exec_config_key(), ''), 'undertale_custom_executable_path': self.app_state.local_config.get(UndertaleGameMode().get_custom_exec_config_key(), ''), 'undertaleyellow_custom_executable_path': self.app_state.local_config.get(UndertaleYellowGameMode().get_custom_exec_config_key(), ''), 'direct_launch_slot_id': self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL), 'mods': {}}
        slot_manager = getattr(self.parent_widget, 'slot_manager', None) if self.parent_widget else None
        if not slot_manager or not hasattr(slot_manager, 'get_active_mod_selections'):
            if is_demo:
                settings['mods']['demo'] = None
            elif is_undertale:
                settings['mods']['undertale'] = None
            elif is_undertaleyellow:
                settings['mods']['undertaleyellow'] = None
            elif is_chapter_mode:
                for chapter_id in range(5):
                    settings['mods'][str(chapter_id)] = None
            else:
                settings['mods']['universal'] = None
            return settings
        if is_demo:
            demo_mods = slot_manager.get_used_mods_list(SLOT_ID_DEMO)
            if demo_mods:
                mod_keys = [get_mod_key(mod) for mod in demo_mods if get_mod_key(mod)]
                settings['mods']['demo'] = mod_keys[0] if len(mod_keys) == 1 else mod_keys
            else:
                settings['mods']['demo'] = None
        elif is_undertale:
            undertale_mods = slot_manager.get_used_mods_list(SLOT_ID_UNDERTALE)
            if undertale_mods:
                mod_keys = [get_mod_key(mod) for mod in undertale_mods if get_mod_key(mod)]
                settings['mods']['undertale'] = mod_keys[0] if len(mod_keys) == 1 else mod_keys
            else:
                settings['mods']['undertale'] = None
        elif is_undertaleyellow:
            from config.constants import SLOT_ID_UNDERTALE_YELLOW
            undertaleyellow_mods = slot_manager.get_used_mods_list(SLOT_ID_UNDERTALE_YELLOW)
            if undertaleyellow_mods:
                mod_keys = [get_mod_key(mod) for mod in undertaleyellow_mods if get_mod_key(mod)]
                settings['mods']['undertaleyellow'] = mod_keys[0] if len(mod_keys) == 1 else mod_keys
            else:
                settings['mods']['undertaleyellow'] = None
        elif is_chapter_mode:
            chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
            for chapter_id in chapter_ids:
                mods = slot_manager.get_used_mods_list(chapter_id)
                if mods:
                    mod_keys = [get_mod_key(mod) for mod in mods if get_mod_key(mod)]
                    settings['mods'][str(chapter_id)] = mod_keys[0] if len(mod_keys) == 1 else mod_keys
                else:
                    settings['mods'][str(chapter_id)] = None
        else:
            universal_mods = slot_manager.get_used_mods_list(SLOT_ID_UNIVERSAL)
            if universal_mods:
                mod_keys = [get_mod_key(mod) for mod in universal_mods if get_mod_key(mod)]
                settings['mods']['universal'] = mod_keys[0] if len(mod_keys) == 1 else mod_keys
            else:
                settings['mods']['universal'] = None
        return settings

    def apply_shortcut_mods(self, mods_settings: Dict[str, Any], is_chapter_mode: Optional[bool] = None):
        try:
            if not mods_settings:
                return
            if not self.parent_widget:
                raise Exception(tr('errors.parent_widget_not_found'))
            slot_manager = getattr(self.parent_widget, 'slot_manager', None)
            if not slot_manager:
                raise Exception('slot_manager not found')
            is_demo = isinstance(self.app_state.game_mode, DemoGameMode)
            is_undertale = isinstance(self.app_state.game_mode, UndertaleGameMode)
            is_undertaleyellow = isinstance(self.app_state.game_mode, UndertaleYellowGameMode)
            if is_chapter_mode is None:
                is_chapter_mode = self.app_state.current_mode == 'chapter'
            if is_demo:
                mod_data = mods_settings.get('demo')
                if mod_data and mod_data != 'no_change':
                    mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                    mods_list = self._get_mods_from_keys(mod_keys)
                    if mods_list:
                        slot_manager.set_mods_list(SLOT_ID_DEMO, mods_list, save_state=False)
                    else:
                        slot_manager.set_mods_list(SLOT_ID_DEMO, [], save_state=False)
                else:
                    slot_manager.set_mods_list(SLOT_ID_DEMO, [], save_state=False)
            elif is_undertale:
                mod_data = mods_settings.get('undertale')
                if mod_data and mod_data != 'no_change':
                    mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                    mods_list = self._get_mods_from_keys(mod_keys)
                    if mods_list:
                        slot_manager.set_mods_list(SLOT_ID_UNDERTALE, mods_list, save_state=False)
                    else:
                        slot_manager.set_mods_list(SLOT_ID_UNDERTALE, [], save_state=False)
                else:
                    slot_manager.set_mods_list(SLOT_ID_UNDERTALE, [], save_state=False)
            elif is_undertaleyellow:
                from config.constants import SLOT_ID_UNDERTALE_YELLOW
                mod_data = mods_settings.get('undertaleyellow')
                if mod_data and mod_data != 'no_change':
                    mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                    mods_list = self._get_mods_from_keys(mod_keys)
                    if mods_list:
                        slot_manager.set_mods_list(SLOT_ID_UNDERTALE_YELLOW, mods_list, save_state=False)
                    else:
                        slot_manager.set_mods_list(SLOT_ID_UNDERTALE_YELLOW, [], save_state=False)
                else:
                    slot_manager.set_mods_list(SLOT_ID_UNDERTALE_YELLOW, [], save_state=False)
            else:
                universal_data = mods_settings.get('universal')
                if universal_data and universal_data != 'no_change':
                    mod_keys = universal_data if isinstance(universal_data, list) else [universal_data]
                    mods_list = self._get_mods_from_keys(mod_keys)
                    if mods_list:
                        slot_manager.set_mods_list(SLOT_ID_UNIVERSAL, mods_list, save_state=False)
                    else:
                        slot_manager.set_mods_list(SLOT_ID_UNIVERSAL, [], save_state=False)
                elif is_chapter_mode:
                    chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
                    for chapter_id in chapter_ids:
                        mod_data = mods_settings.get(str(chapter_id))
                        if mod_data and mod_data != 'no_change':
                            mod_keys = mod_data if isinstance(mod_data, list) else [mod_data]
                            mods_list = self._get_mods_from_keys(mod_keys)
                            if mods_list:
                                slot_manager.set_mods_list(chapter_id, mods_list, save_state=False)
                            else:
                                slot_manager.set_mods_list(chapter_id, [], save_state=False)
                        else:
                            slot_manager.set_mods_list(chapter_id, [], save_state=False)
                else:
                    slot_manager.set_mods_list(SLOT_ID_UNIVERSAL, [], save_state=False)
            logging.info('Shortcut mods applied to used_mods_manager')
        except Exception as e:
            logging.error(f'Failed to apply shortcut mods: {e}', exc_info=True)
            raise Exception(tr('errors.mod_apply_error', error=str(e)))

    def _get_mods_from_keys(self, mod_keys: list) -> list:
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
            if not mod_data:
                installed_mods = self.mod_manager.get_installed_mods_list()
                for installed_mod in installed_mods:
                    installed_mod_key = installed_mod.get('mod_key') or installed_mod.get('key') or installed_mod.get('name')
                    if installed_mod_key == mod_key:
                        mod_data = self.mod_manager.create_mod_object_from_info(installed_mod, getattr(self.app_state, 'all_mods', None))
                        break
            if not mod_data:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                if mod_config:
                    mod_data = self.mod_manager.create_mod_object_from_info(mod_config, getattr(self.app_state, 'all_mods', None))
            if mod_data:
                mods_list.append(mod_data)
        return mods_list

    def launch_game_from_shortcut(self, launch_via_steam=False, use_custom_executable=False, custom_exec_path='', demo_custom_exec_path='', undertale_custom_exec_path='', undertaleyellow_custom_exec_path='', direct_launch_slot_id=-1):
        try:
            if not self.parent_widget:
                raise Exception(tr('errors.parent_widget_not_found'))
            game_launcher = getattr(self.parent_widget, 'game_launcher', None)
            if not game_launcher:
                raise Exception('game_launcher not found')
            if direct_launch_slot_id >= 0:
                self.app_state.current_mode = 'chapter'
                self.app_state.local_config['direct_launch_slot_id'] = direct_launch_slot_id
            if launch_via_steam:
                self.app_state.local_config['launch_via_steam'] = True
            if use_custom_executable:
                is_demo = isinstance(self.app_state.game_mode, DemoGameMode)
                is_undertale = isinstance(self.app_state.game_mode, UndertaleGameMode)
                is_undertaleyellow = isinstance(self.app_state.game_mode, UndertaleYellowGameMode)
                if is_demo:
                    exec_path = demo_custom_exec_path
                    if exec_path:
                        self.app_state.local_config[DemoGameMode().get_custom_exec_config_key()] = exec_path
                elif is_undertale:
                    exec_path = undertale_custom_exec_path
                    if exec_path:
                        self.app_state.local_config[UndertaleGameMode().get_custom_exec_config_key()] = exec_path
                elif is_undertaleyellow:
                    exec_path = undertaleyellow_custom_exec_path
                    if exec_path:
                        self.app_state.local_config[UndertaleYellowGameMode().get_custom_exec_config_key()] = exec_path
                else:
                    exec_path = custom_exec_path
                    if exec_path:
                        self.app_state.local_config[FullGameMode().get_custom_exec_config_key()] = exec_path
                if exec_path:
                    self.app_state.local_config['use_custom_executable'] = True
            game_launcher.is_shortcut_launch = True
            logging.info('Launching game from shortcut with mods via game_launcher')
            game_launcher.launch_game_with_all_mods(execute_plugin_hooks=None, restore_window_callback=None)
        except Exception as e:
            logging.error(f'Failed to launch game from shortcut: {e}', exc_info=True)
            raise Exception(tr('errors.launch_error_details', error=str(e)))

    def _save_shortcut(self, settings: Dict[str, Any]):
        system = platform.system()
        if system == 'Windows':
            file_filter = tr('ui.windows_shortcut_filter')
            default_name = tr('ui.default_shortcut_name_bat')
        elif system == 'Darwin':
            file_filter = 'macOS Command Script (*.command)'
            default_name = tr('ui.default_shortcut_name_command')
        else:
            file_filter = tr('ui.desktop_shortcut_filter')
            default_name = 'DELTAHUB-Deltarune.desktop'
        shortcut_path, _ = QFileDialog.getSaveFileName(self.parent_widget, tr('dialogs.save_shortcut'), os.path.expanduser(f'~/{default_name}'), file_filter)
        if not shortcut_path:
            return
        if getattr(sys, 'frozen', False):
            launcher_executable_path = sys.executable
        else:
            launcher_executable_path = sys.executable
            main_script_path = os.path.join(os.path.dirname(__file__), '..', 'main.py')
        settings_json = json.dumps(settings)
        settings_b64 = base64.b64encode(settings_json.encode('utf-8')).decode('utf-8')
        args = f'--shortcut-launch "{settings_b64}" --shortcut-path "{shortcut_path}"'
        try:
            if system == 'Windows':
                if getattr(sys, 'frozen', False):
                    content = f'@echo off\nstart "" "{launcher_executable_path}" {args}'
                else:
                    content = f'@echo off\nstart "" "{launcher_executable_path}" "{main_script_path}" {args}'
            elif system == 'Darwin':
                content = f'#!/bin/bash\nnohup "{launcher_executable_path}" {args} > /dev/null 2>&1 &'
            else:
                icon_path = resource_path('assets/icons/icon.ico')
                content = f'[Desktop Entry]\nVersion=1.0\nType=Application\nName=Deltarune (DELTAHUB)\nExec="{launcher_executable_path}" {args}\nIcon={icon_path}\nTerminal=false\n'
            with open(shortcut_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if system in ['Linux', 'Darwin']:
                os.chmod(shortcut_path, 493)
            self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.shortcut_created_successfully', path=shortcut_path))
            self.shortcut_created.emit(shortcut_path)
        except Exception as e:
            self.status_changed.emit(tr('status.shortcut_creation_error', error=str(e)), UI_COLORS['status_error'])
            self.feedback_manager.show_message('error', 'errors.error', tr('errors.shortcut_creation_failed', error=str(e)))
