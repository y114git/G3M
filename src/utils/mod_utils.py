"""Mod data extraction utilities."""
import os


def _get_mod_field(mod_data, field, default=None): return mod_data.get(field, default) if isinstance(mod_data, dict) else getattr(mod_data, field, default)
def get_mod_key(mod_data): return None if mod_data is None else (_get_mod_field(mod_data, 'key') or _get_mod_field(mod_data, 'mod_key') or _get_mod_field(mod_data, 'name'))
def get_mod_name(mod_data, default='Unknown'): return default if mod_data is None else _get_mod_field(mod_data, 'name', default)


def get_gamebanana_key(mod_data):
    """Get GameBanana key if mod is from GameBanana."""
    key = _get_mod_field(mod_data, 'key') or _get_mod_field(mod_data, 'mod_key')
    return key if key and key.startswith('gb_') else None


def get_gamebanana_mod_id(mod_data):
    """Get GameBanana mod ID (numeric part after gb_)."""
    return (key := get_gamebanana_key(mod_data)) and key[3:] or None


def resolve_mod_icon(config_data: dict, mod_folder_path: str):
    """Resolve path to mod's icon file."""
    if not mod_folder_path or not os.path.isdir(mod_folder_path):
        return None
    icon_field = (config_data.get('icon') or config_data.get('icon_url') or '').strip()
    if icon_field:
        if icon_field.startswith(('http://', 'https://')):
            return icon_field
        if os.path.isabs(icon_field) or icon_field.startswith(('/', '\\')) or (len(icon_field) >= 2 and icon_field[1] == ':'):
            return None
        icon_path_abs, mod_folder_abs = os.path.abspath(os.path.normpath(os.path.join(mod_folder_path, icon_field))), os.path.abspath(mod_folder_path)
        try:
            if os.path.commonpath([mod_folder_abs, icon_path_abs]) != mod_folder_abs:
                return None
        except ValueError:
            return None
        if os.path.isfile(icon_path_abs):
            return icon_path_abs
    return next((p for ext in ['.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp'] if os.path.isfile(p := os.path.join(mod_folder_path, f'_icon{ext}'))), None)
