import json
import os
import shutil
import tempfile
import threading
import time
import requests
from utils.network_utils import get_session
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage
from config.constants import CLOUD_FUNCTIONS_BASE_URL, UI_COLORS, NETWORK_TIMEOUT_MEDIUM, NETWORK_TIMEOUT_HEAD
from managers.localization_manager import tr
from utils.file_utils import get_unique_mod_dir
from utils.deltamod_converter import DeltamodConverter
from utils.network_utils import download_file
import logging


class PresenceWorker(QObject):
    finished, update_online_count = (pyqtSignal(), pyqtSignal(int))

    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id
        self._busy = False

    @pyqtSlot()
    def run(self):
        try:
            if self._busy:
                return
            self._busy = True
            url = f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat'
            data = {'sessionId': self.session_id}
            session = get_session()
            resp = session.post(url, json=data, timeout=NETWORK_TIMEOUT_MEDIUM)
            if resp.status_code == 200:
                try:
                    data = resp.json() or {}
                    online = int(data.get('online', 0))
                    self.update_online_count.emit(max(online, 0))
                except Exception as e:
                    logging.warning(f'PresenceWorker: parse error: {e}', exc_info=True)
                    self.update_online_count.emit(-1)
            else:
                self.update_online_count.emit(-1)
        except requests.Timeout as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'PresenceWorker: timeout error: {e}')
            logging.debug(safe_msg)
            self.update_online_count.emit(-1)
        except requests.ConnectionError as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'PresenceWorker: connection error: {e}')
            logging.debug(safe_msg)
            self.update_online_count.emit(-1)
        except requests.RequestException as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'PresenceWorker: request error: {e}')
            logging.debug(safe_msg)
            self.update_online_count.emit(-1)
        finally:
            self._busy = False
            self.finished.emit()


class BgLoader(QThread):
    loaded = pyqtSignal(object)

    def __init__(self, path: str, size):
        super().__init__()
        self._path = path
        self._size = size

    def run(self):
        if self._path.lower().endswith('.gif'):
            self.loaded.emit(('gif', self._path))
        else:
            img = QImage(self._path)
            self.loaded.emit(('img', img))


class FetchChangelogWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, source_path_or_url: str, parent=None):
        super().__init__(parent)
        self.source = source_path_or_url

    @pyqtSlot()
    def run(self):
        text = ''
        try:
            if self.source.startswith(('http://', 'https://')):
                params = {'ts': int(time.time())}
                headers = {'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'User-Agent': 'DELTAHUB/1.0'}
                session = get_session()
                with session.get(self.source, params=params, headers=headers, timeout=NETWORK_TIMEOUT_MEDIUM) as resp:
                    resp.raise_for_status()
                    text = resp.text
            elif os.path.exists(self.source) or os.path.exists(self.source.replace('.md', '.txt')):
                path_to_read = self.source if os.path.exists(self.source) else self.source.replace('.md', '.txt')
                with open(path_to_read, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            else:
                text = self.source
        except Exception as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'FetchChangelogWorker: failed to load changelog: {e}')
            logging.warning(safe_msg, exc_info=True)
            text = tr('errors.changelog_load_failed')
        finally:
            self.finished.emit(text)


class FullInstallThread(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, main_window, target_dir: str, make_shortcut: bool = False):
        super().__init__(main_window)
        self.main_window = main_window
        self.target_dir = target_dir
        self._cancelled = False
        self._session = None
        self._active_response = None

    def cancel(self):
        self._cancelled = True
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception as e:
                    logging.warning(f'FullInstallThread.cancel: session close error: {e}', exc_info=True)
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logging.warning(f'FullInstallThread.cancel: response close error: {e}', exc_info=True)
        finally:
            self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])

    def run(self):
        full_install_url = self.main_window.global_settings.get('full_install_url')
        if not full_install_url:
            self.status.emit(tr('errors.files_not_found'), UI_COLORS['status_error'])
            self.finished.emit(False, self.target_dir)
            return
        self.status.emit(tr('status.installing_game_files'), UI_COLORS['status_warning'])
        try:
            session = get_session()
            self._session = session
            resp = session.head(full_install_url, allow_redirects=True, timeout=NETWORK_TIMEOUT_MEDIUM)
            total_size = int(resp.headers.get('content-length', 0))
            downloaded_ref = [0]
            from utils.file_utils import download_and_extract_archive

            def progress_callback(progress):
                self.progress.emit(progress)

            def on_response(r):
                self._active_response = r
            download_and_extract_archive(full_install_url, self.target_dir, progress_callback, total_size, downloaded_ref, session, is_game_installation=True, cancel_check=lambda: self._cancelled, on_response=on_response)
            if self._cancelled:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
                self.finished.emit(False, self.target_dir)
                return
            self.status.emit(tr('status.demo_installation_complete'), UI_COLORS['status_success'])
            self.finished.emit(True, self.target_dir)
        except Exception as e:
            logging.error(f'FullInstallThread.run: installation error: {e}', exc_info=True)
            self.status.emit(tr('errors.full_installation_error').format(str(e)), UI_COLORS['status_error'])
            self.finished.emit(False, self.target_dir)
        finally:
            self._session = None
            self._active_response = None


class InstallModsThread(QThread):
    progress, status, finished = (pyqtSignal(int), pyqtSignal(str, str), pyqtSignal(bool))

    def __init__(self, main_window, install_tasks, was_installed_before: bool):
        super().__init__(main_window)
        self.main_window = main_window
        self.install_tasks = install_tasks
        self.was_installed_before = was_installed_before
        self._cancelled = False
        self._installed_dirs = []
        self.temp_root = None
        self._session = None
        self._active_response = None

    def cancel(self):
        self._cancelled = True
        self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception as e:
                    logging.warning(f'InstallModsThread.cancel: session close error: {e}', exc_info=True)
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logging.warning(f'InstallModsThread.cancel: response close error: {e}', exc_info=True)
        except Exception as e:
            logging.warning(f'InstallModsThread.cancel: cleanup failed: {e}', exc_info=True)

    def _collect_remote_versions_for_chapter(self, mod, chapter_id: int) -> dict:
        versions: dict[str, str] = {}
        if chapter_id == -1:
            if mod.is_valid_for_demo() and mod.demo_version:
                versions['demo'] = mod.demo_version
            return versions
        chapter_data = mod.get_chapter_data(chapter_id)
        if not chapter_data:
            return versions
        if chapter_data.data_file_version:
            versions['data'] = chapter_data.data_file_version
        for extra_file in chapter_data.extra_files:
            if extra_file and extra_file.key and extra_file.version:
                versions[extra_file.key] = extra_file.version
        return versions

    def _should_update_component(self, mod, chapter_id: int, existing_folder: str) -> dict:
        if not existing_folder:
            return {}
        config_path = os.path.join(self.main_window.app_state.mods_dir, existing_folder, 'config.json')
        if not os.path.exists(config_path):
            return {}
        try:
            config_data = self.main_window.settings_manager.read_json(config_path)
            local_versions = config_data.get('chapters', {}).get(str(chapter_id), {}).get('versions', {}) or {}
            remote_versions = self._collect_remote_versions_for_chapter(mod, chapter_id)
            components_to_update: dict[str, dict] = {}
            chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
            if chapter_data and chapter_data.data_file_url and remote_versions.get('data'):
                local_data_v = local_versions.get('data')
                remote_data_v = remote_versions.get('data')
                from utils.file_utils import version_sort_key
                if remote_data_v and version_sort_key(remote_data_v) > version_sort_key(local_data_v or '0.0.0'):
                    components_to_update['data'] = {'url': chapter_data.data_file_url, 'local_version': local_data_v, 'remote_version': remote_data_v}
            if chapter_data:
                for extra_file in chapter_data.extra_files:
                    rv = remote_versions.get(extra_file.key)
                    lv = local_versions.get(extra_file.key)
                    if rv and version_sort_key(rv) > version_sort_key(lv or '0.0.0'):
                        components_to_update[extra_file.key] = {'url': extra_file.url, 'local_version': lv, 'remote_version': rv}
                remote_extra_keys = {ef.key for ef in chapter_data.extra_files}
                for missing_key in [k for k in local_versions.keys() if k != 'data' and k not in remote_extra_keys]:
                    components_to_update[missing_key] = {'delete': True}
            return components_to_update
        except Exception as e:
            logging.error(f'_should_update_component: failed to compute updates: {e}', exc_info=True)
            return {}

    def _increment_downloads_for_installed_mods(self, installed_mods):
        try:
            for mod_key in [key for key in installed_mods if not key.startswith('local_')]:
                self._increment_mod_downloads_on_server(mod_key)
        except Exception as e:
            logging.debug(f'_increment_downloads_for_installed_mods: failed: {e}')

    def _increment_mod_downloads_on_server(self, mod_key):
        try:
            url = f'{CLOUD_FUNCTIONS_BASE_URL}/incrementDownloads'
            data = {'modId': mod_key}
            session = get_session()
            response = session.post(url, json=data, timeout=NETWORK_TIMEOUT_MEDIUM)
            return response.status_code == 200
        except Exception as e:
            logging.debug(f'_increment_mod_downloads_on_server: failed: {e}')
            return False

    def _download_component_file(self, url: str, target_dir: str, component_type: str, progress_callback, total_size: int, downloaded_ref: list[int], session=None):
        import os
        import platform
        from urllib.parse import urlparse, unquote
        if session is None:
            session = get_session()
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if component_type == 'data':
            from config.constants import DATA_FILE_EXTENSIONS
            if not filename.lower().endswith(DATA_FILE_EXTENSIONS):
                if platform.system() == 'Darwin':
                    filename = 'game.ios.xdelta'
                else:
                    filename = 'data.win.xdelta'
        elif not filename or '.' not in filename:
            filename = f'extra_file_{hash(url) % 10000}.zip'
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        try:

            def on_response(r):
                self._active_response = r
            download_file(session, url, target_path, progress_callback, total_size, downloaded_ref, cancel_check=lambda: self._cancelled, on_response=on_response)
        except (requests.Timeout, requests.ConnectionError) as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except OSError as rm_e:
                    logging.debug(f'_download_component_file: cleanup failed: {rm_e}')
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'_download_component_file: network error downloading file: {e}')
            logging.error(safe_msg, exc_info=True)
            raise
        except requests.RequestException as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except OSError as rm_e:
                    logging.debug(f'_download_component_file: cleanup failed: {rm_e}')
            from utils.network_utils import sanitize_log_message
            status_code = getattr(e.response, 'status_code', None)
            safe_msg = sanitize_log_message(f'_download_component_file: request error downloading file: {e}')
            if status_code:
                safe_msg = f'{safe_msg} [HTTP {status_code}]'
            logging.error(safe_msg, exc_info=True)
            raise
        except RuntimeError as e:
            if str(e) == 'download_cancelled':
                if os.path.exists(target_path):
                    try:
                        os.remove(target_path)
                    except OSError as rm_e:
                        logging.debug(f'_download_component_file: cleanup failed: {rm_e}')
                raise
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except OSError as rm_e:
                    logging.debug(f'_download_component_file: cleanup failed: {rm_e}')
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'_download_component_file: unexpected error downloading file: {e}')
            logging.error(safe_msg, exc_info=True)
            raise
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except OSError as rm_e:
                    logging.debug(f'_download_component_file: cleanup failed: {rm_e}')
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'_download_component_file: unexpected error downloading file: {e}')
            logging.error(safe_msg, exc_info=True)
            raise

    def run(self):
        try:
            self.temp_root = tempfile.mkdtemp(prefix='deltahub-install-')
            tasks = []
            total_bytes = 0
            mod_folders = {}
            for mod, chapter_id in self.install_tasks:
                if mod.key not in mod_folders:
                    mod_folder_path = self.main_window.mod_manager.get_mod_folder_path(mod.key)
                    if mod_folder_path:
                        existing_folder = os.path.basename(mod_folder_path)
                        mod_folders[mod.key] = existing_folder
                    else:
                        mod_folders[mod.key] = get_unique_mod_dir(self.main_window.app_state.mods_dir, mod.name)
                existing_folder = mod_folders.get(mod.key, '')
                chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
                if chapter_id == -1 and mod.is_valid_for_demo():
                    tasks.append({'mod': mod, 'url': mod.demo_url, 'chapter_id': -1, 'component': 'demo'})
                elif chapter_data:
                    components_to_update = self._should_update_component(mod, chapter_id, existing_folder)
                    if not components_to_update:
                        if chapter_data.data_file_url:
                            tasks.append({'mod': mod, 'url': chapter_data.data_file_url, 'chapter_id': chapter_id, 'component': 'data'})
                        for extra_file in chapter_data.extra_files:
                            tasks.append({'mod': mod, 'url': extra_file.url, 'chapter_id': chapter_id, 'component': extra_file.key})
                    else:
                        for component, info in components_to_update.items():
                            if info.get('delete'):
                                tasks.append({'mod': mod, 'chapter_id': chapter_id, 'component': component, 'delete': True})
                                continue
                            t = {'mod': mod, 'url': info['url'], 'chapter_id': chapter_id, 'component': component}
                            tasks.append(t)
            if not tasks:
                self.finished.emit(True)
                return
            session = get_session()
            self._session = session
            download_tasks = [t for t in tasks if t.get('url')]
            file_sizes_cache = {}
            for task in download_tasks:
                u = task.get('url')
                try:
                    h = session.head(u, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
                    h.raise_for_status()
                    content_length = int(h.headers.get('content-length', 0))
                    file_sizes_cache[u] = content_length
                    total_bytes += content_length
                except requests.Timeout as e:
                    from utils.network_utils import sanitize_log_message
                    safe_msg = sanitize_log_message(f'InstallModsThread: HEAD timeout: {e}')
                    logging.warning(safe_msg)
                    file_sizes_cache[u] = 0
                    total_bytes = 0
                    break
                except requests.HTTPError as e:
                    from utils.network_utils import sanitize_log_message
                    status_code = e.response.status_code if e.response else None
                    safe_msg = sanitize_log_message(f'InstallModsThread: HEAD HTTP error: {e}')
                    if status_code:
                        safe_msg = f'{safe_msg} [HTTP {status_code}]'
                    logging.warning(safe_msg)
                    file_sizes_cache[u] = 0
                    total_bytes = 0
                    break
                except requests.RequestException as e:
                    from utils.network_utils import sanitize_log_message
                    safe_msg = sanitize_log_message(f'InstallModsThread: HEAD request error: {e}')
                    logging.warning(safe_msg)
                    file_sizes_cache[u] = 0
                    total_bytes = 0
                    break
                except Exception as e:
                    from utils.network_utils import sanitize_log_message
                    safe_msg = sanitize_log_message(f'InstallModsThread: unexpected error during HEAD: {e}')
                    logging.warning(safe_msg, exc_info=True)
                    file_sizes_cache[u] = 0
                    total_bytes = 0
                    break
            if self._cancelled:
                self.finished.emit(False)
                return
            self.status.emit(tr('status.preparing_download'), UI_COLORS['status_warning'])
            if self._cancelled:
                self.finished.emit(False)
                return
            downloaded_ref = [0]
            done_files = 0
            installed_mods = {}
            mod_configs = {}
            total_items = len(download_tasks)
            current_index = 0
            for task in tasks:
                if self._cancelled:
                    self.finished.emit(False)
                    return
                mod = task.get('mod')
                chapter_id = task.get('chapter_id')
                mod_folder_name = mod_folders[mod.key]
                mod_dir = os.path.join(self.temp_root, mod_folder_name)
                if chapter_id == -1:
                    cache_dir = os.path.join(mod_dir, 'demo')
                elif chapter_id == 0:
                    cache_dir = os.path.join(mod_dir, 'chapter_0')
                else:
                    cache_dir = os.path.join(mod_dir, f'chapter_{chapter_id}')
                if task.get('delete'):
                    try:
                        if os.path.exists(cache_dir):
                            for fname in os.listdir(cache_dir):
                                fl = fname.lower()
                                if fl.endswith(('.zip', '.rar', '.7z', '.tar.gz', '.lzma')):
                                    pass
                    except Exception as e:
                        logging.warning(f'InstallModsThread: delete cleanup failed: {e}', exc_info=True)
                    continue
                url = task.get('url')
                if not url:
                    continue
                current_index += 1
                file_size_mb = tr('status.unknown_size')
                file_size_bytes = file_sizes_cache.get(url, 0)
                if file_size_bytes > 0:
                    size_mb = file_size_bytes / (1024 * 1024)
                    file_size_mb = tr('status.unknown_size') if size_mb < 0.05 else f'{size_mb:.1f} MB'
                status_text = f'{mod.name} {current_index}/{total_items} ({file_size_mb})'
                self.status.emit(status_text, UI_COLORS['status_warning'])
                self._installed_dirs.append(cache_dir)
                chapter_data = mod.get_chapter_data(chapter_id)
                is_data_file = chapter_data and url and (chapter_data.data_file_url == url)
                from config.constants import DATA_FILE_EXTENSIONS
                is_xdelta = url.lower().endswith(DATA_FILE_EXTENSIONS) if url else False
                try:
                    if is_data_file:
                        if is_xdelta:

                            def progress_callback(progress):
                                self.progress.emit(progress)
                            self._download_component_file(url, cache_dir, 'data', progress_callback, total_bytes, downloaded_ref, session)
                        else:
                            from utils.file_utils import download_and_extract_archive

                            def progress_callback(progress):
                                self.progress.emit(progress)
                            download_and_extract_archive(url, cache_dir, progress_callback, total_bytes, downloaded_ref, session, cancel_check=lambda: self._cancelled)
                            if self._cancelled:
                                self.finished.emit(False)
                                return
                    else:

                        def progress_callback(progress):
                            self.progress.emit(progress)
                        self._download_component_file(url, cache_dir, 'extra', progress_callback, total_bytes, downloaded_ref, session)
                except RuntimeError as e:
                    if str(e) == 'download_cancelled':
                        raise
                    from utils.network_utils import sanitize_log_message
                    safe_msg = sanitize_log_message(f'InstallModsThread._download_mod_file: download failed: {e}')
                    logging.error(safe_msg, exc_info=True)
                    raise
                except Exception as e:
                    from utils.network_utils import sanitize_log_message
                    safe_msg = sanitize_log_message(f'InstallModsThread._download_mod_file: download failed: {e}')
                    logging.error(safe_msg, exc_info=True)
                    raise
                if mod.key not in installed_mods:
                    installed_mods[mod.key] = {'mod': mod, 'chapters': set()}
                installed_mods[mod.key]['chapters'].add(chapter_id)
                if url and total_bytes == 0:
                    done_files += 1
                    progress = int(done_files / max(1, len(download_tasks)) * 100)
                    self.progress.emit(progress)
            if self._cancelled:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
                self.finished.emit(False)
                return
            for mod_key, mod_data in installed_mods.items():
                mod = mod_data['mod']
                mod_folder_name = mod_folders[mod.key]
                mod_dir = os.path.join(self.main_window.app_state.mods_dir, mod_folder_name)
                files_data = {}
                for chapter_id in mod_data['chapters']:
                    chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
                    versions_dict = {}
                    file_info = {}
                    if chapter_data:
                        if chapter_data.data_file_url and chapter_data.data_file_version:
                            versions_dict['data'] = chapter_data.data_file_version
                        if chapter_data.data_file_url:
                            file_info['data_file_version'] = chapter_data.data_file_version
                        extra_files_dict = {}
                        for extra_file in chapter_data.extra_files:
                            versions_dict[extra_file.key] = extra_file.version
                            if extra_file.key not in extra_files_dict:
                                extra_files_dict[extra_file.key] = []
                            basename = os.path.basename(extra_file.url)
                            extra_files_dict[extra_file.key].append(basename)
                        if extra_files_dict:
                            file_info['extra_files'] = extra_files_dict
                        if versions_dict:
                            file_info['versions'] = versions_dict
                    elif chapter_id == -1 and mod.is_valid_for_demo():
                        file_info['data_file_version'] = mod.demo_version or '1.0.0'
                        file_info['versions'] = {'demo': mod.demo_version or '1.0.0'}
                    if file_info:
                        if chapter_id == -1:
                            file_key = 'demo'
                        elif chapter_id == 0:
                            file_key = '0'
                        else:
                            file_key = str(chapter_id)
                        files_data[file_key] = file_info
                config_data = {'is_local_mod': False, 'mod_key': mod.key, 'name': mod.name, 'author': mod.author, 'version': mod.version, 'game_version': mod.game_version, 'modgame': mod.modgame, 'files': files_data, 'tags': mod.tags}
                mod_configs[mod.key] = {'folder_name': mod_folder_name, 'config': config_data}
            try:
                os.makedirs(self.main_window.app_state.mods_dir, exist_ok=True)
                for entry in os.listdir(self.temp_root or ''):
                    src = os.path.join(self.temp_root, entry)
                    dst = os.path.join(self.main_window.app_state.mods_dir, entry)
                    if os.path.isdir(src):
                        try:
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                        except TypeError:
                            if not os.path.exists(dst):
                                shutil.move(src, dst)
                            else:
                                for root, dirs, files in os.walk(src):
                                    rel = os.path.relpath(root, src)
                                    target_root = os.path.join(dst, rel)
                                    os.makedirs(target_root, exist_ok=True)
                                    for d in dirs:
                                        os.makedirs(os.path.join(target_root, d), exist_ok=True)
                                    for f in files:
                                        shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))
                    else:
                        shutil.copy2(src, dst)
            except Exception as e:
                logging.warning(f'InstallModsThread: copy extracted files failed: {e}')
            if self._cancelled:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
                self.finished.emit(False)
                return
            for mod_key, info in mod_configs.items():
                folder_name = info['folder_name']
                config_data = info['config']
                mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name)
                config_path = os.path.join(mod_dir, 'config.json')
                self.main_window.settings_manager.write_json(config_path, config_data)
            metadata = self.main_window.mod_manager._read_metadata()
            for mod_key in installed_mods.keys():
                metadata[mod_key] = {'installed_date': time.strftime('%Y-%m-%d %H:%M:%S'), 'is_available_on_server': True}
            self.main_window.mod_manager._write_metadata(metadata)
            self._increment_downloads_for_installed_mods(installed_mods.keys())
            if self._cancelled:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
                self.finished.emit(False)
            else:
                self.status.emit(tr('status.installation_complete'), UI_COLORS['status_success'])
                self.finished.emit(True)
        except PermissionError as e:
            logging.warning(f'InstallModsThread.run: permission error: {e}')
            try:
                self.status.emit(tr('errors.permission_error_install'), UI_COLORS['status_error'])
            except Exception as emit_e:
                logging.debug(f'InstallModsThread: failed to emit permission error: {emit_e}')
            self.finished.emit(False)
        except RuntimeError as e:
            if str(e) == 'download_cancelled':
                logging.info('InstallModsThread.run: download cancelled by user')
                self.finished.emit(False)
            else:
                logging.error(f'InstallModsThread.run: installation error: {e}', exc_info=True)
                self.status.emit(tr('errors.installation_error', error=str(e)), UI_COLORS['status_error'])
                self.finished.emit(False)
        except Exception as e:
            logging.error(f'InstallModsThread.run: installation error: {e}', exc_info=True)
            self.status.emit(tr('errors.installation_error', error=str(e)), UI_COLORS['status_error'])
            self.finished.emit(False)
        finally:
            try:
                if self.temp_root and os.path.isdir(self.temp_root):
                    shutil.rmtree(self.temp_root, ignore_errors=True)
            except Exception as cleanup_e:
                logging.debug(f'InstallModsThread: temp cleanup failed: {cleanup_e}')
            self._session = None


class UrlInstallThread(QThread):
    status = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    prompt_required = pyqtSignal(str, str)

    def __init__(self, main_window, url: str):
        super().__init__(main_window)
        self.main_window = main_window
        self.url = url
        self.prompt_event = threading.Event()
        self.prompt_result = False
        self._cancelled = False
        self._session = None
        self._active_response = None

    def cancel(self):
        self._cancelled = True
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception as e:
                    logging.warning(f'UrlInstallThread.cancel: session close error: {e}', exc_info=True)
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logging.warning(f'UrlInstallThread.cancel: response close error: {e}', exc_info=True)
        finally:
            try:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            except Exception as e:
                logging.warning(f'UrlInstallThread.cancel: emit failed: {e}', exc_info=True)

    def run(self):
        try:
            if not self.url.startswith('deltahub://'):
                raise ValueError(tr('errors.invalid_url_scheme'))
            content = self.url[len('deltahub://'):].split(',')[0].strip().rstrip('/')
            if not content.startswith(('http://', 'https://')):
                content = content.replace('https//', 'https://').replace('http//', 'http://')
            download_url = content
            with tempfile.TemporaryDirectory(prefix='dh-url-install-') as temp_dir:
                self.status.emit(tr('status.downloading_from_external'), UI_COLORS['status_warning'])
                archive_path = self._download_archive(download_url, temp_dir)
                with tempfile.TemporaryDirectory(prefix='dh-url-unpack-') as unpack_dir:
                    shutil.unpack_archive(archive_path, unpack_dir)
                    content_path = unpack_dir
                    unpacked_items = os.listdir(unpack_dir)
                    if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                        content_path = os.path.join(unpack_dir, unpacked_items[0])
                    files_in_root = os.listdir(content_path)
                    if 'config.json' in files_in_root and len(files_in_root) == 1:
                        with open(os.path.join(content_path, 'config.json'), 'r', encoding='utf-8') as f:
                            redirect_config = json.load(f)
                        if 'dm_url' in redirect_config:
                            self.status.emit(tr('status.deltamod_redirect_found'), UI_COLORS['status_info'])
                            self.progress.emit(0)
                            self._process_deltamod_archive(redirect_config['dm_url'])
                            return
                    if '_deltamodInfo.json' in files_in_root:
                        self.status.emit(tr('status.deltamod_archive_detected_url'), UI_COLORS['status_info'])
                        converter = DeltamodConverter(content_path, self.main_window.app_state.mods_dir)
                        new_mod_path = converter.convert()
                        if new_mod_path:
                            mod_name = os.path.basename(new_mod_path)
                            self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                        else:
                            raise ValueError(tr('errors.deltamod_conversion_failed_url'))
                        return
                    raise ValueError(tr('errors.unsupported_mod_format_url'))
        except Exception as e:
            self.finished.emit(False, str(e))

    def _process_deltamod_archive(self, url: str):
        with tempfile.TemporaryDirectory(prefix='dh-redirect-dl-') as temp_dir:
            archive_path = self._download_archive(url, temp_dir)
            with tempfile.TemporaryDirectory(prefix='dh-redirect-unpack-') as unpack_dir:
                shutil.unpack_archive(archive_path, unpack_dir)
                content_path = unpack_dir
                unpacked_items = os.listdir(unpack_dir)
                if len(unpacked_items) == 1 and os.path.isdir(os.path.join(unpack_dir, unpacked_items[0])):
                    content_path = os.path.join(unpack_dir, unpacked_items[0])
                if '_deltamodInfo.json' in os.listdir(content_path):
                    converter = DeltamodConverter(content_path, self.main_window.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        mod_name = os.path.basename(new_mod_path)
                        self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                    else:
                        raise ValueError(tr('errors.deltamod_conversion_failed_url'))
                else:
                    raise ValueError(tr('errors.deltamod_archive_invalid_redirect'))

    def _download_archive(self, url: str, temp_dir: str) -> str:
        from urllib.parse import urlparse, unquote
        from utils.network_utils import download_file, get_filename_from_url
        from config.constants import NETWORK_TIMEOUT_HEAD
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename or '.' not in filename:
            session = get_session()
            filename = get_filename_from_url(session, url)
        if not filename:
            filename = 'mod.zip'
        if not any((filename.lower().endswith(ext) for ext in ['.zip', '.rar', '.7z', '.tar.gz', '.lzma'])):
            filename = 'mod.zip'
        archive_path = os.path.join(temp_dir, filename)
        session = get_session()
        self._session = session
        downloaded_ref = [0]
        total_size = 0
        try:
            head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
            total_size = int(head_response.headers.get('content-length', 0))
        except (requests.RequestException, ValueError):
            pass

        def progress_callback(progress):
            self.progress.emit(progress)

        def on_response(r):
            self._active_response = r
        download_file(session, url, archive_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=lambda: self._cancelled, on_response=on_response)
        self.progress.emit(100)
        return archive_path


class FetchHelpContentWorker(QObject):
    finished = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    @pyqtSlot()
    def run(self):
        try:
            from utils.network_utils import get_session
            response = get_session().get(self.url, timeout=NETWORK_TIMEOUT_MEDIUM)
            if response.ok:
                content = response.text
                self.finished.emit(content)
            else:
                error_msg = tr('errors.load_error_http', code=response.status_code)
                self.finished.emit(f'<i>{error_msg}</i>')
        except Exception as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'FetchHelpContentWorker: failed to load help content: {e}')
            logging.warning(safe_msg, exc_info=True)
            self.finished.emit(f"<i>{tr('dialogs.help_content_load_failed')}</i>")


class ModScanThread(QThread):
    scan_completed = pyqtSignal(dict)

    def __init__(self, mods_dir: str, parent=None):
        super().__init__(parent)
        self.mods_dir = mods_dir
        self._cancel_flag = False

    def cancel(self):
        self._cancel_flag = True

    def run(self):
        cache = {}
        if not os.path.exists(self.mods_dir):
            self.scan_completed.emit(cache)
            return
        try:
            with os.scandir(self.mods_dir) as entries:
                for entry in entries:
                    if self._cancel_flag:
                        break
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    folder_name = entry.name
                    folder_path = entry.path
                    config_path = os.path.join(folder_path, 'config.json')
                    if not os.path.exists(config_path):
                        continue
                    try:
                        config_mtime = os.path.getmtime(config_path)
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                        mod_key = config_data.get('mod_key')
                        if not mod_key:
                            continue
                        if mod_key in cache:
                            existing_info = cache[mod_key]
                            if config_mtime <= existing_info.config_mtime:
                                continue
                        mod_info = {'mod_key': mod_key, 'folder_path': folder_path, 'folder_name': folder_name, 'config_data': config_data, 'config_mtime': config_mtime}
                        cache[mod_key] = mod_info
                    except OSError as e:
                        from utils.network_utils import sanitize_log_message
                        safe_msg = sanitize_log_message(f'ModScanThread: failed to access config {config_path}: {e}')
                        logging.warning(safe_msg, exc_info=True)
                        continue
                    except json.JSONDecodeError as e:
                        from utils.network_utils import sanitize_log_message
                        safe_msg = sanitize_log_message(f'ModScanThread: invalid JSON in {config_path}: {e}')
                        logging.warning(safe_msg, exc_info=True)
                        continue
                    except KeyError as e:
                        from utils.network_utils import sanitize_log_message
                        safe_msg = sanitize_log_message(f'ModScanThread: missing key in {config_path}: {e}')
                        logging.debug(safe_msg)
                        continue
        except OSError as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'ModScanThread: failed to list directory {self.mods_dir}: {e}')
            logging.error(safe_msg, exc_info=True)
        self.scan_completed.emit(cache)
