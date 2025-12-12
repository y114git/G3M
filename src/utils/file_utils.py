import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import logging
import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional
from utils.network_utils import download_file, get_filename_from_url, get_session
from config.constants import MOD_CONFIG_FILENAME, META_JSON_FILENAME, ICON_PNG_FILENAME, LEGACY_MOD_CONFIG_FILENAME, LEGACY_META_JSON_FILENAME


def download_file_with_progress(url: str, target_path: str, progress_callback=None, session=None, cancel_check=None, on_response=None, downloaded_ref=None) -> bool:
    from config.constants import NETWORK_TIMEOUT_HEAD
    if session is None:
        session = get_session()
    total_size = 0
    try:
        head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
        total_size = int(head_response.headers.get('content-length', 0))
    except Exception as e:
        logging.debug(f'download_file_with_progress: Could not get content-length from HEAD request: {e}')
    if downloaded_ref is None:
        downloaded_ref = [0]
    try:
        download_file(session, url, target_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=cancel_check, on_response=on_response)
        if progress_callback:
            progress_callback(100)
        return True
    except RuntimeError as e:
        if str(e) == 'download_cancelled':
            logging.debug('download_file_with_progress: Download cancelled by user')
            return False
        logging.error(f'download_file_with_progress: Download failed: {e}', exc_info=True)
        return False
    except Exception as e:
        logging.error(f'download_file_with_progress: Download failed: {e}', exc_info=True)
        return False


def download_and_extract_archive(url: str, target_dir: str, progress_callback=None, total_size: int = 0, downloaded_ref: list[int] | None = None, session=None, is_game_installation=False, cancel_check=None, on_response=None):
    from utils.archive_utils import extract_archive
    if downloaded_ref is None:
        downloaded_ref = [0]
    os.makedirs(target_dir, exist_ok=True)
    if session is None:
        session = get_session()
    fname = get_filename_from_url(session, url)
    with tempfile.TemporaryDirectory(prefix='deltahub-dl-') as tmp:
        tmp_path = os.path.join(tmp, fname)
        download_file(session, url, tmp_path, progress_callback, total_size, downloaded_ref, cancel_check=cancel_check, on_response=on_response)
        if cancel_check and cancel_check():
            return
        extract_archive(tmp_path, target_dir, fname=fname, is_game_installation=is_game_installation)


def _is_symlink(path: str) -> bool:
    try:
        return os.path.islink(path)
    except OSError:
        return False


def _safe_join(base: str, *paths: str) -> str:
    base_abs = os.path.abspath(base)
    final = os.path.abspath(os.path.join(base_abs, *paths))
    if os.path.commonpath([final, base_abs]) != base_abs:
        raise ValueError('path_traversal')
    return final


def normalize_mod_package(mod_root: str, *, rename_legacy: bool = True, check_executables: bool = True, require_mod_config: bool = False, require_manifest: bool = False) -> Dict[str, Optional[str]]:
    if not os.path.isdir(mod_root):
        raise ValueError('mod_root_not_directory')
    _flatten_single_child_directories(mod_root)
    meta_path = find_deltamod_info_file(mod_root)
    mod_config_path = _find_file_recursive(mod_root, MOD_CONFIG_FILENAME)
    icon_path = _find_file_recursive(mod_root, ICON_PNG_FILENAME)
    if require_manifest and (not meta_path):
        raise FileNotFoundError('manifest_missing')
    if require_mod_config and (not mod_config_path):
        raise FileNotFoundError('mod_config_missing')
    if check_executables:
        _ensure_no_prohibited_files(mod_root)
    return {'meta_path': meta_path, 'mod_config_path': mod_config_path, 'icon_path': icon_path}


def _flatten_single_child_directories(root: str):
    while True:
        try:
            entries = [e for e in os.listdir(root) if e not in ('.', '..') and (not e.startswith('__MACOSX'))]
        except OSError:
            return
        files = [e for e in entries if os.path.isfile(os.path.join(root, e))]
        dirs = [e for e in entries if os.path.isdir(os.path.join(root, e))]
        if files or len(dirs) != 1:
            return
        child = os.path.join(root, dirs[0])
        try:
            for item in os.listdir(child):
                src = os.path.join(child, item)
                dst = os.path.join(root, item)
                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        safe_rmtree(dst)
                    else:
                        safe_remove(dst)
                safe_move(src, dst)
            os.rmdir(child)
        except OSError:
            return


def _find_file_recursive(root: str, filename: str) -> Optional[str]:
    filename_lower = filename.lower()
    for current_root, _, files in os.walk(root):
        for f in files:
            if f.lower() == filename_lower:
                return os.path.join(current_root, f)
    return None


def _ensure_no_prohibited_files(root: str):
    prohibited_exts = {'.exe', '.js', '.ts', '.bat', '.cmd'}
    for current_root, _, files in os.walk(root):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in prohibited_exts:
                raise ValueError(f'prohibited_file:{os.path.join(current_root, f)}')


def sanitize_filename(name: str) -> str:
    return re.sub('[\\\\/*?:"<>|]', '', name).strip()


def atomic_write_json(path: str, data: Dict, indent: int = 2) -> None:
    save_json(path, data, indent=indent)


def save_json(path: str, data: Dict, indent: int = 2) -> None:
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    tmp = os.path.join(dir_path, f'{os.path.basename(path)}.{os.getpid()}.{threading.get_ident()}.tmp') if dir_path else f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except (PermissionError, OSError):
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    except (TypeError, ValueError) as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise ValueError(f'Data is not JSON-serializable: {e}') from e


def load_json(path: str, migrate_config: bool = True) -> Dict:
    try:
        if path.endswith('mod_config.json') and (not os.path.exists(path)) and migrate_config:
            legacy_path = path.replace('mod_config.json', 'config.json')
            if os.path.exists(legacy_path):
                path = legacy_path
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if migrate_config and isinstance(data, dict):
            needs_migration = False
            if path.endswith('mod_config.json') or (path.endswith('config.json') and 'mod_key' in data):
                if 'chapters' in data and 'files' not in data:
                    data['files'] = data['chapters']
                    del data['chapters']
                    needs_migration = True
                if 'is_demo_mod' in data and 'modgame' not in data:
                    if data.get('is_demo_mod', False):
                        data['modgame'] = 'deltarunedemo'
                    else:
                        data['modgame'] = 'deltarune'
                    del data['is_demo_mod']
                    needs_migration = True
                if 'tags' in data:
                    tags = data['tags']
                    if isinstance(tags, list):
                        if 'translation' in tags:
                            data['tags'] = ['textedit' if tag == 'translation' else tag for tag in tags]
                            needs_migration = True
                    elif tags == 'translation':
                        data['tags'] = 'textedit'
                        needs_migration = True
            if needs_migration:
                save_json(path, data, indent=2)
        return data
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        backup_path = f'{path}.invalid.bak'
        try:
            os.replace(path, backup_path)
        except OSError:
            pass
        logging.warning(f'Corrupted JSON file detected, backed up to {backup_path}')
        return {}
    except (PermissionError, OSError) as e:
        logging.warning(f'Error loading JSON from {path}: {e}')
        return {}
    except Exception as e:
        logging.error(f'Error loading JSON from {path}: {e}', exc_info=True)
        return {}


def remove_archive_extension(filename: str) -> str:
    filename_lower = filename.lower()
    if filename_lower.endswith('.tar.gz'):
        return filename[:-7]
    elif filename_lower.endswith('.tar.lzma'):
        return filename[:-9]
    else:
        return os.path.splitext(filename)[0]


def get_chapter_folder_name(chapter_id: int, modgame: Optional[str] = None) -> str:
    if chapter_id == -1:
        return 'demo'
    elif chapter_id == 0:
        if modgame == 'pizzaoven':
            return 'pizzaoven'
        elif modgame == 'pizzatower':
            return 'pizzatower'
        else:
            return 'chapter_0'
    else:
        return f'chapter_{chapter_id}'


def get_unique_mod_dir(mods_dir, mod_name):
    sanitized_name = sanitize_filename(mod_name)
    base_dir = os.path.join(mods_dir, sanitized_name)
    if not os.path.exists(base_dir):
        return sanitized_name
    counter = 1
    while True:
        unique_name = f'{sanitized_name}_{counter}'
        unique_dir = os.path.join(mods_dir, unique_name)
        if not os.path.exists(unique_dir):
            return unique_name
        counter += 1


def ensure_writable(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    os.chmod(os.path.join(root, name), mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        return True
    except (OSError, PermissionError):
        return False


def autodetect_path(game_name: str) -> str | None:
    if game_name == 'UNDERTALE YELLOW' or game_name == 'UndertaleYellow' or game_name == 'undertaleyellow':
        return None
    system = platform.system()
    paths = []
    if system == 'Windows':
        program_files = [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')]
        steam_paths = [os.path.join(p, 'Steam', 'steamapps', 'common', game_name) for p in program_files if p]
        paths.extend(steam_paths)
        drive_letters = 'CDEFGHIJKLMNOPQRSTUVWXYZ'
        for drive in drive_letters:
            for steam_subpath_parts in [['Steam', 'steamapps', 'common'], ['SteamLibrary', 'steamapps', 'common'], ['Program Files', 'Steam', 'steamapps', 'common'], ['Program Files (x86)', 'Steam', 'steamapps', 'common']]:
                path = os.path.join(f'{drive}:', *steam_subpath_parts, game_name)
                paths.append(path)
    elif system == 'Linux':
        home = os.path.expanduser('~')
        base_steam_paths = [f'{home}/.steam/steam/steamapps/common/{game_name}', f'{home}/.local/share/Steam/steamapps/common/{game_name}', f'{home}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/{game_name}']
        paths.extend(base_steam_paths)
        mount_points = ['/mnt', '/media', '/run/media', f'{home}/.steam/steam/steamapps']
        for mount_base in mount_points:
            if os.path.isdir(mount_base):
                try:
                    for item in os.listdir(mount_base):
                        item_path = os.path.join(mount_base, item)
                        if os.path.isdir(item_path):
                            steam_lib_path = os.path.join(item_path, 'SteamLibrary', 'steamapps', 'common', game_name)
                            if os.path.exists(steam_lib_path):
                                paths.append(steam_lib_path)
                            steam_path = os.path.join(item_path, 'steamapps', 'common', game_name)
                            if os.path.exists(steam_path):
                                paths.append(steam_path)
                except (OSError, PermissionError):
                    pass
        additional_paths = [f'/run/media/mmcblk0p1/steamapps/common/{game_name}', f'/run/media/mmcblk1p1/steamapps/common/{game_name}', f'/mnt/steam/steamapps/common/{game_name}', f'/media/steam/steamapps/common/{game_name}']
        paths.extend(additional_paths)
    elif system == 'Darwin':
        home = os.path.expanduser('~')
        base_paths = [f'{home}/Library/Application Support/Steam/steamapps/common/{game_name}', f'/Applications/{game_name}', f'{home}/Steam/steamapps/common/{game_name}']
        if game_name.endswith('demo'):
            for parent in filter(os.path.isdir, base_paths):
                for app_name in [f'{game_name}.app', 'DELTARUNE.app']:
                    full_path = os.path.join(parent, app_name)
                    if os.path.exists(full_path):
                        paths.append(full_path)
        else:
            app_paths = [f'{p}/{game_name}.app' for p in base_paths]
            paths.extend(filter(os.path.isdir, app_paths))
    return next((p for p in paths if os.path.exists(p)), None)


def fix_macos_python_symlink(app_dir: Path) -> None:
    try:
        if platform.system() != 'Darwin':
            return
        p = app_dir / 'Contents' / 'Frameworks' / 'Python'
        if not p.exists() or p.is_symlink():
            return
        if p.is_file() and p.stat().st_size < 512:
            try:
                target_rel = p.read_text(encoding='utf-8').strip()
            except Exception as e:
                logging.debug(f'fix_macos_python_symlink: failed to read symlink target: {e}')
                target_rel = 'Python.framework/Versions/3.12/Python'
            p.unlink(missing_ok=True)
            os.symlink(target_rel, p)
            st = os.lstat(p)
            os.chmod(p, stat.S_IMODE(st.st_mode) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as e:
        logging.debug(f'fix_macos_python_symlink: failed: {e}')


def cleanup_old_updater_files():
    try:
        if not getattr(sys, 'frozen', False):
            return
        system = platform.system()
        current_exe_path = os.path.realpath(sys.executable)
        if system == 'Darwin':
            replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), '..', '..'))
        else:
            replace_target = current_exe_path
        backup_path = f'{replace_target}.old'
        if os.path.exists(backup_path):
            safe_rmtree(backup_path)
    except Exception as e:
        logging.debug(f'cleanup_old_updater_files: failed: {e}')


def version_sort_key(version_string: str):
    try:
        s = (version_string or '').strip()
        m = re.match('^(?P<major>\\d+)(?:\\.(?P<minor>\\d+))?(?:\\.(?P<patch>\\d+))?(?P<suffix>[A-Za-z0-9][A-Za-z0-9._-]*)?$', s)
        if m:
            parts = m.groupdict()
            major = int(parts.get('major') or 0)
            minor = int(parts.get('minor') or 0)
            patch = int(parts.get('patch') or 0)
            suffix = (parts.get('suffix') or '').lower()
            has_suffix = 1 if suffix else 0
            return (major, minor, patch, has_suffix, suffix)
        parts = re.split('[.-]', s)
        nums = []
        suffix_part = ''
        for part in parts:
            if part.isdigit():
                nums.append(int(part))
            else:
                suffix_part = ''.join(parts[parts.index(part):]).lower()
                break
        while len(nums) < 3:
            nums.append(0)
        has_suffix = 1 if suffix_part else 0
        return (nums[0], nums[1], nums[2], has_suffix, suffix_part)
    except Exception as e:
        logging.debug(f'version_sort_key: failed to parse "{version_string}": {e}')
        return (0, 0, 0, 0, '')


def get_file_filter(filter_type: str) -> str:
    FILTER_EXTENSIONS = {'image_files': '*.jpg *.png *.bmp *.gif', 'background_images': '*.jpg *.png *.bmp *.gif', 'xdelta_files': '*.xdelta', 'data_files': '*.win *.ios *.xdelta *.vcdiff *.csx', 'archive_files': '*.zip *.rar *.7z *.tar.gz *.lzma', 'extended_archives': '*.zip *.rar *.7z *.tar.gz *.lzma', 'game_files': '*.exe', 'text_files': '*.txt', 'all_files': '*'}

    def tr(key):
        return key.replace('file_descriptions.', '').replace('_', ' ').title()
    FILTER_DESCRIPTIONS = {'image_files': tr('file_descriptions.image_files'), 'background_images': tr('file_descriptions.background_images'), 'xdelta_files': tr('file_descriptions.xdelta_files'), 'data_files': tr('file_descriptions.data_files'), 'archive_files': tr('file_descriptions.archives'), 'extended_archives': tr('file_descriptions.archives'), 'game_files': tr('file_descriptions.game_files'), 'text_files': tr('file_descriptions.text_files'), 'all_files': tr('file_descriptions.all_files')}
    extensions = FILTER_EXTENSIONS.get(filter_type, '*')
    description = FILTER_DESCRIPTIONS.get(filter_type, filter_type)
    all_files_desc = FILTER_DESCRIPTIONS.get('all_files', 'All files')
    return f'{description} ({extensions});;{all_files_desc} (*)'


def find_deltamod_info_file(directory: str) -> str | None:
    info_path = os.path.join(directory, META_JSON_FILENAME)
    if os.path.exists(info_path):
        return info_path
    legacy_info_path = os.path.join(directory, LEGACY_META_JSON_FILENAME)
    if os.path.exists(legacy_info_path):
        return legacy_info_path
    return None


def has_deltamod_info_file(file_list: list[str] | set[str]) -> bool:
    file_set = set(file_list)
    return META_JSON_FILENAME in file_set or LEGACY_META_JSON_FILENAME in file_set


def check_filename_is_deltamod_info(filename: str) -> bool:
    filename_lower = filename.lower()
    return filename == META_JSON_FILENAME or filename_lower == META_JSON_FILENAME.lower() or filename == LEGACY_META_JSON_FILENAME or (filename_lower == LEGACY_META_JSON_FILENAME.lower())


def safe_copy(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    try:
        if os.path.abspath(src) == os.path.abspath(dst):
            logging.debug(f'safe_copy: Skipping copy: source and destination are the same file: {src}')
            return True
    except Exception:
        pass
    dst_dir = os.path.dirname(dst)
    if dst_dir and (not os.path.exists(dst_dir)):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f'safe_copy: Failed to create destination directory {dst_dir}: {e}')
            return False
    for attempt in range(max_retries):
        try:
            shutil.copy2(src, dst)
            return True
        except PermissionError as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_copy: Attempt {attempt + 1}/{max_retries} failed for {src} -> {dst}: {e}, retrying...')
                time.sleep(delay * (attempt + 1))
            else:
                logging.error(f'safe_copy: Failed to copy {src} to {dst} after {max_retries} attempts: {e}')
                return False
        except OSError as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_copy: Attempt {attempt + 1}/{max_retries} failed for {src} -> {dst}: {e}, retrying...')
                time.sleep(delay * (attempt + 1))
            else:
                logging.error(f'safe_copy: Failed to copy {src} to {dst} after {max_retries} attempts: {e}')
                return False
    return False


def safe_remove(path: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(path):
        return True
    for attempt in range(max_retries):
        try:
            if platform.system() == 'Windows':
                try:
                    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
            os.remove(path)
            return True
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_remove: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                time.sleep(delay)
            else:
                logging.warning(f'safe_remove: Failed to remove {path} after {max_retries} attempts: {e}')
                return False
    return False


def safe_move(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(src):
        return False
    dst_dir = os.path.dirname(dst)
    if dst_dir and (not os.path.exists(dst_dir)):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f'safe_move: Failed to create destination directory {dst_dir}: {e}')
            return False
    for attempt in range(max_retries):
        try:
            if platform.system() == 'Windows' and os.path.isfile(src):
                try:
                    os.chmod(src, stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
            shutil.move(src, dst)
            return True
        except (OSError, PermissionError, shutil.Error) as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_move: Attempt {attempt + 1}/{max_retries} failed for {src} -> {dst}: {e}, retrying...')
                time.sleep(delay)
            else:
                logging.warning(f'safe_move: Failed to move {src} to {dst} after {max_retries} attempts: {e}')
                return False
    return False


def safe_rmtree(path: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(path):
        return True
    if not os.path.isdir(path):
        return safe_remove(path, max_retries, delay)

    def handle_rmtree_error(func, path, exc_info):
        if platform.system() == 'Windows':
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            except OSError:
                pass
            try:
                func(path)
            except OSError:
                pass
    for attempt in range(max_retries):
        try:
            shutil.rmtree(path, onexc=handle_rmtree_error)
            return True
        except (OSError, PermissionError, shutil.Error) as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_rmtree: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                time.sleep(delay * (attempt + 1))
            else:
                logging.warning(f'safe_rmtree: Failed to remove {path} after {max_retries} attempts: {e}')
                if platform.system() != 'Windows':
                    try:
                        temp_dir = tempfile.gettempdir()
                        renamed_path = os.path.join(temp_dir, f'deltahub_temp_cleanup_{int(time.time())}')
                        if not os.path.exists(renamed_path):
                            os.rename(path, renamed_path)
                            logging.debug(f'safe_rmtree: Renamed {path} to {renamed_path} for later cleanup')

                            def delayed_cleanup():
                                time.sleep(5)
                                try:
                                    shutil.rmtree(renamed_path, ignore_errors=True)
                                except Exception:
                                    pass
                            threading.Thread(target=delayed_cleanup, daemon=True).start()
                            return True
                    except Exception:
                        pass
                return False
    return False


def migrate_mod_config(mod_dir: str) -> bool:
    old_config_path = os.path.join(mod_dir, LEGACY_MOD_CONFIG_FILENAME)
    config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
    if os.path.exists(old_config_path) and (not os.path.exists(config_path)):
        safe_move(old_config_path, config_path)
        logging.info(f'Migrated mod config.json to mod_config.json in {os.path.basename(mod_dir)}')
    return True
