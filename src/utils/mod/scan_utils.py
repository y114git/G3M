"""Mod directory scanning, validation, and corruption cleanup."""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from config.config import MOD_CONFIG_FILENAME
from utils.mod.config import (
    MOD_CONFIG_MAX_BYTES,
    load_mod_config,
    newer_config_mod_name,
)
from utils.mod.config import (
    validate_mod_config as validate_current_mod_config,
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
    config_digest: str = ""


def validate_mod_config(config_data: dict, config_path: str, folder_name: str) -> bool:
    """Validate one current config before adding it to the library cache."""
    issues = validate_current_mod_config(config_data)
    if not issues:
        return True
    logger.warning(
        "validate_mod_config: Invalid current config in %s: %s",
        config_path,
        "; ".join(f"{issue.path}: {issue.message}" for issue in issues),
        extra={"mod_folder": folder_name, "config_path": config_path},
    )
    return False


def scan_mods_directory(
    mods_dir: str,
    old_cache: dict[str, ModFolderInfo] | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
    newer_config_mods: list[str] | None = None,
) -> tuple[dict[str, ModFolderInfo], dict[str, str]]:
    """Scan the mods directory and return (cache, mods_by_name).

    Names of mods saved in a newer config format than this G3M reads are added to `newer_config_mods`.

    Returns:
        Tuple of (mod cache dict, mods_by_name dict mapping lowercase name -> id)
    """
    cache: dict[str, ModFolderInfo] = {}
    mods_by_name: dict[str, str] = {}
    old_cache = old_cache or {}

    path_to_id: dict[str, str] = {
        info.folder_path: mod_id for mod_id, info in old_cache.items()
    }
    if not os.path.exists(mods_dir):
        return cache, mods_by_name
    try:
        with os.scandir(mods_dir) as entries:
            for entry in entries:
                if is_cancelled is not None and is_cancelled():
                    break
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                except OSError:
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
                    if st.st_size > MOD_CONFIG_MAX_BYTES:
                        logger.warning(
                            "scan_mods_directory: Config exceeds the 4 MiB limit in %s, skipping mod",
                            config_path,
                            extra={"mod_folder": folder_name, "config_path": config_path},
                        )
                        continue
                    config_mtime = st.st_mtime
                    config_bytes = Path(config_path).read_bytes()
                    config_digest = hashlib.sha256(config_bytes).hexdigest()
                    mod_id = path_to_id.get(folder_path)
                    if mod_id is not None:
                        old_info = old_cache[mod_id]
                        if old_info.config_digest == config_digest:
                            cache[mod_id] = old_info
                            mod_name = old_info.config_data.get("name", "")
                            if mod_name:
                                mods_by_name[mod_name.lower()] = mod_id
                            continue

                    try:
                        config_data = load_mod_config(config_path)
                        if not config_data or not isinstance(config_data, dict):
                            logger.warning(
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
                        if newer_config_mods is not None and (
                            name := newer_config_mod_name(config_path)
                        ):
                            newer_config_mods.append(name)
                        logger.warning(
                            f"scan_mods_directory: Config error in {config_path}: {e}",
                            extra={
                                "mod_folder": folder_name,
                                "config_path": config_path,
                            },
                        )
                        continue
                    mod_id = str(config_data.get("id") or "").strip()
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
                        config_digest=config_digest,
                    )
                    cache[cache_key] = mod_info
                    mod_name = str(config_data.get("name") or "")
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
