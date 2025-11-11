import os
import shutil
import logging
import tempfile
import json
import zipfile
from PyQt6.QtCore import QThread, pyqtSignal
from managers.localization_manager import tr
from utils.network_utils import get_session, download_file
from config.constants import NETWORK_TIMEOUT_HEAD, UI_COLORS


class ThemeInstallWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, archive_path: str, config_dir: str, app_state, settings_manager, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.config_dir = config_dir
        self.app_state = app_state
        self.settings_manager = settings_manager
        self._cancelled = False
        self._session = None

    def cancel(self):
        self._cancelled = True
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass

    def _download_archive(self, url: str, target_path: str) -> bool:
        try:
            self.status.emit(tr('themes.downloading_theme'), UI_COLORS['status_warning'])
            session = get_session()
            self._session = session
            total_size = 0
            try:
                head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
                total_size = int(head_response.headers.get('content-length', 0))
            except Exception:
                pass
            downloaded_ref = [0]

            def progress_callback(progress):
                self.progress.emit(progress)
            download_file(session, url, target_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=lambda: self._cancelled)
            self.progress.emit(100)
            return True
        except Exception as e:
            logging.error(f'ThemeInstallWorker: Download failed: {e}', exc_info=True)
            return False

    def _install_theme_from_path(self, content_path: str) -> bool:
        try:
            theme_json_path = None
            if os.path.isfile(content_path) and content_path.endswith('.dhtheme'):
                with tempfile.TemporaryDirectory(prefix='dh-theme-extract-') as extract_dir:
                    with zipfile.ZipFile(content_path, 'r') as zipf:
                        if 'theme.json' not in zipf.namelist():
                            logging.error('ThemeInstallWorker: theme.json not found in theme archive')
                            return False
                        zipf.extractall(extract_dir)
                        theme_json_path = os.path.join(extract_dir, 'theme.json')
                        if not os.path.exists(theme_json_path):
                            logging.error('ThemeInstallWorker: theme.json not found after extraction')
                            return False
                        with open(theme_json_path, 'r', encoding='utf-8') as f:
                            theme_settings = json.load(f)
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
                        for filename in os.listdir(extract_dir):
                            src_path = os.path.join(extract_dir, filename)
                            if filename.startswith('background.'):
                                ext = os.path.splitext(filename)[1]
                                dest_path = os.path.join(self.config_dir, f'custom_background{ext}')
                                shutil.copy2(src_path, dest_path)
                                self.app_state.local_config['custom_background_path'] = dest_path
                            elif filename.startswith('background_music.'):
                                dest_path = os.path.join(self.config_dir, f'custom_background_music{os.path.splitext(filename)[1]}')
                                shutil.copy2(src_path, dest_path)
                            elif filename.startswith('startup_sound.'):
                                dest_path = os.path.join(self.config_dir, f'custom_startup_sound{os.path.splitext(filename)[1]}')
                                shutil.copy2(src_path, dest_path)
            else:
                theme_json_path = os.path.join(content_path, 'theme.json')
                if not os.path.exists(theme_json_path):
                    logging.error('ThemeInstallWorker: theme.json not found in theme directory')
                    return False
                with open(theme_json_path, 'r', encoding='utf-8') as f:
                    theme_settings = json.load(f)
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
                for filename in os.listdir(content_path):
                    src_path = os.path.join(content_path, filename)
                    if filename.startswith('background.'):
                        ext = os.path.splitext(filename)[1]
                        dest_path = os.path.join(self.config_dir, f'custom_background{ext}')
                        shutil.copy2(src_path, dest_path)
                        self.app_state.local_config['custom_background_path'] = dest_path
                    elif filename.startswith('background_music.'):
                        dest_path = os.path.join(self.config_dir, f'custom_background_music{os.path.splitext(filename)[1]}')
                        shutil.copy2(src_path, dest_path)
                    elif filename.startswith('startup_sound.'):
                        dest_path = os.path.join(self.config_dir, f'custom_startup_sound{os.path.splitext(filename)[1]}')
                        shutil.copy2(src_path, dest_path)
            self.settings_manager.write_local_config()
            self.app_state.local_config['first_launch_splash_shown'] = True
            if 'disable_splash' in theme_settings:
                self.app_state.local_config['disable_splash'] = theme_settings['disable_splash']
            elif 'disable_splash' not in self.app_state.local_config:
                self.app_state.local_config['disable_splash'] = True
            self.settings_manager.write_local_config()
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
                    temp_archive_name = f'temp_theme_{os.getpid()}.dhtheme'
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
