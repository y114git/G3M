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
