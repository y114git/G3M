"""Mod directory scanning, validation, and corruption cleanup."""

import json
import logging
import os
from typing import Any

from config.config import LEGACY_MOD_CONFIG_FILENAME, MOD_CONFIG_FILENAME


class ModFolderInfo:
    """Information about a mod folder and its configuration."""

    __slots__ = ("config_data", "config_mtime", "folder_name", "folder_path", "key")

    def __init__(
        self,
        key: str,
        folder_path: str,
        folder_name: str,
        config_data: dict,
        config_mtime: float,
    ) -> None:
        self.key = key
        self.folder_path = folder_path
        self.folder_name = folder_name
        self.config_data = config_data
        self.config_mtime = config_mtime


def normalize_mod_cache(cache: dict[str, Any]) -> dict[str, ModFolderInfo]:
    """Convert any dict-based cache entries to ModFolderInfo instances."""
    normalized_cache: dict[str, ModFolderInfo] = {}
    for key, value in cache.items():
        if isinstance(value, dict):
            normalized_cache[key] = ModFolderInfo(
                key=value.get("key") or value.get("mod_key", key),
                folder_path=value.get("folder_path", ""),
                folder_name=value.get("folder_name", ""),
                config_data=value.get("config_data", {}),
                config_mtime=value.get("config_mtime", 0.0),
            )
        elif isinstance(value, ModFolderInfo):
            normalized_cache[key] = value
    return normalized_cache


def validate_mod_config(config_data: dict, config_path: str, folder_name: str) -> bool:
    """Validate that a mod config dict has the required fields and correct types."""
    if not isinstance(config_data, dict):
        logging.warning(
            f"validate_mod_config: Config is not a dictionary in {config_path}, skipping mod",
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
                "config_type": type(config_data).__name__,
            },
        )
        return False
    has_name = bool(config_data.get("name"))
    has_key = bool(config_data.get("key") or config_data.get("mod_key"))
    if not has_name and (not has_key):
        logging.warning(
            f"validate_mod_config: Config missing both name and key in {config_path}, skipping mod",
            extra={"mod_folder": folder_name, "config_path": config_path},
        )
        return False
    if "name" in config_data and (not isinstance(config_data["name"], str)):
        logging.warning(
            f'validate_mod_config: Config field "name" has invalid type in {config_path}, expected string',
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
                "name_type": type(config_data["name"]).__name__,
            },
        )
        return False
    key_value = config_data.get("key") or config_data.get("mod_key")
    if key_value and (not isinstance(key_value, str)):
        logging.warning(
            f'validate_mod_config: Config field "key" has invalid type in {config_path}, expected string',
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
                "key_type": type(key_value).__name__,
            },
        )
        return False
    if "files" in config_data and (not isinstance(config_data["files"], dict)):
        logging.warning(
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
        logging.warning(
            f'validate_mod_config: Config field "tags" has invalid type in {config_path}, expected list or None',
            extra={
                "mod_folder": folder_name,
                "config_path": config_path,
                "tags_type": type(config_data["tags"]).__name__,
            },
        )
        return False
    return True


def scan_mods_directory(
    mods_dir: str, old_cache: dict[str, ModFolderInfo] | None = None
) -> tuple[dict[str, ModFolderInfo], dict[str, str]]:
    """Scan the mods directory and return (cache, mods_by_name).

    Returns:
        Tuple of (mod cache dict, mods_by_name dict mapping lowercase name -> key)
    """
    cache: dict[str, ModFolderInfo] = {}
    mods_by_name: dict[str, str] = {}
    if old_cache is None:
        old_cache = {}

    old_cache = normalize_mod_cache(old_cache)

    _path_to_key: dict[str, str] = {
        info.folder_path: key for key, info in old_cache.items()
    }
    if not os.path.exists(mods_dir):
        return cache, mods_by_name
    from utils.file_utils import migrate_mod_config

    try:
        with os.scandir(mods_dir) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                folder_name = entry.name
                folder_path = entry.path
                config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                if not os.path.exists(config_path):
                    migrate_mod_config(folder_path)
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
                    except (OSError, PermissionError):
                        pass
                    if not found_nested:
                        continue
                try:
                    st = os.stat(config_path)
                    if st.st_size == 0:
                        logging.warning(
                            f"scan_mods_directory: Corrupted config detected (0 bytes) in {config_path}, skipping mod",
                            extra={
                                "mod_folder": folder_name,
                                "config_path": config_path,
                            },
                        )
                        continue
                    config_mtime = st.st_mtime
                    key = _path_to_key.get(folder_path)
                    if key is not None:
                        old_info = old_cache[key]
                        if config_mtime <= old_info.config_mtime:
                            cache[key] = old_info
                            mod_name = old_info.config_data.get("name", "")
                            if mod_name:
                                mods_by_name[mod_name.lower()] = key
                            continue

                    try:
                        with open(config_path, encoding="utf-8") as f:
                            config_data = json.load(f)
                        if not config_data or not isinstance(config_data, dict):
                            logging.warning(
                                f"scan_mods_directory: Empty config data in {config_path}, skipping mod",
                                extra={
                                    "mod_folder": folder_name,
                                    "config_path": config_path,
                                },
                            )
                            continue
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
                        logging.warning(
                            f"scan_mods_directory: Config error in {config_path}: {e}",
                            extra={
                                "mod_folder": folder_name,
                                "config_path": config_path,
                            },
                        )
                        continue
                    key = config_data.get("key") or config_data.get("mod_key") or ""
                    cache_key = key if key else f"__no_key_{folder_path}"
                    mod_info = ModFolderInfo(
                        key=key,
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
                    logging.warning(
                        f"scan_mods_directory: Corrupted config detected (failed to access) in {config_path}: {e}",
                        exc_info=True,
                        extra={"mod_folder": folder_name, "config_path": config_path},
                    )
                    continue
                except json.JSONDecodeError as e:
                    logging.warning(
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
                    logging.debug(
                        f"scan_mods_directory: missing key in {config_path}: {e}",
                        extra={
                            "mod_folder": folder_name,
                            "config_path": config_path,
                            "missing_key": str(e),
                        },
                    )
                    continue
    except OSError as e:
        logging.error(
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
                    legacy_config_path = os.path.join(
                        folder_path, LEGACY_MOD_CONFIG_FILENAME
                    )
                    if not os.path.exists(legacy_config_path):
                        is_corrupted = True
                        logging.warning(
                            f"cleanup_corrupted_mods: Missing mod_config.json in {folder_name}, marking as corrupted"
                        )
                else:
                    try:
                        config_size = os.path.getsize(config_path)
                        if config_size == 0:
                            is_corrupted = True
                            logging.warning(
                                f"cleanup_corrupted_mods: mod_config.json is 0 bytes in {folder_name}, marking as corrupted"
                            )
                        else:
                            try:
                                with open(config_path, encoding="utf-8") as f:
                                    json.load(f)
                            except (
                                json.JSONDecodeError,
                                OSError,
                                PermissionError,
                            ) as e:
                                is_corrupted = True
                                logging.warning(
                                    f"cleanup_corrupted_mods: Invalid JSON in mod_config.json for {folder_name}: {e}, marking as corrupted"
                                )
                    except (OSError, PermissionError) as e:
                        is_corrupted = True
                        logging.warning(
                            f"cleanup_corrupted_mods: Cannot access mod_config.json in {folder_name}: {e}, marking as corrupted"
                        )
                if is_corrupted:
                    try:
                        from utils.file_utils import safe_rmtree

                        if safe_rmtree(folder_path):
                            removed_count += 1
                            logging.info(
                                f"cleanup_corrupted_mods: Removed corrupted mod folder: {folder_name}"
                            )
                        else:
                            logging.warning(
                                f"cleanup_corrupted_mods: Failed to remove corrupted mod folder: {folder_name}"
                            )
                    except Exception as e:
                        logging.error(
                            f"cleanup_corrupted_mods: Error removing corrupted mod folder {folder_name}: {e}",
                            exc_info=True,
                        )
    except OSError as e:
        logging.error(
            f"cleanup_corrupted_mods: Failed to scan mods directory: {e}", exc_info=True
        )
    if removed_count > 0:
        logging.info(
            f"cleanup_corrupted_mods: Removed {removed_count} corrupted mod(s) during startup cleanup"
        )
    return removed_count
