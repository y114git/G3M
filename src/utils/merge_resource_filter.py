"""Resource hashing, comparison, and vanilla-identical filtering for mod merging."""
import hashlib
import json
import os
import shutil
from typing import Dict, Optional

from utils.file_utils import safe_rmtree, safe_copy


def hash_file(file_path: str) -> Optional[str]:
    try:
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def hash_dir_files(dir_path: str, ext_filter: str = None) -> Optional[str]:
    files = sorted(os.listdir(dir_path)) if not ext_filter else sorted(f for f in os.listdir(dir_path) if f.endswith(ext_filter))
    if not files:
        return None
    h = hashlib.sha256()
    for f in files:
        try:
            with open(os.path.join(dir_path, f), 'rb') as fh:
                h.update(fh.read())
        except Exception:
            pass
    return h.hexdigest()


def hash_json_semantic(file_path: str) -> Optional[str]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    except Exception:
        return hash_file(file_path)


def compute_resource_hashes(objects_dir: str) -> Dict[str, Dict[str, str]]:
    hashes = {'code': {}, 'sprites': {}, 'backgrounds': {}, 'fonts': {}, 'shaders': {}, 'sounds': {}, 'rooms': {}}
    code_dir = os.path.join(objects_dir, 'CodeEntries')
    if os.path.exists(code_dir):
        for file in os.listdir(code_dir):
            if file.endswith('.gml'):
                h = hash_file(os.path.join(code_dir, file))
                if h:
                    hashes['code'][os.path.splitext(file)[0]] = h
    for subdir, key, use_dirs in [('Sprites', 'sprites', True), ('Shaders', 'shaders', True)]:
        res_dir = os.path.join(objects_dir, subdir)
        if os.path.exists(res_dir):
            for name in os.listdir(res_dir):
                item_path = os.path.join(res_dir, name)
                if os.path.isdir(item_path):
                    ext_filter = '.png' if key == 'sprites' else None
                    h = hash_dir_files(item_path, ext_filter)
                    if h:
                        hashes[key][name] = h
    backgrounds_dir = os.path.join(objects_dir, 'Backgrounds')
    if os.path.exists(backgrounds_dir):
        for bg_name in os.listdir(backgrounds_dir):
            bg_path = os.path.join(backgrounds_dir, bg_name)
            if os.path.isdir(bg_path):
                h = hash_dir_files(bg_path, '.png')
                if h:
                    hashes['backgrounds'][bg_name] = h
            elif bg_name.endswith('.png'):
                h = hash_file(bg_path)
                if h:
                    hashes['backgrounds'][os.path.splitext(bg_name)[0]] = h
    fonts_dir = os.path.join(objects_dir, 'Fonts')
    if os.path.exists(fonts_dir):
        font_names = {os.path.splitext(f)[0] for f in os.listdir(fonts_dir) if f.endswith(('.png', '.json'))}
        for font_name in font_names:
            h = hashlib.sha256()
            for ext in ('.png', '.json'):
                fp = os.path.join(fonts_dir, f'{font_name}{ext}')
                if os.path.exists(fp):
                    try:
                        with open(fp, 'rb') as f:
                            h.update(f.read())
                    except Exception:
                        pass
            hashes['fonts'][font_name] = h.hexdigest()
    for subdir, key, exts in [('Sounds', 'sounds', ('.ogg', '.wav')), ('Rooms', 'rooms', ('.json',))]:
        res_dir = os.path.join(objects_dir, subdir)
        if os.path.exists(res_dir):
            for file in os.listdir(res_dir):
                if file.endswith(exts):
                    name = os.path.splitext(file)[0]
                    fp = os.path.join(res_dir, file)
                    if key == 'rooms':
                        h = hash_json_semantic(fp)
                    else:
                        h = hash_file(fp)
                    if h:
                        hashes[key][name] = h
    return hashes


def are_files_semantically_equal(file1: str, file2: str, resource_type: str, logger=None) -> bool:
    try:
        if resource_type == 'room' or resource_type == 'rooms':
            try:
                with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
                    json1 = json.load(f1)
                    json2 = json.load(f2)
                canonical1 = json.dumps(json1, sort_keys=True, separators=(',', ':'))
                canonical2 = json.dumps(json2, sort_keys=True, separators=(',', ':'))
                return canonical1 == canonical2
            except Exception:
                pass
        with open(file1, 'rb') as f1, open(file2, 'rb') as f2:
            while True:
                b1 = f1.read(8192)
                b2 = f2.read(8192)
                if b1 != b2:
                    return False
                if not b1:
                    return True
    except Exception as e:
        if logger:
            logger.warning(f'Failed to compare files {file1} and {file2}: {e}')
        return False


def copy_resource_to_filtered(resource_type: str, resource_name: str, source_objects_dir: str, target_objects_dir: str) -> None:
    if resource_type == 'code':
        source_file = os.path.join(source_objects_dir, 'CodeEntries', f'{resource_name}.gml')
        target_dir = os.path.join(target_objects_dir, 'CodeEntries')
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, f'{resource_name}.gml')
        if os.path.exists(source_file):
            safe_copy(source_file, target_file)
    elif resource_type == 'sprites':
        source_dir = os.path.join(source_objects_dir, 'Sprites', resource_name)
        target_dir = os.path.join(target_objects_dir, 'Sprites', resource_name)
        if os.path.exists(source_dir) and os.path.isdir(source_dir):
            os.makedirs(os.path.dirname(target_dir), exist_ok=True)
            if os.path.exists(target_dir):
                safe_rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
    elif resource_type == 'backgrounds':
        source_dir = os.path.join(source_objects_dir, 'Backgrounds', resource_name)
        source_file = os.path.join(source_objects_dir, 'Backgrounds', f'{resource_name}.png')
        target_dir = os.path.join(target_objects_dir, 'Backgrounds')
        os.makedirs(target_dir, exist_ok=True)
        if os.path.exists(source_dir) and os.path.isdir(source_dir):
            target_subdir = os.path.join(target_dir, resource_name)
            if os.path.exists(target_subdir):
                safe_rmtree(target_subdir)
            shutil.copytree(source_dir, target_subdir)
        elif os.path.exists(source_file):
            safe_copy(source_file, os.path.join(target_dir, f'{resource_name}.png'))
    elif resource_type == 'fonts':
        target_dir = os.path.join(target_objects_dir, 'Fonts')
        os.makedirs(target_dir, exist_ok=True)
        png_file = os.path.join(source_objects_dir, 'Fonts', f'{resource_name}.png')
        json_file = os.path.join(source_objects_dir, 'Fonts', f'{resource_name}.json')
        if os.path.exists(png_file):
            safe_copy(png_file, os.path.join(target_dir, f'{resource_name}.png'))
        if os.path.exists(json_file):
            safe_copy(json_file, os.path.join(target_dir, f'{resource_name}.json'))
    elif resource_type == 'shaders':
        source_dir = os.path.join(source_objects_dir, 'Shaders', resource_name)
        target_dir = os.path.join(target_objects_dir, 'Shaders', resource_name)
        if os.path.exists(source_dir) and os.path.isdir(source_dir):
            os.makedirs(os.path.dirname(target_dir), exist_ok=True)
            if os.path.exists(target_dir):
                safe_rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
    elif resource_type == 'sounds':
        target_dir = os.path.join(target_objects_dir, 'Sounds')
        os.makedirs(target_dir, exist_ok=True)
        for ext in ['.ogg', '.wav']:
            source_file = os.path.join(source_objects_dir, 'Sounds', f'{resource_name}{ext}')
            if os.path.exists(source_file):
                safe_copy(source_file, os.path.join(target_dir, f'{resource_name}{ext}'))
                break
    elif resource_type == 'rooms':
        target_dir = os.path.join(target_objects_dir, 'Rooms')
        os.makedirs(target_dir, exist_ok=True)
        source_file = os.path.join(source_objects_dir, 'Rooms', f'{resource_name}.json')
        if os.path.exists(source_file):
            safe_copy(source_file, os.path.join(target_dir, f'{resource_name}.json'))


def filter_vanilla_identical_resources(vanilla_hashes: Dict[str, Dict[str, str]],
                                       mod_objects_dir: str,
                                       mod_number: int,
                                       mod_name: str,
                                       logger=None) -> Optional[str]:
    if not os.path.exists(mod_objects_dir):
        return None
    mod_hashes = compute_resource_hashes(mod_objects_dir)
    filtered_dir = os.path.join(os.path.dirname(mod_objects_dir), f'Objects_filtered_{mod_number}')
    if os.path.exists(filtered_dir):
        safe_rmtree(filtered_dir)
    os.makedirs(filtered_dir, exist_ok=True)
    removed_counts = {'code': 0, 'sprites': 0, 'backgrounds': 0, 'fonts': 0, 'shaders': 0, 'sounds': 0, 'rooms': 0}
    for resource_type in ['code', 'sprites', 'backgrounds', 'fonts', 'shaders', 'sounds', 'rooms']:
        vanilla_type_hashes = vanilla_hashes.get(resource_type, {})
        mod_type_hashes = mod_hashes.get(resource_type, {})
        for resource_name, mod_hash in mod_type_hashes.items():
            vanilla_hash = vanilla_type_hashes.get(resource_name)
            if vanilla_hash is not None and mod_hash == vanilla_hash:
                removed_counts[resource_type] += 1
                continue
            copy_resource_to_filtered(resource_type, resource_name, mod_objects_dir, filtered_dir)
    total_removed = sum(removed_counts.values())
    if total_removed > 0 and logger:
        summary_parts = [f'{k}: {v}' for k, v in removed_counts.items() if v > 0]
        logger.info(f"[FILTER] Mod {mod_number} ({mod_name}): Removed {total_removed} resources identical to vanilla ({', '.join(summary_parts)})")
    has_content = False
    for root, dirs, files in os.walk(filtered_dir):
        if dirs or files:
            has_content = True
            break
    if not has_content:
        safe_rmtree(filtered_dir)
        return None
    return filtered_dir
