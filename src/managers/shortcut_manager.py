import os
import sys
import json
import base64
import platform
import webbrowser
import subprocess
from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog
from core.app_state import AppState
from ui.common.feedback import FeedbackManager
from managers.mod_manager import ModManager
from models.game_modes import DemoGameMode, FullGameMode, UndertaleGameMode
from config.constants import LAUNCHER_VERSION, UI_COLORS
from managers.localization_manager import tr
from utils.path_utils import resource_path


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
            self.feedback_manager.show_warning('dialogs.cannot_create_shortcut_title', tr('dialogs.path_not_specified'))
            return
        description_lines = [tr('dialogs.shortcut_description'), '', tr('dialogs.current_shortcut_settings'), '']
        game_name = tr('ui.undertale') if settings.get('is_undertale_mode', False) else tr('ui.deltarunedemo') if settings.get('is_demo_mode', False) else tr('ui.deltarune')
        description_lines.append(f"<b>{tr('ui.mod_type_label')}</b> {game_name}")
        if settings.get('is_demo_mode', False):
            mod_key = settings['mods'].get('demo')
            if mod_key:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        elif settings.get('is_undertale_mode', False):
            mod_key = settings['mods'].get('undertale')
            if mod_key:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        else:
            is_chapter_mode = settings.get('is_chapter_mode', False)
            direct_launch_slot_id = settings.get('direct_launch_slot_id', -1)
            if is_chapter_mode:
                if direct_launch_slot_id >= 0:
                    chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                    chapter_name = chapter_names.get(direct_launch_slot_id, tr('ui.chapter_tab_title', chapter_num=direct_launch_slot_id))
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {chapter_name}")
                else:
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {tr('status.disabled')}")
                for chapter_id in [0, 1, 2, 3, 4]:
                    mod_key = settings['mods'].get(str(chapter_id))
                    if mod_key:
                        mod_config = self.mod_manager.get_mod_config(mod_key)
                        mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                        chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                        chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_tab_title', chapter_num=chapter_id))
                        description_lines.append(f'<b>{chapter_name}:</b> {mod_name}')
            else:
                uni_key = settings['mods'].get('universal')
                if uni_key:
                    mod_config = self.mod_manager.get_mod_config(uni_key)
                    mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=uni_key)) if mod_config else tr('errors.mod_not_found', mod_key=uni_key)
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
                else:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.no_mod')}</i>")
        description_lines.append('')
        if settings.get('launch_via_steam'):
            description_lines.append(f"✓ {tr('ui.steam_launch')}")
        elif settings.get('use_custom_executable'):
            custom_path = settings.get('custom_executable_path', '') or settings.get('demo_custom_executable_path', '')
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
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_chapter_mode = hasattr(self.parent_widget, 'chapter_mode_checkbox') and self.parent_widget.chapter_mode_checkbox.isChecked()
        is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
        settings = {'launcher_version': LAUNCHER_VERSION, 'game_path': self.app_state.game_path, 'demo_game_path': self.app_state.demo_game_path, 'is_demo_mode': is_demo_mode, 'is_chapter_mode': is_chapter_mode, 'is_undertale_mode': is_undertale_mode, 'launch_via_steam': self.parent_widget.launch_via_steam_checkbox.isChecked(), 'use_custom_executable': self.parent_widget.use_custom_executable_checkbox.isChecked(), 'custom_executable_path': self.app_state.local_config.get(FullGameMode().get_custom_exec_config_key(), ''), 'demo_custom_executable_path': self.app_state.local_config.get(DemoGameMode().get_custom_exec_config_key(), ''), 'direct_launch_slot_id': self.app_state.local_config.get('direct_launch_slot_id', -1), 'mods': {}}
        if is_demo_mode:
            demo_mod_key = None
            try:
                demo_slot = self.app_state.slots.get(-10) if hasattr(self.app_state, 'slots') else None
                if demo_slot and getattr(demo_slot, 'assigned_mod', None):
                    demo_mod_key = getattr(demo_slot.assigned_mod, 'key', None) or getattr(demo_slot.assigned_mod, 'mod_key', None)
            except Exception:
                demo_mod_key = None
            settings['mods']['demo'] = demo_mod_key
        elif is_undertale_mode:
            undertale_mod_key = None
            try:
                undertale_slot = self.app_state.slots.get(-20) if hasattr(self.app_state, 'slots') else None
                if undertale_slot and getattr(undertale_slot, 'assigned_mod', None):
                    undertale_mod_key = getattr(undertale_slot.assigned_mod, 'key', None) or getattr(undertale_slot.assigned_mod, 'mod_key', None)
            except Exception:
                undertale_mod_key = None
            settings['mods']['undertale'] = undertale_mod_key
        elif is_chapter_mode:
            for slot_frame in self.app_state.slots.values():
                chapter_id = slot_frame.chapter_id
                if chapter_id >= 0:
                    mod_key = None
                    if slot_frame.assigned_mod:
                        mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None)
                    settings['mods'][str(chapter_id)] = mod_key
        else:
            universal_mod_key = None
            try:
                universal_slot = self.app_state.slots.get(-1) if hasattr(self.app_state, 'slots') else None
                if universal_slot and getattr(universal_slot, 'assigned_mod', None):
                    universal_mod_key = getattr(universal_slot.assigned_mod, 'key', None) or getattr(universal_slot.assigned_mod, 'mod_key', None)
            except Exception:
                universal_mod_key = None
            settings['mods']['universal'] = universal_mod_key
        return settings

    def apply_shortcut_mods(self, mods_settings: Dict[str, str]):
        try:
            if not mods_settings:
                return
            if not self.parent_widget:
                raise Exception(tr('errors.parent_widget_not_found'))
            game_launcher = getattr(self.parent_widget, 'game_launcher', None)
            if not game_launcher:
                raise Exception('game_launcher not found')
            selections = {}
            is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
            is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
            if is_demo_mode:
                mod_key = mods_settings.get('demo')
                if mod_key and mod_key != 'no_change':
                    selections[-1] = mod_key
                else:
                    selections[-1] = 'no_change'
            elif is_undertale_mode:
                mod_key = mods_settings.get('undertale')
                if mod_key and mod_key != 'no_change':
                    selections[-1] = mod_key
                else:
                    selections[-1] = 'no_change'
            else:
                universal_key = mods_settings.get('universal')
                if universal_key and universal_key != 'no_change':
                    for chapter_id in range(5):
                        selections[chapter_id] = universal_key
                else:
                    for key, mod_key in mods_settings.items():
                        if key.isdigit() and mod_key and (mod_key != 'no_change'):
                            chapter_id = int(key)
                            selections[chapter_id] = mod_key
                        elif key.isdigit():
                            chapter_id = int(key)
                            selections[chapter_id] = 'no_change'
            if selections:
                success = game_launcher._prepare_game_files(selections)
                if not success:
                    raise Exception(tr('errors.mod_apply_error', error='Failed to prepare game files'))
        except Exception as e:
            raise Exception(tr('errors.mod_apply_error', error=str(e)))

    def launch_game_from_shortcut(self, launch_via_steam=False, use_custom_executable=False, custom_exec_path='', demo_custom_exec_path='', direct_launch_slot_id=-1):
        try:
            if not self.parent_widget:
                raise Exception(tr('errors.parent_widget_not_found'))
            if direct_launch_slot_id >= 0:
                self.app_state.current_mode = 'chapter'
                self.app_state.local_config['direct_launch_slot_id'] = direct_launch_slot_id
            game_launcher = getattr(self.parent_widget, 'game_launcher', None)
            if not game_launcher:
                raise Exception('game_launcher not found')
            if launch_via_steam:
                steam_app_id = self.app_state.game_mode.steam_id
                webbrowser.open(f'steam://run/{steam_app_id}')
            elif direct_launch_slot_id >= 0 and self.app_state.game_mode.direct_launch_allowed and (platform.system() != 'Darwin'):
                launch_config = game_launcher._handle_direct_launch(direct_launch_slot_id)
                if launch_config:
                    subprocess.Popen([launch_config['target']], cwd=launch_config['cwd'])
                else:
                    raise Exception(tr('errors.direct_launch_error'))
            else:
                is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
                current_game_path = self.parent_widget._get_current_game_path()
                if not current_game_path or not os.path.exists(current_game_path):
                    raise Exception(tr('errors.game_files_not_found'))
                executable_path = None
                if use_custom_executable:
                    exec_path = demo_custom_exec_path if is_demo_mode else custom_exec_path
                    if exec_path and os.path.exists(exec_path):
                        executable_path = exec_path
                    else:
                        raise Exception(tr('errors.specified_executable_not_found'))
                else:
                    if isinstance(self.app_state.game_mode, UndertaleGameMode):
                        possible_names = ['UNDERTALE.exe', 'undertale.exe']
                    else:
                        possible_names = ['DELTARUNE.exe', 'deltarune.exe', 'SURVEY_PROGRAM.exe', 'survey_program.exe']
                    for name in possible_names:
                        test_path = os.path.join(current_game_path, name)
                        if os.path.exists(test_path):
                            executable_path = test_path
                            break
                    if not executable_path:
                        raise Exception(tr('errors.executable_not_found_simple'))
                subprocess.Popen([executable_path], cwd=current_game_path)
        except Exception as e:
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
            self.feedback_manager.show_info('dialogs.success', tr('dialogs.shortcut_created_successfully', path=shortcut_path))
            self.shortcut_created.emit(shortcut_path)
        except Exception as e:
            self.status_changed.emit(tr('status.shortcut_creation_error', error=str(e)), UI_COLORS['status_error'])
            self.feedback_manager.show_error('errors.error', tr('errors.shortcut_creation_failed', error=str(e)))
