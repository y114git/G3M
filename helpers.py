import os, platform, re, shutil, stat, sys, tempfile, time, zipfile, psutil, requests
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QThread, QObject, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QMessageBox
from localization import tr

LAUNCHER_VERSION = "1.9.9"

APP_ID = "deltahub.y.114"
from dotenv import load_dotenv

def _load_config_sources():
    # 1) Load from standard .env (dev)
    load_dotenv()
    # 2) Load from config.env next to executable (for packaged app)
    try:
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath('.')
        cfg_path = os.path.join(exe_dir, 'config.env')
        if os.path.exists(cfg_path):
            load_dotenv(cfg_path)
    except Exception:
        pass
    # 3) Load from embedded secrets module (generated at build time)
    try:
        import importlib
        _se = importlib.import_module('secrets_embed')
        # Only set if not already present in environment
        for k in ("DATA_FIREBASE_URL", "FIREBASE_API_KEY", "FIREBASE_AUTH_EMAIL", "FIREBASE_AUTH_PASS", "INTERNAL_SALT"):
            if not os.getenv(k, "") and hasattr(_se, k):
                os.environ[k] = getattr(_se, k)
    except Exception:
        pass

_load_config_sources()
# Single database URL for data (mods, globals, stats)
DATA_FIREBASE_URL = os.getenv("DATA_FIREBASE_URL", "")
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "")
FIREBASE_AUTH_EMAIL = os.getenv("FIREBASE_AUTH_EMAIL", "")
FIREBASE_AUTH_PASS = os.getenv("FIREBASE_AUTH_PASS", "")

_FB_ID_TOKEN = None
_FB_TOKEN_EXPIRES_AT = 0.0

def get_firebase_id_token() -> str:
    import time
    global _FB_ID_TOKEN, _FB_TOKEN_EXPIRES_AT
    if not (FIREBASE_API_KEY and FIREBASE_AUTH_EMAIL and FIREBASE_AUTH_PASS):
        return ""
    if _FB_ID_TOKEN and time.time() < _FB_TOKEN_EXPIRES_AT - 30:
        return _FB_ID_TOKEN
    try:
        resp = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}",
            json={"email": FIREBASE_AUTH_EMAIL, "password": FIREBASE_AUTH_PASS, "returnSecureToken": True},
            timeout=10,
        )
        data = resp.json() if resp.ok else {}
        token = data.get("idToken", "")
        expires_in = int(data.get("expiresIn", 0)) if token else 0
        if token and expires_in:
            _FB_ID_TOKEN = token
            _FB_TOKEN_EXPIRES_AT = time.time() + expires_in
            return token
    except Exception:
        pass
    return ""

def _fb_url(base: str, path: str, with_auth: bool = True) -> str:
    base = base.rstrip('/')
    url = f"{base}/{path}.json"
    if with_auth:
        t = get_firebase_id_token()
        if t:
            return f"{url}?auth={t}"
    return url
STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO = "1671210", "1690940"
GAME_PROCESS_NAMES = ["DELTARUNE.exe", "DELTARUNE", "runner"]
SAVE_SLOT_FINISH_MAP = {0: 3, 1: 4, 2: 5}
ARCH = platform.machine()
DEFAULT_FONT_FALLBACK_CHAIN = ["Determination Sans Rus", "DejaVu Sans", "Noto Sans", "Liberation Sans", "Arial", "Noto Color Emoji", "Segoe UI Emoji", "Apple Color Emoji"]
SOCIAL_LINKS = {"telegram": "https://t.me/y_maintg", "discord": "https://discord.gg/gg4EvZpWKd"}
UI_COLORS = {"status_error": "red", "status_warning": "orange", "status_success": "green", "status_info": "gray", "status_ready": "lightgreen", "status_steam": "blue", "link": "#00BFFF", "social_discord": "#8A2BE2", "saves_button": "yellow"}
THEMES = {"default": {"name": "Deltarune", "background": "assets/bg_fountain.gif", "font_family": "Determination Sans Rus", "font_size_main": 16, "font_size_small": 12, "colors": {"main_fg": "#000000", "top_level_fg": "#000000", "button": "#000000", "button_hover": "#222222", "button_text": "#FFFFFF", "border": "#FFFFFF", "text": "#FFFFFF"}}}
BROWSER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def resource_path(relative_path: str) -> str:
    return os.path.join(getattr(sys, '_MEIPASS', os.path.abspath(".")), relative_path)

def format_timestamp() -> str:
    return time.strftime('%d.%m.%y %H:%M')

class GameMode:
    _path_key: str; _custom_exec_key: str; steam_id: str; tab_names: list[str]; path_change_button_text: str; direct_launch_allowed: bool
    def get_game_path(self, config: dict) -> str: return config.get(self._path_key, '')
    def set_game_path(self, config: dict, path: str): config[self._path_key] = path
    def get_custom_exec_config_key(self) -> str: return self._custom_exec_key
    def get_chapter_id(self, ui_index: int) -> int: raise NotImplementedError
    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]: raise NotImplementedError

class FullGameMode(GameMode):
    def __init__(self):
        self._path_key, self._custom_exec_key, self.steam_id, self.tab_names, self.path_change_button_text, self.direct_launch_allowed = 'game_path', 'custom_executable_path', STEAM_APP_ID_FULL, [tr("tabs.main_menu"), tr("tabs.chapter_1"), tr("tabs.chapter_2"), tr("tabs.chapter_3"), tr("tabs.chapter_4")], tr("buttons.change_path"), True
    def get_chapter_id(self, ui_index: int) -> int: return ui_index
    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]: return {i: [mod for mod in all_mods if not mod.is_demo_mod and not mod.hide_mod and not mod.ban_status and mod.get_chapter_data(i)] for i in range(5)}

class DemoGameMode(GameMode):
    def __init__(self):
        self._path_key, self._custom_exec_key, self.steam_id, self.tab_names, self.path_change_button_text, self.direct_launch_allowed = 'demo_game_path', 'demo_custom_executable_path', STEAM_APP_ID_DEMO, [tr("tabs.demo")], tr("buttons.change_demo_path"), False
    def get_chapter_id(self, ui_index: int) -> int: return -1
    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]: return {0: [mod for mod in all_mods if mod.is_valid_for_demo() and not mod.hide_mod and not mod.ban_status]}

@dataclass
class ModExtraFile:
    key: str
    version: str
    url: str

@dataclass
class ModChapterData:
    description: Optional[str] = None
    data_file_url: Optional[str] = None
    data_win_version: Optional[str] = None
    extra_files: List[ModExtraFile] = field(default_factory=list)

    def is_valid(self) -> bool:
        return bool(self.data_file_url or self.extra_files)

@dataclass
class ModInfo:
    key: str
    name: str
    version: str
    author: str
    tagline: str
    game_version: str
    description_url: str
    downloads: int
    is_demo_mod: bool
    is_verified: bool
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    hide_mod: bool = False
    is_piracy_protected: bool = False
    ban_status: bool = False
    chapters: Dict[int, ModChapterData] = field(default_factory=dict)
    demo_url: Optional[str] = None
    demo_version: Optional[str] = None
    created_date: Optional[str] = None
    last_updated: Optional[str] = None
    screenshots_url: List[str] = field(default_factory=list)

    def get_chapter_data(self, chapter_id: int) -> Optional[ModChapterData]:
        return self.chapters.get(chapter_id)

    def is_valid_for_demo(self) -> bool:
        if not self.is_demo_mod:
            return False
        if self.key.startswith('local_'):
            return bool(self.chapters and self.chapters.get(-1))
        return bool(self.demo_url and self.demo_version)

def download_and_extract_archive(url: str, target_dir: str, progress_signal, total_size: int, downloaded_ref: list[int], session=None, is_game_installation=False):
    import rarfile
    from urllib.parse import urlparse, unquote
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    os.makedirs(target_dir, exist_ok=True)
    if session is None:
        session = requests.Session(); session.headers.update(BROWSER_HEADERS)
        retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=10)
        session.mount("http://", adapter); session.mount("https://", adapter)
    fname = _get_filename_from_url(session, url)
    with tempfile.TemporaryDirectory(prefix="deltahub-dl-") as tmp:
        tmp_path = os.path.join(tmp, fname); _download_file(session, url, tmp_path, progress_signal, total_size, downloaded_ref); _extract_archive(tmp_path, target_dir, fname, is_game_installation)

def _get_filename_from_url(session, url):
    try:
        from urllib.parse import urlparse, unquote
        response = session.head(url, timeout=10, allow_redirects=True)
        if content_disp := response.headers.get('Content-Disposition'):
            if fn_match := re.search(r'filename\*?=(.+)', content_disp, re.IGNORECASE):
                fn_data = fn_match.group(1).strip()
                return unquote(fn_data[7:], 'utf-8') if fn_data.lower().startswith("utf-8''") else fn_data.strip('"\'')
        if (path := urlparse(response.url).path) and path != "/" and not path.endswith("/") and "." in (potential_name := os.path.basename(unquote(path))): return potential_name
    except: pass
    return Path(url.split("?", 1)[0]).name or "file.tmp"

def _download_file(session, url, tmp_path, progress_signal, total_size, downloaded_ref):
    with session.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=262144):
                if chunk: f.write(chunk); downloaded_ref[0] += len(chunk)
                if total_size > 0: progress_signal.emit(int(downloaded_ref[0] / total_size * 100))

def _extract_archive(tmp_path, target_dir, fname, is_game_installation=False):
    import rarfile
    low = fname.lower(); extractors = {"zip": lambda: zipfile.ZipFile(tmp_path, "r").extractall(target_dir), "rar": lambda: rarfile.RarFile(tmp_path, "r").extractall(target_dir)}
    for ext, extractor in extractors.items():
        if low.endswith(f".{ext}"): extractor(); _cleanup_extracted_archive(target_dir, is_game_installation); return
    shutil.copy2(tmp_path, os.path.join(target_dir, fname))

def _cleanup_extracted_archive(target_dir: str, is_game_installation: bool = False):
    if is_game_installation:
        cleanup_dir_pattern = re.compile(r'^chapter\d+_(windows|mac)$', re.I)
        for root, dirs, files in os.walk(target_dir, topdown=False):
            for dir_name in dirs[:]:
                if cleanup_dir_pattern.match(dir_name):
                    try: shutil.rmtree(os.path.join(root, dir_name)); dirs.remove(dir_name)
                    except OSError: pass
    else:
        cleanup_files, cleanup_dir_pattern = ('data.win', 'game.ios'), re.compile(r'^chapter\d+_(windows|mac)$', re.I)
        for root, dirs, files in os.walk(target_dir, topdown=False):
            for file in files:
                if file.lower() in cleanup_files:
                    try: os.remove(os.path.join(root, file))
                    except OSError: pass
            for dir_name in dirs[:]:
                if cleanup_dir_pattern.match(dir_name):
                    try: shutil.rmtree(os.path.join(root, dir_name)); dirs.remove(dir_name)
                    except OSError: pass

class GameMonitorThread(QThread):
    finished = pyqtSignal(bool)
    def __init__(self, process, vanilla_mode, parent=None): super().__init__(parent); self.process, self.vanilla_mode = process, vanilla_mode
    def run(self):
        increment_launch_counter()
        if self.process:
            try: self.process.wait()
            except Exception: pass
            finally: self.finished.emit(self.vanilla_mode); return
        game_appeared = False
        for _ in range(30):
            if is_game_running(): game_appeared = True; break
            time.sleep(1)
        if not game_appeared: self.finished.emit(self.vanilla_mode); return
        while is_game_running(): time.sleep(0.5)
        self.finished.emit(self.vanilla_mode)

class PresenceWorker(QObject):
    finished, update_online_count = pyqtSignal(), pyqtSignal(int)
    def __init__(self, session_id): super().__init__(); self.session_id = session_id
    def run(self):
        now = int(time.time())
        try:
            # Update own heartbeat under stats/sessions/<id>
            requests.put(_fb_url(DATA_FIREBASE_URL, f"stats/sessions/{self.session_id}"), json=now, timeout=5)
            # Compute online by counting active sessions in last 70s
            try:
                resp = requests.get(_fb_url(DATA_FIREBASE_URL, "stats/sessions"), timeout=5)
                online = 0
                if resp.status_code == 200 and isinstance(resp.json(), dict):
                    now_ts = int(time.time())
                    for _, ts in (resp.json() or {}).items():
                        try:
                            if isinstance(ts, int) and (now_ts - ts) <= 70:
                                online += 1
                        except Exception:
                            pass
                self.update_online_count.emit(max(online, 0))
            except requests.RequestException:
                pass

        except requests.RequestException: pass
        finally: self.finished.emit()

class FetchTranslationsThread(QThread):
    result, status = pyqtSignal(bool), pyqtSignal(str, str)
    def __init__(self, main_window, force_update=False): super().__init__(main_window); self.main_window, self.force_update = main_window, force_update
    def run(self):
        try:
            response = requests.get(_fb_url(DATA_FIREBASE_URL, "mods"), timeout=15); response.raise_for_status()
            all_mods = []



            for key, data in (response.json() or {}).items():
                if not isinstance(data, dict): continue
                files_data = {}
                chapters_data = data.get("chapters", {})

                if isinstance(chapters_data, list):
                    chapters_items = [(str(i), chapter_data) for i, chapter_data in enumerate(chapters_data) if chapter_data is not None]
                elif isinstance(chapters_data, dict):
                    chapters_items = list(chapters_data.items())
                else:
                    chapters_items = []



                for chapter_key, chapter_data in chapters_items:
                        if not isinstance(chapter_data, dict): continue



                        try: chapter_id = int(chapter_key[1:]) if chapter_key.startswith("c") else int(chapter_key)
                        except (ValueError, TypeError):
                            continue

                        if chapter_id == -1: chapter_key = 'demo'
                        elif chapter_id == 0: chapter_key = 'menu'
                        elif 1 <= chapter_id <= 4: chapter_key = f'chapter_{chapter_id}'
                        else:
                            continue

                        files_entry = {}
                        if chapter_data.get('data_file_url'): files_entry.update({'data_win_url': chapter_data['data_file_url'], 'data_win_version': chapter_data.get('data_win_version', '1.0.0')})
                        if extra_files := chapter_data.get('extra_files', []): files_entry['extra'] = {ef.get('key', 'unknown'): {'url': ef.get('url', ''), 'version': ef.get('version', '1.0.0')} for ef in extra_files if isinstance(ef, dict)}

                        if files_entry:
                            files_data[chapter_key] = files_entry
                composite_version = self._aggregate_versions(files_data); base_version = data.get("version")
                screens_list = data.get("screenshots_url", [])
                if isinstance(screens_list, str):
                    # support comma-separated fallback
                    screens_list = [s.strip() for s in screens_list.split(",") if s.strip()]
                elif not isinstance(screens_list, list):
                    screens_list = []
                mod = ModInfo(key=key, name=data.get("name", tr("status.unknown_mod")), author=data.get("author", tr("status.unknown_author_status")), version=f"{base_version}|{composite_version}" if base_version else composite_version, tagline=data.get("tagline", tr("status.no_description_status")), game_version=data.get("game_version", tr("status.no_version")), description_url=data.get("description_url", ""), downloads=data.get("downloads", 0), is_demo_mod=data.get("is_demo_mod", False), is_verified=data.get("is_verified", False), icon_url=data.get("icon_url"), tags=data.get("tags", []), hide_mod=data.get("hide_mod", False), is_piracy_protected=data.get("is_piracy_protected", False), ban_status=data.get("ban_status", False), demo_url=files_data.get("demo", {}).get("url") if files_data else None, demo_version=files_data.get("demo", {}).get("version", "1.0.0") if files_data else "1.0.0", created_date=data.get("created_date"), last_updated=data.get("last_updated"), screenshots_url=screens_list)

                if self._process_mod_chapters(mod, files_data):
                    all_mods.append(mod)
            local_mods = []
            if hasattr(self.main_window, 'mods_dir') and os.path.exists(self.main_window.mods_dir):
                existing_local_keys = set()
                for folder_name in os.listdir(self.main_window.mods_dir):
                    folder_path = os.path.join(self.main_window.mods_dir, folder_name)
                    if os.path.isdir(folder_path):
                        config_path = os.path.join(folder_path, "config.json")
                        if os.path.exists(config_path):
                            try:
                                config_data = self.main_window._read_json(config_path)
                                if config_data and config_data.get('is_local_mod') and config_data.get('mod_key'):
                                    existing_local_keys.add(config_data['mod_key'])
                            except:
                                continue

                for mod in self.main_window.all_mods:
                    if hasattr(mod, 'key') and mod.key.startswith('local_') and mod.key in existing_local_keys:
                        local_mods.append(mod)

            self.main_window.all_mods = all_mods + local_mods

            self._update_remote_exists_flags(all_mods); self.result.emit(True)
        except Exception as e: self.status.emit(tr("errors.update_list_failed").format(str(e)), UI_COLORS["status_error"]); self.result.emit(False)
    def _aggregate_versions(self, node):
        collected = set()
        def _walk(n):
            if isinstance(n, dict):
                if v := n.get("version"): collected.add(v)
                for child in n.values(): _walk(child)
            elif isinstance(n, (list, tuple)):
                for item in n: _walk(item)
        _walk(node); return "|".join(sorted(collected, key=version_sort_key, reverse=True)) if collected else "1.0.0"
    def _process_mod_chapters(self, mod, files_data):
        for chapter_name, chapter_id in {"menu": 0, "chapter_1": 1, "chapter_2": 2, "chapter_3": 3, "chapter_4": 4}.items():
            if not (chapter_data := files_data.get(chapter_name)):
                continue

            has_dw_version = not chapter_data.get("data_win_url") or bool(chapter_data.get("data_win_version"))
            extra_files_data = chapter_data.get("extra", {}).items()

            if not has_dw_version or (extra_files_data and not all(v.get("version") for _, v in extra_files_data)):
                return False

            mod_chapter_data = ModChapterData(data_file_url=chapter_data.get("data_win_url"), data_win_version=chapter_data.get("data_win_version", "1.0.0"), extra_files=[ModExtraFile(key=k, **v) for k, v in extra_files_data])
            if description_url := chapter_data.get("description_url"):
                try: desc_resp = requests.get(description_url, timeout=10); desc_resp.raise_for_status(); mod_chapter_data.description = desc_resp.text
                except requests.RequestException: mod_chapter_data.description = tr("errors.description_load_failed")

            if mod_chapter_data.is_valid():
                mod.chapters[chapter_id] = mod_chapter_data
        return True
    def _update_remote_exists_flags(self, all_mods):
        remote_mod_keys = {mod.key for mod in all_mods}

        if hasattr(self.main_window, 'mods_dir') and os.path.exists(self.main_window.mods_dir):
            for folder_name in os.listdir(self.main_window.mods_dir):
                folder_path = os.path.join(self.main_window.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue

                config_path = os.path.join(folder_path, "config.json")
                if os.path.exists(config_path):
                    try:
                        config_data = self.main_window._read_json(config_path)
                        if config_data:
                            mod_key = config_data.get('mod_key')
                            is_local_mod = config_data.get('is_local_mod', False)

                            if mod_key and not is_local_mod:
                                is_available = mod_key in remote_mod_keys
                                if config_data.get('is_available_on_server') != is_available:
                                    config_data['is_available_on_server'] = is_available
                                    self.main_window._write_json(config_path, config_data)
                    except:
                        continue

class InstallTranslationsThread(QThread):
    progress, status, finished = pyqtSignal(int), pyqtSignal(str, str), pyqtSignal(bool)
    def __init__(self, main_window, install_tasks): super().__init__(main_window); self.main_window, self.install_tasks, self._cancelled, self._installed_dirs = main_window, install_tasks, False, []
    def cancel(self):
        self._cancelled = True; import shutil
        for dir_path in self._installed_dirs:
            try:
                if os.path.exists(dir_path): shutil.rmtree(dir_path)
            except: pass
        self.status.emit(tr("status.operation_cancelled"), UI_COLORS["status_error"]); self.finished.emit(False)

    def _find_existing_mod_folder(self, mod_key: str) -> str:
        if not os.path.exists(self.main_window.mods_dir):
            return ""

        for folder_name in os.listdir(self.main_window.mods_dir):
            config_path = os.path.join(self.main_window.mods_dir, folder_name, "config.json")
            if os.path.exists(config_path):
                try:
                    config_data = self.main_window._read_json(config_path)
                    if config_data.get("mod_key") == mod_key:
                        return folder_name
                except:
                    continue
        return ""

    def _parse_composite_version(self, composite_version: str) -> dict:
        if not composite_version:
            return {}

        result = {}
        parts = composite_version.split('|')

        for part in parts:
            if ':' in part:
                key, version = part.split(':', 1)
                result[key] = version

        return result

    def _should_update_component(self, mod: ModInfo, chapter_id: int, existing_folder: str) -> dict:
        if not existing_folder:
            return {}

        config_path = os.path.join(self.main_window.mods_dir, existing_folder, "config.json")
        if not os.path.exists(config_path):
            return {}

        try:
            config_data = self.main_window._read_json(config_path)
            local_chapters = config_data.get("chapters", {})
            local_chapter_data = local_chapters.get(str(chapter_id), {})
            local_composite = local_chapter_data.get("composite_version", "")

            local_versions = self._parse_composite_version(local_composite)
            remote_composite = self.main_window._get_composite_version_for_chapter(mod, chapter_id)
            remote_versions = self._parse_composite_version(remote_composite)

            components_to_update = {}
            chapter_data = mod.get_chapter_data(chapter_id)

            if chapter_data:
                is_xdelta_mod = getattr(mod, 'is_piracy_protected', False)

                remote_data_version = remote_versions.get('data')
                local_data_version = local_versions.get('data')

                local_is_xdelta = any(f.endswith('.xdelta') for f in os.listdir(os.path.join(self.main_window.mods_dir, existing_folder)) if os.path.isfile(os.path.join(self.main_window.mods_dir, existing_folder, f)))

                if is_xdelta_mod != local_is_xdelta:
                    mod_folder_path = os.path.join(self.main_window.mods_dir, existing_folder)
                    self._remove_data_files_from_mod_folder(mod_folder_path)

                if remote_data_version and remote_data_version != local_data_version:
                    components_to_update['data'] = {
                        'url': chapter_data.data_file_url,
                        'local_version': local_data_version,
                        'remote_version': remote_data_version,
                        'is_xdelta': is_xdelta_mod
                    }

                for extra_file in chapter_data.extra_files:
                    remote_version = remote_versions.get(extra_file.key)
                    local_version = local_versions.get(extra_file.key)
                    if remote_version and remote_version != local_version:
                        components_to_update[extra_file.key] = {
                            'url': extra_file.url,
                            'local_version': local_version,
                            'remote_version': remote_version
                        }

            return components_to_update

        except Exception:
            return {}

    def _remove_data_files_from_mod_folder(self, mod_folder_path: str):
        try:
            for root, dirs, files in os.walk(mod_folder_path):
                for file in files:
                    file_lower = file.lower()
                    if (file_lower.endswith('.win') and 'data' in file_lower) or \
                       (file_lower.endswith('.ios') and 'game' in file_lower) or \
                       file_lower in ('data.win', 'data.ios', 'game.ios') or \
                       file_lower.endswith('.xdelta'):
                        file_path = os.path.join(root, file)
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            print(f"Cannot delete file {file_path}: {e}")
        except Exception as e:
            print(f"Error removing data files from {mod_folder_path}: {e}")

    def run(self):
        import os, shutil
        try:
            tasks = []
            total_bytes = 0
            mod_folders = {}
            for mod, chapter_id in self.install_tasks:
                if mod.key not in mod_folders:
                    existing_folder = self._find_existing_mod_folder(mod.key)
                    if existing_folder:
                        mod_folders[mod.key] = existing_folder
                    else:
                        mod_folders[mod.key] = get_unique_mod_dir(self.main_window.mods_dir, mod.name)

                existing_folder = mod_folders.get(mod.key, "")
                chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None

                if chapter_id == -1 and mod.is_valid_for_demo():
                    tasks.append({'mod': mod, 'url': mod.demo_url, 'chapter_id': -1, 'component': 'demo'})
                elif chapter_data:
                    components_to_update = self._should_update_component(mod, chapter_id, existing_folder)

                    if not components_to_update:
                        if chapter_data.data_file_url:
                            is_xdelta_mod = getattr(mod, 'is_piracy_protected', False)
                            tasks.append({'mod': mod, 'url': chapter_data.data_file_url, 'chapter_id': chapter_id, 'component': 'data', 'is_xdelta': is_xdelta_mod})
                        for extra_file in chapter_data.extra_files:
                            tasks.append({'mod': mod, 'url': extra_file.url, 'chapter_id': chapter_id, 'component': extra_file.key, 'is_xdelta': False})
                    else:
                        for component, info in components_to_update.items():
                            is_xdelta = info.get('is_xdelta', False) if component == 'data' else False
                            tasks.append({'mod': mod, 'url': info['url'], 'chapter_id': chapter_id, 'component': component, 'is_xdelta': is_xdelta})

            if not tasks:
                self.finished.emit(True)
                return


            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
            retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=10)
            session.mount("http://", adapter)
            session.mount("https://", adapter)


            file_sizes_cache = {}
            for task in tasks:
                u = task['url']
                try:
                    h = session.head(u, allow_redirects=True, timeout=15)
                    content_length = int(h.headers.get("content-length", 0))
                    file_sizes_cache[u] = content_length
                    total_bytes += content_length
                except Exception:
                    file_sizes_cache[u] = 0
                    total_bytes = 0
                    break

            if not tasks:
                self.finished.emit(True)
                return

            if self._cancelled:
                return

            self.status.emit(tr("status.preparing_download"), UI_COLORS["status_warning"])

            if self._cancelled:
                return

            downloaded_ref = [0]
            done_files = 0
            installed_mods = {}

            for task in tasks:
                if self._cancelled:
                    return

                mod, url, chapter_id = task['mod'], task['url'], task['chapter_id']
                file_size_mb = tr("status.unknown_size")
                file_size_bytes = file_sizes_cache.get(url, 0)
                if file_size_bytes > 0:
                    size_mb = file_size_bytes / (1024 * 1024)
                    file_size_mb = tr("status.unknown_size") if size_mb < 0.05 else f"{size_mb:.1f} MB"

                self.status.emit(tr("status.downloading").format(mod.name, file_size_mb), UI_COLORS["status_warning"])
                mod_folder_name = mod_folders[mod.key]
                mod_dir = os.path.join(self.main_window.mods_dir, mod_folder_name)
                if chapter_id == -1:
                    cache_dir = os.path.join(mod_dir, "demo")
                else:
                    cache_dir = os.path.join(mod_dir, f"chapter_{chapter_id}")

                self._installed_dirs.append(cache_dir)
                chapter_data = mod.get_chapter_data(chapter_id)
                is_data_file = chapter_data and chapter_data.data_file_url == url
                is_xdelta = task.get('is_xdelta', False)

                if is_data_file:
                    if is_xdelta:
                        self._download_xdelta_file(
                            url, cache_dir, self.progress, total_bytes, downloaded_ref, session)
                    else:
                        download_and_extract_archive(
                            url, cache_dir, self.progress, total_bytes, downloaded_ref, session)
                else:
                    self._download_archive_file(
                        url, cache_dir, self.progress, total_bytes, downloaded_ref, session)


                if mod.key not in installed_mods:
                    installed_mods[mod.key] = {'mod': mod, 'chapters': set()}
                installed_mods[mod.key]['chapters'].add(chapter_id)

                if total_bytes == 0:
                    done_files += 1
                    self.progress.emit(int(done_files / len(tasks) * 100))


            for mod_key, mod_data in installed_mods.items():
                mod = mod_data['mod']
                mod_folder_name = mod_folders[mod.key]
                mod_dir = os.path.join(self.main_window.mods_dir, mod_folder_name)

                chapters_data = {}
                for chapter_id in mod_data['chapters']:
                    chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None
                    if chapter_data:
                        composite_version = self.main_window._get_composite_version_for_chapter(mod, chapter_id)
                        if composite_version:
                            chapters_data[str(chapter_id)] = {"composite_version": composite_version}
                    elif chapter_id == -1 and mod.is_valid_for_demo():
                        chapters_data[str(chapter_id)] = {"composite_version": mod.demo_version}

                config_data = {
                    "is_local_mod": False,
                    "mod_key": mod.key,
                    "name": mod.name,
                    "author": mod.author,
                    "version": mod.version,
                    "game_version": mod.game_version,
                    "is_demo_mod": mod.is_demo_mod,
                    "installed_date": time.strftime('%Y-%m-%d %H:%M:%S'),
                    "is_available_on_server": True,
                    "chapters": chapters_data
                }

                config_path = os.path.join(mod_dir, "config.json")
                self.main_window._write_json(config_path, config_data)


            self._increment_downloads_for_installed_mods(installed_mods)

            self.status.emit(tr("status.installation_complete"), UI_COLORS["status_success"])
            self.finished.emit(True)

        except PermissionError as e:
            path = e.filename if e.filename else self.main_window.mods_dir
            self.status.emit(tr("errors.permission_error_install"), UI_COLORS["status_error"])
            QMessageBox.critical(self.main_window, tr("dialogs.access_error"),
                                 tr("dialogs.permission_error_message").format(path))
            self.finished.emit(False)

        except Exception as e:
            self.status.emit(tr("errors.installation_error").format(str(e)), UI_COLORS["status_error"])
            self.finished.emit(False)

    def _increment_downloads_for_installed_mods(self, installed_mods):
        try:
            for mod_key in installed_mods:
                if not mod_key.startswith("local_") and self._can_increment_download_by_config(mod_key):
                    if self._increment_mod_downloads_on_server(mod_key):
                        self._update_install_date_in_config(mod_key)
        except Exception: pass

    def _get_user_ip(self):
        try: return requests.get('https://api.ipify.org', timeout=5).text.strip()
        except Exception: return "127.0.0.1"

    def _can_increment_download_by_config(self, mod_key):
        try:
            import datetime
            for folder_name in os.listdir(self.main_window.mods_dir):
                config_path = os.path.join(self.main_window.mods_dir, folder_name, "config.json")
                if os.path.isfile(config_path):
                    try:
                        config_data = self.main_window._read_json(config_path)
                        if config_data.get("mod_key") == mod_key:
                            installed_date_str = config_data.get("installed_date", "")
                            if installed_date_str:
                                installed_date = datetime.datetime.strptime(installed_date_str, '%Y-%m-%d %H:%M:%S')
                                time_diff = datetime.datetime.now() - installed_date
                                return time_diff.total_seconds() >= 43200
                            return True
                    except:
                        continue
            return False
        except:
            return False

    def _update_install_date_in_config(self, mod_key):
        try:
            for folder_name in os.listdir(self.main_window.mods_dir):
                config_path = os.path.join(self.main_window.mods_dir, folder_name, "config.json")
                if os.path.isfile(config_path):
                    try:
                        config_data = self.main_window._read_json(config_path)
                        if config_data.get("mod_key") == mod_key:
                            config_data["installed_date"] = time.strftime('%Y-%m-%d %H:%M:%S')
                            self.main_window._write_json(config_path, config_data)
                            return
                    except:
                        continue
        except:
            pass

    def _increment_mod_downloads_on_server(self, mod_key):
        try:
            check_response = requests.get(_fb_url(DATA_FIREBASE_URL, f"mods/{mod_key}"), timeout=10)
            if check_response.status_code != 200 or not (mod_data := check_response.json()): return False
            new_downloads = mod_data.get('downloads', 0) + 1
            response = requests.put(_fb_url(DATA_FIREBASE_URL, f"mods/{mod_key}/downloads"), json=new_downloads, timeout=10)
            return response.status_code in [200, 204]
        except Exception: return False

    def _download_archive_file(self, url: str, target_dir: str, progress_signal, total_size: int, downloaded_ref: list[int], session=None):
        import os
        from urllib.parse import urlparse, unquote

        if session is None:
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)

        parsed_url = urlparse(url)
        filename = unquote(os.path.basename(parsed_url.path))

        if not filename or '.' not in filename:
            filename = f"extra_file_{hash(url) % 10000}.zip"

        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)


        try:
            response = session.get(url, stream=True, timeout=30)
            response.raise_for_status()

            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_ref[0] += len(chunk)
                        if total_size > 0:
                            progress_signal.emit(int(downloaded_ref[0] / total_size * 100))

        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except:
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
            if platform.system() == "Darwin":
                filename = "game.ios.xdelta"
            else:
                filename = "data.win.xdelta"

        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)

        try:
            response = session.get(url, stream=True, timeout=30)
            response.raise_for_status()

            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_ref[0] += len(chunk)
                        if total_size > 0:
                            progress_signal.emit(int(downloaded_ref[0] / total_size * 100))

        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except:
                    pass
            raise e

class FullInstallThread(QThread):
    progress = pyqtSignal(int)
    status   = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, main_window, target_dir: str, make_shortcut: bool = False):
        super().__init__(main_window)
        self.main_window = main_window
        self.target_dir = target_dir

    def run(self):
        full_install_url = self.main_window.global_settings.get("full_install_url")
        if not full_install_url:
            self.status.emit(tr("errors.files_not_found"), UI_COLORS["status_error"])
            self.finished.emit(False, self.target_dir)
            return
        self.status.emit(tr("status.installing_game_files"), UI_COLORS["status_warning"])
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
            retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=10)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

            resp = session.head(full_install_url, allow_redirects=True, timeout=15)
            total_size = int(resp.headers.get("content-length", 0))
            downloaded_ref = [0]
            download_and_extract_archive(full_install_url, self.target_dir, self.progress, total_size, downloaded_ref, session, is_game_installation=True)


            self.status.emit(tr("status.demo_installation_complete"), UI_COLORS["status_success"])
            self.finished.emit(True, self.target_dir)
        except Exception as e:
            self.status.emit(tr("errors.full_installation_error").format(str(e)), UI_COLORS["status_error"])
            self.finished.emit(False, self.target_dir)

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
        text = ""
        try:
            if self.source.startswith(("http://", "https://")):
                params = {'ts': int(time.time())}
                headers = {"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "DELTAHUB/1.0"}
                with requests.get(self.source, params=params, headers=headers, timeout=10) as resp:
                    resp.raise_for_status()
                    text = resp.text
            elif os.path.exists(self.source) or os.path.exists(self.source.replace(".md", ".txt")):
                path_to_read = self.source if os.path.exists(self.source) else self.source.replace(".md", ".txt")
                with open(path_to_read, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            else:
                text = self.source
        except Exception:
            text = tr("errors.changelog_load_failed")
        finally:
            self.finished.emit(text)

def increment_launch_counter():
    os_key = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system(), "other")
    try:
        current_resp = requests.get(_fb_url(DATA_FIREBASE_URL, f"stats/launches/{os_key}"), timeout=5)
        current = current_resp.json() if current_resp.status_code == 200 and isinstance(current_resp.json(), int) else 0
        requests.put(_fb_url(DATA_FIREBASE_URL, f"stats/launches/{os_key}"), json=current + 1, timeout=5)
    except requests.RequestException: pass

def get_app_support_path():
    system = platform.system()
    path = {"Windows": os.path.join(os.getenv('APPDATA', ''), "DELTAHUB"), "Darwin": os.path.join(os.path.expanduser('~'), "Library/Application Support/DELTAHUB")}.get(system, os.path.join(os.path.expanduser('~'), ".local/share/DELTAHUB"))
    os.makedirs(os.path.join(path, "cache"), exist_ok=True); return os.path.join(path, "cache")


def get_legacy_ylauncher_path() -> str:
    """Returns the old YLauncher config folder path for the current OS."""
    system = platform.system()
    if system == "Windows":
        return os.path.join(os.getenv('APPDATA', ''), "YLauncher")
    elif system == "Darwin":
        return os.path.join(os.path.expanduser('~'), "Library/Application Support/YLauncher")
    else:
        return os.path.join(os.path.expanduser('~'), ".local/share/YLauncher")

def get_launcher_dir() -> str: return os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath(".")

# User-writable data root for mods/logs/etc.
def get_user_data_root() -> str:
    system = platform.system()
    if system == "Windows":
        root = os.getenv('LOCALAPPDATA') or os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(root, "DELTAHUB")
    elif system == "Darwin":
        return os.path.join(os.path.expanduser('~'), "Library", "Application Support", "DELTAHUB")
    else:
        return os.path.join(os.path.expanduser('~'), ".local", "share", "DELTAHUB")

def get_user_mods_dir() -> str:
    return os.path.join(get_user_data_root(), "mods")

def sanitize_filename(name: str) -> str: return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def get_unique_mod_dir(mods_dir, mod_name):
    sanitized_name = sanitize_filename(mod_name)
    base_dir = os.path.join(mods_dir, sanitized_name)
    if not os.path.exists(base_dir):
        return sanitized_name
    counter = 1
    while True:
        unique_name = f"{sanitized_name}_{counter}"
        unique_dir = os.path.join(mods_dir, unique_name)
        if not os.path.exists(unique_dir):
            return unique_name
        counter += 1


def is_game_running():
    return any(proc.info['name'] in GAME_PROCESS_NAMES for proc in psutil.process_iter(['name']))

def get_default_save_path() -> str:
    system = platform.system()
    return {"Windows": os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "DELTARUNE"), "Darwin": os.path.expanduser("~/Library/Application Support/com.tobyfox.deltarune")}.get(system, os.path.expanduser("~/.steam/steam/steamapps/compatdata/1690940/pfx/drive_c/users/steamuser/Local Settings/Application Data/DELTARUNE"))
    
def is_valid_save_path(path: str) -> bool: return bool(path and os.path.isdir(path) and os.listdir(path))

def is_valid_game_path(path: str, skip_data_check: bool = False) -> bool:
    if not path or not os.path.isdir(path):
        return False

    if platform.system() == "Darwin":
        app_path = Path(path)
        if not path.endswith(".app"):
            app_path = next((app_path / name for name in ("DELTARUNE.app", "DELTARUNEdemo.app") if (app_path / name).is_dir()), None)

        if not app_path or not app_path.is_dir():
            return False

        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        res_dir = contents / "Resources"

        if not macos_dir.is_dir() or not res_dir.is_dir():
            return False

        try:
            has_executable = any(p.is_file() and os.access(p, os.X_OK) for p in macos_dir.iterdir())
        except OSError:
            return False

        if skip_data_check:
            return has_executable

        has_data = (res_dir / "game.ios").is_file() or (res_dir / "data.win").is_file()
        return has_executable and has_data

    return (os.path.isfile(os.path.join(path, "DELTARUNE.exe")) or
            os.path.isfile(os.path.join(path, "DELTARUNE")))

def ensure_writable(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode; os.chmod(path, mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for name in dirs + files: os.chmod(os.path.join(root, name), mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        return True
    except (OSError, PermissionError): return False

def autodetect_path(game_name: str) -> str | None:
    system, paths = platform.system(), []
    if system == "Windows":
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if root := os.getenv(env): paths.append(os.path.join(root, "Steam", "steamapps", "common", game_name))
        for drive in "CDE": paths.extend([f"{drive}:/Steam/steamapps/common/{game_name}", f"{drive}:/SteamLibrary/steamapps/common/{game_name}"])
    elif system == "Linux": paths.extend([os.path.expanduser(f"~/.steam/steam/steamapps/common/{game_name}"), os.path.expanduser(f"~/.local/share/Steam/steamapps/common/{game_name}"), f"/run/media/mmcblk0p1/steamapps/common/{game_name}"])
    elif system == "Darwin":
        if game_name.endswith("demo"):
            for parent in [os.path.expanduser(f"~/Library/Application Support/Steam/steamapps/common/{game_name}"), f"/Applications/{game_name}"]:
                if os.path.isdir(parent):
                    for app_name in [f"{game_name}.app", "DELTARUNE.app"]:
                        if os.path.exists(full_path := os.path.join(parent, app_name)): paths.append(full_path)
        else: paths.extend([loc for loc in [os.path.expanduser(f"~/Library/Application Support/Steam/steamapps/common/{game_name}/{game_name}.app"), f"/Applications/{game_name}.app"] if os.path.isdir(loc)])
    return next((p for p in paths if os.path.exists(p)), None)

def fix_macos_python_symlink(app_dir: Path) -> None:
    try:
        if platform.system() != "Darwin": return
        p = app_dir / "Contents" / "Frameworks" / "Python"
        if not p.exists() or p.is_symlink(): return
        if p.is_file() and p.stat().st_size < 512:
            try: target_rel = p.read_text(encoding="utf-8").strip()
            except Exception: target_rel = "Python.framework/Versions/3.12/Python"
            p.unlink(missing_ok=True); os.symlink(target_rel, p); st = os.lstat(p); os.chmod(p, stat.S_IMODE(st.st_mode) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception: pass

def cleanup_old_updater_files():
    try:
        if not getattr(sys, 'frozen', False): return
        system = platform.system(); current_exe_path = os.path.realpath(sys.executable)
        replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), "..", "..")) if system == "Darwin" else current_exe_path
        backup_path = f"{replace_target}.old"
        if os.path.exists(backup_path): shutil.rmtree(backup_path, ignore_errors=True)
    except Exception: pass

def check_internet_connection() -> bool:
    try: requests.get("https://www.google.com", timeout=5); return True
    except requests.RequestException: return False

import hashlib, secrets, string
INTERNAL_SALT = os.getenv("INTERNAL_SALT", "")
def generate_secret_key() -> str: return f"RUNE-{''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(14))}"
def hash_secret_key(secret_key: str) -> str:
    return hashlib.sha256((secret_key + INTERNAL_SALT).encode('utf-8')).hexdigest()

def possible_secret_hashes(secret_key: str) -> list[str]:
    hashes = []
    current = hashlib.sha256((secret_key + INTERNAL_SALT).encode('utf-8')).hexdigest()
    hashes.append(current)
    legacy_salt = "deltahub_launcher_internal_secret"
    if INTERNAL_SALT != legacy_salt:
        hashes.append(hashlib.sha256((secret_key + legacy_salt).encode('utf-8')).hexdigest())
    return hashes

def verify_secret_key(entered_key: str, stored_hash: str) -> bool:
    return stored_hash in possible_secret_hashes(entered_key)
def show_error(parent, title, message): from PyQt6.QtWidgets import QMessageBox; QMessageBox.critical(parent, title, message)
def show_info(parent, title, message): from PyQt6.QtWidgets import QMessageBox; QMessageBox.information(parent, title, message)
def confirm_action(parent, title, message): from PyQt6.QtWidgets import QMessageBox; return QMessageBox.question(parent, title, message) == QMessageBox.StandardButton.Yes
def version_sort_key(version_string: str):
    try:
        numeric_parts = []
        for part in version_string.split('.'):
            try: numeric_parts.append(int(part))
            except ValueError: numeric_parts.append(0)
        while len(numeric_parts) < 3: numeric_parts.append(0)
        return tuple(numeric_parts[:3])
    except: return (0, 0, 0)
def game_version_sort_key(version_string: str):
    try:
        import re
        if match := re.match(r'^(\d+)\.(\d+)([A-Z]?)$', version_string.strip()):
            major, minor, letter = int(match.group(1)), int(match.group(2)), match.group(3)
            return (major, minor, 0 if letter == "" else (ord(letter) - ord('A') + 1))
        else:
            parts = version_string.split('.')
            return (int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0, int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0, 0)
    except: return (0, 0, 0)

def detect_field_type_by_text(text: str) -> str:
    """
    Определяет тип поля по его тексту.
    Используется для обратной совместимости с существующим кодом.
    ВНИМАНИЕ: Эта функция временная, нужно заменить на data-атрибуты!
    """
    text_lower = text.lower()
    
    # Проверяем ключевые слова для определения типа поля
    if any(keyword in text_lower for keyword in ["ссылка", "путь", "url", "link"]):
        return "file_path"
    elif "версия" in text_lower or "version" in text_lower:
        return "version"
    elif "дополнительные файлы" in text_lower or "extra files" in text_lower:
        return "extra_files"
    
    return "unknown"

def get_file_filter(filter_type: str) -> str:
    """
    Безопасная функция для получения фильтров файлов.
    Комбинирует локализованные описания с постоянными расширениями файлов.
    """
    # Постоянные расширения файлов (не подлежат локализации!)
    FILTER_EXTENSIONS = {
        'image_files': '*.jpg *.png *.bmp *.gif',
        'background_images': '*.jpg *.png *.bmp *.gif',
        'xdelta_files': '*.xdelta',
        'data_files': '*.win *.ios',
        'archive_files': '*.zip *.rar',
        'extended_archives': '*.zip *.rar *.7z *.tar.gz',
        'game_files': '*.exe',
        'text_files': '*.txt',
        'all_files': '*'
    }
    
    # Локализованные описания (можно переводить)
    FILTER_DESCRIPTIONS = {
        'image_files': tr('file_descriptions.image_files'),
        'background_images': tr('file_descriptions.background_images'),
        'xdelta_files': tr('file_descriptions.xdelta_files'),
        'data_files': tr('file_descriptions.data_files'),
        'archive_files': tr('file_descriptions.archive_files'),
        'extended_archives': tr('file_descriptions.extended_archives'),
        'game_files': tr('file_descriptions.game_files'),
        'text_files': tr('file_descriptions.text_files'),
        'all_files': tr('file_descriptions.all_files')
    }
    
    # Получаем расширения и описание
    extensions = FILTER_EXTENSIONS.get(filter_type, '*')
    description = FILTER_DESCRIPTIONS.get(filter_type, filter_type)
    
    # Формируем фильтр в правильном формате
    all_files_desc = FILTER_DESCRIPTIONS.get('all_files', 'All files')
    return f"{description} ({extensions});;{all_files_desc} (*)"