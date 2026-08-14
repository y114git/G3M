"""Shared AFOM/CYOP helpers for Pizza Tower install and launch flows."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Callable

from utils.file_utils import remove_archive_extension

logger = logging.getLogger(__name__)


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
    backup_or_mark: Callable[[str], object],
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
    backup_or_mark: Callable[[str], object],
    logger=None,
) -> bool:
    try:
        resolved_root = os.path.normcase(os.path.realpath(source_root))
        pending = [(source_root, "")]
        visited_dirs: set[str] = set()
        while pending:
            source_dir, rel_dir = pending.pop()
            real_dir = os.path.normcase(os.path.realpath(source_dir))
            if real_dir in visited_dirs:
                continue
            visited_dirs.add(real_dir)
            with os.scandir(source_dir) as entries:
                for entry in entries:
                    rel_path = os.path.join(rel_dir, entry.name)
                    try:
                        if entry.is_symlink():
                            if logger:
                                logger.debug("Skipping symlink: %s", entry.path)
                            continue
                        resolved_entry = os.path.normcase(os.path.realpath(entry.path))
                        if os.path.commonpath((resolved_root, resolved_entry)) != resolved_root:
                            if logger:
                                logger.warning("Skipping path outside source root: %s", entry.path)
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append((entry.path, rel_path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            if logger:
                                logger.debug("Skipping broken link: %s", entry.path)
                            continue
                    except OSError:
                        if logger:
                            logger.debug("Skipping inaccessible link: %s", entry.path)
                        continue
                    target_file = os.path.join(target_root, rel_path)
                    os.makedirs(os.path.dirname(target_file), exist_ok=True)
                    if backup_or_mark(target_file) is False:
                        return False
                    shutil.copy2(entry.path, target_file)
        return True
    except Exception as e:
        if logger:
            logger.debug("_copy_tree_contents failed: %s", e)
        return False


def _extract_archive_contents(
    archive_path: str,
    target_root: str,
    backup_or_mark: Callable[[str], object],
    extract_archive,
) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix="g3m_afom_towers_") as temp_dir:
            extract_archive(archive_path, temp_dir)
            return _copy_tree_contents(temp_dir, target_root, backup_or_mark)
    except Exception:
        return False
