"""Theme installation worker.

This module provides a worker thread for installing custom themes.
"""
import os
import shutil
import logging
import tempfile
import json
from services.localization_service import tr
from config.constants import UI_COLORS
from workers.base_install_worker import BaseInstallWorker


class ThemeInstallWorker(BaseInstallWorker):

    def __init__(self, archive_path: str, config_dir: str, app_state, settings_service, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.config_dir = config_dir
        self.app_state = app_state
        self.settings_service = settings_service

    def _apply_theme_settings(self, theme_settings: dict, source_dir: str) -> None:
        for key, value in theme_settings.items():
            self.app_state.local_config[key] = value
        for old_file in ['custom_background_music.mp3', 'custom_background_music.wav', 'custom_startup_sound.mp3', 'custom_startup_sound.wav']:
            old_file_path = os.path.join(self.config_dir, old_file)
            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                except Exception as e:
                    logging.warning(f'Failed to remove old file {old_file}: {e}')
        self.app_state.local_config['custom_background_path'] = ''
        _asset_prefixes = {
            'background.': 'custom_background',
            'background_music.': 'custom_background_music',
            'startup_sound.': 'custom_startup_sound',
            'custom_logo.': 'custom_logo',
            'custom_font.': 'custom_font'
        }
        for filename in os.listdir(source_dir):
            src_path = os.path.join(source_dir, filename)
            for prefix, dest_name in _asset_prefixes.items():
                if filename.startswith(prefix):
                    ext = os.path.splitext(filename)[1]
                    dest_path = os.path.join(self.config_dir, f'{dest_name}{ext}')
                    shutil.copy2(src_path, dest_path)
                    if prefix == 'background.':
                        self.app_state.local_config['custom_background_path'] = dest_path
                    break

    def _download_archive(self, url: str, target_path: str) -> bool:
        return self._download_archive_base(url, target_path, tr('themes.downloading_theme'))

    def _install_theme_from_path(self, content_path: str) -> bool:
        try:
            if os.path.isfile(content_path):
                with tempfile.TemporaryDirectory(prefix='dh-theme-extract-') as extract_dir:
                    from utils.archive_utils import extract_any_archive
                    try:
                        extract_any_archive(content_path, extract_dir)
                    except Exception as e:
                        logging.exception(f'ThemeInstallWorker: Failed to extract theme archive: {e}')
                        return False
                    theme_json_path = os.path.join(extract_dir, 'theme.json')
                    if not os.path.exists(theme_json_path):
                        logging.error('ThemeInstallWorker: theme.json not found after extraction')
                        return False
                    with open(theme_json_path, 'r', encoding='utf-8') as f:
                        theme_settings = json.load(f)
                    self._apply_theme_settings(theme_settings, extract_dir)
            else:
                theme_json_path = os.path.join(content_path, 'theme.json')
                if not os.path.exists(theme_json_path):
                    logging.error('ThemeInstallWorker: theme.json not found in theme directory')
                    return False
                with open(theme_json_path, 'r', encoding='utf-8') as f:
                    theme_settings = json.load(f)
                self._apply_theme_settings(theme_settings, content_path)
            self.app_state.local_config['first_launch_splash_shown'] = True
            if 'disable_splash' in theme_settings:
                self.app_state.local_config['disable_splash'] = theme_settings['disable_splash']
                self.settings_service.write_local_config()
                return True
            else:
                if 'disable_splash' not in self.app_state.local_config:
                    self.app_state.local_config['disable_splash'] = True
                self.settings_service.write_local_config()
                return True
        except Exception as e:
            logging.error(f'ThemeInstallWorker: Error installing theme from path: {e}', exc_info=True)
            return False

    def run(self):
        try:
            archive_is_url = self.archive_path.startswith('http://') or self.archive_path.startswith('https://')
            if archive_is_url:
                url = self.archive_path
                with tempfile.TemporaryDirectory(prefix='dh-theme-import-') as temp_dir:
                    temp_archive_name = f'temp_theme_{os.getpid()}.zip'
                    temp_archive_path = os.path.join(temp_dir, temp_archive_name)
                    try:
                        if not self._download_archive(url, temp_archive_path):
                            self.finished.emit(False, tr('themes.download_failed'))
                            return
                    except Exception as e:
                        self.finished.emit(False, tr('themes.download_error', error=str(e)))
                        return
                    if self._cancelled:
                        self.finished.emit(False, tr('status.operation_cancelled'))
                        return
                    self.status.emit(tr('themes.installing_theme'), UI_COLORS['status_warning'])
                    if self._install_theme_from_path(temp_archive_path):
                        self.status.emit(tr('themes.theme_installed'), 'success')
                        self.finished.emit(True, tr('themes.theme_installed_success'))
                    else:
                        self.finished.emit(False, tr('themes.installation_failed'))
            else:
                if not os.path.exists(self.archive_path):
                    self.finished.emit(False, tr('themes.archive_not_found'))
                    return
                self.status.emit(tr('themes.installing_theme'), UI_COLORS['status_warning'])
                if self._install_theme_from_path(self.archive_path):
                    self.status.emit(tr('themes.theme_installed'), 'success')
                    self.finished.emit(True, tr('themes.theme_installed_success'))
                else:
                    self.finished.emit(False, tr('themes.installation_failed'))
        except Exception as e:
            logging.error(f'ThemeInstallWorker: Installation failed: {e}', exc_info=True)
            self.finished.emit(False, tr('themes.installation_error', error=str(e)))
