"""Resource detection helpers for mod merge import pipeline."""
import os


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
