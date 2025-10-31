import json
import os
import platform
import re
import shutil
import tempfile
import threading
import zipfile
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QApplication
from managers.localization_manager import tr, LocalizationManager
from config.constants import LAUNCHER_VERSION, UI_COLORS
from models.game_modes import DemoGameMode, UndertaleGameMode
from utils.file_utils import get_file_filter
from utils.game_utils import is_valid_game_path


class SettingsManager(QObject):
    settings_changed = pyqtSignal()
    language_changed = pyqtSignal(str)
    theme_changed = pyqtSignal()
    restart_required = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)

    def __init__(self, app_state, feedback_manager, localization_manager: LocalizationManager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.lang_manager = localization_manager
        self.parent_widget = parent

    def read_json(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and path.endswith('config.json'):
                needs_migration = False
                if 'chapters' in data and 'files' not in data:
                    data['files'] = data['chapters']
                    del data['chapters']
                    needs_migration = True
                if 'is_demo_mod' in data and 'modgame' not in data:
                    if data.get('is_demo_mod', False):
                        data['modgame'] = 'deltarunedemo'
                    else:
                        data['modgame'] = 'deltarune'
                    del data['is_demo_mod']
                    needs_migration = True
                if needs_migration:
                    self.write_json(path, data)
            return data
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            backup_path = f'{path}.invalid.bak'
            try:
                os.replace(path, backup_path)
            except OSError:
                pass
            self.feedback_manager.update_status(tr('dialogs.corrupted_files_found'), UI_COLORS['status_warning'])
            return {}

    def write_json(self, path: str, data):
        try:
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except (PermissionError, OSError):
            self._handle_permission_error(os.path.dirname(path))
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.file_write_error', error=str(e)), UI_COLORS['status_error'])

    def _handle_permission_error(self, directory: str):
        if self.parent_widget and hasattr(self.parent_widget, '_handle_permission_error'):
            self.parent_widget._handle_permission_error(directory)
        else:
            self.feedback_manager.show_error('errors.permission_denied', directory)

    def write_local_config(self):
        self.write_json(self.app_state.config_path, self.app_state.local_config)

    def migrate_config_if_needed(self):
        self.app_state.local_config['cache_format_version'] = LAUNCHER_VERSION
        defaults = {'game_path': '', 'last_selected': {}, 'use_custom_executable': False, 'demo_game_path': '', 'launch_via_steam': False, 'direct_launch_slot_id': -1, 'demo_mode_enabled': False, 'chapter_mode_enabled': False, 'custom_background_path': '', 'custom_executable_path': '', 'background_disabled': False, 'custom_color_background': '', 'custom_color_button': '', 'custom_color_border': '', 'custom_color_button_hover': '', 'custom_color_text': '', 'mods_dir_path': '', 'custom_color_version_text': '', 'beta_updates_enabled': False}
        for key, value in defaults.items():
            self.app_state.local_config.setdefault(key, value)
        self.write_local_config()

    def on_language_changed(self, language_code: str):
        current_language = self.app_state.local_config.get('language', 'en')
        if language_code == current_language:
            return
        self.app_state.local_config['language'] = language_code
        self.write_json(self.app_state.config_path, self.app_state.local_config)
        self.language_changed.emit(language_code)

    def on_toggle_beta_updates(self, enabled: bool):
        self.app_state.local_config['beta_updates_enabled'] = enabled
        self.write_local_config()
        self.settings_changed.emit()

    def on_toggle_fullscreen(self, enabled: bool):
        self.app_state.local_config['fullscreen_enabled'] = enabled
        self.write_local_config()
        self.settings_changed.emit()

    def on_toggle_hide_library_filters(self, enabled: bool):
        self.app_state.local_config['hide_library_filters'] = enabled
        self.write_local_config()
        self.settings_changed.emit()

    def on_toggle_steam_launch(self, enabled: bool):
        self.app_state.local_config['launch_via_steam'] = enabled
        self.write_local_config()
        self.settings_changed.emit()

    def on_toggle_custom_executable(self, enabled: bool):
        self.app_state.local_config['use_custom_executable'] = enabled
        if not enabled:
            self.app_state.local_config[self.app_state.game_mode.get_custom_exec_config_key()] = ''
        self.write_local_config()
        self.settings_changed.emit()

    def select_custom_executable_file(self) -> Optional[str]:
        dlg_title = tr('ui.select_launch_file')
        filepath, _ = QFileDialog.getOpenFileName(self.parent_widget, dlg_title)
        if filepath:
            self.app_state.local_config[self.app_state.game_mode.get_custom_exec_config_key()] = filepath
            self.write_local_config()
            self.settings_changed.emit()
            return filepath
        return None

    def on_toggle_disable_background(self, enabled: bool):
        self.app_state.local_config['background_disabled'] = enabled
        self.write_local_config()
        self.theme_changed.emit()

    def on_toggle_disable_splash(self, enabled: bool):
        self.app_state.local_config['disable_splash'] = enabled
        self.write_local_config()

    def prompt_for_game_path(self, is_initial=False) -> bool:
        if isinstance(self.app_state.game_mode, DemoGameMode):
            title = tr('dialogs.select_demo_folder')
            message = tr('dialogs.demo_not_found')
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            title = tr('dialogs.select_undertale_folder')
            message = tr('dialogs.undertale_not_found')
        else:
            title = tr('dialogs.select_deltarune_folder')
            message = tr('dialogs.deltarune_not_found')
        if is_initial:
            self.feedback_manager.show_info('dialogs.path_not_found', tr('dialogs.game_path_instruction', message=message))
        if platform.system() == 'Darwin':
            path, _ = QFileDialog.getOpenFileName(self.parent_widget, title, '', 'Application bundle (*.app);;All files (*)')
            if not path:
                path = QFileDialog.getExistingDirectory(self.parent_widget, title)
        else:
            path = QFileDialog.getExistingDirectory(self.parent_widget, title)
        if path:
            corrected_path = path
            if platform.system() == 'Darwin' and (not path.endswith('.app')):
                if isinstance(self.app_state.game_mode, UndertaleGameMode):
                    app_names = ('UNDERTALE.app',)
                else:
                    app_names = ('DELTARUNE.app', 'DELTARUNEdemo.app')
                for app_name in app_names:
                    candidate = os.path.join(path, app_name)
                    if os.path.isdir(candidate):
                        corrected_path = candidate
                        break
            if isinstance(self.app_state.game_mode, UndertaleGameMode):
                game_type = 'undertale'
            else:
                game_type = 'deltarune'
            if is_valid_game_path(corrected_path, False, game_type):
                self.app_state.game_mode.set_game_path(self.app_state.local_config, corrected_path)
                self.write_local_config()
                self.feedback_manager.update_status(tr('status.game_path_set', path=corrected_path), UI_COLORS['status_success'])
                self.settings_changed.emit()
                return True
            else:
                self.feedback_manager.show_warning('dialogs.invalid_folder', tr('dialogs.invalid_game_folder'))
        return False

    def prompt_for_mods_dir(self):
        current_mods_dir = self.app_state.mods_dir
        new_parent_dir = QFileDialog.getExistingDirectory(self.parent_widget, tr('ui.select_new_mods_folder'), os.path.dirname(current_mods_dir))
        if not new_parent_dir or os.path.dirname(current_mods_dir) == new_parent_dir:
            return
        new_mods_dir = os.path.join(new_parent_dir, 'mods')
        if os.path.exists(new_mods_dir):
            self.feedback_manager.show_error('errors.mods_folder_exists', dir=new_parent_dir)
            return
        try:
            self.feedback_manager.update_status(tr('status.moving_mods_folder'), UI_COLORS['status_warning'])
            QApplication.processEvents()
            shutil.move(current_mods_dir, new_mods_dir)
            self.app_state.mods_dir = new_mods_dir
            self.app_state.local_config['mods_dir_path'] = new_parent_dir
            self.write_local_config()
            self.feedback_manager.show_info('dialogs.success', tr('dialogs.mods_folder_moved', path=new_mods_dir))
            self.feedback_manager.update_status(tr('status.mods_folder_location_changed'), UI_COLORS['status_success'])
            self.settings_changed.emit()
        except Exception as e:
            self.feedback_manager.show_error('dialogs.mods_folder_move_failed', error=str(e))
            self.app_state.mods_dir = current_mods_dir
            self.feedback_manager.update_status(tr('status.mods_folder_change_error'), UI_COLORS['status_error'])

    def on_background_button_click(self):
        if self.app_state.local_config.get('custom_background_path'):
            self.app_state.local_config['custom_background_path'] = ''
        else:
            filepath, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('ui.select_background_image'), '', get_file_filter('background_images'))
            if not filepath:
                return
            self.app_state.local_config['custom_background_path'] = filepath
        self.write_local_config()
        self.theme_changed.emit()

    def on_background_music_button_click(self):
        mp3 = os.path.join(self.app_state.config_dir, 'custom_background_music.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_background_music.wav')
        custom_exists = os.path.exists(mp3) or os.path.exists(wav)
        if custom_exists:
            try:
                for p in (mp3, wav):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                self.feedback_manager.show_info('dialogs.success', tr('dialogs.background_music_removed'))
                self.theme_changed.emit()
            except Exception:
                self.feedback_manager.show_warning('errors.error', tr('errors.remove_background_music_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.select_background_music'), '', 'Audio Files (*.mp3 *.wav)')
            if file_path:
                lower = file_path.lower()
                if not (lower.endswith('.mp3') or lower.endswith('.wav')):
                    self.feedback_manager.show_warning('errors.error', tr('errors.can_select_only_mp3_wav'))
                    return
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = '.mp3' if lower.endswith('.mp3') else '.wav'
                    dest_path = os.path.join(self.app_state.config_dir, f'custom_background_music{ext}')
                    shutil.copy2(file_path, dest_path)
                    self.feedback_manager.show_info('dialogs.success', tr('dialogs.background_music_selected'))
                    self.theme_changed.emit()
                except Exception:
                    self.feedback_manager.show_warning('errors.error', tr('errors.copy_background_music_failed'))

    def on_startup_sound_button_click(self):
        mp3 = os.path.join(self.app_state.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_startup_sound.wav')
        existing = self._get_startup_sound_path()
        if existing:
            try:
                for p in (mp3, wav):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                self.feedback_manager.show_info('dialogs.success', tr('dialogs.startup_sound_removed'))
                self.theme_changed.emit()
            except Exception:
                self.feedback_manager.show_warning('errors.error', tr('errors.remove_startup_sound_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.select_startup_sound'), '', 'Audio Files (*.mp3 *.wav)')
            if file_path:
                lower = file_path.lower()
                if not (lower.endswith('.mp3') or lower.endswith('.wav')):
                    self.feedback_manager.show_warning('errors.error', tr('errors.can_select_only_mp3_wav'))
                    return
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = '.mp3' if lower.endswith('.mp3') else '.wav'
                    dest = os.path.join(self.app_state.config_dir, f'custom_startup_sound{ext}')
                    shutil.copy2(file_path, dest)
                    self.feedback_manager.show_info('dialogs.success', tr('dialogs.startup_sound_selected'))
                    self.theme_changed.emit()
                except Exception:
                    self.feedback_manager.show_warning('errors.error', tr('errors.copy_startup_sound_failed'))

    def _get_startup_sound_path(self) -> Optional[str]:
        mp3 = os.path.join(self.app_state.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_startup_sound.wav')
        if os.path.exists(mp3):
            return mp3
        if os.path.exists(wav):
            return wav
        return None

    def is_valid_hex_color(self, s: str) -> bool:
        return bool(re.fullmatch('#[0-9a-fA-F]{6}', s or ''))

    def on_custom_style_edited(self, color_widgets: dict):
        for key, widget in color_widgets.items():
            color = widget.text()
            config_key = f'custom_color_{key}'
            if color and self.is_valid_hex_color(color):
                self.app_state.local_config[config_key] = color
            else:
                self.app_state.local_config[config_key] = ''
        self.write_local_config()
        self.theme_changed.emit()

    def export_theme(self):
        theme_file_path, _ = QFileDialog.getSaveFileName(self.parent_widget, tr('dialogs.export_theme_title'), '', f"{tr('file_descriptions.theme_files')} (*.dhtheme)")
        if not theme_file_path:
            return
        theme_settings = {'custom_color_background': self.app_state.local_config.get('custom_color_background', ''), 'custom_color_button': self.app_state.local_config.get('custom_color_button', ''), 'custom_color_border': self.app_state.local_config.get('custom_color_border', ''), 'custom_color_button_hover': self.app_state.local_config.get('custom_color_button_hover', ''), 'custom_color_text': self.app_state.local_config.get('custom_color_text', ''), 'custom_color_version_text': self.app_state.local_config.get('custom_color_version_text', ''), 'background_disabled': self.app_state.local_config.get('background_disabled', False), 'disable_splash': self.app_state.local_config.get('disable_splash', False)}
        with zipfile.ZipFile(theme_file_path, 'w') as zipf:
            zipf.writestr('theme.json', json.dumps(theme_settings, indent=2))
            bg_path = self.app_state.local_config.get('custom_background_path')
            if bg_path and os.path.exists(bg_path):
                zipf.write(bg_path, f'background{os.path.splitext(bg_path)[1]}')
            music_path = self._get_background_music_path()
            if music_path and os.path.exists(music_path):
                zipf.write(music_path, f'background_music{os.path.splitext(music_path)[1]}')
            sound_path = self._get_startup_sound_path()
            if sound_path and os.path.exists(sound_path):
                zipf.write(sound_path, f'startup_sound{os.path.splitext(sound_path)[1]}')
        self.feedback_manager.show_info('dialogs.success', tr('dialogs.theme_exported_success'))

    def _get_background_music_path(self) -> Optional[str]:
        mp3 = os.path.join(self.app_state.config_dir, 'custom_background_music.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_background_music.wav')
        if os.path.exists(mp3):
            return mp3
        if os.path.exists(wav):
            return wav
        return None

    def import_theme(self):
        theme_file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.import_theme_title'), '', f"{tr('file_descriptions.theme_files')} (*.dhtheme)")
        if not theme_file_path:
            return
        try:
            with zipfile.ZipFile(theme_file_path, 'r') as zipf:
                if 'theme.json' not in zipf.namelist():
                    raise ValueError('Missing theme.json')
                with tempfile.TemporaryDirectory() as temp_dir:
                    zipf.extractall(temp_dir)
                    with open(os.path.join(temp_dir, 'theme.json'), 'r') as f:
                        theme_settings = json.load(f)
                    for key, value in theme_settings.items():
                        self.app_state.local_config[key] = value
                    for old_file in ['custom_background_music.mp3', 'custom_background_music.wav', 'custom_startup_sound.mp3', 'custom_startup_sound.wav']:
                        if os.path.exists(os.path.join(self.app_state.config_dir, old_file)):
                            os.remove(os.path.join(self.app_state.config_dir, old_file))
                    self.app_state.local_config['custom_background_path'] = ''
                    for filename in os.listdir(temp_dir):
                        src_path = os.path.join(temp_dir, filename)
                        if filename.startswith('background.'):
                            ext = os.path.splitext(filename)[1]
                            dest_path = os.path.join(self.app_state.config_dir, f'custom_background{ext}')
                            shutil.copy2(src_path, dest_path)
                            self.app_state.local_config['custom_background_path'] = dest_path
                        elif filename.startswith('background_music.'):
                            shutil.copy2(src_path, os.path.join(self.app_state.config_dir, f'custom_background_music{os.path.splitext(filename)[1]}'))
                        elif filename.startswith('startup_sound.'):
                            shutil.copy2(src_path, os.path.join(self.app_state.config_dir, f'custom_startup_sound{os.path.splitext(filename)[1]}'))
            self.write_local_config()
            self.app_state.local_config['first_launch_splash_shown'] = True
            self.app_state.local_config['disable_splash'] = True
            self.write_local_config()
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_manager.show_info('dialogs.success', tr('dialogs.theme_imported_success'))
        except Exception as e:
            self.feedback_manager.show_error('dialogs.error', tr('dialogs.theme_import_failed', error=str(e)))

    def on_reset_settings_click(self, callbacks: dict):
        if not self.feedback_manager.ask_question('dialogs.reset_settings_confirm_title', 'dialogs.reset_settings_confirm_text', '', False):
            return
        language = self.app_state.local_config.get('language', 'en')
        custom_files = [os.path.join(self.app_state.config_dir, 'custom_background_music.mp3'), os.path.join(self.app_state.config_dir, 'custom_background_music.wav'), os.path.join(self.app_state.config_dir, 'custom_startup_sound.mp3'), os.path.join(self.app_state.config_dir, 'custom_startup_sound.wav')]
        for file_path in custom_files:
            if os.path.exists(file_path):
                os.remove(file_path)
        self.app_state.local_config.clear()
        self.app_state.local_config['language'] = language
        config_keys_to_clear = ['saved_slots_deltarune', 'saved_slots_deltarune_chapter', 'saved_slots_deltarunedemo', 'saved_slots_undertale']
        for key in config_keys_to_clear:
            if key in self.app_state.local_config:
                del self.app_state.local_config[key]
        self.write_local_config()
        if 'migrate_config' in callbacks:
            callbacks['migrate_config']()
        self.theme_changed.emit()
        self.settings_changed.emit()
        self.feedback_manager.show_info('dialogs.success', tr('status.settings_reset_success'))

    def disable_direct_launch(self):
        self.app_state.local_config['direct_launch_slot_id'] = -1
        self.write_local_config()
        self.settings_changed.emit()
