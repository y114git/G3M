import os
from typing import Any, Optional


def get_mod_key(mod_data: Any) -> Optional[str]:
    if mod_data is None:
        return None
    if isinstance(mod_data, dict):
        return mod_data.get('key') or mod_data.get('mod_key') or mod_data.get('name')
    return getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)


def get_mod_name(mod_data: Any, default: str = 'Unknown') -> str:
    if mod_data is None:
        return default
    if isinstance(mod_data, dict):
        return mod_data.get('name', default)
    return getattr(mod_data, 'name', default)


def resolve_mod_icon(config_data: dict, mod_folder_path: str) -> Optional[str]:
    if not mod_folder_path or not os.path.isdir(mod_folder_path):
        return None
    icon_field = config_data.get('icon')
    if icon_field and isinstance(icon_field, str) and icon_field.strip():
        icon_field = icon_field.strip()
        if icon_field.startswith(('http://', 'https://')):
            return icon_field
        if os.path.isabs(icon_field):
            return None
        if icon_field.startswith(('/', '\\')) or (len(icon_field) >= 2 and icon_field[1] == ':'):
            return None
        icon_path = os.path.normpath(os.path.join(mod_folder_path, icon_field))
        mod_folder_abs = os.path.abspath(mod_folder_path)
        icon_path_abs = os.path.abspath(icon_path)
        try:
            common_path = os.path.commonpath([mod_folder_abs, icon_path_abs])
            if common_path != mod_folder_abs:
                return None
        except ValueError:
            return None
        if os.path.exists(icon_path_abs) and os.path.isfile(icon_path_abs):
            return icon_path_abs
    icon_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp']
    for ext in icon_extensions:
        legacy_icon = os.path.join(mod_folder_path, f'_icon{ext}')
        if os.path.exists(legacy_icon) and os.path.isfile(legacy_icon):
            return legacy_icon
    return None
