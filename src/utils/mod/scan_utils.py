"""Mod directory scanning, validation, and corruption cleanup."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from config.config import MOD_CONFIG_FILENAME
from utils.file_utils import load_json
from utils.mod.config_parser import (
    MOD_ALLOWED_TAGS,
    MOD_CONFIG_VERSION,
    MOD_FIELD_LIMITS,
    normalize_mod_config_data,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModFolderInfo:
    """Information about a mod folder and its configuration."""

    id: str
    folder_path: str
    folder_name: str
    config_data: dict
    config_mtime: float


def normalize_mod_cache(cache: dict[str, Any]) -> dict[str, ModFolderInfo]:
    """Convert any dict-based cache entries to ModFolderInfo instances."""
    normalized_cache: dict[str, ModFolderInfo] = {}
    for mod_id, value in cache.items():
        if isinstance(value, dict):
            normalized_cache[mod_id] = ModFolderInfo(
                id=value.get("id", mod_id),
                folder_path=value.get("folder_path", ""),
                folder_name=value.get("folder_name", ""),
                config_data=value.get("config_data", {}),
                config_mtime=value.get("config_mtime", 0.0),
            )
        elif isinstance(value, ModFolderInfo):
            normalized_cache[mod_id] = value
    return normalized_cache


def validate_mod_config(config_data: dict, config_path: str, folder_name: str) -> bool:
    """Validate that a mod config dict has the required fields and correct types."""
    required_string_fields = (
        ("config_version", MOD_CONFIG_VERSION, None),
        ("id", None, MOD_FIELD_LIMITS["id"]),
        ("name", None, MOD_FIELD_LIMITS["name"]),
        ("version", None, MOD_FIELD_LIMITS["version"]),
        ("game", None, MOD_FIELD_LIMITS["game"]),
    )
    for field_name, expected_value, max_len in required_string_fields:
        value = config_data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            logger.warning(
                "validate_mod_config: Missing required string field %s in %s, skipping mod",
                field_name,
                config_path,
                extra={"mod_folder": folder_name, "config_path": config_path},
            )
            return False
        if expected_value is not None and value != expected_value:
            logger.warning(
                "validate_mod_config: Invalid %s=%s in %s, skipping mod",
                field_name,
                value,
                config_path,
                extra={"mod_folder": folder_name, "config_path": config_path},
            )
            return False
        if max_len is not None and len(value) > max_len:
            logger.warning(
                "validate_mod_config: Field %s exceeds limit in %s, skipping mod",
                field_name,
                config_path,
                extra={"mod_folder": folder_name, "config_path": config_path},
            )
            return False
    if len(str(config_data.get("description", ""))) > MOD_FIELD_LIMITS["description"]:
        logger.warning(
            'validate_mod_config: Config field "description" exceeds max length in %s',
            config_path,
            extra={"mod_folder": folder_name, "config_path": config_path},
        )
        return False
    if "homepage" in config_data and (
        not isinstance(config_data["homepage"], str)
        or len(config_data["homepage"]) > MOD_FIELD_LIMITS["homepage"]
    ):
        logger.warning(
            'validate_mod_config: Config field "homepage" is invalid in %s',
            config_path,
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
            },
        )
        return False
    if "files" in config_data and (not isinstance(config_data["files"], dict)):
        logger.warning(
            f'validate_mod_config: Config field "files" has invalid type in {config_path}, expected dict',
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
                "files_type": type(config_data["files"]).__name__,
            },
        )
        return False
    if "tags" in config_data and (
        not isinstance(config_data["tags"], (list, type(None)))
    ):
        logger.warning(
            f'validate_mod_config: Config field "tags" has invalid type in {config_path}, expected list or None',
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
                "tags_type": type(config_data["tags"]).__name__,
            },
        )
        return False
    tags = config_data.get("tags")
    if isinstance(tags, list) and any(tag not in MOD_ALLOWED_TAGS for tag in tags):
        logger.warning(
            'validate_mod_config: Config field "tags" contains invalid values in %s',
            config_path,
            extra={"mod_folder": folder_name, "config_path": config_path},
        )
        return False
    for file_key, file_info in (config_data.get("files") or {}).items():
        if len(str(file_key)) > MOD_FIELD_LIMITS["file_value"] or not isinstance(
            file_info, dict
        ):
            logger.warning(
                "validate_mod_config: Invalid file entry %s in %s",
                file_key,
                config_path,
                extra={"mod_folder": folder_name, "config_path": config_path},
            )
            return False
        for field_name in ("description", "data_file_path"):
            field_value = file_info.get(field_name)
            if field_value not in (None, "") and (
                not isinstance(field_value, str)
                or len(field_value) > MOD_FIELD_LIMITS["file_value"]
            ):
                return False
        extra_files = file_info.get("extra_files", [])
        if not isinstance(extra_files, list):
            return False
        for extra_file in extra_files:
            if not isinstance(extra_file, str) or len(extra_file) > MOD_FIELD_LIMITS[
                "file_value"
            ]:
                return False
    return True


def scan_mods_directory(
    mods_dir: str, old_cache: dict[str, ModFolderInfo] | None = None
) -> tuple[dict[str, ModFolderInfo], dict[str, str]]:
    """Scan the mods directory and return (cache, mods_by_name).

    Returns:
        Tuple of (mod cache dict, mods_by_name dict mapping lowercase name -> id)
    """
    cache: dict[str, ModFolderInfo] = {}
    mods_by_name: dict[str, str] = {}
    if old_cache is None:
        old_cache = {}

    old_cache = normalize_mod_cache(old_cache)

    path_to_id: dict[str, str] = {
        info.folder_path: mod_id for mod_id, info in old_cache.items()
    }
    if not os.path.exists(mods_dir):
        return cache, mods_by_name
    try:
        with os.scandir(mods_dir) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                folder_name = entry.name
                folder_path = entry.path
                config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                if not os.path.exists(config_path):
                    found_nested = False
                    try:
                        with os.scandir(folder_path) as sub_entries:
                            for sub in sub_entries:
                                if sub.is_dir():
                                    nested_config_path = os.path.join(
                                        sub.path, MOD_CONFIG_FILENAME
                                    )
                                    if os.path.exists(nested_config_path):
                                        config_path = nested_config_path
                                        folder_path = sub.path
                                        found_nested = True
                                        break
                    except (OSError, PermissionError) as error:
                        logger.debug("Best-effort operation failed: %s", error, exc_info=True)
                    if not found_nested:
                        continue
                try:
                    st = os.stat(config_path)
                    if st.st_size == 0:
                        logger.warning(
                            f"scan_mods_directory: Corrupted config detected (0 bytes) in {config_path}, skipping mod",
                            extra={
                                "mod_folder": folder_name,
                                "config_path": config_path,
                            },
                        )
                        continue
                    config_mtime = st.st_mtime
                    mod_id = path_to_id.get(folder_path)
                    if mod_id is not None:
                        old_info = old_cache[mod_id]
                        if config_mtime <= old_info.config_mtime:
                            cache[mod_id] = old_info
                            mod_name = old_info.config_data.get("name", "")
                            if mod_name:
                                mods_by_name[mod_name.lower()] = mod_id
                            continue

                    try:
                        config_data = load_json(
                            config_path, persist_normalized=False
                        )
                        if not config_data or not isinstance(config_data, dict):
                            logger.warning(
                                f"scan_mods_directory: Empty config data in {config_path}, skipping mod",
                                extra={
                                    "mod_folder": folder_name,
                                    "config_path": config_path,
                                },
                            )
                            continue
                        normalize_mod_config_data(
                            config_data, mod_root_path=folder_path
                        )
                        if not validate_mod_config(
                            config_data, config_path, folder_name
                        ):
                            continue
                    except (
                        json.JSONDecodeError,
                        TypeError,
                        ValueError,
                        AttributeError,
                    ) as e:
                        logger.warning(
                            f"scan_mods_directory: Config error in {config_path}: {e}",
                            extra={
                                "mod_folder": folder_name,
                                "config_path": config_path,
                            },
                        )
                        continue
                    mod_id = (config_data.get("id") or "").strip()
                    if not mod_id:
                        logger.warning(
                            f"scan_mods_directory: Config missing usable id in {config_path}, skipping mod",
                            extra={
                                "mod_folder": folder_name,
                                "config_path": config_path,
                            },
                        )
                        continue
                    cache_key = mod_id
                    mod_info = ModFolderInfo(
                        id=mod_id,
                        folder_path=folder_path,
                        folder_name=folder_name,
                        config_data=config_data,
                        config_mtime=config_mtime,
                    )
                    cache[cache_key] = mod_info
                    mod_name = config_data.get("name", "")
                    if mod_name:
                        mods_by_name[mod_name.lower()] = cache_key
                except (OSError, PermissionError) as e:
                    logger.warning(
                        f"scan_mods_directory: Corrupted config detected (failed to access) in {config_path}: {e}",
                        exc_info=True,
                        extra={"mod_folder": folder_name, "config_path": config_path},
                    )
                    continue
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"scan_mods_directory: Corrupted config detected (invalid JSON) in {config_path}: {e}",
                        exc_info=True,
                        extra={
                            "mod_folder": folder_name,
                            "config_path": config_path,
                            "json_line": getattr(e, "lineno", None),
                            "json_col": getattr(e, "colno", None),
                        },
                    )
                    continue
                except KeyError as e:
                    logger.debug(
                        f"scan_mods_directory: missing id in {config_path}: {e}",
                        extra={
                            "mod_folder": folder_name,
                            "config_path": config_path,
                            "missing_key": str(e),
                        },
                    )
                    continue
    except OSError as e:
        logger.error(
            f"scan_mods_directory: failed to list directory {mods_dir}: {e}",
            exc_info=True,
            extra={"mods_dir": mods_dir},
        )
    return cache, mods_by_name


def cleanup_corrupted_mods(mods_dir: str) -> int:
    """Remove mod folders with missing or corrupted config files. Returns count removed."""
    if not os.path.exists(mods_dir):
        return 0
    removed_count = 0
    try:
        with os.scandir(mods_dir) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                folder_path = entry.path
                folder_name = entry.name
                config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                is_corrupted = False
                if not os.path.exists(config_path):
                    nested_config_path = None
                    try:
                        child_dirs = [
                            sub.path
                            for sub in os.scandir(folder_path)
                            if sub.is_dir(follow_symlinks=False)
                        ]
                    except (OSError, PermissionError):
                        child_dirs = []
                    if len(child_dirs) == 1:
                        candidate = os.path.join(child_dirs[0], MOD_CONFIG_FILENAME)
                        if os.path.exists(candidate):
                            nested_config_path = candidate
                    if nested_config_path:
                        config_path = nested_config_path
                    else:
                        is_corrupted = True
                        logger.warning(
                            f"cleanup_corrupted_mods: Missing mod_config.json in {folder_name}, marking as corrupted"
                        )
                else:
                    try:
                        config_size = os.path.getsize(config_path)
                        if config_size == 0:
                            is_corrupted = True
                            logger.warning(
                                f"cleanup_corrupted_mods: mod_config.json is 0 bytes in {folder_name}, marking as corrupted"
                            )
                        else:
                            try:
                                load_json(config_path, persist_normalized=False)
                            except (
                                json.JSONDecodeError,
                                OSError,
                                PermissionError,
                            ) as e:
                                is_corrupted = True
                                logger.warning(
                                    f"cleanup_corrupted_mods: Invalid JSON in mod_config.json for {folder_name}: {e}, marking as corrupted"
                                )
                    except (OSError, PermissionError) as e:
                        is_corrupted = True
                        logger.warning(
                            f"cleanup_corrupted_mods: Cannot access mod_config.json in {folder_name}: {e}, marking as corrupted"
                        )
                if is_corrupted:
                    try:
                        from utils.file_utils import safe_rmtree

                        if safe_rmtree(folder_path):
                            removed_count += 1
                            logger.info(
                                f"cleanup_corrupted_mods: Removed corrupted mod folder: {folder_name}"
                            )
                        else:
                            logger.warning(
                                f"cleanup_corrupted_mods: Failed to remove corrupted mod folder: {folder_name}"
                            )
                    except Exception as e:
                        logger.error(
                            f"cleanup_corrupted_mods: Error removing corrupted mod folder {folder_name}: {e}",
                            exc_info=True,
                        )
    except OSError as e:
        logger.error(
            f"cleanup_corrupted_mods: Failed to scan mods directory: {e}", exc_info=True
        )
    if removed_count > 0:
        logger.info(
            f"cleanup_corrupted_mods: Removed {removed_count} corrupted mod(s) during startup cleanup"
        )
    return removed_count
