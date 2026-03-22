"""Mod data extraction utilities."""

import os


def _get_mod_field(mod_data, field, default=None):
    return (
        mod_data.get(field, default)
        if isinstance(mod_data, dict)
        else getattr(mod_data, field, default)
    )


def get_mod_key(mod_data):
    return (
        None
        if mod_data is None
        else (
            _get_mod_field(mod_data, "key")
            or _get_mod_field(mod_data, "mod_key")
            or _get_mod_field(mod_data, "name")
        )
    )


def get_mod_name(mod_data, default="Unknown"):
    return default if mod_data is None else _get_mod_field(mod_data, "name", default)


def get_gamebanana_key(mod_data):
    """Get GameBanana key if mod is from GameBanana."""
    key = _get_mod_field(mod_data, "key") or _get_mod_field(mod_data, "mod_key")
    return (
        key
        if key
        and isinstance(key, str)
        and (key.startswith("gb_mod_") or key.startswith("gb_wip_"))
        else None
    )


def parse_gamebanana_key(key):
    """Parse gb_{type}_{id} key → (type_str, numeric_id_str) or (None, None)."""
    if not key or not isinstance(key, str):
        return None, None
    if key.startswith("gb_mod_"):
        return "mod", key[7:]
    if key.startswith("gb_wip_"):
        return "wip", key[7:]
    return None, None


def get_gamebanana_mod_id(mod_data):
    """Get GameBanana numeric ID string from mod data."""
    _, mod_id = parse_gamebanana_key(get_gamebanana_key(mod_data))
    return mod_id


def get_gamebanana_item_type(mod_data):
    """Get GB API item type ('Mod' or 'Wip') from mod data key.

    Returns 'Wip' if gb_type == 'wip', otherwise returns 'Mod' as default.
    Falls back to 'Mod' when parse_gamebanana_key(get_gamebanana_key(mod_data))
    yields gb_type == None (invalid/non-GameBanana key). Callers who need to
    distinguish "actual Mod" vs "couldn't parse" should call parse_gamebanana_key
    directly and inspect its return value.
    """
    gb_type, _ = parse_gamebanana_key(get_gamebanana_key(mod_data))
    return "Wip" if gb_type == "wip" else "Mod"


def resolve_mod_icon(config_data: dict, mod_folder_path: str):
    """Resolve path to mod's icon file."""
    if not mod_folder_path or not os.path.isdir(mod_folder_path):
        return None
    icon_field = (config_data.get("icon") or config_data.get("icon_url") or "").strip()
    if icon_field:
        if icon_field.startswith(("http://", "https://")):
            return icon_field
        if (
            os.path.isabs(icon_field)
            or icon_field.startswith(("/", "\\"))
            or (len(icon_field) >= 2 and icon_field[1] == ":")
        ):
            return None
        icon_path_abs, mod_folder_abs = (
            os.path.abspath(
                os.path.normpath(os.path.join(mod_folder_path, icon_field))
            ),
            os.path.abspath(mod_folder_path),
        )
        try:
            if os.path.commonpath([mod_folder_abs, icon_path_abs]) != mod_folder_abs:
                return None
        except ValueError:
            return None
        if os.path.isfile(icon_path_abs):
            return icon_path_abs
    return next(
        (
            p
            for ext in [".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp"]
            if os.path.isfile(p := os.path.join(mod_folder_path, f"_icon{ext}"))
        ),
        None,
    )


def sort_gamebanana_files_by_priority(files: list[dict]) -> list[dict]:
    """Sort GameBanana files by compatibility priority (deltahub > deltamod > others)."""

    def _priority(file_info: dict) -> tuple[int, str]:
        compatibility = str(file_info.get("compatibility") or "").lower()
        if compatibility == "deltahub":
            rank = 0
        elif compatibility == "deltamod":
            rank = 1
        else:
            rank = 2
        return (rank, str(file_info.get("name") or ""))

    return sorted(files or [], key=_priority)
