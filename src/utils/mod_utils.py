"""Mod data extraction utilities."""
import os
from typing import Any, Optional


def _get_mod_field(mod_data: Any, field: str, default: Any = None) -> Any:
    """Get a field from mod data (dict or object)."""
    return mod_data.get(field, default) if isinstance(mod_data, dict) else getattr(mod_data, field, default)


def get_mod_key(mod_data: Any) -> Optional[str]:
    """Get the unique key identifier for a mod."""
    return None if mod_data is None else (_get_mod_field(mod_data, 'key') or _get_mod_field(mod_data, 'mod_key') or _get_mod_field(mod_data, 'name'))


def get_gamebanana_key(mod_data: Any) -> Optional[str]:
    """Get GameBanana key if mod is from GameBanana."""
    key = _get_mod_field(mod_data, 'key') or _get_mod_field(mod_data, 'mod_key')
    return key if key and key.startswith('gb_') else None


def get_gamebanana_mod_id(mod_data: Any) -> Optional[str]:
    """Get GameBanana mod ID (numeric part after gb_)."""
    key = get_gamebanana_key(mod_data)
    return key[3:] if key else None


def get_mod_name(mod_data: Any, default: str = 'Unknown') -> str:
    """Get the display name of a mod."""
    return default if mod_data is None else _get_mod_field(mod_data, 'name', default)


def resolve_mod_icon(config_data: dict, mod_folder_path: str) -> Optional[str]:
    """Resolve the path to a mod's icon file."""
    if not mod_folder_path or not os.path.isdir(mod_folder_path):
        return None
    icon_field = config_data.get('icon') or config_data.get('icon_url')
    if icon_field and isinstance(icon_field, str) and icon_field.strip():
        icon_field = icon_field.strip()
        if icon_field.startswith(('http://', 'https://')):
            return icon_field
        if os.path.isabs(icon_field) or icon_field.startswith(('/', '\\')) or (len(icon_field) >= 2 and icon_field[1] == ':'):
            return None
        icon_path_abs = os.path.abspath(os.path.normpath(os.path.join(mod_folder_path, icon_field)))
        mod_folder_abs = os.path.abspath(mod_folder_path)
        try:
            if os.path.commonpath([mod_folder_abs, icon_path_abs]) != mod_folder_abs:
                return None
        except ValueError:
            return None
        if os.path.exists(icon_path_abs) and os.path.isfile(icon_path_abs):
            return icon_path_abs
    for ext in ['.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp']:
        legacy_icon = os.path.join(mod_folder_path, f'_icon{ext}')
        if os.path.exists(legacy_icon) and os.path.isfile(legacy_icon):
            return legacy_icon
    return None
