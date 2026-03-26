"""Utilities for parsing mod config data into model objects."""

import os

from config.config import LEGACY_DESCRIPTION_KEY, LEGACY_ICON_KEY
from models.mod_models import ModExtraFile
from utils.file_utils import normalize_chapter_id
from utils.mod_utils import resolve_mod_icon

MOD_CONFIG_KEY_ORDER = (
    "id",
    "version",
    "name",
    "description",
    "author",
    "icon",
    "external_url",
    "game",
    "game_version",
    "tags",
    "files",
)


def normalize_mod_config_data(config_data: dict) -> bool:
    """Normalize config keys to the current schema."""
    if not isinstance(config_data, dict):
        return False
    changed = False
    description_value = config_data.get("description")
    if description_value in (None, ""):
        description_value = config_data.get(LEGACY_DESCRIPTION_KEY)
        if LEGACY_DESCRIPTION_KEY in config_data:
            changed = True
    icon_value = config_data.get("icon")
    if icon_value in (None, ""):
        icon_value = config_data.get(LEGACY_ICON_KEY)
        if LEGACY_ICON_KEY in config_data:
            changed = True
    normalized_items = []
    seen_keys = set()
    for key, value in config_data.items():
        if key == LEGACY_DESCRIPTION_KEY:
            key, value = "description", description_value
        elif key == LEGACY_ICON_KEY:
            key, value = "icon", icon_value
        elif key == "description":
            value = description_value
        elif key == "icon":
            value = icon_value
        if key == "files" and isinstance(value, dict):
            normalized_files = {
                normalize_chapter_id(file_key, config_data.get("game")): file_info
                for file_key, file_info in value.items()
            }
            changed = changed or normalized_files != value
            value = normalized_files
        if key in seen_keys:
            changed = True
            continue
        seen_keys.add(key)
        normalized_items.append((key, value))
    changed = changed or list(config_data.items()) != normalized_items
    if not changed:
        return False
    config_data.clear()
    config_data.update(normalized_items)
    return True


def build_mod_config_data(config_data: dict) -> dict:
    """Build an ordered mod config payload."""
    normalized = dict(config_data or {})
    normalize_mod_config_data(normalized)
    ordered = {
        key: normalized[key]
        for key in MOD_CONFIG_KEY_ORDER
        if key in normalized and normalized[key] not in (None, "")
    }
    for key, value in normalized.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return ordered


def parse_extra_files_raw(
    extra_files_raw,
    ch_info: dict,
    chapter_folder: str | None = None,
    as_dicts: bool = False,
) -> list:
    """Parse extra_files data from a chapter config into a list.

    Args:
        extra_files_raw: Raw extra_files data (list, dict, or None).
        ch_info: The parent chapter info dict (for 'versions' lookups).
        chapter_folder: If set, resolve relative URLs against this folder.
        as_dicts: If True, return dicts instead of ModExtraFile objects.

    Returns:
        List of ModExtraFile objects (or dicts if as_dicts=True).
    """
    result = []
    if not extra_files_raw:
        return result

    def _make_entry(key: str, version: str, url: str):
        if as_dicts:
            return {"key": key, "version": version, "url": url}
        return ModExtraFile(key=key, version=version, url=url)

    if isinstance(extra_files_raw, list):
        for ef_data in extra_files_raw:
            if isinstance(ef_data, dict):
                try:
                    url = ef_data.get("url", "")
                    if url and chapter_folder and not os.path.isabs(url):
                        url = os.path.join(chapter_folder, url)
                    result.append(
                        _make_entry(
                            key=ef_data.get("key", ""),
                            version=ef_data.get("version", "1.0.0"),
                            url=url,
                        )
                    )
                except KeyError, TypeError, ValueError:
                    pass
            elif isinstance(ef_data, ModExtraFile):
                if as_dicts:
                    result.append(
                        {
                            "key": ef_data.key,
                            "version": ef_data.version,
                            "url": ef_data.url,
                        }
                    )
                else:
                    result.append(ef_data)
    elif isinstance(extra_files_raw, dict):
        versions = ch_info.get("versions", {})
        if not isinstance(versions, dict):
            versions = {}
        for group_key, filenames in extra_files_raw.items():
            if isinstance(filenames, list):
                for filename in filenames:
                    url = filename
                    if chapter_folder and filename and not os.path.isabs(filename):
                        url = os.path.join(chapter_folder, filename)
                    result.append(
                        _make_entry(
                            key=group_key,
                            version=versions.get(group_key, "1.0.0"),
                            url=url,
                        )
                    )
    return result


def resolve_data_file_version(ch_info: dict) -> str:
    """Extract the data file version from a chapter info dict."""
    version = ch_info.get("data_file_version")
    if not version and isinstance(ch_info.get("versions"), dict):
        version = ch_info.get("versions", {}).get("data")
    return version or "1.0.0"


def resolve_chapter_folder(
    file_key: str, mod_folder_path: str, game: str | None = None
) -> str | None:
    """Resolve the chapter subfolder path for a given file_key."""
    if not mod_folder_path:
        return None
    from utils.file_utils import get_chapter_folder_name

    folder_name = get_chapter_folder_name(file_key, game)
    return os.path.join(mod_folder_path, folder_name) if folder_name else None


def resolve_local_icon_path(config_data: dict, mod_folder_path: str | None) -> str:
    """Resolve a mod icon from config data and folder path."""
    normalize_mod_config_data(config_data)
    if not mod_folder_path:
        return config_data.get("icon", "")
    icon_from_config = config_data.get("icon", "")
    icon_path = ""
    if icon_from_config and not icon_from_config.startswith(
        ("http://", "https://")
    ):
        if not os.path.isabs(icon_from_config):
            resolved = os.path.normpath(
                os.path.join(mod_folder_path, icon_from_config)
            )
            if os.path.exists(resolved) and os.path.isfile(resolved):
                icon_path = resolved
        else:
            icon_path = icon_from_config
    if not icon_path:
        resolved_icon = resolve_mod_icon(config_data, mod_folder_path)
        if resolved_icon:
            icon_path = resolved_icon
    return icon_path


def normalize_files_data(files_data: dict, game: str | None = None) -> dict:
    """Normalize files_data dict for use with ModInfo.from_dict().

    Returns a dict where each chapter's extra_files are list-of-dicts
    and data_file_version is resolved.
    """
    normalized = {}
    for raw_file_key, ch_info in files_data.items():
        if not isinstance(ch_info, dict):
            continue
        file_key = normalize_chapter_id(raw_file_key, game)
        extra_files_list = parse_extra_files_raw(
            ch_info.get("extra_files", []),
            ch_info,
            as_dicts=True,
        )
        file_info = normalized.setdefault(
            file_key,
            {
                "description": None,
                "data_file_url": None,
                "data_file_version": "1.0.0",
                "extra_files": [],
            },
        )
        if ch_info.get("description") not in (None, ""):
            file_info["description"] = ch_info.get("description")
        if ch_info.get("data_file_url"):
            file_info["data_file_url"] = ch_info.get("data_file_url")
        file_info["data_file_version"] = resolve_data_file_version(ch_info)
        for extra_file in extra_files_list:
            if extra_file not in file_info["extra_files"]:
                file_info["extra_files"].append(extra_file)
    return normalized
