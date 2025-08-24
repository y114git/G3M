import os
import time
import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage
from config.constants import CLOUD_FUNCTIONS_BASE_URL, BROWSER_HEADERS, UI_COLORS
from utils.file_utils import download_and_extract_archive
from localization.manager import tr

class PresenceWorker(QObject):
    finished, update_online_count = (pyqtSignal(), pyqtSignal(int))

    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def run(self):
        try:
            url = f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat'
            data = {'sessionId': self.session_id}
            resp = requests.post(url, json=data, timeout=8)
            if resp.status_code == 200:
                try:
                    data = resp.json() or {}
                    online = int(data.get('online', 0))
                    self.update_online_count.emit(max(online, 0))
                except Exception:
                    pass
        except requests.RequestException:
            pass
        finally:
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

    def __init__(self, main_window, target_dir: str, make_shortcut: bool=False):
        super().__init__(main_window)
        self.main_window = main_window
        self.target_dir = target_dir

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
            resp = session.head(full_install_url, allow_redirects=True, timeout=15)
            total_size = int(resp.headers.get('content-length', 0))
            downloaded_ref = [0]
            download_and_extract_archive(full_install_url, self.target_dir, self.progress, total_size, downloaded_ref, session, is_game_installation=True)
            self.status.emit(tr('status.demo_installation_complete'), UI_COLORS['status_success'])
            self.finished.emit(True, self.target_dir)
        except Exception as e:
            self.status.emit(tr('errors.full_installation_error').format(str(e)), UI_COLORS['status_error'])
            self.finished.emit(False, self.target_dir)

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

    def cancel(self):
        self._cancelled = True
        self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])

    def _find_existing_mod_folder(self, mod_key: str) -> str:
        if not os.path.exists(self.main_window.mods_dir):
            return ''
        for folder_name in os.listdir(self.main_window.mods_dir):
            config_path = os.path.join(self.main_window.mods_dir, folder_name, 'config.json')
            if os.path.exists(config_path):
                try:
                    config_data = self.main_window._read_json(config_path)
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
        config_path = os.path.join(self.main_window.mods_dir, existing_folder, 'config.json')
        if not os.path.exists(config_path):
            return {}
        try:
            config_data = self.main_window._read_json(config_path)
            local_versions = config_data.get('chapters', {}).get(str(chapter_id), {}).get('versions', {}) or {}
            remote_versions = self._collect_remote_versions_for_chapter(mod, chapter_id)
            components_to_update: dict[str, dict] = {}
            chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
            if chapter_data and chapter_data.data_file_url and remote_versions.get('data'):
                is_piracy_protected = getattr(mod, 'is_piracy_protected', False)
                is_xdelta_mod = getattr(mod, 'is_xdelta', is_piracy_protected)
                local_is_xdelta = False
                try:
                    mod_path = os.path.join(self.main_window.mods_dir, existing_folder)
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
            for mod_key in installed_mods:
                if not mod_key.startswith('local_') and self._can_increment_download_by_config(mod_key):
                    if self._increment_mod_downloads_on_server(mod_key):
                        self._update_install_date_in_config(mod_key)
        except Exception:
            pass

    def _get_user_ip(self):
        try:
            response = requests.get('https://api.ipify.org', timeout=5)
            return response.text.strip()
        except Exception:
            return '127.0.0.1'

    def _get_global_rate_limit_data(self):
        try:
            from utils.path_utils import get_app_support_path
            config_path = os.path.join(get_app_support_path(), 'rate_limit_data.json')
            if os.path.exists(config_path):
                return self.main_window._read_json(config_path)
            return {}
        except Exception:
            return {}

    def _update_global_rate_limit_data(self, mod_key):
        try:
            current_ip = self._get_user_ip()
            from utils.path_utils import get_app_support_path
            config_path = os.path.join(get_app_support_path(), 'rate_limit_data.json')
            rate_limit_data = self._get_global_rate_limit_data()
            ip_mod_key = f'{current_ip}:{mod_key}'
            now_str = time.strftime('%Y-%m-%d %H:%M:%S')
            rate_limit_data[ip_mod_key] = now_str
            self.main_window._write_json(config_path, rate_limit_data)
        except Exception:
            pass

    def _can_increment_download_by_config(self, mod_key):
        try:
            import datetime
            current_ip = self._get_user_ip()
            rate_limit_data = self._get_global_rate_limit_data()
            ip_mod_key = f'{current_ip}:{mod_key}'
            last_increment_time = rate_limit_data.get(ip_mod_key, '')
            if not last_increment_time:
                return True
            last_increment_dt = datetime.datetime.strptime(last_increment_time, '%Y-%m-%d %H:%M:%S')
            time_diff = datetime.datetime.now() - last_increment_dt
            return time_diff.total_seconds() >= 43200
        except Exception:
            return False

    def _update_install_date_in_config(self, mod_key):
        try:
            for folder_name in os.listdir(self.main_window.mods_dir):
                config_path = os.path.join(self.main_window.mods_dir, folder_name, 'config.json')
                if os.path.isfile(config_path):
                    try:
                        config_data = self.main_window._read_json(config_path)
                        if config_data.get('mod_key') == mod_key:
                            now_str = time.strftime('%Y-%m-%d %H:%M:%S')
                            config_data['installed_date'] = now_str
                            config_data['last_download_increment'] = now_str
                            self.main_window._write_json(config_path, config_data)
                            self._update_global_rate_limit_data(mod_key)
                            return
                    except Exception:
                        continue
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

    def _download_archive_file(self, url: str, target_dir: str, progress_signal, total_size: int, downloaded_ref: list[int], session=None):
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
            from utils.file_utils import _download_file
            _download_file(session, url, target_path, progress_signal, total_size, downloaded_ref)
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass
            raise e

    def _download_xdelta_file(self, url: str, target_dir: str, progress_signal, total_size: int, downloaded_ref: list[int], session=None):
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
            from utils.file_utils import _download_file
            _download_file(session, url, target_path, progress_signal, total_size, downloaded_ref)
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass
            raise e

    def run(self):
        import os
        import shutil
        import tempfile
        import time
        try:
            self.temp_root = tempfile.mkdtemp(prefix='deltahub-install-')
            tasks = []
            total_bytes = 0
            mod_folders = {}
            from utils.file_utils import get_unique_mod_dir
            for mod, chapter_id in self.install_tasks:
                if mod.key not in mod_folders:
                    existing_folder = self._find_existing_mod_folder(mod.key)
                    if existing_folder:
                        mod_folders[mod.key] = existing_folder
                    else:
                        mod_folders[mod.key] = get_unique_mod_dir(self.main_window.mods_dir, mod.name)
                existing_folder = mod_folders.get(mod.key, '')
                chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
                if chapter_id == -1 and mod.is_valid_for_demo():
                    tasks.append({'mod': mod, 'url': mod.demo_url, 'chapter_id': -1, 'component': 'demo'})
                elif chapter_data:
                    components_to_update = self._should_update_component(mod, chapter_id, existing_folder)
                    if not components_to_update:
                        if chapter_data.data_file_url:
                            is_piracy_protected = getattr(mod, 'is_piracy_protected', False)
                            is_xdelta_mod = getattr(mod, 'is_xdelta', is_piracy_protected)
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
                                if fl.endswith(('.zip', '.rar', '.7z')):
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
                            self._download_xdelta_file(url, cache_dir, self.progress, total_bytes, downloaded_ref, session)
                        else:
                            from utils.file_utils import download_and_extract_archive
                            download_and_extract_archive(url, cache_dir, self.progress, total_bytes, downloaded_ref, session)
                    else:
                        self._download_archive_file(url, cache_dir, self.progress, total_bytes, downloaded_ref, session)
                except Exception:
                    raise
                if mod.key not in installed_mods:
                    installed_mods[mod.key] = {'mod': mod, 'chapters': set()}
                installed_mods[mod.key]['chapters'].add(chapter_id)
                if url and total_bytes == 0:
                    done_files += 1
                    progress = int(done_files / max(1, len(download_tasks)) * 100)
                    self.progress.emit(progress)
            for mod_key, mod_data in installed_mods.items():
                mod = mod_data['mod']
                mod_folder_name = mod_folders[mod.key]
                mod_dir = os.path.join(self.main_window.mods_dir, mod_folder_name)
                files_data = {}
                for chapter_id in mod_data['chapters']:
                    chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
                    versions_dict = {}
                    file_info = {}
                    if chapter_data:
                        if chapter_data.data_file_version:
                            versions_dict['data'] = chapter_data.data_file_version
                        if chapter_data.data_file_url:
                            file_info['data_file_url'] = chapter_data.data_file_url
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
                        if mod.demo_version:
                            versions_dict['demo'] = mod.demo_version
                            file_info['versions'] = versions_dict
                    if file_info:
                        if chapter_id == -1:
                            file_key = 'demo'
                        elif chapter_id == 0:
                            file_key = '0'
                        else:
                            file_key = str(chapter_id)
                        files_data[file_key] = file_info
                config_data = {'is_local_mod': False, 'mod_key': mod.key, 'name': mod.name, 'author': mod.author, 'version': mod.version, 'game_version': mod.game_version, 'modtype': mod.modtype, 'installed_date': time.strftime('%Y-%m-%d %H:%M:%S'), 'is_available_on_server': True, 'files': files_data}
                config_path = os.path.join(mod_dir, 'config.json')
                self.main_window._write_json(config_path, config_data)
            self._increment_downloads_for_installed_mods(installed_mods.keys())
            try:
                os.makedirs(self.main_window.mods_dir, exist_ok=True)
                for entry in os.listdir(self.temp_root or ''):
                    src = os.path.join(self.temp_root, entry)
                    dst = os.path.join(self.main_window.mods_dir, entry)
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
            self.status.emit(tr('status.installation_complete'), UI_COLORS['status_success'])
            self.finished.emit(True)
        except PermissionError as e:
            path = e.filename if e.filename else self.main_window.mods_dir
            self.status.emit(tr('errors.permission_error_install'), UI_COLORS['status_error'])
            from PyQt6.QtWidgets import QMessageBox
            error_message = tr('dialogs.permission_error_message').format(path)
            QMessageBox.critical(self.main_window, tr('dialogs.access_error'), error_message)
            self.finished.emit(False)
        except Exception as e:
            self.status.emit(tr('errors.installation_error').format(str(e)), UI_COLORS['status_error'])
            self.finished.emit(False)
        finally:
            if not self._cancelled:
                try:
                    if self.temp_root and os.path.isdir(self.temp_root):
                        shutil.rmtree(self.temp_root, ignore_errors=True)
                except Exception:
                    pass

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
        except Exception as e:
            print(f'Error loading help content: {e}')
            self.finished.emit(f"<i>{tr('dialogs.help_content_load_failed')}</i>")