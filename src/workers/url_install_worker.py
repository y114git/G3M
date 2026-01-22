import os
import json
import shutil
import tempfile
import threading
import logging
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS, NETWORK_TIMEOUT_HEAD, MOD_CONFIG_FILENAME, CLOUD_FUNCTIONS_BASE_URL
from managers.localization_manager import tr
from utils.file_utils import has_deltamod_info_file, check_filename_is_deltamod_info
from utils.deltamod_converter import DeltamodConverter
from utils.network_utils import get_session, download_file
from utils.ui_utils import format_size_mb


class UrlInstallThread(QThread):
    status = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    unrar_needed = pyqtSignal()
    prompt_required = pyqtSignal(str, str)
    manual_install_required = pyqtSignal(str, str, str)

    def __init__(self, main_window, url: str):
        super().__init__(main_window)
        self.main_window = main_window
        self.url = url
        self.prompt_event = threading.Event()
        self.prompt_result = False
        self._cancelled = False
        self._session = None
        self._active_response = None
        self._unrar_event = threading.Event()
        self._unrar_installed = False

    def signal_unrar_installed(self, success: bool):
        self._unrar_installed = success
        self._unrar_event.set()

    def wait_for_unrar_install(self, timeout: float = 120.0) -> bool:
        self._unrar_event.clear()
        self._unrar_installed = False
        self.unrar_needed.emit()
        self._unrar_event.wait(timeout=timeout)
        return self._unrar_installed

    def cancel(self):
        self._cancelled = True
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    logging.warning('UrlInstallThread.cancel: session close error', exc_info=True)
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception:
                    logging.warning('UrlInstallThread.cancel: response close error', exc_info=True)
        finally:
            try:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            except Exception as e:
                logging.warning(f'UrlInstallThread.cancel: emit failed: {e}', exc_info=True)

    def run(self):
        try:
            if self.url.startswith('deltahub://'):
                content = self.url[len('deltahub://'):].split(',')[0].strip().rstrip('/')
                if len(content) == 64 and all((c in '0123456789abcdef' for c in content.lower())):
                    self._install_mod_from_hash(content)
                    return
                if not content.startswith(('http://', 'https://')):
                    content = content.replace('https//', 'https://').replace('http//', 'http://')
                download_url = content
            else:
                download_url = self.url
            with tempfile.TemporaryDirectory(prefix='dh-url-install-') as temp_dir:
                self.status.emit(tr('status.downloading_from_external'), UI_COLORS['status_warning'])
                archive_path = self._download_archive(download_url, temp_dir)
                if archive_path.lower().endswith('.dhtheme'):
                    self._install_theme_from_file(archive_path)
                    return
                redirect_result = self._check_redirect(archive_path, temp_dir)
                if redirect_result:
                    return
                content_type = self._detect_content_type(archive_path)
                if content_type == 'theme':
                    self._extract_and_install_theme(archive_path, temp_dir)
                elif content_type == 'plugin':
                    self._install_plugin_from_archive(archive_path)
                elif content_type == 'mod':
                    self._install_mod_from_archive(archive_path, temp_dir)
                else:
                    self._prepare_for_manual_install(archive_path)
        except Exception as e:
            self.finished.emit(False, str(e))

    def _process_deltahub_redirect(self, url: str, redirect_config: dict):
        with tempfile.TemporaryDirectory(prefix='dh-redirect-dl-') as temp_dir:
            archive_path = self._download_archive(url, temp_dir)
            with tempfile.TemporaryDirectory(prefix='dh-redirect-unpack-') as unpack_dir:
                shutil.unpack_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                files_in_root = os.listdir(content_path)
                if MOD_CONFIG_FILENAME in files_in_root:
                    mod_dir = self._install_deltahub_mod_from_path(content_path)
                    if mod_dir:
                        mod_name = os.path.basename(mod_dir)
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.mod_installation_failed'))
                elif has_deltamod_info_file(files_in_root):
                    converter = DeltamodConverter(content_path, self.main_window.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        mod_name = os.path.basename(new_mod_path)
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.deltamod_conversion_failed_url'))
                else:
                    raise ValueError(tr('errors.deltamod_archive_invalid_redirect'))

    def _process_deltamod_archive(self, url: str):
        with tempfile.TemporaryDirectory(prefix='dh-redirect-dl-') as temp_dir:
            archive_path = self._download_archive(url, temp_dir)
            with tempfile.TemporaryDirectory(prefix='dh-redirect-unpack-') as unpack_dir:
                shutil.unpack_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                files_in_root = os.listdir(content_path)
                if MOD_CONFIG_FILENAME in files_in_root:
                    mod_dir = self._install_deltahub_mod_from_path(content_path)
                    if mod_dir:
                        mod_name = os.path.basename(mod_dir)
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.mod_installation_failed'))
                elif has_deltamod_info_file(files_in_root):
                    converter = DeltamodConverter(content_path, self.main_window.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        mod_name = os.path.basename(new_mod_path)
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.deltamod_conversion_failed_url'))
                else:
                    raise ValueError(tr('errors.deltamod_archive_invalid_redirect'))

    def _install_deltahub_mod_from_path(self, content_path: str) -> Optional[str]:
        from utils.file_utils import sanitize_filename
        mod_config_path = None
        for root, dirs, files in os.walk(content_path):
            if MOD_CONFIG_FILENAME in files:
                mod_config_path = os.path.join(root, MOD_CONFIG_FILENAME)
                break
        if not mod_config_path:
            logging.error('mod_config.json not found in DELTAHUB mod archive')
            return None
        try:
            with open(mod_config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        except Exception as e:
            logging.error(f'Error reading mod_config.json: {e}')
            return None
        key = config_data.get('key') or config_data.get('mod_key')
        if not key:
            mod_name = config_data.get('name', 'imported_mod')
            key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
            config_data['key'] = key
            if 'mod_key' in config_data:
                del config_data['mod_key']
        mod_name = config_data.get('name', 'imported_mod')
        folder_name = sanitize_filename(mod_name)
        target_mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name)
        counter = 1
        while os.path.exists(target_mod_dir):
            folder_name_with_counter = f'{folder_name}_{counter}'
            target_mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name_with_counter)
            counter += 1
        os.makedirs(target_mod_dir, exist_ok=True)
        for item in os.listdir(content_path):
            src_path = os.path.join(content_path, item)
            dst_path = os.path.join(target_mod_dir, item)
            if os.path.isdir(src_path):
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
        config_data['is_local_mod'] = True
        target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
        try:
            with open(target_config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logging.info(f'Installed DELTAHUB mod from URL: {target_mod_dir}, key={key}')
        except Exception as e:
            logging.error(f'Error writing mod_config.json: {e}')
            return None
        return target_mod_dir

    def _download_archive(self, url: str, temp_dir: str) -> str:
        import requests
        from urllib.parse import urlparse, unquote
        from utils.network_utils import get_filename_from_url
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename or '.' not in filename:
            session = get_session()
            filename = get_filename_from_url(session, url)
        if not filename:
            from utils.archive_utils import get_file_extension_from_url
            file_ext = get_file_extension_from_url(url)
            filename = f'archive{file_ext}'
        supported_extensions = ['.zip', '.rar', '.7z', '.tar.gz', '.lzma', '.dhtheme']
        if not any((filename.lower().endswith(ext) for ext in supported_extensions)):
            from utils.archive_utils import get_file_extension_from_url
            file_ext = get_file_extension_from_url(url)
            filename = f'archive{file_ext}'
        archive_path = os.path.join(temp_dir, filename)
        session = get_session()
        self._session = session
        downloaded_ref = [0]
        total_size = 0
        try:
            head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
            total_size = int(head_response.headers.get('content-length', 0))
        except (requests.RequestException, ValueError) as e:
            logging.debug(f'UrlInstallThread: Could not get content-length from HEAD request: {e}')

        def progress_callback(progress):
            self.progress.emit(progress)
            if total_size > 0:
                downloaded_mb = format_size_mb(downloaded_ref[0])
                total_mb = format_size_mb(total_size)
                self.status.emit(f"{tr('status.downloading_mod')} ({downloaded_mb} / {total_mb})", UI_COLORS['status_warning'])

        def on_response(r):
            self._active_response = r
        download_file(session, url, archive_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=lambda: self._cancelled, on_response=on_response)
        self.progress.emit(100)
        return archive_path

    def _detect_content_type(self, archive_path: str) -> str:
        import zipfile
        import tarfile
        archive_lower = archive_path.lower()
        if archive_lower.endswith('.dhtheme'):
            return 'theme'
        try:
            if archive_lower.endswith('.zip') or archive_lower.endswith('.dhtheme'):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for name in zf.namelist():
                        normalized = name.replace('\\', '/').strip('/')
                        if normalized.lower().endswith('.dhtheme'):
                            return 'theme'
                        if normalized == 'plugin_init.py' or normalized.endswith('/plugin_init.py'):
                            return 'plugin'
                        if normalized == MOD_CONFIG_FILENAME or normalized.endswith(f'/{MOD_CONFIG_FILENAME}'):
                            return 'mod'
                        if check_filename_is_deltamod_info(normalized):
                            return 'mod'
            elif archive_lower.endswith('.tar.gz'):
                with tarfile.open(archive_path, 'r:gz') as tf:
                    for member in tf.getmembers():
                        name = member.name.replace('\\', '/').strip('/')
                        if name.lower().endswith('.dhtheme'):
                            return 'theme'
                        if name == 'plugin_init.py' or name.endswith('/plugin_init.py'):
                            return 'plugin'
                        if name == MOD_CONFIG_FILENAME or name.endswith(f'/{MOD_CONFIG_FILENAME}'):
                            return 'mod'
                        if check_filename_is_deltamod_info(name):
                            return 'mod'
            elif archive_lower.endswith('.rar'):
                try:
                    import rarfile
                    with rarfile.RarFile(archive_path, 'r') as rf:
                        for name in rf.namelist():
                            normalized = name.replace('\\', '/').strip('/')
                            if normalized.lower().endswith('.dhtheme'):
                                return 'theme'
                            if normalized == 'plugin_init.py' or normalized.endswith('/plugin_init.py'):
                                return 'plugin'
                            if normalized == MOD_CONFIG_FILENAME or normalized.endswith(f'/{MOD_CONFIG_FILENAME}'):
                                return 'mod'
                            if check_filename_is_deltamod_info(normalized):
                                return 'mod'
                except (OSError, ImportError) as e:
                    logging.debug(f'UrlInstallThread: Could not open RAR archive (rarfile may not be available): {e}')
            elif archive_lower.endswith('.7z'):
                try:
                    import py7zr
                    with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                        for name in zf.getnames():
                            normalized = name.replace('\\', '/').strip('/')
                            if normalized.lower().endswith('.dhtheme'):
                                return 'theme'
                            if normalized == 'plugin_init.py' or normalized.endswith('/plugin_init.py'):
                                return 'plugin'
                            if normalized == MOD_CONFIG_FILENAME or normalized.endswith(f'/{MOD_CONFIG_FILENAME}'):
                                return 'mod'
                            if check_filename_is_deltamod_info(normalized):
                                return 'mod'
                except (OSError, ImportError) as e:
                    logging.debug(f'UrlInstallThread: Could not open 7z archive (py7zr may not be available): {e}')
        except Exception as e:
            logging.error(f'UrlInstallThread: Error detecting content type: {e}', exc_info=True)
        result = self._detect_content_type_from_extracted(archive_path)
        return result if result is not None else ''

    def _detect_content_type_from_extracted(self, archive_path: str) -> Optional[str]:
        with tempfile.TemporaryDirectory(prefix='dh-detect-type-') as unpack_dir:
            try:
                from utils.archive_utils import extract_any_archive
                extract_any_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                for root, dirs, files in os.walk(content_path):
                    for file in files:
                        if file.lower().endswith('.dhtheme'):
                            return 'theme'
                for root, dirs, files in os.walk(content_path):
                    if 'plugin_init.py' in files:
                        return 'plugin'
                for root, dirs, files in os.walk(content_path):
                    if MOD_CONFIG_FILENAME in files:
                        return 'mod'
                files_in_root = os.listdir(content_path)
                if has_deltamod_info_file(files_in_root):
                    return 'mod'
                for root, dirs, files in os.walk(content_path):
                    if has_deltamod_info_file(files):
                        return 'mod'
            except Exception as e:
                logging.error(f'UrlInstallThread: Error detecting content type from extracted: {e}', exc_info=True)
        return None

    def _prepare_for_manual_install(self, archive_path: str):
        try:
            from utils.archive_utils import extract_archive, extract_with_unrar_retry
            persistent_temp_dir = tempfile.mkdtemp(prefix='deltahub_url_manual_install_')
            try:
                archive_filename = os.path.basename(archive_path)
                preserved_archive_path = os.path.join(persistent_temp_dir, archive_filename)
                shutil.copy2(archive_path, preserved_archive_path)
                extract_dir = os.path.join(persistent_temp_dir, 'extracted')
                os.makedirs(extract_dir, exist_ok=True)
                extract_with_unrar_retry(preserved_archive_path, extract_dir, self, extract_archive)
                content_path = extract_dir
                contents = os.listdir(extract_dir)
                if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
                    content_path = os.path.join(extract_dir, contents[0])
                self.status.emit(tr('status.manual_install_ready'), UI_COLORS['status_info'])
                self.manual_install_required.emit(content_path, preserved_archive_path, persistent_temp_dir)
            except Exception:
                try:
                    shutil.rmtree(persistent_temp_dir, ignore_errors=True)
                except Exception:
                    pass
                raise
        except Exception as e:
            logging.error(f'UrlInstallThread: Error preparing for manual install: {e}', exc_info=True)
            self.finished.emit(False, tr('errors.manual_install_failed', error=str(e)))

    def _install_theme_from_file(self, theme_file_path: str):
        try:
            import zipfile
            self.status.emit(tr('themes.installing_theme'), UI_COLORS['status_warning'])
            config_dir = self.main_window.app_state.config_dir
            app_state = self.main_window.app_state
            settings_manager = self.main_window.settings_manager
            theme_settings = None
            with zipfile.ZipFile(theme_file_path, 'r') as zipf:
                if 'theme.json' not in zipf.namelist():
                    raise ValueError('Missing theme.json')
                from utils.archive_utils import extract_with_unrar_retry
                with tempfile.TemporaryDirectory(prefix='dh-theme-extract-') as temp_dir:
                    extract_with_unrar_retry(theme_file_path, temp_dir, self)
                    theme_json_path = os.path.join(temp_dir, 'theme.json')
                    with open(theme_json_path, 'r', encoding='utf-8') as f:
                        theme_settings = json.load(f)
                    for key, value in theme_settings.items():
                        app_state.local_config[key] = value
                    for old_file in ['custom_background_music.mp3', 'custom_background_music.wav', 'custom_startup_sound.mp3', 'custom_startup_sound.wav']:
                        old_file_path = os.path.join(config_dir, old_file)
                        if os.path.exists(old_file_path):
                            try:
                                os.remove(old_file_path)
                            except Exception as e:
                                logging.warning(f'Failed to remove old file {old_file}: {e}')
                    app_state.local_config['custom_background_path'] = ''
                    for filename in os.listdir(temp_dir):
                        src_path = os.path.join(temp_dir, filename)
                        if filename.startswith('background.'):
                            ext = os.path.splitext(filename)[1]
                            dest_path = os.path.join(config_dir, f'custom_background{ext}')
                            shutil.copy2(src_path, dest_path)
                            app_state.local_config['custom_background_path'] = dest_path
                        elif filename.startswith('background_music.'):
                            dest_path = os.path.join(config_dir, f'custom_background_music{os.path.splitext(filename)[1]}')
                            shutil.copy2(src_path, dest_path)
                        elif filename.startswith('startup_sound.'):
                            dest_path = os.path.join(config_dir, f'custom_startup_sound{os.path.splitext(filename)[1]}')
                            shutil.copy2(src_path, dest_path)
            if theme_settings:
                settings_manager.write_local_config()
                app_state.local_config['first_launch_splash_shown'] = True
                if 'disable_splash' in theme_settings:
                    app_state.local_config['disable_splash'] = theme_settings['disable_splash']
                elif 'disable_splash' not in app_state.local_config:
                    app_state.local_config['disable_splash'] = True
                settings_manager.write_local_config()
            try:
                if os.path.exists(theme_file_path):
                    os.remove(theme_file_path)
            except Exception as e:
                logging.warning(f'UrlInstallThread: Failed to remove theme file: {e}')
            self.status.emit(tr('themes.theme_installed'), 'success')
            self.finished.emit(True, tr('themes.theme_installed_success'))
        except Exception as e:
            logging.error(f'UrlInstallThread: Error installing theme from file: {e}', exc_info=True)
            self.finished.emit(False, tr('themes.installation_error', error=str(e)))

    def _extract_and_install_theme(self, archive_path: str, temp_dir: str):
        with tempfile.TemporaryDirectory(prefix='dh-theme-extract-') as unpack_dir:
            try:
                shutil.unpack_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                theme_file_path = None
                for root, dirs, files in os.walk(content_path):
                    for file in files:
                        if file.lower().endswith('.dhtheme'):
                            theme_file_path = os.path.join(root, file)
                            break
                    if theme_file_path:
                        break
                if not theme_file_path:
                    raise ValueError(tr('themes.archive_not_found'))
                with tempfile.TemporaryDirectory(prefix='dh-theme-temp-') as theme_temp_dir:
                    temp_theme_path = os.path.join(theme_temp_dir, os.path.basename(theme_file_path))
                    shutil.copy2(theme_file_path, temp_theme_path)
                    self._install_theme_from_file(temp_theme_path)
            except Exception as e:
                logging.error(f'UrlInstallThread: Error extracting theme: {e}', exc_info=True)
                self.finished.emit(False, tr('themes.installation_error', error=str(e)))

    def _install_plugin_from_archive(self, archive_path: str):
        try:
            self.status.emit(tr('plugins.installing_plugin'), UI_COLORS['status_warning'])
            plugins_dir = self.main_window.app_state.plugins_dir
            archive_name = os.path.basename(archive_path)
            if not archive_name or '.' not in archive_name:
                from utils.archive_utils import get_file_extension_from_content
                file_ext = get_file_extension_from_content(archive_path)
                archive_name = f'plugin{file_ext}'
            target_archive_path = os.path.join(plugins_dir, archive_name)
            shutil.copy2(archive_path, target_archive_path)
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
            except Exception as e:
                logging.warning(f'UrlInstallThread: Failed to remove plugin archive: {e}')
            self.status.emit(tr('plugins.plugin_installed'), 'success')
            self.finished.emit(True, tr('plugins.plugin_installed_success'))
        except Exception as e:
            logging.error(f'UrlInstallThread: Error installing plugin: {e}', exc_info=True)
            self.finished.emit(False, tr('plugins.installation_error', error=str(e)))

    def _check_redirect(self, archive_path: str, temp_dir: str) -> bool:
        try:
            with tempfile.TemporaryDirectory(prefix='dh-redirect-check-') as unpack_dir:
                from utils.archive_utils import extract_any_archive
                extract_any_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                files_in_root = os.listdir(content_path)
                redirect_config_path = None
                if MOD_CONFIG_FILENAME in files_in_root and len(files_in_root) == 1:
                    redirect_config_path = os.path.join(content_path, MOD_CONFIG_FILENAME)
                if redirect_config_path:
                    try:
                        with open(redirect_config_path, 'r', encoding='utf-8') as f:
                            redirect_config = json.load(f)
                        key = redirect_config.get('key') or redirect_config.get('mod_key')
                        if key and len(redirect_config) == 1:
                            self._install_mod_from_key(key)
                            return True
                        redirect_url = redirect_config.get('dm_url') or redirect_config.get('external_url') or redirect_config.get('download_url')
                        if redirect_url:
                            self.status.emit(tr('status.deltamod_redirect_found'), UI_COLORS['status_info'])
                            self.progress.emit(0)
                            if MOD_CONFIG_FILENAME in files_in_root:
                                self._process_deltahub_redirect(redirect_url, redirect_config)
                            else:
                                self._process_deltamod_archive(redirect_url)
                            return True
                    except Exception as e:
                        logging.warning(f'UrlInstallThread: Error reading redirect config: {e}')
        except Exception as e:
            logging.warning(f'UrlInstallThread: Error checking redirect: {e}')
        return False

    def _install_mod_from_hash(self, mod_hash: str):
        try:
            self._install_mod_from_key(mod_hash)
        except Exception as e:
            logging.error(f'UrlInstallThread: Error installing mod from hash: {e}', exc_info=True)
            self.finished.emit(False, tr('errors.mod_installation_failed'))

    def _install_mod_from_key(self, key: str):
        try:
            from workers.fetch_mods import FetchModsThread
            from workers.install_mods_worker import InstallModsThread
            self.status.emit(tr('status.downloading_mod'), UI_COLORS['status_info'])
            session = get_session()
            resp = session.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getModData?modId={key}', timeout=10)
            if resp.status_code != 200 or not resp.json():
                resp = session.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingModData?modId={key}', timeout=10)
                if resp.status_code != 200 or not resp.json():
                    raise ValueError(tr('errors.mod_not_found'))
            mod_data = resp.json()
            mod_data['key'] = key
            fetch_thread = FetchModsThread(self.main_window, force_update=False)
            mod_info = fetch_thread._parse_single_mod(key, mod_data)
            if not mod_info:
                raise ValueError(tr('errors.mod_not_found'))
            install_tasks = []
            for chapter_id in [0, 1, 2, 3, 4, -1]:
                chapter_data = mod_info.get_chapter_data(chapter_id) if chapter_id != -1 else None
                if chapter_id == -1 and mod_info.is_valid_for_demo():
                    install_tasks.append((mod_info, -1))
                elif chapter_data and chapter_data.is_valid():
                    install_tasks.append((mod_info, chapter_id))
            if not install_tasks:
                raise ValueError(tr('errors.mod_has_no_files'))
            install_thread = InstallModsThread(self.main_window, install_tasks, was_installed_before=False)
            install_thread.progress.connect(lambda p: self.progress.emit(p))
            install_thread.status.connect(lambda msg, color: self.status.emit(msg, color))

            def on_install_finished(success):
                if success:
                    mod_name = mod_info.name
                    self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                else:
                    self.finished.emit(False, tr('errors.mod_installation_failed'))
            install_thread.finished.connect(on_install_finished)
            install_thread.start()
            install_thread.wait()
        except Exception as e:
            logging.error(f'UrlInstallThread: Error installing mod from key: {e}', exc_info=True)
            self.finished.emit(False, tr('errors.mod_installation_failed'))

    def _install_mod_from_archive(self, archive_path: str, temp_dir: str):
        try:
            with tempfile.TemporaryDirectory(prefix='dh-url-unpack-') as unpack_dir:
                shutil.unpack_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                files_in_root = os.listdir(content_path)
                if has_deltamod_info_file(files_in_root):
                    self.status.emit(tr('status.deltamod_archive_detected_url'), UI_COLORS['status_info'])
                    converter = DeltamodConverter(content_path, self.main_window.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        mod_name = os.path.basename(new_mod_path)
                        try:
                            if os.path.exists(archive_path):
                                os.remove(archive_path)
                        except Exception as e:
                            logging.warning(f'UrlInstallThread: Failed to remove mod archive: {e}')
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.deltamod_conversion_failed_url'))
                    return
                if MOD_CONFIG_FILENAME in files_in_root:
                    self.status.emit(tr('status.installing_mod'), UI_COLORS['status_info'])
                    mod_dir = self._install_deltahub_mod_from_path(content_path)
                    if mod_dir:
                        mod_name = os.path.basename(mod_dir)
                        try:
                            if os.path.exists(archive_path):
                                os.remove(archive_path)
                        except Exception as e:
                            logging.warning(f'UrlInstallThread: Failed to remove mod archive: {e}')
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.mod_installation_failed'))
                else:
                    raise ValueError(tr('errors.unsupported_mod_format_url'))
        except Exception as e:
            logging.error(f'UrlInstallThread: Error installing mod: {e}', exc_info=True)
            self.finished.emit(False, str(e))
