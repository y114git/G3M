"""Shared AFOM/CYOP helpers for Pizza Tower install and launch flows."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable

from utils.file_utils import remove_archive_extension


def get_pizzatower_towers_dir() -> str:
    appdata = os.getenv("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "PizzaTower_GM2", "towers")


def is_top_level_towers_archive(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized or "/" in normalized:
        return False
    return remove_archive_extension(normalized).lower() == "towers"


def is_towers_subpath(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    return normalized == "towers" or normalized.startswith("towers/")


def apply_afom_towers_from_mod_source(
    mod_source_dir: str,
    *,
    backup_or_mark: Callable[[str], None],
    logger,
    extract_archive,
) -> bool:
    towers_dir = get_pizzatower_towers_dir()
    os.makedirs(towers_dir, exist_ok=True)

    source_towers_dir = os.path.join(mod_source_dir, "towers")
    if os.path.isdir(source_towers_dir):
        if not _copy_tree_contents(source_towers_dir, towers_dir, backup_or_mark):
            return False
        logger.debug("Applied AFOM towers directory into %s", towers_dir)

    for entry in os.listdir(mod_source_dir):
        source_path = os.path.join(mod_source_dir, entry)
        if not os.path.isfile(source_path):
            continue
        if not is_top_level_towers_archive(entry):
            continue
        if not _extract_archive_contents(source_path, towers_dir, backup_or_mark, extract_archive):
            return False
        logger.debug("Applied AFOM towers archive %s into %s", source_path, towers_dir)
    return True


def _copy_tree_contents(
    source_root: str,
    target_root: str,
    backup_or_mark: Callable[[str], None],
    logger=None,
) -> bool:
    try:
        for root, _dirs, files in os.walk(source_root):
            rel_root = os.path.relpath(root, source_root)
            rel_root = "" if rel_root == "." else rel_root
            for file_name in files:
                source_file = os.path.join(root, file_name)
                target_file = (
                    os.path.join(target_root, file_name)
                    if not rel_root
                    else os.path.join(target_root, rel_root, file_name)
                )
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                backup_or_mark(target_file)
                shutil.copy2(source_file, target_file)
        return True
    except Exception as e:
        if logger:
            logger.debug("_copy_tree_contents failed: %s", e)
        return False


def _extract_archive_contents(
    archive_path: str,
    target_root: str,
    backup_or_mark: Callable[[str], None],
    extract_archive,
) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix="g3m_afom_towers_") as temp_dir:
            extract_archive(archive_path, temp_dir)
            return _copy_tree_contents(temp_dir, target_root, backup_or_mark)
    except Exception:
        return False
