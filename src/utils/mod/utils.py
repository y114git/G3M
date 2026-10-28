"""Mod data extraction utilities."""

import os
import re
from collections.abc import Mapping
from typing import TypeGuard
from urllib.parse import urlparse

from utils.mod.config import mod_local_relative_path

# "[https://]gamebanana.com/mmdl/{fileId}[,{Mod|Wip},{modId}]", with or without the colon and a trailing query
_GB_DOWNLOAD_LINK = re.compile(
    r"(?:https?:?//)?(?:www\.)?gamebanana\.com/mmdl/(\d+)(?:\?[^,]*)?(?:,(Mod|Wip),(\d+))?(?:\?.*)?/?",
    re.IGNORECASE | re.ASCII,
)


def parse_gamebanana_download_link(text: str) -> tuple[str, tuple[str, str] | None] | None:
    """Split a GameBanana 1-click link into (file id, ("Mod"/"Wip", mod id)); the mod part may be missing."""
    match = _GB_DOWNLOAD_LINK.fullmatch(text.strip())
    if not match:
        return None
    file_id, item_type, mod_id = match.groups()
    return file_id, (item_type.capitalize(), mod_id) if item_type and mod_id else None


def parse_gamebanana_mod_url(url: str) -> tuple[str, int] | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.casefold() in {"gamebanana.com", "www.gamebanana.com"}
        and len(parts) == 2 and parts[0].casefold() in {"mods", "wips"}
        and parts[1].isascii() and parts[1].isdigit()
    ):
        return ("Wip" if parts[0].casefold() == "wips" else "Mod", int(parts[1]))
    return None


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


def is_gamebanana_id(mod_id: object) -> TypeGuard[str]:
    """Whether a mod id names a GameBanana mod or WIP (``gb_mod_<n>`` or ``gb_wip_<n>``)."""
    return isinstance(mod_id, str) and mod_id.startswith(("gb_mod_", "gb_wip_"))


def get_gamebanana_id(mod_data):
    """Get GameBanana id if mod is from GameBanana."""
    mod_id = _get_mod_field(mod_data, "id")
    return mod_id if is_gamebanana_id(mod_id) else None


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
    icon_value = str(config_data.get("icon") or "").strip()
    raw_placeholders = config_data.get("placeholders")
    placeholders: Mapping[str, object] = (
        raw_placeholders if isinstance(raw_placeholders, Mapping) else {}
    )
    icon_field = mod_local_relative_path(
        icon_value,
        placeholders,
    )
    if icon_field is None:
        icon_field = icon_value
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
    return None


_MANUAL_PACKAGE = re.compile(r"xdelta|vcdiff|manual")


def sort_gamebanana_files_by_priority(files: list[dict]) -> list[dict]:
    """Sort GameBanana files by compatibility priority (g3m > deltamod > others)."""

    def _priority(file_info: dict) -> tuple[int, int, int, int, str]:
        compatibility = str(file_info.get("compatibility") or "").lower()
        if compatibility == "g3m":
            rank = 0
        elif compatibility == "deltamod":
            rank = 1
        else:
            rank = 2
        try:
            timestamp = int(file_info.get("timestamp") or file_info.get("_tsDateAdded") or 0)
        except (TypeError, ValueError):
            timestamp = 0
        try:
            file_id = int(file_info.get("id") or file_info.get("_idRow") or 0)
        except (TypeError, ValueError):
            file_id = 0
        # Authors label packages by name: a G3M package installs by itself, a bare XDELTA or manual one never does.
        label = f"{file_info.get('name') or file_info.get('_sFile') or ''} {file_info.get('description') or ''}".casefold()
        kind = 2 if _MANUAL_PACKAGE.search(label) else 0 if "g3m" in label else 1
        return (rank, kind, -timestamp, -file_id, str(file_info.get("name") or "").casefold())

    return sorted(files or [], key=_priority)
