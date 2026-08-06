"""Utilities for parsing, migrating, and canonicalizing mod config data."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from config.config import CYOP_AFOM_TAG
from models.game_modes import get_all_games
from services.migration_service import (
    build_extra_file_entry,
    migrate_mod_config_legacy_fields,
)
from utils.file_utils import normalize_chapter_id
from utils.mod.utils import resolve_mod_icon

MOD_CONFIG_VERSION = "1.0.0"
MOD_ALLOWED_TAGS = ("textedit", "customization", "gameplay", "other", CYOP_AFOM_TAG)
MOD_FIELD_LIMITS = {
    "id": 50,
    "name": 50,
    "author": 50,
    "version": 20,
    "game": 30,
    "description": 200,
    "homepage": 200,
    "icon": 200,
    "game_version": 20,
    "file_value": 1000,
}
MOD_METADATA_KEY_ORDER = (
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
)
MOD_INFO_FILE_VISIBILITY = ("show", "hide", "remove")
MOD_RUNTIME_KEY_ORDER = (
    "config_version",
    *MOD_METADATA_KEY_ORDER,
    "info_files",
    "files",
)


def _trim_string(value, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _normalize_extra_file_path(path_value: str) -> str:
    raw = str(path_value or "")
    if not raw:
        return ""
    preserve_trailing_slash = raw.rstrip().endswith(("/", "\\"))
    normalized = raw.replace("\\", "/").strip()
    if not normalized:
        return ""
    if preserve_trailing_slash:
        normalized = normalized.rstrip("/")
        return f"{normalized}/" if normalized else ""
    return normalized


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
        raw_tag = _trim_string(tag, 100)
        normalized = (
            CYOP_AFOM_TAG
            if raw_tag.casefold() == CYOP_AFOM_TAG.casefold()
            else raw_tag.lower()
        )
        if normalized in MOD_ALLOWED_TAGS and normalized not in result:
            result.append(normalized)
    return result


def _sanitize_extra_files(extra_files_raw) -> list[str | dict[str, str]]:
    result: list[str | dict[str, str]] = []
    for entry in parse_extra_file_entries_raw(extra_files_raw):
        extra_file = entry["file_path"]
        file_path = _normalize_extra_file_path(
            _trim_string(extra_file, MOD_FIELD_LIMITS["file_value"])
        )
        if not file_path:
            continue
        value = build_extra_file_entry(file_path, entry["status"])
        if value not in result:
            result.append(value)
    return result


def _sanitize_info_files(info_files_raw) -> dict[str, str]:
    """Sanitize info_files config dict. Info files must be file paths, not directories."""
    result: dict[str, str] = {}
    if not isinstance(info_files_raw, dict):
        return result
    for raw_path, raw_visibility in info_files_raw.items():
        file_path = _normalize_extra_file_path(
            _trim_string(raw_path, MOD_FIELD_LIMITS["file_value"])
        ).rstrip("/")
        if not file_path:
            continue
        visibility = str(raw_visibility or "").strip().lower()
        result[file_path] = (
            visibility if visibility in MOD_INFO_FILE_VISIBILITY else "show"
        )
    return result


def _get_metadata_value(config_data: dict, key: str):
    metadata = config_data.get("metadata")
    if key in config_data and config_data.get(key) not in (None, "", [], {}):
        return config_data.get(key)
    if isinstance(metadata, dict):
        return metadata.get(key)
    return config_data.get(key)


def _get_legacy_layout_prefixes(mod_root_path: str | None) -> list[str]:
    if not mod_root_path or not os.path.isdir(mod_root_path):
        return []
    known_game_dirs = {game.game_id for game in get_all_games()}
    candidates: list[str] = []
    for entry in sorted(os.listdir(mod_root_path)):
        entry_path = os.path.join(mod_root_path, entry)
        if not os.path.isdir(entry_path):
            continue
        if (
            entry.startswith("chapter_")
            or entry in {"demo", "menu", "universal"}
            or entry in known_game_dirs
        ):
            candidates.append(entry)
    return candidates


def _migrate_legacy_layout_path(path_value: str, mod_root_path: str | None) -> str:
    preserve_trailing_slash = str(path_value or "").rstrip().endswith(("/", "\\"))
    normalized_path = _normalize_extra_file_path(path_value)
    if preserve_trailing_slash and normalized_path.endswith("/"):
        lookup_path = normalized_path[:-1]
    else:
        lookup_path = normalized_path
    if not normalized_path or not mod_root_path or os.path.isabs(normalized_path):
        return normalized_path
    direct_path = os.path.join(mod_root_path, lookup_path)
    if os.path.exists(direct_path):
        return normalized_path
    matches = []
    for prefix in _get_legacy_layout_prefixes(mod_root_path):
        candidate = os.path.join(mod_root_path, prefix, lookup_path)
        if os.path.exists(candidate):
            migrated = f"{prefix}/{lookup_path}" if lookup_path else prefix
            if preserve_trailing_slash:
                migrated = migrated.rstrip("/") + "/"
            matches.append(migrated)
    return matches[0] if len(matches) == 1 else normalized_path


def _sanitize_files(
    files_data: dict,
    game: str,
    mod_root_path: str | None = None,
) -> dict[str, dict]:
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
        data_file_path = _trim_string(
            ch_info.get("data_file_path") or ch_info.get("data_file_url"),
            MOD_FIELD_LIMITS["file_value"],
        )
        if data_file_path:
            entry["data_file_path"] = _migrate_legacy_layout_path(
                data_file_path, mod_root_path
            )
        extra_files = _sanitize_extra_files(ch_info.get("extra_files", []))
        if extra_files:
            entry["extra_files"] = []
            for extra_file in extra_files:
                if isinstance(extra_file, dict):
                    entry["extra_files"].append(
                        {
                            **extra_file,
                            "file_path": _migrate_legacy_layout_path(
                                extra_file["file_path"], mod_root_path
                            ),
                        }
                    )
                else:
                    entry["extra_files"].append(
                        _migrate_legacy_layout_path(extra_file, mod_root_path)
                    )
            if not entry["extra_files"]:
                entry.pop("extra_files", None)
        normalized[file_key] = entry
    return normalized


def normalize_mod_config_data(
    config_data: dict,
    mod_root_path: str | None = None,
) -> bool:
    """Normalize config keys and values to the canonical 1.0.0 schema."""
    if not isinstance(config_data, dict):
        return False
    changed = migrate_mod_config_legacy_fields(config_data)
    canonical = {
        "config_version": MOD_CONFIG_VERSION,
        "id": _trim_string(
            _get_metadata_value(config_data, "id"), MOD_FIELD_LIMITS["id"]
        ),
        "name": _trim_string(
            _get_metadata_value(config_data, "name"), MOD_FIELD_LIMITS["name"]
        ),
        "version": _trim_string(
            _get_metadata_value(config_data, "version"), MOD_FIELD_LIMITS["version"]
        )
        or "1.0.0",
        "author": _trim_string(
            _get_metadata_value(config_data, "author"), MOD_FIELD_LIMITS["author"]
        ),
        "description": _trim_string(
            _get_metadata_value(config_data, "description"),
            MOD_FIELD_LIMITS["description"],
        ),
        "homepage": _normalize_homepage(_get_metadata_value(config_data, "homepage")),
        "icon": _trim_string(
            _get_metadata_value(config_data, "icon"), MOD_FIELD_LIMITS["icon"]
        ),
        "game": _trim_string(
            _get_metadata_value(config_data, "game"), MOD_FIELD_LIMITS["game"]
        )
        or "deltarune",
        "game_version": _trim_string(
            _get_metadata_value(config_data, "game_version"),
            MOD_FIELD_LIMITS["file_value"],
        ),
        "tags": _sanitize_tags(_get_metadata_value(config_data, "tags")),
        "info_files": _sanitize_info_files(config_data.get("info_files")),
        "files": {},
    }
    canonical["files"] = _sanitize_files(
        config_data.get("files", {}),
        canonical["game"],
        mod_root_path,
    )
    ordered = {
        key: canonical[key]
        for key in MOD_RUNTIME_KEY_ORDER
        if canonical[key] not in (None, "", [], {})
    }
    if list(config_data.items()) != list(ordered.items()):
        changed = True
        config_data.clear()
        config_data.update(ordered)
    return changed


def build_mod_config_data(config_data: dict) -> dict:
    """Build the canonical on-disk mod config payload."""
    normalized = dict(config_data or {})
    normalize_mod_config_data(normalized)
    metadata = {
        key: normalized[key]
        for key in MOD_METADATA_KEY_ORDER
        if normalized.get(key) not in (None, "", [], {})
    }
    info_files = normalized.get("info_files", {})
    files = normalized.get("files", {})
    return {
        key: value
        for key, value in (
            ("config_version", MOD_CONFIG_VERSION),
            ("metadata", metadata),
            ("info_files", info_files),
            ("files", files),
        )
        if value not in (None, "", [], {})
    }


def parse_extra_files_raw(
    extra_files_raw,
    mod_root_path: str | None = None,
) -> list[str]:
    """Parse extra_files data from a chapter config into a list."""
    entries = parse_extra_file_entries_raw(extra_files_raw, mod_root_path)
    return [entry["file_path"] for entry in entries if entry["status"] == "install"]


def parse_extra_file_entries_raw(
    extra_files_raw,
    mod_root_path: str | None = None,
) -> list[dict[str, str]]:
    """Parse extra files while preserving their extensible deployment status."""
    result: list[dict[str, str]] = []
    if not extra_files_raw:
        return result

    def _resolve_runtime_path(file_path: str) -> str:
        normalized_path = _normalize_extra_file_path(file_path)
        if not normalized_path or not mod_root_path or os.path.isabs(normalized_path):
            return normalized_path
        preserve_trailing_slash = normalized_path.endswith("/")
        join_path = normalized_path[:-1] if preserve_trailing_slash else normalized_path
        resolved = os.path.normpath(os.path.join(mod_root_path, join_path))
        return resolved + os.sep if preserve_trailing_slash else resolved

    def _append_entry(file_path: str, status: object = "install") -> None:
        resolved_path = _resolve_runtime_path(file_path)
        if resolved_path:
            normalized_status = str(status or "install").strip().lower()
            result.append({"file_path": resolved_path, "status": normalized_status})

    if isinstance(extra_files_raw, list):
        for ef_data in extra_files_raw:
            if isinstance(ef_data, dict):
                file_path = ef_data.get("file_path") or ef_data.get("url", "")
                if isinstance(file_path, str) and file_path:
                    _append_entry(file_path, ef_data.get("status"))
            elif isinstance(ef_data, str):
                _append_entry(ef_data)
    elif isinstance(extra_files_raw, dict):
        for filenames in extra_files_raw.values():
            if isinstance(filenames, list):
                for filename in filenames:
                    _append_entry(filename)
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


def resolve_mod_file_path(mod_folder_path: str | None, stored_path: str | None) -> str:
    """Resolve a stored mod-relative path against the mod root."""
    if not stored_path:
        return ""
    path_value = str(stored_path).replace("\\", "/").strip()
    if not path_value:
        return ""
    if os.path.isabs(path_value):
        return path_value
    if not mod_folder_path:
        return path_value
    migrated_path = _migrate_legacy_layout_path(path_value, mod_folder_path)
    return os.path.normpath(os.path.join(mod_folder_path, migrated_path))


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
    for raw_file_key, ch_info in _sanitize_files(
        files_data, game or "deltarune"
    ).items():
        normalized[raw_file_key] = {
            "description": ch_info.get("description"),
            "data_file_path": ch_info.get("data_file_path"),
            "extra_files": parse_extra_files_raw(ch_info.get("extra_files", [])),
        }
    return normalized
