"""Utilities for parsing, migrating, and canonicalizing mod config data."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from models.mod_models import ModExtraFile
from services.migration_service import migrate_mod_config_legacy_fields
from utils.file_utils import normalize_chapter_id
from utils.mod_utils import resolve_mod_icon

MOD_CONFIG_VERSION = "1.0.0"
MOD_ALLOWED_TAGS = ("textedit", "customization", "gameplay", "other")
MOD_FIELD_LIMITS = {
    "id": 50,
    "name": 50,
    "version": 20,
    "game": 30,
    "description": 200,
    "homepage": 1000,
    "icon": 1000,
    "game_version": 1000,
    "file_value": 1000,
}
MOD_CONFIG_KEY_ORDER = (
    "config_version",
    "id",
    "name",
    "version",
    "author",
    "description",
    "homepage",
    "icon",
    "game",
    "game_version",
    "tags",
    "files",
)


def _trim_string(value, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _normalize_homepage(value) -> str:
    url = _trim_string(value, MOD_FIELD_LIMITS["homepage"])
    if not url:
        return ""
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _sanitize_tags(tags_raw) -> list[str]:
    if not isinstance(tags_raw, list):
        tags_raw = [tags_raw] if tags_raw else []
    result: list[str] = []
    for tag in tags_raw:
        normalized = _trim_string(tag, 100).lower()
        if normalized in MOD_ALLOWED_TAGS and normalized not in result:
            result.append(normalized)
    return result


def _sanitize_extra_files(extra_files_raw) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for extra_file in parse_extra_files_raw(extra_files_raw, {}, as_dicts=True):
        key = _trim_string(extra_file.get("key"), MOD_FIELD_LIMITS["file_value"])
        url = _trim_string(extra_file.get("url"), MOD_FIELD_LIMITS["file_value"])
        if not key or not url:
            continue
        payload = {"key": key, "url": url}
        if payload not in result:
            result.append(payload)
    return result


def _sanitize_files(files_data: dict, game: str) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    if not isinstance(files_data, dict):
        return normalized
    for raw_file_key, ch_info in files_data.items():
        if not isinstance(ch_info, dict):
            continue
        file_key = _trim_string(
            normalize_chapter_id(raw_file_key, game),
            MOD_FIELD_LIMITS["file_value"],
        )
        if not file_key:
            continue
        entry: dict[str, object] = {}
        description = _trim_string(
            ch_info.get("description"), MOD_FIELD_LIMITS["description"]
        )
        if description:
            entry["description"] = description
        data_file_url = _trim_string(
            ch_info.get("data_file_url"), MOD_FIELD_LIMITS["file_value"]
        )
        if data_file_url:
            entry["data_file_url"] = data_file_url
        extra_files = _sanitize_extra_files(ch_info.get("extra_files", []))
        if extra_files:
            entry["extra_files"] = extra_files
        if entry:
            normalized[file_key] = entry
    return normalized


def normalize_mod_config_data(config_data: dict) -> bool:
    """Normalize config keys and values to the canonical 1.0.0 schema."""
    if not isinstance(config_data, dict):
        return False
    changed = migrate_mod_config_legacy_fields(config_data)
    canonical = {
        "config_version": MOD_CONFIG_VERSION,
        "id": _trim_string(config_data.get("id"), MOD_FIELD_LIMITS["id"]),
        "name": _trim_string(config_data.get("name"), MOD_FIELD_LIMITS["name"]),
        "version": _trim_string(config_data.get("version"), MOD_FIELD_LIMITS["version"])
        or "1.0.0",
        "author": _trim_string(config_data.get("author"), MOD_FIELD_LIMITS["file_value"]),
        "description": _trim_string(
            config_data.get("description"), MOD_FIELD_LIMITS["description"]
        ),
        "homepage": _normalize_homepage(config_data.get("homepage")),
        "icon": _trim_string(config_data.get("icon"), MOD_FIELD_LIMITS["icon"]),
        "game": _trim_string(config_data.get("game"), MOD_FIELD_LIMITS["game"])
        or "deltarune",
        "game_version": _trim_string(
            config_data.get("game_version"), MOD_FIELD_LIMITS["file_value"]
        ),
        "tags": _sanitize_tags(config_data.get("tags")),
        "files": {},
    }
    canonical["files"] = _sanitize_files(config_data.get("files", {}), canonical["game"])
    ordered = {
        key: canonical[key]
        for key in MOD_CONFIG_KEY_ORDER
        if canonical[key] not in (None, "", [], {})
    }
    if list(config_data.items()) != list(ordered.items()):
        changed = True
        config_data.clear()
        config_data.update(ordered)
    return changed


def build_mod_config_data(config_data: dict) -> dict:
    """Build a strict ordered mod config payload."""
    normalized = dict(config_data or {})
    normalize_mod_config_data(normalized)
    return normalized


def parse_extra_files_raw(
    extra_files_raw,
    ch_info: dict,
    chapter_folder: str | None = None,
    as_dicts: bool = False,
) -> list:
    """Parse extra_files data from a chapter config into a list."""
    result = []
    if not extra_files_raw:
        return result

    def _make_entry(key: str, url: str):
        if as_dicts:
            return {"key": key, "url": url}
        return ModExtraFile(key=key, url=url)

    if isinstance(extra_files_raw, list):
        for ef_data in extra_files_raw:
            if isinstance(ef_data, dict):
                url = ef_data.get("url", "")
                if url and chapter_folder and not os.path.isabs(url):
                    url = os.path.join(chapter_folder, url)
                result.append(_make_entry(key=ef_data.get("key", ""), url=url))
            elif isinstance(ef_data, ModExtraFile):
                result.append(
                    {"key": ef_data.key, "url": ef_data.url} if as_dicts else ef_data
                )
    elif isinstance(extra_files_raw, dict):
        for group_key, filenames in extra_files_raw.items():
            if isinstance(filenames, list):
                for filename in filenames:
                    url = filename
                    if chapter_folder and filename and not os.path.isabs(filename):
                        url = os.path.join(chapter_folder, filename)
                    result.append(_make_entry(key=group_key, url=url))
    return result


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
    if icon_from_config and not icon_from_config.startswith(("http://", "https://")):
        if not os.path.isabs(icon_from_config):
            resolved = os.path.normpath(os.path.join(mod_folder_path, icon_from_config))
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
    """Normalize files data for runtime models."""
    normalized = {}
    for raw_file_key, ch_info in _sanitize_files(files_data, game or "deltarune").items():
        extra_files_list = parse_extra_files_raw(
            ch_info.get("extra_files", []),
            ch_info,
            as_dicts=True,
        )
        normalized[raw_file_key] = {
            "description": ch_info.get("description"),
            "data_file_url": ch_info.get("data_file_url"),
            "extra_files": extra_files_list,
        }
    return normalized
