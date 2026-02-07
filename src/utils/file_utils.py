"""File operation utilities."""
import os
import platform
import re
import shutil
import stat
import tempfile
import logging
import json
import threading
import time
from typing import Dict, Optional, Callable, TypeVar
from utils.network_utils import download_file, get_filename_from_url, get_session
from config.constants import MOD_CONFIG_FILENAME, META_JSON_FILENAME, ICON_PNG_FILENAME, LEGACY_MOD_CONFIG_FILENAME, LEGACY_META_JSON_FILENAME
T = TypeVar('T')
_IS_WIN = platform.system() == 'Windows'


def _retry_operation(operation: Callable[[], T], max_retries: int = 5, delay: float = 0.1, op_name: str = 'operation', path: str = '') -> T:
    """Retry a file operation with exponential backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return operation()
        except (OSError, PermissionError, shutil.Error) as e:
            last_error = e
            if attempt < max_retries - 1:
                logging.debug(f'{op_name}: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                time.sleep(delay * (attempt + 1))
            else:
                logging.warning(f'{op_name}: Failed for {path} after {max_retries} attempts: {e}')
    raise last_error if last_error else RuntimeError(f'{op_name} failed')


def _fix_windows_permissions(path: str) -> None:
    if _IS_WIN:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass


def download_file_with_progress(url: str, target_path: str, progress_callback=None, session=None, cancel_check=None, on_response=None, downloaded_ref=None) -> bool:
    from config.constants import NETWORK_TIMEOUT_HEAD
    session = session or get_session()
    total_size = 0
    try:
        total_size = int(session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD).headers.get('content-length', 0))
    except Exception as e:
        logging.debug(f'download_file_with_progress: Could not get content-length: {e}')
    downloaded_ref = downloaded_ref or [0]
    try:
        download_file(session, url, target_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=cancel_check, on_response=on_response)
        if progress_callback:
            progress_callback(100)
        return True
    except RuntimeError as e:
        if str(e) == 'download_cancelled':
            logging.debug('download_file_with_progress: Download cancelled')
            return False
        logging.error(f'download_file_with_progress: Download failed: {e}', exc_info=True)
        return False
    except Exception as e:
        logging.error(f'download_file_with_progress: Download failed: {e}', exc_info=True)
        return False


def download_and_extract_archive(url: str, target_dir: str, progress_callback=None, total_size: int = 0, downloaded_ref: list[int] | None = None, session=None, is_game_installation=False, cancel_check=None, on_response=None):
    from utils.archive_utils import extract_archive
    downloaded_ref, session = downloaded_ref or [0], session or get_session()
    os.makedirs(target_dir, exist_ok=True)
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
    meta_path, mod_config_path, icon_path = find_deltamod_info_file(mod_root), _find_file_recursive(mod_root, MOD_CONFIG_FILENAME), _find_file_recursive(mod_root, ICON_PNG_FILENAME)
    if require_manifest and not meta_path:
        raise FileNotFoundError('manifest_missing')
    if require_mod_config and not mod_config_path:
        raise FileNotFoundError('mod_config_missing')
    if check_executables:
        _ensure_no_prohibited_files(mod_root)
    return {'meta_path': meta_path, 'mod_config_path': mod_config_path, 'icon_path': icon_path}


def _flatten_single_child_directories(root: str):
    while True:
        try:
            entries = [e for e in os.listdir(root) if e not in ('.', '..') and not e.startswith('__MACOSX')]
        except OSError:
            return
        files, dirs = [e for e in entries if os.path.isfile(os.path.join(root, e))], [e for e in entries if os.path.isdir(os.path.join(root, e))]
        if files or len(dirs) != 1:
            return
        child = os.path.join(root, dirs[0])
        try:
            for item in os.listdir(child):
                src, dst = os.path.join(child, item), os.path.join(root, item)
                if os.path.exists(dst):
                    safe_rmtree(dst) if os.path.isdir(dst) else safe_remove(dst)
                safe_move(src, dst)
            os.rmdir(child)
        except OSError:
            return


def _find_file_recursive(root: str, filename: str) -> Optional[str]:
    fn_lower = filename.lower()
    for r, _, files in os.walk(root):
        for f in files:
            if f.lower() == fn_lower:
                return os.path.join(r, f)
    return None


def _ensure_no_prohibited_files(root: str):
    prohibited = {'.exe', '.js', '.ts', '.bat', '.cmd'}
    for r, _, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() in prohibited:
                raise ValueError(f'prohibited_file:{os.path.join(r, f)}')


def sanitize_filename(name: str) -> str:
    return re.sub('[\\\\/*?:"<>|]', '', name).strip()


def _cleanup_tmp(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def save_json(path: str, data: Dict, indent: int = 2, max_retries: int = 5, delay: float = 0.1) -> None:
    """Save JSON data to file with retry logic."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    data_to_save = data.copy() if isinstance(data, dict) else data
    if isinstance(data_to_save, dict) and (path.endswith('mod_config.json') or (path.endswith('config.json') and ('mod_key' in data_to_save or 'key' in data_to_save))):
        if 'mod_key' in data_to_save:
            if 'key' not in data_to_save:
                data_to_save['key'] = data_to_save['mod_key']
            del data_to_save['mod_key']
        if 'modgame' in data_to_save and 'game' in data_to_save:
            del data_to_save['modgame']
    tmp = os.path.join(dir_path, f'{os.path.basename(path)}.{os.getpid()}.{threading.get_ident()}.tmp') if dir_path else f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    last_error = None
    for attempt in range(max_retries):
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=indent, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                _fix_windows_permissions(path) if os.path.exists(path) else None
                os.replace(tmp, path)
                return
            except (PermissionError, OSError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    logging.debug(f'save_json: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                    time.sleep(delay * (attempt + 1))
                _cleanup_tmp(tmp)
                if attempt >= max_retries - 1:
                    raise
        except (PermissionError, OSError) as e:
            last_error = e
            if attempt < max_retries - 1:
                logging.debug(f'save_json: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                time.sleep(delay * (attempt + 1))
            _cleanup_tmp(tmp)
            if attempt >= max_retries - 1:
                raise
        except (TypeError, ValueError) as e:
            _cleanup_tmp(tmp)
            raise ValueError(f'Data is not JSON-serializable: {e}') from e
    if last_error:
        raise last_error


def load_json(path: str, migrate_config: bool = True) -> Dict:
    """Load JSON file with optional config migration."""
    try:
        if path.endswith('mod_config.json') and not os.path.exists(path) and migrate_config:
            legacy_path = path.replace('mod_config.json', 'config.json')
            if os.path.exists(legacy_path):
                path = legacy_path
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if migrate_config and isinstance(data, dict):
            needs_migration = False
            if path.endswith('mod_config.json') or (path.endswith('config.json') and ('mod_key' in data or 'key' in data)):
                if 'mod_key' in data:
                    if 'key' not in data:
                        data['key'] = data.pop('mod_key')
                        needs_migration = True
                    else:
                        del data['mod_key']
                        needs_migration = True
                if 'modgame' in data:
                    if 'game' not in data:
                        data['game'] = data.pop('modgame')
                        needs_migration = True
                    else:
                        del data['modgame']
                        needs_migration = True
                if 'chapters' in data and 'files' not in data:
                    data['files'] = data['chapters']
                    del data['chapters']
                    needs_migration = True
                if 'is_demo_mod' in data and 'game' not in data:
                    data['game'] = 'deltarunedemo' if data.get('is_demo_mod', False) else 'deltarune'
                    del data['is_demo_mod']
                    needs_migration = True
                if 'tags' in data:
                    tags = data['tags']
                    if isinstance(tags, list) and 'translation' in tags:
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
    fl = filename.lower()
    return filename[:-7] if fl.endswith('.tar.gz') else (filename[:-9] if fl.endswith('.tar.lzma') else os.path.splitext(filename)[0])


def get_chapter_folder_name(chapter_id: int, game: Optional[str] = None, modgame: Optional[str] = None) -> str:
    from config.constants import SLOT_ID_PIZZA_TOWER, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_DEMO, SLOT_ID_SUGARY_SPIRE
    game_value = game or modgame
    if chapter_id == -1 or chapter_id == SLOT_ID_DEMO:
        return 'demo'
    if chapter_id == SLOT_ID_PIZZA_TOWER:
        return 'pizzatower' if game_value == 'pizzatower' else f'chapter_{chapter_id}'
    if chapter_id in (SLOT_ID_UNDERTALE, 0, SLOT_ID_UNDERTALE_YELLOW):
        return 'chapter_0'
    if chapter_id == SLOT_ID_SUGARY_SPIRE:
        return 'sugaryspire'
    return f'chapter_{chapter_id}'


def get_unique_mod_dir(mods_dir, mod_name):
    sanitized = sanitize_filename(mod_name)
    if not os.path.exists(os.path.join(mods_dir, sanitized)):
        return sanitized
    counter = 1
    while os.path.exists(os.path.join(mods_dir, f'{sanitized}_{counter}')):
        counter += 1
    return f'{sanitized}_{counter}'


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
    for name in (META_JSON_FILENAME, LEGACY_META_JSON_FILENAME):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return None


def has_deltamod_info_file(file_list: list[str] | set[str]) -> bool:
    file_set = set(file_list)
    return META_JSON_FILENAME in file_set or LEGACY_META_JSON_FILENAME in file_set


def check_filename_is_deltamod_info(filename: str) -> bool:
    return filename.lower() in {META_JSON_FILENAME.lower(), LEGACY_META_JSON_FILENAME.lower()}


def _ensure_dst_dir(dst: str, op_name: str) -> bool:
    dst_dir = os.path.dirname(dst)
    if dst_dir and not os.path.exists(dst_dir):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f'{op_name}: Failed to create dest dir {dst_dir}: {e}')
            return False
    return True


def safe_copy(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    try:
        if os.path.abspath(src) == os.path.abspath(dst):
            return True
    except Exception:
        pass
    if not _ensure_dst_dir(dst, 'safe_copy'):
        return False
    try:
        _retry_operation(lambda: shutil.copy2(src, dst), max_retries, delay, 'safe_copy', f'{src} -> {dst}')
        return True
    except Exception:
        return False


def safe_remove(path: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(path):
        return True

    def do_remove():
        _fix_windows_permissions(path)
        os.remove(path)
    try:
        _retry_operation(do_remove, max_retries, delay, 'safe_remove', path)
        return True
    except Exception:
        return False


def safe_move(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(src):
        return False
    if not _ensure_dst_dir(dst, 'safe_move'):
        return False

    def do_move():
        if os.path.isfile(src):
            _fix_windows_permissions(src)
        shutil.move(src, dst)
    try:
        _retry_operation(do_move, max_retries, delay, 'safe_move', f'{src} -> {dst}')
        return True
    except Exception:
        return False


def _rmtree_error_handler(func, path, exc_info):
    if platform.system() == 'Windows':
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            func(path)
        except OSError:
            pass


def safe_rmtree(path: str, max_retries: int = 3, delay: float = 0.5) -> bool:
    if not os.path.exists(path):
        return True
    if not os.path.isdir(path):
        return safe_remove(path, max_retries, delay)
    try:
        _retry_operation(lambda: shutil.rmtree(path, onexc=_rmtree_error_handler), max_retries, delay, 'safe_rmtree', path)
        return True
    except Exception:
        if not _IS_WIN:
            try:
                renamed = os.path.join(tempfile.gettempdir(), f'deltahub_cleanup_{int(time.time())}')
                if not os.path.exists(renamed):
                    os.rename(path, renamed)
                    threading.Thread(target=lambda: (time.sleep(5), shutil.rmtree(renamed, ignore_errors=True)), daemon=True).start()
                    return True
            except Exception:
                pass
        return False


def migrate_mod_config(mod_dir: str) -> bool:
    old_config_path = os.path.join(mod_dir, LEGACY_MOD_CONFIG_FILENAME)
    config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
    if os.path.exists(old_config_path) and (not os.path.exists(config_path)):
        safe_move(old_config_path, config_path)
        logging.info(f'Migrated mod config.json to mod_config.json in {os.path.basename(mod_dir)}')
    return True
