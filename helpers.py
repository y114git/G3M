import os, platform, re, shutil, stat, sys, tempfile, time, zipfile, psutil, requests
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QThread, QObject, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QMessageBox
from localization import tr


LAUNCHER_VERSION = "2.0.1"

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
        for k in ("DATA_FIREBASE_URL", "CLOUD_FUNCTIONS_BASE_URL", "INTERNAL_SALT"):
            if not os.getenv(k, "") and hasattr(_se, k):
                os.environ[k] = getattr(_se, k)
    except Exception:
        pass

_load_config_sources()
# Single database URL for data (mods, globals, stats)
DATA_FIREBASE_URL = os.getenv("DATA_FIREBASE_URL", "")
# Base URL for Cloud Functions (set this after deploy)
CLOUD_FUNCTIONS_BASE_URL = os.getenv("CLOUD_FUNCTIONS_BASE_URL", "")

_FB_ID_TOKEN = None
_FB_TOKEN_EXPIRES_AT = 0.0

def get_firebase_id_token() -> str:
    # Disabled: no client-side Firebase auth. All writes go through Cloud Functions.
    return ""

def _fb_url(base: str, path: str, with_auth: bool = True) -> str:
    base = base.rstrip('/')
    # Client no longer appends auth tokens; reads are public via security rules
    url = f"{base}/{path}.json"
    return url
STEAM_APP_ID_FULL, STEAM_APP_ID_DEMO, STEAM_APP_ID_UNDERTALE = "1671210", "1690940", "391540"
GAME_PROCESS_NAMES = ["DELTARUNE.exe", "DELTARUNE", "UNDERTALE.exe", "UNDERTALE", "runner"]
SAVE_SLOT_FINISH_MAP = {0: 3, 1: 4, 2: 5}
ARCH = platform.machine()
DEFAULT_FONT_FALLBACK_CHAIN = ["Determination Sans Rus", "DejaVu Sans", "Noto Sans", "Liberation Sans", "Arial", "Noto Color Emoji", "Segoe UI Emoji", "Apple Color Emoji"]
SOCIAL_LINKS = {"telegram": "https://t.me/y_maintg", "discord": "https://discord.gg/gg4EvZpWKd"}
UI_COLORS = {"status_error": "red", "status_warning": "orange", "status_success": "green", "status_info": "gray", "status_ready": "lightgreen", "status_steam": "blue", "link": "#00BFFF", "social_discord": "#8A2BE2", "saves_button": "yellow"}
THEMES = {"default": {"name": "Deltarune", "background": "assets/bg_fountain.gif", "font_family": "Determination Sans Rus", "font_size_main": 16, "font_size_small": 12, "colors": {"main_fg": "#000000", "top_level_fg": "#000000", "button": "#000000", "button_hover": "#333333", "button_text": "#FFFFFF", "border": "#FFFFFF", "text": "#FFFFFF"}}}
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
    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]: return {i: [mod for mod in all_mods if mod.modtype == 'deltarune' and not mod.hide_mod and not mod.ban_status and mod.get_chapter_data(i)] for i in range(5)}

class DemoGameMode(GameMode):
    def __init__(self):
        self._path_key, self._custom_exec_key, self.steam_id, self.tab_names, self.path_change_button_text, self.direct_launch_allowed = 'demo_game_path', 'demo_custom_executable_path', STEAM_APP_ID_DEMO, [tr("tabs.demo")], tr("buttons.change_demo_path"), False
    def get_chapter_id(self, ui_index: int) -> int: return -1
    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]: return {0: [mod for mod in all_mods if mod.is_valid_for_demo() and not mod.hide_mod and not mod.ban_status]}

class UndertaleGameMode(GameMode):
    def __init__(self):
        self._path_key, self._custom_exec_key, self.steam_id, self.tab_names, self.path_change_button_text, self.direct_launch_allowed = 'undertale_game_path', 'undertale_custom_executable_path', STEAM_APP_ID_UNDERTALE, [tr("tabs.undertale")], tr("buttons.change_undertale_path"), True
    def get_chapter_id(self, ui_index: int) -> int: return 0  # Single file for UNDERTALE
    def filter_mods_for_ui(self, all_mods: list['ModInfo']) -> dict[int, list['ModInfo']]: return {0: [mod for mod in all_mods if mod.modtype == 'undertale' and not mod.hide_mod and not mod.ban_status and mod.files.get('undertale')]}

@dataclass
class ModExtraFile:
    key: str
    version: str
    url: str

@dataclass
class ModChapterData:
    description: Optional[str] = None
    data_file_url: Optional[str] = None
    data_file_version: Optional[str] = None
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
    modtype: str  # "deltarune", "deltarunedemo", or "undertale"
    is_verified: bool
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    hide_mod: bool = False
    is_xdelta: bool = False
    ban_status: bool = False
    files: Dict[str, ModChapterData] = field(default_factory=dict)  # renamed from chapters
    demo_url: Optional[str] = None
    demo_version: Optional[str] = None
    created_date: Optional[str] = None
    last_updated: Optional[str] = None
    screenshots_url: List[str] = field(default_factory=list)

    def get_chapter_data(self, chapter_id: int) -> Optional[ModChapterData]:
        # Map chapter_id to file key
        chapter_map = {0: "0", 1: "1", 2: "2", 3: "3", 4: "4", -1: "demo"}

        # Special handling for UNDERTALE
        if self.modtype == 'undertale' and chapter_id == 0:
            return self.files.get("undertale")

        file_key = chapter_map.get(chapter_id)
        return self.files.get(file_key) if file_key else None

    def is_valid_for_demo(self) -> bool:
        if self.modtype != 'deltarunedemo':
            return False
        if self.key.startswith('local_'):
            return bool(self.files and self.files.get("demo"))
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

def _download_file(session, url, tmp_path, progress_signal, total_size, downloaded_ref, max_retries: int = 5):
    import os, time
    expected_size = 0
    try:
        h = session.head(url, allow_redirects=True, timeout=15)
        expected_size = int(h.headers.get("content-length", 0))
    except Exception:
        expected_size = 0
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            current_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers = {}
            if expected_size and 0 < current_size < expected_size:
                headers["Range"] = f"bytes={current_size}-"
            r = session.get(url, stream=True, timeout=60, allow_redirects=True, headers=headers)
            r.raise_for_status()
            status_code = getattr(r, "status_code", 200)
            # If server ignored Range (200) but we have partial data, avoid double-counting progress
            duplicate_remaining = 0
            mode = "ab"
            if status_code == 206 and "Range" in headers:
                mode = "ab"
            else:
                mode = "wb"
                if current_size > 0:
                    duplicate_remaining = current_size
            this_request_expected = 0
            try:
                this_request_expected = int(r.headers.get("content-length", 0))
            except Exception:
                this_request_expected = 0
            written_this_request = 0
            with open(tmp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    sz = len(chunk)
                    written_this_request += sz
                    if duplicate_remaining > 0:
                        if sz <= duplicate_remaining:
                            duplicate_remaining -= sz
                        else:
                            add = sz - duplicate_remaining
                            downloaded_ref[0] += add
                            duplicate_remaining = 0
                    else:
                        downloaded_ref[0] += sz
                    if total_size > 0:
                        try:
                            progress_signal.emit(int(min(100, max(0, downloaded_ref[0] / total_size * 100))))
                        except Exception:
                            pass
            final_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            # Validate per-request and overall sizes when known
            if this_request_expected and written_this_request < this_request_expected:
                raise IOError("connection dropped during download")
            if expected_size and final_size < expected_size:
                # try to resume more
                continue
            return
        except Exception:
            if attempt >= max_retries:
                raise
            try:
                time.sleep(min(2.0, 0.2 * attempt))
            except Exception:
                pass

def _extract_archive(tmp_path, target_dir, fname, is_game_installation=False):
    import rarfile
    low = fname.lower()
    extractors = {
        "zip": lambda: zipfile.ZipFile(tmp_path, "r").extractall(target_dir),
        "rar": lambda: rarfile.RarFile(tmp_path, "r").extractall(target_dir)
    }
    # Try py7zr if available
    try:
        import py7zr
        extractors["7z"] = lambda: py7zr.SevenZipFile(tmp_path, mode='r').extractall(path=target_dir)
    except Exception:
        pass
    for ext, extractor in extractors.items():
        if low.endswith(f".{ext}"):
            extractor()
            _cleanup_extracted_archive(target_dir, is_game_installation)
            return
    shutil.copy2(tmp_path, os.path.join(target_dir, fname))

def _cleanup_extracted_archive(target_dir: str, is_game_installation: bool = False):
    if is_game_installation:
        # Чистим только временные директории при установке игры
        cleanup_dir_pattern = re.compile(r'^chapter\d+_(windows|mac)$', re.I)
        for root, dirs, files in os.walk(target_dir, topdown=False):
            for dir_name in dirs[:]:
                if cleanup_dir_pattern.match(dir_name):
                    try:
                        shutil.rmtree(os.path.join(root, dir_name))
                        dirs.remove(dir_name)
                    except OSError:
                        pass
    else:
        # Ничего не удаляем в мод-папках — модовые файлы должны оставаться нетронутыми
        return

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

    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id

    def run(self):
        try:
            # Use Cloud Function to update presence and compute current online count
            resp = requests.post(f"{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat", json={"sessionId": self.session_id}, timeout=8)
            if resp.status_code == 200:
                try:
                    data = resp.json() or {}
                    online = int(data.get("online", 0))
                    self.update_online_count.emit(max(online, 0))
                except Exception:
                    pass
        except requests.RequestException:
            pass
        finally:
            self.finished.emit()

class FetchTranslationsThread(QThread):
    result, status = pyqtSignal(bool), pyqtSignal(str, str)
    def __init__(self, main_window, force_update=False): super().__init__(main_window); self.main_window, self.force_update = main_window, force_update
    def run(self):
        try:
            response = requests.get(f"{CLOUD_FUNCTIONS_BASE_URL}/getMods", timeout=15); response.raise_for_status()
            all_mods = []



            for key, data in (response.json() or {}).items():
                if not isinstance(data, dict): continue
                files_data = {}

                # Support both new "files" and legacy "chapters" structure
                raw_data = data.get("files", data.get("chapters", {}))

                if isinstance(raw_data, list):
                    chapters_items = [(str(i), chapter_data) for i, chapter_data in enumerate(raw_data) if chapter_data is not None]
                elif isinstance(raw_data, dict):
                    chapters_items = list(raw_data.items())
                else:
                    chapters_items = []

                # Determine modtype from is_demo_mod or explicit modtype
                modtype = data.get("modtype", "deltarune")  # Default to deltarune
                if modtype == "deltarune" and data.get("is_demo_mod", False):
                    modtype = "deltarunedemo"  # Legacy compatibility

                for chapter_key, chapter_data in chapters_items:
                    if not isinstance(chapter_data, dict):
                        continue

                    # Handle legacy chapter ID format
                    try:
                        chapter_id = int(chapter_key[1:]) if chapter_key.startswith("c") else int(chapter_key)
                    except (ValueError, TypeError):
                        # New format uses string keys directly
                        if chapter_key in ["0", "1", "2", "3", "4", "demo", "undertale"]:
                            pass  # Valid key
                        else:
                            continue

                    # Map legacy chapter IDs to new format
                    if isinstance(chapter_key, str) and chapter_key.isdigit():
                        # Already in new format (0, 1, 2, 3, 4)
                        pass
                    elif chapter_key == "demo":
                        # Already correct
                        pass
                    elif chapter_key == "undertale":
                        # Already correct
                        pass
                    else:
                        # Legacy format conversion
                        if chapter_id == -1:
                            chapter_key = 'demo'
                        elif chapter_id == 0:
                            chapter_key = '0'
                        elif 1 <= chapter_id <= 4:
                            chapter_key = str(chapter_id)
                        else:
                            continue

                    data_url = chapter_data.get('data_file_url')
                    data_version = chapter_data.get('data_file_version', '1.0.0')
                    files_entry = {}
                    if data_url:
                        files_entry.update({'data_file_url': data_url, 'data_file_version': data_version})
                    if extra_files := chapter_data.get('extra_files', []):
                        files_entry['extra'] = {ef.get('key', 'unknown'): {'url': ef.get('url', ''), 'version': ef.get('version', '1.0.0')} for ef in extra_files if isinstance(ef, dict)}

                    if files_entry:
                        files_data[chapter_key] = files_entry

                composite_version = self._aggregate_versions(files_data); base_version = data.get("version")
                screens_list = data.get("screenshots_url", [])
                if isinstance(screens_list, str):
                    # support comma-separated fallback
                    screens_list = [s.strip() for s in screens_list.split(",") if s.strip()]
                elif not isinstance(screens_list, list):
                    screens_list = []

                mod = ModInfo(key=key, name=data.get("name", tr("status.unknown_mod")), author=data.get("author", tr("status.unknown_author_status")), version=f"{base_version}|{composite_version}" if base_version else composite_version, tagline=data.get("tagline", tr("status.no_description_status")), game_version=data.get("game_version", tr("status.no_version")), description_url=data.get("description_url", ""), downloads=data.get("downloads", 0), modtype=modtype, is_verified=data.get("is_verified", False), icon_url=data.get("icon_url"), tags=data.get("tags", []), hide_mod=data.get("hide_mod", False), is_xdelta=(data.get("is_xdelta", data.get("is_piracy_protected", False))), ban_status=data.get("ban_status", False), demo_url=files_data.get("demo", {}).get("url") if files_data else None, demo_version=files_data.get("demo", {}).get("version", "1.0.0") if files_data else "1.0.0", created_date=data.get("created_date"), last_updated=data.get("last_updated"), screenshots_url=screens_list)

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
        # Process all file entries, now using string keys instead of chapter IDs
        for file_key, chapter_data in files_data.items():
            if not isinstance(chapter_data, dict):
                continue

            has_df_version = not chapter_data.get("data_file_url") or bool(chapter_data.get("data_file_version"))
            extra_files_data = chapter_data.get("extra", {}).items()

            if not has_df_version or (extra_files_data and not all(v.get("version") for _, v in extra_files_data)):
                return False

            mod_chapter_data = ModChapterData(data_file_url=chapter_data.get("data_file_url"), data_file_version=chapter_data.get("data_file_version", "1.0.0"), extra_files=[ModExtraFile(key=k, **v) for k, v in extra_files_data])
            if description_url := chapter_data.get("description_url"):
                try: desc_resp = requests.get(description_url, timeout=10); desc_resp.raise_for_status(); mod_chapter_data.description = desc_resp.text
                except requests.RequestException: mod_chapter_data.description = tr("errors.description_load_failed")

            if mod_chapter_data.is_valid():
                mod.files[file_key] = mod_chapter_data
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
    def __init__(self, main_window, install_tasks):
        super().__init__(main_window)
        self.main_window = main_window
        self.install_tasks = install_tasks
        self._cancelled = False
        self._installed_dirs = []
        self.temp_root = None  # Временная папка для безопасной установки
    def cancel(self):
        # Только устанавливаем флаг отмены и уведомляем UI. Очистку выполняет основной поток после завершения.
        self._cancelled = True
        self.status.emit(tr("status.operation_cancelled"), UI_COLORS["status_error"])

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

    def _collect_remote_versions_for_chapter(self, mod: ModInfo, chapter_id: int) -> dict:
        """Формирует словарь версий для удалённых компонентов главы мода.
        Структура: {'data': '1.0.1', 'key1': '1.0.0', ...}
        """
        versions: dict[str, str] = {}
        if chapter_id == -1:
            # Для демо-версии используем отдельный ключ
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

    def _should_update_component(self, mod: ModInfo, chapter_id: int, existing_folder: str) -> dict:
        """
        Возвращает словарь компонентов, требующих обновления/удаления.
        Ключи — имена компонентов ('data' и ключи extra), значения — dict с полями:
          - url (если требуется скачивание)
          - local_version / remote_version
          - delete: True (если компонент удалён на сервере)
          - is_xdelta / type_changed (для 'data' при смене типа установки)
        """
        if not existing_folder:
            return {}

        config_path = os.path.join(self.main_window.mods_dir, existing_folder, "config.json")
        if not os.path.exists(config_path):
            return {}

        try:
            config_data = self.main_window._read_json(config_path)
            # Читаем локальные версии из структурированного словаря
            local_versions = (config_data.get("chapters", {})
                              .get(str(chapter_id), {})
                              .get("versions", {})) or {}

            # Собираем удалённые версии
            remote_versions = self._collect_remote_versions_for_chapter(mod, chapter_id)

            components_to_update: dict[str, dict] = {}
            chapter_data = mod.get_chapter_data(chapter_id) if chapter_id != -1 else None

            # Обработка data (учитываем возможный xdelta)
            if chapter_data and chapter_data.data_file_url and remote_versions.get('data'):
                is_xdelta_mod = getattr(mod, 'is_xdelta', getattr(mod, 'is_piracy_protected', False))
                local_is_xdelta = False
                try:
                    local_is_xdelta = any(
                        f.lower().endswith('.xdelta')
                        for f in os.listdir(os.path.join(self.main_window.mods_dir, existing_folder))
                        if os.path.isfile(os.path.join(self.main_window.mods_dir, existing_folder, f))
                    )
                except Exception:
                    local_is_xdelta = False
                type_changed = (is_xdelta_mod != local_is_xdelta)

                local_data_v = local_versions.get('data')
                remote_data_v = remote_versions.get('data')
                # Сравнение по ключу сортировки версий
                if (remote_data_v and
                    (type_changed or version_sort_key(remote_data_v) > version_sort_key(local_data_v or "0.0.0"))):
                    components_to_update['data'] = {
                        'url': chapter_data.data_file_url,
                        'local_version': local_data_v,
                        'remote_version': remote_data_v,
                        'is_xdelta': is_xdelta_mod,
                        'type_changed': type_changed
                    }

            # Обработка extra-файлов (обновления)
            if chapter_data:
                for extra_file in chapter_data.extra_files:
                    rv = remote_versions.get(extra_file.key)
                    lv = local_versions.get(extra_file.key)
                    if rv and version_sort_key(rv) > version_sort_key(lv or "0.0.0"):
                        components_to_update[extra_file.key] = {
                            'url': extra_file.url,
                            'local_version': lv,
                            'remote_version': rv
                        }

                # Удалённые на сервере extra-файлы — помечаем на удаление
                remote_extra_keys = {ef.key for ef in chapter_data.extra_files}
                for missing_key in [k for k in local_versions.keys() if k != 'data' and k not in remote_extra_keys]:
                    components_to_update[missing_key] = {'delete': True}

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
                       file_lower in ('data.win', 'data.ios', 'game.ios'):
                        file_path = os.path.join(root, file)
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            print(f"Cannot delete file {file_path}: {e}")
        except Exception as e:
            print(f"Error removing data files from {mod_folder_path}: {e}")

    def run(self):
        import os, shutil, tempfile
        try:
            # Готовим временную директорию для безопасной установки
            self.temp_root = tempfile.mkdtemp(prefix="deltahub-install-")
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
                            is_xdelta_mod = getattr(mod, 'is_xdelta', getattr(mod, 'is_piracy_protected', False))
                            tasks.append({'mod': mod, 'url': chapter_data.data_file_url, 'chapter_id': chapter_id, 'component': 'data', 'is_xdelta': is_xdelta_mod})
                        for extra_file in chapter_data.extra_files:
                            is_xdelta_mod = getattr(mod, 'is_xdelta', getattr(mod, 'is_piracy_protected', False))
                            tasks.append({'mod': mod, 'url': extra_file.url, 'chapter_id': chapter_id, 'component': extra_file.key, 'is_xdelta': is_xdelta_mod})
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
                    # Добавляем задачу очистки устаревших архивов (удаленные extra)
                    if chapter_data:
                        from urllib.parse import urlparse, unquote
                        allowed = set()
                        for extra_file in chapter_data.extra_files:
                            p = urlparse(extra_file.url).path
                            fn = unquote(os.path.basename(p)) if p else ''
                            if fn:
                                allowed.add(fn.lower())
                        tasks.append({'mod': mod, 'chapter_id': chapter_id, 'cleanup_archives': True, 'allowed': list(allowed)})

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


            # Составляем список реальных задач загрузки (с URL)
            download_tasks = [t for t in tasks if t.get('url')]

            file_sizes_cache = {}
            for task in download_tasks:
                u = task.get('url')
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
                self.finished.emit(False)
                return

            self.status.emit(tr("status.preparing_download"), UI_COLORS["status_warning"])

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
                # Пишем во временную папку; позже перенесем в финальную mods_dir
                mod_dir = os.path.join(self.temp_root, mod_folder_name)
                # Определяем папку для файлов на основе chapter_id
                if chapter_id == -1:
                    cache_dir = os.path.join(mod_dir, "demo")
                elif chapter_id == 0:
                    cache_dir = os.path.join(mod_dir, "chapter_0")  # Меню/глава 0 храним в 'chapter_0' для согласованности с лаунчером
                else:
                    cache_dir = os.path.join(mod_dir, f"chapter_{chapter_id}")

                # Очистка устаревших архивов (удаленные extra)
                if task.get('cleanup_archives'):
                    try:
                        allowed = set((task.get('allowed') or []))
                        if os.path.exists(cache_dir):
                            for fname in os.listdir(cache_dir):
                                fl = fname.lower()
                                if fl.endswith(('.zip', '.rar', '.7z')) and fl not in allowed:
                                    try:
                                        os.remove(os.path.join(cache_dir, fname))
                                    except Exception:
                                        pass
                    except Exception: pass
                    continue

                # Удаление компонента (extra, отсутствующий на сервере)
                if task.get('delete'):
                    try:
                        if os.path.exists(cache_dir):
                            for fname in os.listdir(cache_dir):
                                fl = fname.lower()
                                if fl.endswith(('.zip', '.rar', '.7z')):
                                    # Удаление конкретных лишних архивов уже обработано в cleanup_archives
                                    pass
                    except Exception:
                        pass
                    continue

                url = task.get('url')
                # Для задач без URL (удаление/очистка) не увеличиваем счётчик и не показываем прогресс как скачивание
                if not url:
                    # Выполняем нефайловые задачи (cleanup/delete) как и раньше
                    file_size_mb = tr("status.unknown_size")
                else:
                    current_index += 1
                    file_size_mb = tr("status.unknown_size")
                    file_size_bytes = file_sizes_cache.get(url, 0)
                    if file_size_bytes > 0:
                        size_mb = file_size_bytes / (1024 * 1024)
                        file_size_mb = tr("status.unknown_size") if size_mb < 0.05 else f"{size_mb:.1f} MB"

                    # Показываем только информацию о компоненте
                    self.status.emit(f"{mod.name} {current_index}/{total_items} ({file_size_mb})", UI_COLORS["status_warning"])

                self._installed_dirs.append(cache_dir)
                chapter_data = mod.get_chapter_data(chapter_id)
                is_data_file = chapter_data and url and (chapter_data.data_file_url == url)
                is_xdelta = task.get('is_xdelta', False)

                # Если меняется тип data↔xdelta — удаляем противоположный тип перед скачиванием
                if is_data_file and task.get('type_changed'):
                    try:
                        if is_xdelta:
                            # Переход на xdelta — удалить data.win/game.ios
                            if os.path.exists(cache_dir):
                                for fname in os.listdir(cache_dir):
                                    fl = fname.lower()
                                    if fl in ('data.win','game.ios') or fl.endswith('.win') or fl.endswith('.ios'):
                                        try:
                                            os.remove(os.path.join(cache_dir, fname))
                                        except Exception:
                                            pass
                        else:
                            # Переход на data — удалить .xdelta
                            if os.path.exists(cache_dir):
                                for fname in os.listdir(cache_dir):
                                    if fname.lower().endswith('.xdelta'):
                                        try:
                                            os.remove(os.path.join(cache_dir, fname))
                                        except Exception:
                                            pass
                    except Exception: pass

                try:
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
                except Exception:
                    raise


                if mod.key not in installed_mods:
                    installed_mods[mod.key] = {'mod': mod, 'chapters': set()}
                installed_mods[mod.key]['chapters'].add(chapter_id)

                if url and total_bytes == 0:
                    done_files += 1
                    self.progress.emit(int(done_files / max(1, len(download_tasks)) * 100))


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
                        # Формируем словарь версий по компонентам
                        if chapter_data.data_file_version:
                            versions_dict['data'] = chapter_data.data_file_version
                        if chapter_data.data_file_url:
                            file_info['data_file_url'] = chapter_data.data_file_url
                            file_info['data_file_version'] = chapter_data.data_file_version

                        # Extra files
                        extra_files_dict = {}
                        for extra_file in chapter_data.extra_files:
                            versions_dict[extra_file.key] = extra_file.version
                            if extra_file.key not in extra_files_dict:
                                extra_files_dict[extra_file.key] = []
                            extra_files_dict[extra_file.key].append(os.path.basename(extra_file.url))

                        if extra_files_dict:
                            file_info['extra_files'] = extra_files_dict
                        if versions_dict:
                            file_info['versions'] = versions_dict

                    elif chapter_id == -1 and mod.is_valid_for_demo():
                        # Для демо сохраняем версию как отдельный компонент
                        if mod.demo_version:
                            versions_dict['demo'] = mod.demo_version
                            file_info['versions'] = versions_dict

                    if file_info:
                        # Map chapter_id to file key
                        if chapter_id == -1:
                            file_key = 'demo'
                        elif chapter_id == 0:
                            file_key = '0'
                        else:
                            file_key = str(chapter_id)
                        files_data[file_key] = file_info

                config_data = {
                    "is_local_mod": False,
                    "mod_key": mod.key,
                    "name": mod.name,
                    "author": mod.author,
                    "version": mod.version,
                    "game_version": mod.game_version,
                    "modtype": mod.modtype,
                    "installed_date": time.strftime('%Y-%m-%d %H:%M:%S'),
                    "is_available_on_server": True,
                    "files": files_data
                }

                config_path = os.path.join(mod_dir, "config.json")
                self.main_window._write_json(config_path, config_data)


                self._increment_downloads_for_installed_mods(installed_mods)

                # Переносим из временной папки в финальную директорию модов
                try:
                    os.makedirs(self.main_window.mods_dir, exist_ok=True)
                    for entry in os.listdir(self.temp_root or ""):
                        src = os.path.join(self.temp_root, entry)
                        dst = os.path.join(self.main_window.mods_dir, entry)
                        if os.path.isdir(src):
                            try:
                                shutil.copytree(src, dst, dirs_exist_ok=True)
                            except TypeError:
                                # Python <3.8 fallback: merge manually
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
                finally:
                    try:
                        if self.temp_root and os.path.isdir(self.temp_root):
                            shutil.rmtree(self.temp_root, ignore_errors=True)
                    except Exception:
                        pass

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
        finally:
            # Если установка была отменена — не удаляем здесь temp_root, очистку выполнит основной поток
            if not self._cancelled:
                try:
                    if self.temp_root and os.path.isdir(self.temp_root):
                        shutil.rmtree(self.temp_root, ignore_errors=True)
                except Exception:
                    pass

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

    def _get_global_rate_limit_data(self):
        """Получает данные rate limiting из глобального конфига приложения."""
        try:
            config_path = os.path.join(get_app_support_path(), "rate_limit_data.json")
            if os.path.exists(config_path):
                return self.main_window._read_json(config_path)
            return {}
        except:
            return {}

    def _update_global_rate_limit_data(self, mod_key):
        """Обновляет данные rate limiting в глобальном конфиге."""
        try:
            current_ip = self._get_user_ip()
            config_path = os.path.join(get_app_support_path(), "rate_limit_data.json")

            # Читаем существующие данные
            rate_limit_data = self._get_global_rate_limit_data()

            # Добавляем/обновляем запись для текущего IP+мода
            ip_mod_key = f"{current_ip}:{mod_key}"
            now_str = time.strftime('%Y-%m-%d %H:%M:%S')
            rate_limit_data[ip_mod_key] = now_str

            # Сохраняем обновленные данные
            self.main_window._write_json(config_path, rate_limit_data)
        except:
            pass

    def _can_increment_download_by_config(self, mod_key):
        try:
            import datetime
            current_ip = self._get_user_ip()

            # Читаем глобальные данные rate limiting из конфига приложения
            rate_limit_data = self._get_global_rate_limit_data()

            # Проверяем последний инкремент для текущего IP и мода
            ip_mod_key = f"{current_ip}:{mod_key}"
            last_increment_time = rate_limit_data.get(ip_mod_key, "")

            # Если нет записи для этого IP+мода, разрешаем инкремент
            if not last_increment_time:
                return True

            # Проверяем прошло ли 12 часов с последнего инкремента
            last_increment_dt = datetime.datetime.strptime(last_increment_time, '%Y-%m-%d %H:%M:%S')
            time_diff = datetime.datetime.now() - last_increment_dt
            return time_diff.total_seconds() >= 43200  # 12 часов = 43200 секунд
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
                            now_str = time.strftime('%Y-%m-%d %H:%M:%S')
                            config_data["installed_date"] = now_str
                            config_data["last_download_increment"] = now_str
                            self.main_window._write_json(config_path, config_data)

                            # Обновляем глобальные данные rate limiting
                            self._update_global_rate_limit_data(mod_key)
                            return
                    except:
                        continue
        except:
            pass

    def _increment_mod_downloads_on_server(self, mod_key):
        try:
            response = requests.post(f"{CLOUD_FUNCTIONS_BASE_URL}/incrementDownloads", json={"modId": mod_key}, timeout=10)
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
            filename = f"extra_file_{hash(url) % 10000}.zip"

        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)

        try:
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
            if platform.system() == "Darwin":
                filename = "game.ios.xdelta"
            else:
                filename = "data.win.xdelta"

        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)

        try:
            _download_file(session, url, target_path, progress_signal, total_size, downloaded_ref)
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
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
        requests.post(f"{CLOUD_FUNCTIONS_BASE_URL}/incrementLaunches", json={"os": os_key}, timeout=5)
    except requests.RequestException:
        pass

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

def is_valid_game_path(path: str, skip_data_check: bool = False, game_type: str = "deltarune") -> bool:
    if not path or not os.path.isdir(path):
        return False

    if platform.system() == "Darwin":
        app_path = Path(path)
        if not path.endswith(".app"):
            if game_type == "undertale":
                app_path = next((app_path / name for name in ("UNDERTALE.app",) if (app_path / name).is_dir()), None)
            else:
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

    # Windows/Linux validation
    if game_type == "undertale":
        return (os.path.isfile(os.path.join(path, "UNDERTALE.exe")) or
                os.path.isfile(os.path.join(path, "UNDERTALE")))
    else:
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
        'archive_files': '*.zip *.rar *.7z',
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