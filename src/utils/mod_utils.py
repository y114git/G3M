"""Mod data extraction utilities."""

import os

from config.config import LEGACY_ICON_KEY


def _get_mod_field(mod_data, field, default=None):
    return (
        mod_data.get(field, default)
        if isinstance(mod_data, dict)
        else getattr(mod_data, field, default)
    )


def get_mod_id(mod_data):
    return (
        None
        if mod_data is None
        else (_get_mod_field(mod_data, "id") or _get_mod_field(mod_data, "name"))
    )


def get_mod_name(mod_data, default="Unknown"):
    return default if mod_data is None else _get_mod_field(mod_data, "name", default)


def get_gamebanana_id(mod_data):
    """Get GameBanana id if mod is from GameBanana."""
    mod_id = _get_mod_field(mod_data, "id")
    return (
        mod_id
        if mod_id
        and isinstance(mod_id, str)
        and (mod_id.startswith("gb_mod_") or mod_id.startswith("gb_wip_"))
        else None
    )


def parse_gamebanana_mod_id(mod_id):
    """Parse gb_{type}_{id} id -> (type_str, numeric_id_str) or (None, None)."""
    if not mod_id or not isinstance(mod_id, str):
        return None, None
    if mod_id.startswith("gb_mod_"):
        return "mod", mod_id[7:]
    if mod_id.startswith("gb_wip_"):
        return "wip", mod_id[7:]
    return None, None


def get_gamebanana_mod_id(mod_data):
    """Get GameBanana numeric ID string from mod data."""
    _, mod_id = parse_gamebanana_mod_id(get_gamebanana_id(mod_data))
    return mod_id


def get_gamebanana_item_type(mod_data):
    """Get GB API item type ('Mod' or 'Wip') from mod data id.

    Returns 'Wip' if gb_type == 'wip', otherwise returns 'Mod' as default.
    Falls back to 'Mod' when parse_gamebanana_mod_id(get_gamebanana_id(mod_data))
    yields gb_type == None (invalid/non-GameBanana id). Callers who need to
    distinguish "actual Mod" vs "couldn't parse" should call parse_gamebanana_mod_id
    directly and inspect its return value.
    """
    gb_type, _ = parse_gamebanana_mod_id(get_gamebanana_id(mod_data))
    return "Wip" if gb_type == "wip" else "Mod"


def resolve_mod_icon(config_data: dict, mod_folder_path: str):
    """Resolve path to mod's icon file."""
    if not mod_folder_path or not os.path.isdir(mod_folder_path):
        return None
    icon_field = (config_data.get("icon") or config_data.get(LEGACY_ICON_KEY) or "").strip()
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
