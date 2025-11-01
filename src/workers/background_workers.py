import json
import os
import rarfile
import shutil
import tempfile
import threading
import time
import zipfile
import py7zr
import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage
from config.constants import BROWSER_HEADERS, CLOUD_FUNCTIONS_BASE_URL, UI_COLORS
from managers.localization_manager import tr
from utils.file_utils import get_unique_mod_dir
from utils.deltamod_converter import DeltamodConverter
from utils.network_utils import download_file


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
            resp = requests.post(url, json=data, timeout=8)
            if resp.status_code == 200:
                try:
                    data = resp.json() or {}
                    online = int(data.get('online', 0))
                    self.update_online_count.emit(max(online, 0))
                except Exception:
                    self.update_online_count.emit(-1)
            else:
                self.update_online_count.emit(-1)
        except requests.RequestException:
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


class FetchChangelogThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, source_path_or_url: str, parent=None):
        super().__init__(parent)
        self.source = source_path_or_url

    def run(self):
        text = ''
        try:
            if self.source.startswith(('http://', 'https://')):
                params = {'ts': int(time.time())}
                headers = {'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'User-Agent': 'DELTAHUB/1.0'}
                with requests.get(self.source, params=params, headers=headers, timeout=10) as resp:
                    resp.raise_for_status()
                    text = resp.text
            elif os.path.exists(self.source) or os.path.exists(self.source.replace('.md', '.txt')):
                path_to_read = self.source if os.path.exists(self.source) else self.source.replace('.md', '.txt')
                with open(path_to_read, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            else:
                text = self.source
        except Exception:
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
                except Exception:
                    pass
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception:
                    pass
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
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
            retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=10)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            self._session = session
            resp = session.head(full_install_url, allow_redirects=True, timeout=10)
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
                except Exception:
                    pass
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception:
                    pass
        except Exception:
            pass

    def _find_existing_mod_folder(self, mod_key: str) -> str:
        if not os.path.exists(self.main_window.app_state.mods_dir):
            return ''
        for folder_name in os.listdir(self.main_window.app_state.mods_dir):
            config_path = os.path.join(self.main_window.app_state.mods_dir, folder_name, 'config.json')
            if os.path.exists(config_path):
                try:
                    config_data = self.main_window.settings_manager.read_json(config_path)
                    if config_data.get('mod_key') == mod_key:
                        return folder_name
                except Exception:
                    continue
        return ''

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
                is_xdelta_mod = getattr(mod, 'is_xdelta', False)
                local_is_xdelta = False
                try:
                    mod_path = os.path.join(self.main_window.app_state.mods_dir, existing_folder)
                    local_is_xdelta = any((f.lower().endswith('.xdelta') for f in os.listdir(mod_path) if os.path.isfile(os.path.join(mod_path, f))))
                except Exception:
                    local_is_xdelta = False
                type_changed = is_xdelta_mod != local_is_xdelta
                local_data_v = local_versions.get('data')
                remote_data_v = remote_versions.get('data')
                from utils.file_utils import version_sort_key
                if remote_data_v and (type_changed or version_sort_key(remote_data_v) > version_sort_key(local_data_v or '0.0.0')):
                    components_to_update['data'] = {'url': chapter_data.data_file_url, 'local_version': local_data_v, 'remote_version': remote_data_v, 'is_xdelta': is_xdelta_mod, 'type_changed': type_changed}
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
        except Exception:
            return {}

    def _increment_downloads_for_installed_mods(self, installed_mods):
        try:
            for mod_key in [key for key in installed_mods if not key.startswith('local_')]:
                self._increment_mod_downloads_on_server(mod_key)
        except Exception:
            pass

    def _increment_mod_downloads_on_server(self, mod_key):
        try:
            url = f'{CLOUD_FUNCTIONS_BASE_URL}/incrementDownloads'
            data = {'modId': mod_key}
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def _download_archive_file(self, url: str, target_dir: str, progress_callback, total_size: int, downloaded_ref: list[int], session=None):
        import os
        from urllib.parse import urlparse, unquote
        if session is None:
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename or '.' not in filename:
            filename = f'extra_file_{hash(url) % 10000}.zip'
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        try:

            def on_response(r):
                self._active_response = r
            download_file(session, url, target_path, progress_callback, total_size, downloaded_ref, cancel_check=lambda: self._cancelled, on_response=on_response)
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass
            raise e

    def _download_xdelta_file(self, url: str, target_dir: str, progress_callback, total_size: int, downloaded_ref: list[int], session=None):
        import os
        from urllib.parse import urlparse, unquote
        if session is None:
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename.endswith('.xdelta'):
            import platform
            if platform.system() == 'Darwin':
                filename = 'game.ios.xdelta'
            else:
                filename = 'data.win.xdelta'
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        try:

            def on_response(r):
                self._active_response = r
            download_file(session, url, target_path, progress_callback, total_size, downloaded_ref, cancel_check=lambda: self._cancelled, on_response=on_response)
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass
            raise e

    def run(self):
        try:
            self.temp_root = tempfile.mkdtemp(prefix='deltahub-install-')
            tasks = []
            total_bytes = 0
            mod_folders = {}
            for mod, chapter_id in self.install_tasks:
                if mod.key not in mod_folders:
                    existing_folder = self._find_existing_mod_folder(mod.key)
                    if existing_folder:
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
                            is_xdelta_mod = getattr(mod, 'is_xdelta', False)
                            tasks.append({'mod': mod, 'url': chapter_data.data_file_url, 'chapter_id': chapter_id, 'component': 'data', 'is_xdelta': is_xdelta_mod})
                        for extra_file in chapter_data.extra_files:
                            tasks.append({'mod': mod, 'url': extra_file.url, 'chapter_id': chapter_id, 'component': extra_file.key})
                    else:
                        for component, info in components_to_update.items():
                            if info.get('delete'):
                                tasks.append({'mod': mod, 'chapter_id': chapter_id, 'component': component, 'delete': True})
                                continue
                            is_xdelta = info.get('is_xdelta', False) if component == 'data' else False
                            t = {'mod': mod, 'url': info['url'], 'chapter_id': chapter_id, 'component': component, 'is_xdelta': is_xdelta}
                            if component == 'data' and info.get('type_changed'):
                                t['type_changed'] = True
                            tasks.append(t)
            if not tasks:
                self.finished.emit(True)
                return
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
            retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=10)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            self._session = session
            download_tasks = [t for t in tasks if t.get('url')]
            file_sizes_cache = {}
            for task in download_tasks:
                u = task.get('url')
                try:
                    h = session.head(u, allow_redirects=True, timeout=15)
                    content_length = int(h.headers.get('content-length', 0))
                    file_sizes_cache[u] = content_length
                    total_bytes += content_length
                except Exception:
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
                    except Exception:
                        pass
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
                is_xdelta = task.get('is_xdelta', False)
                try:
                    if is_data_file:
                        if is_xdelta:

                            def progress_callback(progress):
                                self.progress.emit(progress)
                            self._download_xdelta_file(url, cache_dir, progress_callback, total_bytes, downloaded_ref, session)
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
                        self._download_archive_file(url, cache_dir, progress_callback, total_bytes, downloaded_ref, session)
                except Exception:
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
            except Exception:
                pass
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
        except PermissionError:
            try:
                self.status.emit(tr('errors.permission_error_install'), UI_COLORS['status_error'])
            except Exception:
                pass
            self.finished.emit(False)
        except Exception as e:
            self.status.emit(tr('errors.installation_error', error=str(e)), UI_COLORS['status_error'])
            self.finished.emit(False)
        finally:
            try:
                if self.temp_root and os.path.isdir(self.temp_root):
                    shutil.rmtree(self.temp_root, ignore_errors=True)
            except Exception:
                pass
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
                except Exception:
                    pass
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception:
                    pass
        finally:
            try:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            except Exception:
                pass

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

    def _ask_user(self, title: str, message: str) -> bool:
        self.prompt_event.clear()
        self.prompt_required.emit(title, message)
        self.prompt_event.wait()
        return self.prompt_result

    def _download_archive(self, url: str, temp_dir: str) -> str:
        from urllib.parse import urlparse, unquote
        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename:
            filename = 'mod.zip'
        if not any((filename.lower().endswith(ext) for ext in ['.zip', '.rar', '.7z', '.tar.gz', '.lzma'])):
            filename = 'mod.zip'
        archive_path = os.path.join(temp_dir, filename)
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)
        response = self._session.get(url, stream=True, timeout=30)
        self._active_response = response
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        with open(archive_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if self._cancelled:
                    raise RuntimeError('download_cancelled')
                if not chunk:
                    continue
                f.write(chunk)
                downloaded_size += len(chunk)
                if total_size > 0:
                    progress = int(downloaded_size * 100 / total_size)
                    self.progress.emit(progress)
        self.progress.emit(100)
        return archive_path

    def _extract_and_read_config(self, archive_path: str) -> dict | None:
        archive_path_lower = archive_path.lower()
        config_content = None
        try:
            if archive_path_lower.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    if 'config.json' in zf.namelist():
                        config_content = zf.read('config.json')
            elif archive_path_lower.endswith('.rar'):
                with rarfile.RarFile(archive_path, 'r') as rf:
                    if 'config.json' in rf.namelist():
                        config_content = rf.read('config.json')
            elif archive_path_lower.endswith('.7z'):
                with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                    if 'config.json' in zf.getnames():
                        extract_dir = os.path.join(os.path.dirname(archive_path), '7z_config')
                        zf.extract(path=extract_dir, targets=['config.json'])
                        config_file_path = os.path.join(extract_dir, 'config.json')
                        if os.path.exists(config_file_path):
                            with open(config_file_path, 'rb') as f:
                                config_content = f.read()
            elif archive_path_lower.endswith('.tar.gz'):
                import tarfile
                with tarfile.open(archive_path, 'r:gz') as tf:
                    if 'config.json' in tf.getnames():
                        extracted_file = tf.extractfile('config.json')
                        if extracted_file:
                            config_content = extracted_file.read()
            if config_content:
                return json.loads(config_content)
        except Exception:
            return None
        return None

    def _is_metadata_only(self, archive_path: str) -> bool:
        archive_path_lower = archive_path.lower()
        try:
            if archive_path_lower.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    return len(zf.namelist()) == 1 and zf.namelist()[0] == 'config.json'
            elif archive_path_lower.endswith('.rar'):
                with rarfile.RarFile(archive_path, 'r') as rf:
                    return len(rf.namelist()) == 1 and rf.namelist()[0] == 'config.json'
            elif archive_path_lower.endswith('.7z'):
                with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                    return len(zf.getnames()) == 1 and zf.getnames()[0] == 'config.json'
            elif archive_path_lower.endswith('.tar.gz'):
                import tarfile
                with tarfile.open(archive_path, 'r:gz') as tf:
                    return len(tf.getnames()) == 1 and 'config.json' in tf.getnames()
        except Exception:
            return False
        return False

    def _extract_full_archive(self, archive_path: str, target_dir: str):
        archive_path_lower = archive_path.lower()
        if archive_path_lower.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(target_dir)
        elif archive_path_lower.endswith('.rar'):
            with rarfile.RarFile(archive_path, 'r') as rf:
                rf.extractall(target_dir)
        elif archive_path_lower.endswith('.7z'):
            with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                zf.extractall(path=target_dir)
        elif archive_path_lower.endswith('.tar.gz'):
            import tarfile
            with tarfile.open(archive_path, 'r:gz') as tf:
                tf.extractall(target_dir)
        elif archive_path_lower.endswith('.lzma'):
            import lzma
            import shutil
            output_path = os.path.join(target_dir, os.path.splitext(os.path.basename(archive_path))[0])
            with lzma.open(archive_path) as f_in, open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        else:
            raise ValueError(tr('errors.unsupported_archive_format'))


class FetchHelpContentThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            import requests
            response = requests.get(self.url, timeout=10)
            if response.ok:
                content = response.text
                self.finished.emit(content)
            else:
                error_msg = tr('errors.load_error_http', code=response.status_code)
                self.finished.emit(f'<i>{error_msg}</i>')
        except Exception:
            self.finished.emit(f"<i>{tr('dialogs.help_content_load_failed')}</i>")
