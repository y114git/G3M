"""Mod type, asset, and resource detection utilities for the patching system."""
import logging
import os
import platform
import re
import zipfile
from typing import List, Optional

from config.constants import DATA_WIN_FILENAME


def find_files_by_extension(directory: str, extensions: List[str],
                            exact_names: Optional[List[str]] = None) -> List[str]:
    found_files = []
    if not os.path.isdir(directory):
        return found_files
    extensions_lower = [ext.lower() if not ext.startswith('.') else ext.lower() for ext in extensions]
    exact_names_lower = [name.lower() for name in exact_names] if exact_names else None
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_lower = file.lower()
            if exact_names_lower and file_lower in exact_names_lower:
                found_files.append(os.path.join(root, file))
            elif any((file_lower.endswith(ext) for ext in extensions_lower)):
                found_files.append(os.path.join(root, file))
    return found_files


def find_g3m_patches(mod_source_dir: str) -> List[str]:
    """Find .zip archives that contain g3mpatch.json inside (g3mpatch format)."""
    results = []
    if not os.path.isdir(mod_source_dir):
        return results
    for root, dirs, files in os.walk(mod_source_dir):
        for f in files:
            if f.lower().endswith('.zip'):
                zip_path = os.path.join(root, f)
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        if 'g3mpatch.json' in zf.namelist():
                            results.append(zip_path)
                except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
                    logging.warning(f'find_g3m_patches: Failed to read zip {zip_path}: {e}')
    return results


def find_ready_data_win_files(mod_source_dir: str, logger=None) -> List[str]:
    ready_files = []
    if not os.path.isdir(mod_source_dir):
        return ready_files
    data_file_names = [DATA_WIN_FILENAME, 'game.ios']
    main_files = find_files_by_extension(mod_source_dir, ['.win', '.ios'], data_file_names)
    for file_path in main_files:
        file_lower = os.path.basename(file_path).lower()
        if file_lower in [name.lower() for name in data_file_names]:
            ready_files.append(file_path)
            if logger:
                logger.debug(f'Found ready data file: {file_path}')
        elif file_lower.endswith('.win') and file_lower != DATA_WIN_FILENAME.lower():
            ready_files.append(file_path)
            if logger:
                logger.debug(f'Found ready .win file: {file_path}')
    if logger:
        logger.info(f'find_ready_data_win_files: found {len(ready_files)} ready data file(s) in {mod_source_dir}')
    return ready_files


def find_data_win(target_dir: str) -> Optional[str]:
    system = platform.system()
    if system == 'Darwin':
        ios_path = os.path.join(target_dir, 'game.ios')
        if os.path.exists(ios_path):
            return ios_path
    else:
        win_path = os.path.join(target_dir, DATA_WIN_FILENAME)
        if os.path.exists(win_path):
            return win_path
    return None


def extract_chapter_id_from_path(path: str) -> Optional[str]:
    match = re.search('chapter[_-]?(\\d+)', path, re.IGNORECASE)
    if match:
        return match.group(1)
    if 'demo' in path.lower():
        return 'deltarunedemo'
    return None


def find_target_files_for_xdelta(target_dir: str, patch_filename: str) -> List[str]:
    target_files = []
    if not os.path.isdir(target_dir):
        return target_files
    excluded_files = {DATA_WIN_FILENAME.lower(), 'game.ios'}
    patch_base_lower = os.path.splitext(patch_filename)[0].lower()
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            file_lower = file.lower()
            if file_lower in excluded_files:
                continue
            if file_lower == patch_base_lower:
                target_files.append(os.path.join(root, file))
    return target_files


def resolve_macos_path(base_path: str, app_name: str) -> str:
    if platform.system() != 'Darwin':
        return base_path
    if base_path.endswith('.app'):
        return os.path.join(base_path, 'Contents', 'Resources')
    app_path = os.path.join(base_path, app_name)
    if os.path.isdir(app_path):
        return os.path.join(app_path, 'Contents', 'Resources')
    return base_path


def has_content(objects_dir: str, subdir: str) -> bool:
    p = os.path.join(objects_dir, subdir)
    return bool(os.path.exists(p) and os.listdir(p))


def get_file_resources(obj_dir: str, subdir: str, exts, exclude=None) -> list:
    p = os.path.join(obj_dir, subdir)
    if not os.path.exists(p):
        return []
    return [os.path.splitext(f)[0] for f in os.listdir(p) if f.endswith(exts) and (not exclude or not f.endswith(exclude))]


def no_res(obj_dir: str) -> list:
    return []


def json_res(subdir: str):
    def _get_json_resources(obj_dir: str) -> list:
        return get_file_resources(obj_dir, subdir, '.json')
    return _get_json_resources
