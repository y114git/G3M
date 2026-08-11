"""Mod type, asset, and resource detection utilities for the patching system."""

import logging
import os
import platform
import re
import zipfile

from config.config import (
    GAME_DATA_FILE_EXTENSIONS,
    MOD_TYPE_CSX,
    MOD_TYPE_DATAFILE,
    MOD_TYPE_G3MPATCH,
    MOD_TYPE_OVERRIDES_ONLY,
    MOD_TYPE_XDELTA,
)
from models.game_modes import get_game
from utils.path_utils import (
    find_supported_game_data_file,
    get_supported_game_data_filenames,
)

logger = logging.getLogger(__name__)


def find_files_by_extension(
    directory: str, extensions: list[str], exact_names: list[str] | None = None
) -> list[str]:
    found_files = []
    if not os.path.isdir(directory):
        return found_files
    extensions_lower = [ext.lower() for ext in extensions]
    exact_names_lower = [name.lower() for name in exact_names] if exact_names else None
    for root, _dirs, files in os.walk(directory):
        for file in files:
            file_lower = file.lower()
            if (exact_names_lower and file_lower in exact_names_lower) or any(
                file_lower.endswith(ext) for ext in extensions_lower
            ):
                found_files.append(os.path.join(root, file))
    return found_files


def is_g3mpatch_package(path: str) -> bool:
    lower_path = str(path or "").lower()
    if lower_path.endswith(".g3mpatch"):
        return True
    if not lower_path.endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            archive.getinfo("g3mpatch.json")
        return True
    except Exception:
        return False


def find_ready_data_win_files(mod_source_dir: str, logger=None) -> list[str]:
    ready_files = []
    if not os.path.isdir(mod_source_dir):
        return ready_files
    data_file_names = get_supported_game_data_filenames()
    main_files = find_files_by_extension(
        mod_source_dir, list(GAME_DATA_FILE_EXTENSIONS), list(data_file_names)
    )
    for file_path in main_files:
        file_lower = os.path.basename(file_path).lower()
        if file_lower in [name.lower() for name in data_file_names]:
            ready_files.append(file_path)
            if logger:
                logger.debug(f"Found ready data file: {file_path}")
        elif file_lower.endswith(GAME_DATA_FILE_EXTENSIONS):
            ready_files.append(file_path)
            if logger:
                logger.debug(f"Found ready data file by extension: {file_path}")
    if logger:
        logger.info(
            f"find_ready_data_win_files: found {len(ready_files)} ready data file(s) in {mod_source_dir}"
        )
    return ready_files


def classify_patch_file(path: str | None) -> tuple[str | None, str]:
    if not path or not os.path.isfile(path):
        return (None, MOD_TYPE_OVERRIDES_ONLY)
    lower_path = str(path).lower()
    if is_g3mpatch_package(path):
        return (path, MOD_TYPE_G3MPATCH)
    if lower_path.endswith((".xdelta", ".vcdiff")):
        return (path, MOD_TYPE_XDELTA)
    if lower_path.endswith(".csx"):
        return (path, MOD_TYPE_CSX)
    if lower_path.endswith(GAME_DATA_FILE_EXTENSIONS):
        return (path, MOD_TYPE_DATAFILE)
    return (None, MOD_TYPE_OVERRIDES_ONLY)


def classify_mod_directory(mod_source_dir: str) -> tuple[str | None, str]:
    """Classify a mod directory with one filesystem traversal."""
    if not os.path.isdir(mod_source_dir):
        return (None, MOD_TYPE_OVERRIDES_ONLY)

    first_g3mpatch = None
    first_xdelta = None
    first_csx = None
    first_data_file = None
    for root, _dirs, files in os.walk(mod_source_dir):
        is_root = os.path.normcase(root) == os.path.normcase(mod_source_dir)
        for filename in files:
            path = os.path.join(root, filename)
            lower_name = filename.lower()
            if first_g3mpatch is None and is_g3mpatch_package(path):
                first_g3mpatch = path
            if (
                first_xdelta is None
                and is_root
                and lower_name.endswith((".xdelta", ".vcdiff"))
            ):
                first_xdelta = path
            if first_csx is None and lower_name.endswith(".csx"):
                first_csx = path
            if first_data_file is None and lower_name.endswith(GAME_DATA_FILE_EXTENSIONS):
                first_data_file = path

    if first_g3mpatch:
        return (first_g3mpatch, MOD_TYPE_G3MPATCH)
    if first_xdelta:
        return (first_xdelta, MOD_TYPE_XDELTA)
    if first_csx:
        return (first_csx, MOD_TYPE_CSX)
    if first_data_file:
        return (first_data_file, MOD_TYPE_DATAFILE)
    return (None, MOD_TYPE_OVERRIDES_ONLY)


def find_data_win(
    target_dir: str, preferred_name: str = "", game_id: str = ""
) -> str | None:
    game = get_game(game_id) if game_id else None
    explicit_name = getattr(game, "data_file_name", "") if game else ""
    if explicit_name:
        return find_supported_game_data_file(
            target_dir,
            explicit_name,
            fallback_to_supported_names=False,
        )
    return find_supported_game_data_file(target_dir, preferred_name)


def extract_chapter_id_from_path(path: str) -> str | None:
    match = re.search(r"chapter[_-]?(\d+)", path, re.IGNORECASE)
    if match:
        return match.group(1)
    if "demo" in path.lower():
        return "deltarunedemo"
    return None


def find_target_files_for_xdelta(target_dir: str, patch_filename: str) -> list[str]:
    target_files = []
    if not os.path.isdir(target_dir):
        return target_files
    excluded_files = {
        name.lower() for name in get_supported_game_data_filenames(patch_filename)
    }
    patch_base_lower = os.path.splitext(patch_filename)[0].lower()
    for root, _dirs, files in os.walk(target_dir):
        for file in files:
            file_lower = file.lower()
            if file_lower in excluded_files:
                continue
            if file_lower == patch_base_lower:
                target_files.append(os.path.join(root, file))
    return target_files


def resolve_macos_path(base_path: str, app_name: str) -> str:
    if platform.system() != "Darwin":
        return base_path
    if base_path.endswith(".app"):
        return os.path.join(base_path, "Contents", "Resources")
    app_path = os.path.join(base_path, app_name)
    if os.path.isdir(app_path):
        return os.path.join(app_path, "Contents", "Resources")
    return base_path


def get_file_resources(obj_dir: str, subdir: str, exts, exclude=None) -> list:
    p = os.path.join(obj_dir, subdir)
    if not os.path.exists(p):
        return []
    return [
        os.path.splitext(f)[0]
        for f in os.listdir(p)
        if f.endswith(exts) and (not exclude or not f.endswith(exclude))
    ]
