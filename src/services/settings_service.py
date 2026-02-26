"""Application settings management."""
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
from PyQt6.QtGui import QFontDatabase
from services.localization_service import tr, LocalizationManager
from config.constants import LAUNCHER_VERSION, UI_COLORS

from utils.file_utils import get_file_filter


class SettingsManager(QObject):
    """Manages application settings and configuration."""
    settings_changed = pyqtSignal()
    language_changed = pyqtSignal(str)
    theme_changed = pyqtSignal()
    restart_required = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)
    _IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.mp4', '.webm', '.avi', '.mkv', '.mov', '.m4v', '.3gp', '.mpg', '.mpeg', '.flv', '.wmv')
    _FONT_EXTENSIONS = ('.ttf', '.otf')
    _AUDIO_EXTENSIONS = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac')

    def __init__(self, app_state, feedback_service, localization_service: LocalizationManager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.lang_service = localization_service
        self.parent_widget = parent

    def read_json(self, path: str):
        from utils.file_utils import load_json
        data = load_json(path, migrate_config=True)
        if not data and os.path.exists(path):
            backup_path = f'{path}.invalid.bak'
            if os.path.exists(backup_path):
                self.feedback_service.update_status(tr('dialogs.corrupted_files_found'), UI_COLORS['status_warning'])
        return data

    def write_json(self, path: str, data):
        try:
            from utils.file_utils import save_json
            save_json(path, data, indent=2)
        except (PermissionError, OSError):
            self._handle_permission_error(os.path.dirname(path))
        except (ValueError, TypeError) as e:
            logging.error(f'[SettingsManager] JSON serialization error for {path}: {e}', exc_info=True)
            self.feedback_service.update_status(tr('errors.file_write_error', error=str(e)), UI_COLORS['status_error'])
        except Exception as e:
            self.feedback_service.update_status(tr('errors.file_write_error', error=str(e)), UI_COLORS['status_error'])

    def _handle_permission_error(self, directory: str):
        if self.parent_widget and hasattr(self.parent_widget, '_handle_permission_error'):
            self.parent_widget._handle_permission_error(directory)
        else:
            self.feedback_service.show_message('error', 'errors.no_write_permission_for', path=directory)

    def _get_audio_paths(self, base_name: str) -> list[str]:
        return [os.path.join(self.app_state.config_dir, f'custom_{base_name}{ext}') for ext in self._AUDIO_EXTENSIONS]

    def _remove_files(self, paths) -> None:
        for file_path in paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    def write_local_config(self):
        self.write_json(self.app_state.config_path, self.app_state.local_config)

    def migrate_config_if_needed(self):
        self.app_state.local_config['cache_format_version'] = LAUNCHER_VERSION
        defaults = {
            'game_path': '', 'last_selected': {}, 'use_custom_executable': False, 'demo_game_path': '',
            'launch_via_steam': False, 'use_portproton': False, 'portproton_path': '', 'direct_launch_chapter': '',
            'demo_mode_enabled': False, 'chapter_mode_enabled': False, 'custom_background_path': '',
            'custom_executable_path': '', 'background_disabled': False, 'custom_color_background': '',
            'custom_color_button': '', 'custom_color_border': '', 'custom_color_button_hover': '',
            'custom_color_text': '', 'custom_color_version_text': '', 'beta_updates_enabled': False,
            'pizzatower_game_path': '', 'pizzatower_custom_executable_path': '', 'skip_patching_warnings': False,
            'merge_properties': False, 'merge_code': False, 'hide_mods_browser_tab': False,
            'hide_library_tab': False, 'hide_plugins_tab': False, 'hide_library_filters': False
        }
        for key, value in defaults.items():
            self.app_state.local_config.setdefault(key, value)
        self.app_state.local_config.setdefault('disable_splash', False)
        self.app_state.local_config.setdefault('first_launch_splash_shown', False)
        self.write_local_config()

    def on_language_changed(self, language_code: str):
        current_language = self.app_state.local_config.get('language', 'en')
        if language_code == current_language:
            return
        self.app_state.local_config['language'] = language_code
        self.write_json(self.app_state.config_path, self.app_state.local_config)
        self.language_changed.emit(language_code)

    def _toggle_setting(self, key: str, enabled: bool, signal: str = 'settings_changed'):
        self.app_state.local_config[key] = enabled
        self.write_local_config()
        if signal:
            getattr(self, signal).emit()

    def on_toggle_beta_updates(self, enabled: bool): self._toggle_setting('beta_updates_enabled', enabled)
    def on_toggle_fullscreen(self, enabled: bool): self._toggle_setting('fullscreen_enabled', enabled)
    def on_toggle_hide_library_filters(self, enabled: bool): self._toggle_setting('hide_library_filters', enabled)
    def on_toggle_steam_launch(self, enabled: bool): self._toggle_setting('launch_via_steam', enabled)
    def on_toggle_portproton(self, enabled: bool): self._toggle_setting('use_portproton', enabled)
    def on_toggle_hide_wips_without_downloads(self, enabled: bool): self._toggle_setting('hide_wips_without_downloads', enabled)
    def on_toggle_dont_hide_window_on_launch(self, enabled: bool): self._toggle_setting('dont_hide_window_on_launch', enabled)
    def on_toggle_disable_background(self, enabled: bool): self._toggle_setting('background_disabled', enabled, 'theme_changed')
    def on_toggle_disable_splash(self, enabled: bool): self._toggle_setting('disable_splash', enabled, None)
    def on_toggle_skip_patching_warnings(self, enabled: bool): self._toggle_setting('skip_patching_warnings', enabled)
    def on_toggle_hide_mods_browser_tab(self, enabled: bool): self._toggle_setting('hide_mods_browser_tab', enabled, None)
    def on_toggle_hide_library_tab(self, enabled: bool): self._toggle_setting('hide_library_tab', enabled, None)
    def on_toggle_hide_plugins_tab(self, enabled: bool): self._toggle_setting('hide_plugins_tab', enabled, None)

    def on_toggle_merge_properties(self, enabled: bool):
        self._toggle_setting('merge_properties', enabled, None)

    def on_toggle_merge_code(self, enabled: bool):
        self._toggle_setting('merge_code', enabled, None)

    def select_portproton_path(self) -> Optional[str]:
        filepath, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('ui.select_portproton_path'))
        if filepath:
            self._toggle_setting('portproton_path', filepath)
            return filepath
        return None

    def prompt_for_game_path(self, is_initial=False) -> bool:
        game = self.app_state.game_mode
        title, message = tr(game.path_select_dialog_key), tr(game.path_not_found_dialog_key)
        if is_initial:
            self.feedback_service.show_message('info', 'dialogs.path_not_found', tr('dialogs.game_path_instruction', message=message))
        if platform.system() == 'Darwin':
            path, _ = QFileDialog.getOpenFileName(self.parent_widget, title, os.path.expanduser('~'), 'Application bundle (*.app);;All files (*)')
            if not path:
                path = QFileDialog.getExistingDirectory(self.parent_widget, title, os.path.expanduser('~'))
        else:
            path = QFileDialog.getExistingDirectory(self.parent_widget, title, os.path.expanduser('~'))
        if path:
            corrected_path = path
            if platform.system() == 'Darwin' and not path.endswith('.app'):
                app_names = game.macos_app_names
                for app_name in app_names:
                    candidate = os.path.join(path, app_name)
                    if os.path.isdir(candidate):
                        corrected_path = candidate
                        break
            self.app_state.game_mode.set_game_path(self.app_state.local_config, corrected_path)
            self.write_local_config()
            self.feedback_service.update_status(tr('status.game_path_set', path=corrected_path), UI_COLORS['status_success'])
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

    def _handle_audio_file_click(self, base_name: str, select_dialog_key: str, removed_msg_key: str, remove_fail_key: str, copy_fail_key: str, custom_path_getter: str = ''):
        paths = self._get_audio_paths(base_name)
        existing = ''
        if custom_path_getter and self.parent_widget and hasattr(self.parent_widget, 'customization_service'):
            existing = getattr(self.parent_widget.customization_service, custom_path_getter, lambda: '')() or ''
        if not existing:
            existing = next((p for p in paths if os.path.exists(p)), '')
        if existing:
            try:
                self._remove_files(paths)
                self.feedback_service.show_message('info', 'dialogs.success', tr(removed_msg_key))
                self.theme_changed.emit()
            except Exception:
                self.feedback_service.show_message('warning', 'errors.error', tr(remove_fail_key))
        else:
            audio_filter = 'Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac);;All Files (*)'
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr(select_dialog_key), '', audio_filter)
            if file_path:
                lower = file_path.lower()
                valid_exts = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac')
                if not lower.endswith(valid_exts):
                    self.feedback_service.show_message('warning', 'errors.error', tr('errors.invalid_audio_format', 'Unsupported audio format.'))
                    return
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = os.path.splitext(lower)[1]
                    dest = os.path.join(self.app_state.config_dir, f'custom_{base_name}{ext}')
                    shutil.copy2(file_path, dest)
                    self.theme_changed.emit()
                except Exception as e:
                    logging.error(f'[SettingsManager] Failed to copy {base_name}: {e}', exc_info=True)
                    self.feedback_service.show_message('warning', 'errors.error', tr(copy_fail_key))

    def on_background_music_button_click(self):
        self._handle_audio_file_click('background_music', 'dialogs.select_background_music', 'dialogs.background_music_removed', 'errors.remove_background_music_failed', 'errors.copy_background_music_failed')

    def on_startup_sound_button_click(self):
        self._handle_audio_file_click('startup_sound', 'dialogs.select_startup_sound', 'dialogs.startup_sound_removed', 'errors.remove_startup_sound_failed', 'errors.copy_startup_sound_failed', 'get_startup_sound_path')

    def _remove_logo_files(self):
        for ext in self._IMAGE_EXTENSIONS:
            path = os.path.join(self.app_state.config_dir, f'custom_logo{ext}')
            if os.path.exists(path):
                os.remove(path)

    def on_logo_button_click(self):
        existing_logo = ''
        if self.parent_widget and hasattr(self.parent_widget, 'customization_service'):
            existing_logo = self.parent_widget.customization_service.get_custom_logo_path()
        if existing_logo:
            try:
                self._remove_logo_files()
                self.feedback_service.show_message('info', 'dialogs.success', tr('dialogs.logo_removed'))
                self.theme_changed.emit()
            except Exception:
                self.feedback_service.show_message('warning', 'errors.error', tr('errors.remove_logo_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.select_logo'), '', get_file_filter('background_images'))
            if file_path:
                try:
                    os.makedirs(self.app_state.config_dir, exist_ok=True)
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext not in self._IMAGE_EXTENSIONS:
                        self.feedback_service.show_message('warning', 'errors.error', tr('errors.invalid_image_format'))
                        return
                    self._remove_logo_files()
                    shutil.copy2(file_path, os.path.join(self.app_state.config_dir, f'custom_logo{ext}'))
                    self.theme_changed.emit()
                except Exception:
                    self.feedback_service.show_message('warning', 'errors.error', tr('errors.copy_logo_failed'))

    def _remove_font_files(self):
        for ext in self._FONT_EXTENSIONS:
            path = os.path.join(self.app_state.config_dir, f'custom_font{ext}')
            if os.path.exists(path):
                os.remove(path)

    def on_font_button_click(self):
        cs = getattr(self.parent_widget, 'customization_service', None)
        if cs and cs.get_custom_font_path():
            try:
                self._remove_font_files()
                if hasattr(self.parent_widget, 'custom_font_family'):
                    self.parent_widget.custom_font_family = self.lang_service.load_font()
                self._update_font_button_text()
                self.theme_changed.emit()
            except Exception:
                self.feedback_service.show_message('warning', 'errors.error', tr('errors.remove_font_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self.parent_widget, tr('dialogs.select_font_file'), '', f"{tr('file_descriptions.font_files')} (*.ttf *.otf)")
            if not file_path:
                return
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self._FONT_EXTENSIONS:
                self.feedback_service.show_message('warning', 'errors.error', tr('errors.invalid_font_file'))
                return
            try:
                os.makedirs(self.app_state.config_dir, exist_ok=True)
                self._remove_font_files()
                target_path = os.path.join(self.app_state.config_dir, f'custom_font{ext}')
                shutil.copy2(file_path, target_path)
                font_id = QFontDatabase.addApplicationFont(target_path)
                if font_id != -1 and self.parent_widget:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        self.parent_widget.custom_font_family = families[0]
                self._update_font_button_text()
                self.theme_changed.emit()
            except Exception as e:
                logging.error(f"Failed to copy font: {e}")
                self.feedback_service.show_message('warning', 'errors.error', tr('errors.copy_font_failed', 'Failed to copy font'))

    def _update_font_button_text(self):
        btn = getattr(self.parent_widget, 'change_font_button', None)
        cs = getattr(self.parent_widget, 'customization_service', None)
        if btn and cs:
            btn.setText(cs.get_font_button_text())

    def is_valid_hex_color(self, s: str) -> bool:
        return bool(re.fullmatch('#[0-9a-fA-F]{6}', s or ''))

    def on_custom_style_edited(self, color_widgets: dict):
        for key, widget in color_widgets.items():
            color = widget.text()
            self.app_state.local_config[f'custom_color_{key}'] = color if color and self.is_valid_hex_color(color) else ''
        self.write_local_config()
        self.theme_changed.emit()

    def export_theme(self):
        theme_file_path, _ = QFileDialog.getSaveFileName(self.parent_widget, tr('dialogs.export_theme_title'), '', f"{tr('file_descriptions.theme_files')} (*.zip)")
        if not theme_file_path:
            return
        _color_keys = ('custom_color_background', 'custom_color_button', 'custom_color_border', 'custom_color_button_hover', 'custom_color_text', 'custom_color_version_text')
        theme_settings = {k: self.app_state.local_config.get(k, '') for k in _color_keys}
        theme_settings.update({'background_disabled': self.app_state.local_config.get('background_disabled', False), 'disable_splash': self.app_state.local_config.get('disable_splash', False)})
        with zipfile.ZipFile(theme_file_path, 'w') as zipf:
            zipf.writestr('theme.json', json.dumps(theme_settings, indent=2))
            assets = [('custom_background_path', 'background')]
            if self.parent_widget and hasattr(self.parent_widget, 'customization_service'):
                cs = self.parent_widget.customization_service
                assets += [(cs.get_background_music_path(), 'background_music'), (cs.get_startup_sound_path(), 'startup_sound'), (cs.get_custom_logo_path(), 'custom_logo'), (cs.get_custom_font_path(), 'custom_font')]
            else:
                assets.append((None, None))
            for src, name in assets:
                path = self.app_state.local_config.get(src) if isinstance(src, str) and os.path.sep not in src and '/' not in src else src
                if path and os.path.exists(path):
                    zipf.write(path, f'{name}{os.path.splitext(path)[1]}')
        self.feedback_service.show_message('info', 'dialogs.success', tr('dialogs.theme_exported_success'))

    def import_theme(self):
        from ui.dialogs.import_dialog import ImportDialog
        from PyQt6.QtWidgets import QDialog
        dialog = ImportDialog(self.parent_widget, self.feedback_service, 'themes', '*.zip')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._install_theme_from_file(dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._install_theme_from_url(dialog.selected_url)

    def _install_theme_from_file(self, theme_file_path: str):
        try:
            with zipfile.ZipFile(theme_file_path, 'r') as zipf:
                if 'theme.json' not in zipf.namelist():
                    raise ValueError
        except Exception:
            self.feedback_service.show_message('error', 'dialogs.error', tr('dialogs.theme_invalid_archive'))
            return

        from utils.path_utils import resource_path, get_user_themes_dir
        import shutil
        theme_dir_abs = os.path.normcase(os.path.normpath(os.path.dirname(os.path.abspath(theme_file_path))))

        if theme_dir_abs not in (os.path.normcase(os.path.normpath(os.path.abspath(d))) for d in (resource_path('assets/themes'), get_user_themes_dir())):
            cb = getattr(self.parent_widget, 'do_not_save_theme_checkbox', None)
            if not (cb and cb.isChecked()):
                dest = os.path.join(get_user_themes_dir(), os.path.basename(theme_file_path))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(theme_file_path, dest)
                if hasattr(self.parent_widget, 'theme'):
                    self.parent_widget.theme.init_theme_list()

        try:
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
                        raise FileNotFoundError('theme.json not found in extracted archive')
                with open(theme_json_path, 'r', encoding='utf-8') as f:
                    theme_settings = json.load(f)
                for key, value in theme_settings.items():
                    self.app_state.local_config[key] = value

                for base in ('background_music', 'startup_sound'):
                    self._remove_files(self._get_audio_paths(base))
                self._remove_logo_files()
                self._remove_font_files()
                self.app_state.local_config['custom_background_path'] = ''

                _asset_prefixes = {
                    'background.': 'custom_background',
                    'background_music.': 'custom_background_music',
                    'startup_sound.': 'custom_startup_sound',
                    'custom_logo.': 'custom_logo',
                    'custom_font.': 'custom_font'
                }

                for filename in os.listdir(temp_dir):
                    for prefix, dest_name in _asset_prefixes.items():
                        if filename.startswith(prefix):
                            ext = os.path.splitext(filename)[1]
                            dest_path = os.path.join(self.app_state.config_dir, f'{dest_name}{ext}')
                            shutil.copy2(os.path.join(temp_dir, filename), dest_path)
                            if prefix == 'background.':
                                self.app_state.local_config['custom_background_path'] = dest_path
                            break

            self.write_local_config()
            self.app_state.local_config['first_launch_splash_shown'] = True

            if 'disable_splash' in theme_settings:
                self.app_state.local_config['disable_splash'] = theme_settings['disable_splash']
            elif 'disable_splash' not in self.app_state.local_config:
                self.app_state.local_config['disable_splash'] = True

            self.write_local_config()
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_service.show_message('info', 'dialogs.success', tr('dialogs.theme_imported_success'))
        except Exception as e:
            self.feedback_service.show_message('error', 'dialogs.error', tr('dialogs.theme_import_failed', error=str(e)))

    def _install_theme_from_url(self, url: str):
        try:
            from workers.install.theme_install_worker import ThemeInstallWorker
            worker = ThemeInstallWorker(url, self.app_state.config_dir, self.app_state, self, self.parent_widget)
            worker.status.connect(lambda msg, color: self.feedback_service.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
            worker.finished.connect(self._on_theme_install_finished)
            worker.unrar_needed.connect(self._on_unrar_needed)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(f'SettingsManager: Error installing theme from URL: {e}', exc_info=True)
            self.feedback_service.show_message('error', 'errors.error', tr('themes.installation_error', error=str(e)))

    def _on_unrar_needed(self):
        try:
            from utils.archive_utils import prompt_for_unrar_install
            worker = self.app_state.current_task
            success = prompt_for_unrar_install(parent_widget=self.parent_widget)
            if success:
                logging.info('UnRAR installed successfully from theme worker request')
            else:
                logging.info('User declined UnRAR installation from theme worker request')
            if worker and hasattr(worker, 'signal_unrar_installed'):
                worker.signal_unrar_installed(success)
        except Exception as e:
            logging.error(f'SettingsManager: Error handling UnRAR installation request: {e}')
            if self.app_state.current_task and hasattr(self.app_state.current_task, 'signal_unrar_installed'):
                self.app_state.current_task.signal_unrar_installed(False)

    def _on_theme_install_finished(self, success: bool, message: str):
        self.app_state.reset_install_state()
        if success:
            self.theme_changed.emit()
            self.settings_changed.emit()
            self.feedback_service.update_status(message, 'green')
            self.feedback_service.show_message('info', 'dialogs.success', message)
        else:
            logging.warning(f'Theme installation failed: {message}')
            self.feedback_service.update_status(message or tr('errors.error'), 'red')
            self.feedback_service.show_message('error', 'errors.error', message)

    def on_reset_settings_click(self, callbacks: dict):
        if not self.feedback_service.ask_question('dialogs.reset_settings_confirm_title', 'dialogs.reset_settings_confirm_text', '', False):
            return
        language = self.app_state.local_config.get('language', 'en')
        for base in ('background_music', 'startup_sound'):
            self._remove_files(self._get_audio_paths(base))
        self._remove_logo_files()
        self._remove_font_files()
        self.app_state.local_config.clear()
        self.app_state.local_config['language'] = language
        self.write_local_config()
        if 'migrate_config' in callbacks:
            callbacks['migrate_config']()
        self.theme_changed.emit()
        self.settings_changed.emit()
        self.feedback_service.show_message('info', 'dialogs.success', tr('status.settings_reset_success'))

    def disable_direct_launch(self):
        self.app_state.local_config['direct_launch_chapter'] = ''
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
        if not getattr(self, '_geometry_save_timer', None):
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
