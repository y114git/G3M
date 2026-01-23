"""File operation utilities.

This module provides utilities for file operations including downloading,
extracting archives, JSON handling, and safe file operations with retries.
"""
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
from typing import Dict, Optional, Callable, TypeVar
from utils.network_utils import download_file, get_filename_from_url, get_session
from config.constants import MOD_CONFIG_FILENAME, META_JSON_FILENAME, ICON_PNG_FILENAME, LEGACY_MOD_CONFIG_FILENAME, LEGACY_META_JSON_FILENAME
T = TypeVar('T')


def _retry_operation(operation: Callable[[], T], max_retries: int = 5, delay: float = 0.1, op_name: str = 'operation', path: str = '') -> T:
    """Retry a file operation with exponential backoff.

    Args:
        operation: Operation to retry.
        max_retries: Maximum retry attempts.
        delay: Initial delay between retries.
        op_name: Operation name for logging.
        path: File path for logging.

    Returns:
        T: Operation result.

    Raises:
        Last exception if all retries fail.
    """
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
    """Fix Windows file permissions for write access.

    Args:
        path: Path to fix permissions for.
    """
    if platform.system() == 'Windows':
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass


def download_file_with_progress(url: str, target_path: str, progress_callback=None, session=None, cancel_check=None, on_response=None, downloaded_ref=None) -> bool:
    """Download file with progress tracking.

    Args:
        url: URL to download from.
        target_path: Path to save file.
        progress_callback: Callback for progress updates.
        session: Requests session to use.
        cancel_check: Function to check if cancelled.
        on_response: Callback for response handling.
        downloaded_ref: Reference to track downloaded bytes.

    Returns:
        bool: True if download successful.
    """
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
    """Download and extract an archive file.

    Args:
        url: URL to download from.
        target_dir: Directory to extract to.
        progress_callback: Callback for progress updates.
        total_size: Total file size in bytes.
        downloaded_ref: Reference to track downloaded bytes.
        session: Requests session to use.
        is_game_installation: Whether this is a game installation.
        cancel_check: Function to check if cancelled.
        on_response: Callback for response handling.
    """
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
    """Check if a path is a symbolic link.

    Args:
        path: Path to check.

    Returns:
        bool: True if path is a symlink.
    """
    try:
        return os.path.islink(path)
    except OSError:
        return False


def _safe_join(base: str, *paths: str) -> str:
    """Safely join paths with directory traversal protection.

    Args:
        base: Base directory path.
        *paths: Path components to join.

    Returns:
        str: Joined absolute path.

    Raises:
        ValueError: If path traversal is detected.
    """
    base_abs = os.path.abspath(base)
    final = os.path.abspath(os.path.join(base_abs, *paths))
    if os.path.commonpath([final, base_abs]) != base_abs:
        raise ValueError('path_traversal')
    return final


def normalize_mod_package(mod_root: str, *, rename_legacy: bool = True, check_executables: bool = True, require_mod_config: bool = False, require_manifest: bool = False) -> Dict[str, Optional[str]]:
    """Normalize a mod package structure and locate key files.

    Args:
        mod_root: Root directory of the mod package.
        rename_legacy: Whether to rename legacy files.
        check_executables: Whether to check for prohibited executables.
        require_mod_config: Whether mod_config.json is required.
        require_manifest: Whether manifest file is required.

    Returns:
        Dict[str, Optional[str]]: Paths to meta, mod_config, and icon files.

    Raises:
        ValueError: If mod_root is not a directory.
        FileNotFoundError: If required files are missing.
    """
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
    """Flatten directory structure by moving up single child directories.

    Args:
        root: Root directory to flatten.
    """
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
    """Recursively search for a file by name (case-insensitive).

    Args:
        root: Root directory to search.
        filename: Filename to find.

    Returns:
        Optional[str]: Path to file if found, None otherwise.
    """
    filename_lower = filename.lower()
    for current_root, _, files in os.walk(root):
        for f in files:
            if f.lower() == filename_lower:
                return os.path.join(current_root, f)
    return None


def _ensure_no_prohibited_files(root: str):
    """Check for prohibited file types in directory tree.

    Args:
        root: Root directory to check.

    Raises:
        ValueError: If prohibited files are found.
    """
    prohibited_exts = {'.exe', '.js', '.ts', '.bat', '.cmd'}
    for current_root, _, files in os.walk(root):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in prohibited_exts:
                raise ValueError(f'prohibited_file:{os.path.join(current_root, f)}')


def sanitize_filename(name: str) -> str:
    """Remove invalid characters from filename.

    Args:
        name: Filename to sanitize.

    Returns:
        str: Sanitized filename.
    """
    return re.sub('[\\\\/*?:"<>|]', '', name).strip()


def _cleanup_tmp(path: str) -> None:
    """Clean up temporary file if it exists.

    Args:
        path: Path to temporary file.
    """
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def atomic_write_json(path: str, data: Dict, indent: int = 2) -> None:
    """Atomically write JSON data to file.

    Args:
        path: File path.
        data: Data to write.
        indent: JSON indentation level.
    """
    save_json(path, data, indent=indent)


def save_json(path: str, data: Dict, indent: int = 2, max_retries: int = 5, delay: float = 0.1) -> None:
    """Save JSON data to file with retry logic.

    Args:
        path: File path.
        data: Data to save.
        indent: JSON indentation level.
        max_retries: Maximum retry attempts.
        delay: Delay between retries.
    """
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
                if platform.system() == 'Windows' and os.path.exists(path):
                    try:
                        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
                os.replace(tmp, path)
                return
            except (PermissionError, OSError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    logging.debug(f'save_json: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                    time.sleep(delay * (attempt + 1))
                    _cleanup_tmp(tmp)
                else:
                    _cleanup_tmp(tmp)
                    raise
        except (PermissionError, OSError) as e:
            last_error = e
            if attempt < max_retries - 1:
                logging.debug(f'save_json: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                time.sleep(delay * (attempt + 1))
                _cleanup_tmp(tmp)
            else:
                _cleanup_tmp(tmp)
                raise
        except (TypeError, ValueError) as e:
            _cleanup_tmp(tmp)
            raise ValueError(f'Data is not JSON-serializable: {e}') from e
    if last_error:
        raise last_error


def load_json(path: str, migrate_config: bool = True) -> Dict:
    """Load JSON file with optional config migration.

    This function loads a JSON file from disk and optionally performs
    migration of legacy configuration formats to the current format.
    It handles missing files gracefully and supports automatic config updates.

    Args:
        path: Path to the JSON file to load.
        migrate_config: Whether to perform config migration (default: True).

    Migration features:
    - Legacy config.json to mod_config.json migration
    - Field name updates (mod_key -> key, modgame -> game)
    - Structure changes (chapters -> files)
    - Game detection from demo mod flags
    - Tag normalization (translation -> textedit)

    Returns:
        Dict: Loaded JSON data, empty dict if file doesn't exist.

    Note:
        When migration is enabled, the file will be automatically
        updated with the new format if changes are needed.
    """
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
                    if data.get('is_demo_mod', False):
                        data['game'] = 'deltarunedemo'
                    else:
                        data['game'] = 'deltarune'
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


def get_chapter_folder_name(chapter_id: int, game: Optional[str] = None, modgame: Optional[str] = None) -> str:
    from config.constants import SLOT_ID_PIZZA_TOWER, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_DEMO, SLOT_ID_SUGARY_SPIRE
    game_value = game or modgame
    if chapter_id == -1 or chapter_id == SLOT_ID_DEMO:
        return 'demo'
    elif chapter_id == SLOT_ID_PIZZA_TOWER:
        if game_value == 'pizzatower':
            return 'pizzatower'
        return f'chapter_{chapter_id}'
    elif chapter_id == SLOT_ID_UNDERTALE or chapter_id == 0:
        return 'chapter_0'
    elif chapter_id == SLOT_ID_UNDERTALE_YELLOW:
        return 'chapter_0'
    elif chapter_id == SLOT_ID_SUGARY_SPIRE:
        return 'sugaryspire'
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


def is_path_in_steam_common(game_path: str, game_name: str) -> bool:
    """Check if a game path is within a Steam common directory.

    This function determines whether a given game path is located in
    a Steam installation's common games directory. It checks across
    multiple platforms and Steam installation locations.

    Args:
        game_path: Path to the game directory to check.
        game_name: Name of the game to match against.

    Checks include:
    - Path analysis for steamapps/common structure
    - Windows Program Files Steam installations
    - Linux Steam home directory locations
    - macOS Steam application support directories
    - Case-insensitive path matching

    Returns:
        bool: True if the path is within a Steam common directory,
              False otherwise.
    """
    if not game_path or not os.path.isdir(game_path):
        return False
    try:
        game_path_abs = os.path.abspath(game_path)
        game_path_normalized = os.path.normpath(game_path_abs).lower()
        game_name_lower = game_name.lower()
    except (OSError, ValueError):
        return False
    path_parts = game_path_normalized.replace('\\', '/').split('/')
    try:
        for i, part in enumerate(path_parts):
            if part == 'steamapps' and i + 1 < len(path_parts) and (path_parts[i + 1] == 'common'):
                if i + 2 < len(path_parts) and path_parts[i + 2] == game_name_lower:
                    return True
                if i + 2 < len(path_parts):
                    return True
    except (IndexError, AttributeError):
        pass
    system = platform.system()
    if system == 'Windows':
        program_files = [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')]
        for pf in program_files:
            if pf:
                steam_common = os.path.normpath(os.path.join(pf, 'Steam', 'steamapps', 'common', game_name)).lower()
                if game_path_normalized == steam_common or game_path_normalized.startswith(steam_common.replace('\\', '/') + '/'):
                    return True
    elif system == 'Linux':
        home = os.path.expanduser('~')
        base_steam_paths = [os.path.join(home, '.steam', 'steam', 'steamapps', 'common', game_name), os.path.join(home, '.local', 'share', 'Steam', 'steamapps', 'common', game_name), os.path.join(home, '.var', 'app', 'com.valvesoftware.Steam', 'data', 'Steam', 'steamapps', 'common', game_name)]
        for steam_path in base_steam_paths:
            try:
                if os.path.exists(steam_path):
                    steam_path_normalized = os.path.normpath(os.path.abspath(steam_path)).lower().replace('\\', '/')
                    if game_path_normalized == steam_path_normalized or game_path_normalized.startswith(steam_path_normalized + '/'):
                        return True
            except (OSError, ValueError):
                continue
    elif system == 'Darwin':
        home = os.path.expanduser('~')
        base_paths = [os.path.join(home, 'Library', 'Application Support', 'Steam', 'steamapps', 'common', game_name), os.path.join(home, 'Steam', 'steamapps', 'common', game_name)]
        for steam_path in base_paths:
            try:
                if os.path.exists(steam_path):
                    steam_path_normalized = os.path.normpath(os.path.abspath(steam_path)).lower().replace('\\', '/')
                    if game_path_normalized == steam_path_normalized or game_path_normalized.startswith(steam_path_normalized + '/'):
                        return True
            except (OSError, ValueError):
                continue
    return False


def autodetect_path(game_name: str) -> str | None:
    """Autodetect game installation path across multiple platforms.

    This function searches for game installations in common locations
    including Steam directories, program files, and various mount points.
    It supports Windows, Linux, and macOS with platform-specific paths.

    Args:
        game_name: Name of the game to search for.

    Supported games:
    - Pizza Tower (with multiple name variations)
    - Other Steam games

    Search locations include:
    - Steam installation directories
    - Program Files folders (Windows)
    - Steam library folders
    - Mount points and media directories (Linux)
    - Application Support directories (macOS)

    Returns:
        str | None: Path to game directory if found, None otherwise.

    Note:
        Some games like Undertale Yellow and Sugary Spire return None
        as they require manual path specification.
    """
    if game_name == 'UNDERTALE YELLOW' or game_name == 'UndertaleYellow' or game_name == 'undertaleyellow':
        return None
    if game_name == 'SUGARY SPIRE' or game_name == 'SugarySpire' or game_name == 'sugaryspire':
        return None
    system = platform.system()
    paths = []
    if system == 'Windows':
        program_files = [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')]
        steam_paths = [os.path.join(p, 'Steam', 'steamapps', 'common', game_name) for p in program_files if p]
        paths.extend(steam_paths)
        if game_name == 'Pizza Tower':
            pizza_tower_variations = ['Pizza Tower', 'PizzaTower', 'pizzatower']
            for variation in pizza_tower_variations:
                for p in program_files:
                    if p:
                        paths.append(os.path.join(p, 'Steam', 'steamapps', 'common', variation))
        drive_letters = 'CDEFGHIJKLMNOPQRSTUVWXYZ'
        for drive in drive_letters:
            for steam_subpath_parts in [['Steam', 'steamapps', 'common'], ['SteamLibrary', 'steamapps', 'common'], ['Program Files', 'Steam', 'steamapps', 'common'], ['Program Files (x86)', 'Steam', 'steamapps', 'common']]:
                path = os.path.join(f'{drive}:', *steam_subpath_parts, game_name)
                paths.append(path)
                if game_name == 'Pizza Tower':
                    for variation in ['Pizza Tower', 'PizzaTower', 'pizzatower']:
                        paths.append(os.path.join(f'{drive}:', *steam_subpath_parts, variation))
    elif system == 'Linux':
        home = os.path.expanduser('~')
        base_steam_paths = [f'{home}/.steam/steam/steamapps/common/{game_name}', f'{home}/.local/share/Steam/steamapps/common/{game_name}', f'{home}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/{game_name}']
        paths.extend(base_steam_paths)
        if game_name == 'Pizza Tower':
            for variation in ['Pizza Tower', 'PizzaTower', 'pizzatower']:
                paths.extend([f'{home}/.steam/steam/steamapps/common/{variation}', f'{home}/.local/share/Steam/steamapps/common/{variation}', f'{home}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/{variation}'])
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
        if game_name == 'Pizza Tower':
            for variation in ['Pizza Tower', 'PizzaTower', 'pizzatower']:
                base_paths.extend([f'{home}/Library/Application Support/Steam/steamapps/common/{variation}', f'/Applications/{variation}', f'{home}/Steam/steamapps/common/{variation}'])
        if game_name.endswith('demo'):
            for parent in filter(os.path.isdir, base_paths):
                for app_name in [f'{game_name}.app', 'DELTARUNE.app']:
                    full_path = os.path.join(parent, app_name)
                    if os.path.exists(full_path):
                        paths.append(full_path)
        else:
            app_paths = [f'{p}/{game_name}.app' for p in base_paths]
            paths.extend(filter(os.path.isdir, app_paths))
            if game_name == 'Pizza Tower':
                for variation in ['Pizza Tower', 'PizzaTower', 'pizzatower']:
                    variation_paths = [f'{p}/{variation}.app' for p in base_paths]
                    paths.extend(filter(os.path.isdir, variation_paths))
    return next((p for p in paths if os.path.exists(p)), None)


def fix_macos_python_symlink(app_dir: Path) -> None:
    """Fix Python symlink in macOS app bundles.

    This function fixes the Python symlink in macOS app bundles that
    may be created incorrectly during packaging. It converts a text
    file containing the symlink target into a proper symbolic link.

    Args:
        app_dir: Path to the app bundle directory.

    Operations:
    - Checks if running on macOS
    - Validates Python framework path
    - Reads symlink target from text file
    - Creates proper symbolic link
    - Sets executable permissions

    Returns:
        None, but fixes the Python symlink if needed.
    """
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
    """Generate a sort key for version strings.

    This function parses version strings and creates a tuple that can
    be used for proper version sorting. It handles semantic versioning
    formats and various suffixes.

    Args:
        version_string: Version string to parse (e.g., "1.2.3", "2.0.1-beta").

    Supported formats:
    - Semantic versioning (major.minor.patch)
    - Version suffixes (alpha, beta, rc, etc.)
    - Simple numeric versions
    - Mixed alphanumeric versions

    Returns:
        tuple: Sort key in format (major, minor, patch, has_suffix, suffix)
               for proper version ordering.

    Note:
        Invalid version strings return (0, 0, 0, 0, '') as fallback.
    """
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
            return True
    except Exception:
        pass
    dst_dir = os.path.dirname(dst)
    if dst_dir and (not os.path.exists(dst_dir)):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f'safe_copy: Failed to create dest dir {dst_dir}: {e}')
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
    """Safely move a file or directory with retry mechanism.

    This function moves files or directories with proper error handling,
    permission fixes, and retry logic for common filesystem issues.

    Args:
        src: Source path to move from.
        dst: Destination path to move to.
        max_retries: Maximum number of retry attempts (default: 5).
        delay: Delay between retries in seconds (default: 0.1).

    Features:
    - Automatic destination directory creation
    - Windows permission fixes for files
    - Retry mechanism for transient errors
    - Comprehensive error handling

    Returns:
        bool: True if move was successful, False otherwise.
    """
    if not os.path.exists(src):
        return False
    dst_dir = os.path.dirname(dst)
    if dst_dir and (not os.path.exists(dst_dir)):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f'safe_move: Failed to create dest dir {dst_dir}: {e}')
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
    """Safely remove a directory tree with retry mechanism.

    This function removes directory trees with proper error handling,
    permission fixes, and retry logic. It includes special handling
    for Windows filesystem issues.

    Args:
        path: Directory path to remove.
        max_retries: Maximum number of retry attempts (default: 3).
        delay: Delay between retries in seconds (default: 0.5).

    Features:
    - Retry mechanism with custom error handler
    - Windows-specific permission fixes
    - Fallback rename-and-delete strategy
    - Threaded cleanup for stubborn directories

    Returns:
        bool: True if removal was successful, False otherwise.
    """
    if not os.path.exists(path):
        return True
    if not os.path.isdir(path):
        return safe_remove(path, max_retries, delay)
    try:
        _retry_operation(lambda: shutil.rmtree(path, onexc=_rmtree_error_handler), max_retries, delay, 'safe_rmtree', path)
        return True
    except Exception:
        if platform.system() != 'Windows':
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
