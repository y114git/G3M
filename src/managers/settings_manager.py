import json
import logging
import os
import platform
import re
import shutil
import tempfile
import zipfile
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QByteArray
from PyQt6.QtWidgets import QFileDialog, QWidget
from managers.localization_manager import tr, LocalizationManager
from config.constants import LAUNCHER_VERSION, UI_COLORS, SLOT_ID_UNIVERSAL
from models.game_modes import DemoGameMode, UndertaleGameMode
from utils.file_utils import get_file_filter


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
        from utils.file_utils import load_json
        data = load_json(path, migrate_config=True)
        if not data and os.path.exists(path):
            backup_path = f'{path}.invalid.bak'
            if os.path.exists(backup_path):
                self.feedback_manager.update_status(tr('dialogs.corrupted_files_found'), UI_COLORS['status_warning'])
        return data

    def write_json(self, path: str, data):
        try:
            from utils.file_utils import save_json
            save_json(path, data, indent=2)
        except (PermissionError, OSError):
            self._handle_permission_error(os.path.dirname(path))
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.file_write_error', error=str(e)), UI_COLORS['status_error'])

    def _handle_permission_error(self, directory: str):
        if self.parent_widget and hasattr(self.parent_widget, '_handle_permission_error'):
            self.parent_widget._handle_permission_error(directory)
        else:
            self.feedback_manager.show_message('error', 'errors.no_write_permission_for', path=directory)

    def write_local_config(self):
        self.write_json(self.app_state.config_path, self.app_state.local_config)

    def migrate_config_if_needed(self):
        self.app_state.local_config['cache_format_version'] = LAUNCHER_VERSION
        defaults = {'game_path': '', 'last_selected': {}, 'use_custom_executable': False, 'demo_game_path': '', 'launch_via_steam': False, 'use_portproton': False, 'portproton_path': '', 'direct_launch_slot_id': SLOT_ID_UNIVERSAL, 'demo_mode_enabled': False, 'chapter_mode_enabled': False, 'custom_background_path': '', 'custom_executable_path': '', 'background_disabled': False, 'custom_color_background': '', 'custom_color_button': '', 'custom_color_border': '', 'custom_color_button_hover': '', 'custom_color_text': '', 'custom_color_version_text': '', 'beta_updates_enabled': False, 'clear_logs_on_startup': False, 'fast_merging_enabled': False, 'pizzatower_game_path': '', 'pizzatower_custom_executable_path': ''}
        for key, value in defaults.items():
            self.app_state.local_config.setdefault(key, value)
        if 'disable_splash' not in self.app_state.local_config:
            self.app_state.local_config['disable_splash'] = False
        if 'first_launch_splash_shown' not in self.app_state.local_config:
            self.app_state.local_config['first_launch_splash_shown'] = False
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

    def on_toggle_clear_logs(self, enabled: bool):
        self.app_state.local_config['clear_logs_on_startup'] = enabled
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

    def on_toggle_portproton(self, enabled: bool):
        self.app_state.local_config['use_portproton'] = enabled
        self.write_local_config()
        self.settings_changed.emit()

    def select_portproton_path(self) -> Optional[str]:
        dlg_title = tr('ui.select_portproton_path')
        filepath, _ = QFileDialog.getOpenFileName(self.parent_widget, dlg_title)
        if filepath:
            self.app_state.local_config['portproton_path'] = filepath
            self.write_local_config()
            self.settings_changed.emit()
            return filepath
        return None

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
        from models.game_modes import UndertaleYellowGameMode, PizzaTowerGameMode
        if isinstance(self.app_state.game_mode, DemoGameMode):
            title = tr('dialogs.select_demo_folder')
            message = tr('dialogs.demo_not_found')
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            title = tr('dialogs.select_undertale_folder')
            message = tr('dialogs.undertale_not_found')
        elif isinstance(self.app_state.game_mode, UndertaleYellowGameMode):
            title = tr('dialogs.select_undertaleyellow_folder')
            message = tr('dialogs.undertaleyellow_not_found')
        elif isinstance(self.app_state.game_mode, PizzaTowerGameMode):
            title = tr('dialogs.select_pizzatower_folder')
            message = tr('dialogs.pizzatower_not_found')
        else:
            title = tr('dialogs.select_deltarune_folder')
            message = tr('dialogs.deltarune_not_found')
        if is_initial:
            self.feedback_manager.show_message('info', 'dialogs.path_not_found', tr('dialogs.game_path_instruction', message=message))
        if platform.system() == 'Darwin':
            path, _ = QFileDialog.getOpenFileName(self.parent_widget, title, '', 'Application bundle (*.app);;All files (*)')
            if not path:
                path = QFileDialog.getExistingDirectory(self.parent_widget, title)
        else:
            path = QFileDialog.getExistingDirectory(self.parent_widget, title)
        if path:
            corrected_path = path
            if platform.system() == 'Darwin' and (not path.endswith('.app')):
                if isinstance(self.app_state.game_mode, UndertaleGameMode) or isinstance(self.app_state.game_mode, UndertaleYellowGameMode):
                    app_names = ('UNDERTALE.app',)
                elif isinstance(self.app_state.game_mode, PizzaTowerGameMode):
                    app_names = ('PizzaTower.app',)
                else:
                    app_names = ('DELTARUNE.app', 'DELTARUNEdemo.app')
                for app_name in app_names:
                    candidate = os.path.join(path, app_name)
                    if os.path.isdir(candidate):
                        corrected_path = candidate
                        break
            self.app_state.game_mode.set_game_path(self.app_state.local_config, corrected_path)
            self.write_local_config()
            self.feedback_manager.update_status(tr('status.game_path_set', path=corrected_path), UI_COLORS['status_success'])
            self.settings_changed.emit()
            return True
        return False

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
                self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.background_music_removed'))
                self.theme_changed.emit()
            except Exception:
                self.feedback_manager.show_message('warning', 'errors.error', tr('errors.remove_background_music_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.select_background_music'), '', 'Audio Files (*.mp3 *.wav)')
            if file_path:
                lower = file_path.lower()
                if not (lower.endswith('.mp3') or lower.endswith('.wav')):
                    self.feedback_manager.show_message('warning', 'errors.error', tr('errors.can_select_only_mp3_wav'))
                    return
                try:
                    import logging
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = '.mp3' if lower.endswith('.mp3') else '.wav'
                    dest_path = os.path.join(self.app_state.config_dir, f'custom_background_music{ext}')
                    logging.info(f'[SettingsManager] Copying background music from {file_path} to {dest_path}')
                    shutil.copy2(file_path, dest_path)
                    logging.info(f'[SettingsManager] Background music copied successfully, file exists: {os.path.exists(dest_path)}')
                    self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.background_music_selected'))
                    self.theme_changed.emit()
                except Exception as e:
                    import logging
                    logging.error(f'[SettingsManager] Failed to copy background music: {e}', exc_info=True)
                    self.feedback_manager.show_message('warning', 'errors.error', tr('errors.copy_background_music_failed'))

    def on_startup_sound_button_click(self):
        mp3 = os.path.join(self.app_state.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_startup_sound.wav')
        existing = ''
        if self.parent_widget and hasattr(self.parent_widget, 'customization_manager'):
            existing = self.parent_widget.customization_manager.get_startup_sound_path()
        elif os.path.exists(mp3):
            existing = mp3
        elif os.path.exists(wav):
            existing = wav
        if existing:
            try:
                for p in (mp3, wav):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.startup_sound_removed'))
                self.theme_changed.emit()
            except Exception:
                self.feedback_manager.show_message('warning', 'errors.error', tr('errors.remove_startup_sound_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.select_startup_sound'), '', 'Audio Files (*.mp3 *.wav)')
            if file_path:
                lower = file_path.lower()
                if not (lower.endswith('.mp3') or lower.endswith('.wav')):
                    self.feedback_manager.show_message('warning', 'errors.error', tr('errors.can_select_only_mp3_wav'))
                    return
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = '.mp3' if lower.endswith('.mp3') else '.wav'
                    dest = os.path.join(self.app_state.config_dir, f'custom_startup_sound{ext}')
                    shutil.copy2(file_path, dest)
                    self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.startup_sound_selected'))
                    self.theme_changed.emit()
                except Exception:
                    self.feedback_manager.show_message('warning', 'errors.error', tr('errors.copy_startup_sound_failed'))

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
            music_path = None
            sound_path = None
            if self.parent_widget and hasattr(self.parent_widget, 'customization_manager'):
                music_path = self.parent_widget.customization_manager.get_background_music_path() or None
                sound_path = self.parent_widget.customization_manager.get_startup_sound_path() or None
            if music_path and os.path.exists(music_path):
                zipf.write(music_path, f'background_music{os.path.splitext(music_path)[1]}')
            if sound_path and os.path.exists(sound_path):
                zipf.write(sound_path, f'startup_sound{os.path.splitext(sound_path)[1]}')
        self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.theme_exported_success'))

    def import_theme(self):
        from ui.dialogs.import_dialog import ImportDialog
        from PyQt6.QtWidgets import QDialog
        dialog = ImportDialog(self.parent_widget, self.feedback_manager, 'themes', '*.dhtheme')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._install_theme_from_file(dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._install_theme_from_url(dialog.selected_url)

    def _install_theme_from_file(self, theme_file_path: str):
        try:
            with zipfile.ZipFile(theme_file_path, 'r') as zipf:
                if 'theme.json' not in zipf.namelist():
                    raise ValueError('Missing theme.json')
            from utils.archive_utils import extract_any_archive
            with tempfile.TemporaryDirectory() as temp_dir:
                extract_any_archive(theme_file_path, temp_dir)
                theme_json_path = os.path.join(temp_dir, 'theme.json')
                if not os.path.exists(theme_json_path):
                    for root, dirs, files in os.walk(temp_dir):
                        if 'theme.json' in files:
                            theme_json_path = os.path.join(root, 'theme.json')
                            break
                    else:
                        raise FileNotFoundError(f'theme.json not found in extracted archive')
                with open(theme_json_path, 'r', encoding='utf-8') as f:
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
            if 'disable_splash' in theme_settings:
                self.app_state.local_config['disable_splash'] = theme_settings['disable_splash']
            elif 'disable_splash' not in self.app_state.local_config:
                self.app_state.local_config['disable_splash'] = True
            self.write_local_config()
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_manager.show_message('info', 'dialogs.success', tr('dialogs.theme_imported_success'))
        except Exception as e:
            self.feedback_manager.show_message('error', 'dialogs.error', tr('dialogs.theme_import_failed', error=str(e)))

    def _install_theme_from_url(self, url: str):
        try:
            from workers.theme_install_worker import ThemeInstallWorker
            worker = ThemeInstallWorker(url, self.app_state.config_dir, self.app_state, self, self.parent_widget)
            worker.status.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
            worker.finished.connect(self._on_theme_install_finished)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            import logging
            logging.error(f'SettingsManager: Error installing theme from URL: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('themes.installation_error', error=str(e)))

    def _on_theme_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.app_state.progress_bar_visible = False
        self.app_state.progress_bar_value = 0
        self.app_state.clear_current_task()
        if success:
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_manager.update_status(message, 'green')
            self.feedback_manager.show_message('info', 'dialogs.success', message)
        else:
            import logging
            logging.warning(f'Theme installation failed: {message}')
            self.feedback_manager.update_status(message or tr('errors.error'), 'red')
            self.feedback_manager.show_message('error', 'errors.error', message)

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
        self.feedback_manager.show_message('info', 'dialogs.success', tr('status.settings_reset_success'))

    def disable_direct_launch(self):
        self.app_state.local_config['direct_launch_slot_id'] = SLOT_ID_UNIVERSAL
        self.write_local_config()
        self.settings_changed.emit()

    def load_window_geometry(self, widget: QWidget) -> bool:
        saved = self.app_state.local_config.get('window_geometry')
        if not saved:
            return False
        try:
            widget.restoreGeometry(QByteArray.fromHex(saved.encode()))
            return True
        except (ValueError, AttributeError) as e:
            logging.debug(f'load_window_geometry: failed: {e}')
            return False

    def save_window_geometry(self, widget: QWidget):
        geom_ba = widget.saveGeometry()
        self.app_state.local_config['window_geometry'] = geom_ba.toHex().data().decode()
        self.write_local_config()

    def schedule_geometry_save(self, widget: QWidget, timeout_ms: int = 500):
        if not hasattr(self, '_geometry_save_timer'):
            self._geometry_save_timer = None
        if self._geometry_save_timer is None:
            self._geometry_save_timer = QTimer()
            self._geometry_save_timer.setSingleShot(True)
            self._geometry_save_timer.timeout.connect(lambda: self.save_window_geometry(widget))
        else:
            self._geometry_save_timer.stop()
        self._geometry_save_timer.start(timeout_ms)

    def lock_window_size(self, widget: QWidget):
        try:
            sz = widget.size()
            widget.setMinimumSize(sz)
            widget.setMaximumSize(sz)
        except (AttributeError, ValueError) as e:
            logging.debug(f'lock_window_size: failed: {e}')

    def unlock_window_size(self, widget: QWidget):
        try:
            widget.setMinimumSize(0, 0)
            widget.setMaximumSize(16777215, 16777215)
        except (AttributeError, ValueError) as e:
            logging.debug(f'unlock_window_size: failed: {e}')
