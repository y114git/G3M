"""Mod type, asset, and resource detection utilities for the patching system."""
import os
import platform
import re
from typing import Dict, List, Optional

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


def find_data_patches(mod_source_dir: str) -> List[str]:
    return find_files_by_extension(mod_source_dir, ['.xdelta', '.vcdiff'])


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
    info_datawinmod_dir = None
    if mod_source_dir:
        mod_root = os.path.dirname(mod_source_dir) if os.path.basename(mod_source_dir).startswith('chapter_') else mod_source_dir
        info_datawinmod_path = os.path.join(mod_root, 'INFO', 'datawinmod')
        if os.path.isdir(info_datawinmod_path):
            info_datawinmod_dir = info_datawinmod_path
            if logger:
                logger.debug(f'Found INFO/datawinmod directory: {info_datawinmod_path}')
    if info_datawinmod_dir:
        chapter_name = os.path.basename(mod_source_dir)
        datawinmod_chapter_dir = os.path.join(info_datawinmod_dir, chapter_name)
        if os.path.isdir(datawinmod_chapter_dir):
            if logger:
                logger.debug(f'Searching for ready files in INFO/datawinmod: {datawinmod_chapter_dir}')
            info_files = find_files_by_extension(datawinmod_chapter_dir, ['.win', '.ios'], data_file_names)
            ready_files.extend(info_files)
            if logger:
                for file_path in info_files:
                    logger.debug(f'Found ready data file in INFO/datawinmod: {file_path}')
    if logger:
        logger.info(f'find_ready_data_win_files: found {len(ready_files)} ready data file(s) in {mod_source_dir}')
    return ready_files


def find_csx_scripts(mod_source_dir: str) -> List[str]:
    return find_files_by_extension(mod_source_dir, ['.csx'])


def dir_has_files(dir_path: str, ext_filter: tuple = None) -> bool:
    try:
        if not os.path.exists(dir_path):
            return False
        if ext_filter:
            return any(f.endswith(ext_filter) for f in os.listdir(dir_path))
        return bool(os.listdir(dir_path))
    except Exception:
        return False


def detect_mod_type(mod_source_dir: str, logger=None) -> Dict[str, bool]:
    mod_type = {'has_xdelta_patch': False, 'has_ready_data_win': False, 'has_csx_scripts': False, 'has_file_overrides': False}
    if not os.path.isdir(mod_source_dir):
        return mod_type
    mod_type['has_xdelta_patch'] = bool(find_data_patches(mod_source_dir))
    mod_type['has_ready_data_win'] = bool(find_ready_data_win_files(mod_source_dir, logger=logger))
    mod_type['has_csx_scripts'] = bool(find_csx_scripts(mod_source_dir))
    has_other_files = False
    for root, dirs, files in os.walk(mod_source_dir):
        for file in files:
            file_lower = file.lower()
            if file_lower in ('config.json', '_icon.png', 'mod_config.json'):
                continue
            if file_lower.endswith(('.xdelta', '.vcdiff')):
                continue
            if file_lower.endswith(('data.win', 'game.ios')):
                continue
            if file_lower.endswith('.csx'):
                continue
            has_other_files = True
            break
        if has_other_files:
            break
    if has_other_files:
        mod_type['has_file_overrides'] = True
    return mod_type


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


def detect_mod_asset_types(mod_dir: str, logger=None) -> Dict[str, bool]:
    asset_types = {'has_code': False, 'has_textures': False, 'has_shaders': False, 'has_tilesets': False, 'has_fonts': False, 'has_sounds': False, 'has_rooms': False}
    objects_dir = os.path.join(mod_dir, 'Objects')
    if os.path.exists(objects_dir):
        asset_types['has_code'] = dir_has_files(os.path.join(objects_dir, 'CodeEntries'))
        asset_types['has_textures'] = any(os.path.exists(os.path.join(objects_dir, d)) for d in ('Sprites', 'Backgrounds', 'Fonts'))
        asset_types['has_shaders'] = dir_has_files(os.path.join(objects_dir, 'Shaders'))
        asset_types['has_tilesets'] = dir_has_files(os.path.join(objects_dir, 'Backgrounds'), ('.png',))
        asset_types['has_fonts'] = dir_has_files(os.path.join(objects_dir, 'Fonts'))
        asset_types['has_sounds'] = dir_has_files(os.path.join(objects_dir, 'Sounds'), ('.wav', '.ogg'))
        asset_types['has_rooms'] = dir_has_files(os.path.join(objects_dir, 'Rooms'), ('.json',))
    elif os.path.exists(os.path.join(mod_dir, 'data.win')):
        for k in ('has_code', 'has_textures', 'has_shaders', 'has_tilesets', 'has_fonts', 'has_sounds'):
            asset_types[k] = True
        if logger:
            logger.debug(f'Objects directory not found for {mod_dir}, assuming mod has all asset types (will be verified by export scripts)')
    return asset_types


def has_content(objects_dir: str, subdir: str) -> bool:
    p = os.path.join(objects_dir, subdir)
    return bool(os.path.exists(p) and os.listdir(p))


def get_dir_resources(obj_dir: str, subdir: str) -> list:
    p = os.path.join(obj_dir, subdir)
    return [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))] if os.path.exists(p) else []


def get_file_resources(obj_dir: str, subdir: str, exts, exclude=None) -> list:
    p = os.path.join(obj_dir, subdir)
    if not os.path.exists(p):
        return []
    return [os.path.splitext(f)[0] for f in os.listdir(p) if f.endswith(exts) and (not exclude or not f.endswith(exclude))]


def get_font_resources(obj_dir: str) -> list:
    fonts_path = os.path.join(obj_dir, 'Fonts')
    if not os.path.exists(fonts_path):
        return []
    font_names = set()
    for f in os.listdir(fonts_path):
        if f.endswith(('.png', '.json')):
            font_names.add(os.path.splitext(f)[0])
        elif f.startswith('glyphs_') and f.endswith('.csv'):
            font_names.add(f[7:-4])
    return list(font_names)


def get_tileset_config_resource(obj_dir: str) -> list:
    tilesets_path = os.path.join(obj_dir, 'Tilesets')
    return ['tilesets_config'] if os.path.exists(tilesets_path) and os.path.exists(os.path.join(tilesets_path, 'config.json')) else []


def get_gml_resources(obj_dir: str, logger=None) -> list:
    code_files = get_file_resources(obj_dir, 'CodeEntries', '.gml')
    if code_files and logger:
        logger.debug(f'[IMPORT] Code files to import: {code_files[:10]}...' if len(code_files) > 10 else f'[IMPORT] Code files to import: {code_files}')
    return code_files


def no_res(obj_dir: str) -> list:
    return []


def json_res(subdir: str):
    def _get_json_resources(obj_dir: str) -> list:
        return get_file_resources(obj_dir, subdir, '.json')
    return _get_json_resources
