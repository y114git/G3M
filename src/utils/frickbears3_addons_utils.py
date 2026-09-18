"""Shared helpers for FRICKBEARS3 addon install and launch flows."""

from __future__ import annotations

import os
from collections.abc import Callable

from utils.file_utils import remove_archive_extension
from utils.pizzatower_afom_utils import _copy_tree_contents, _extract_archive_contents


def is_top_level_addons_archive(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized or "/" in normalized:
        return False
    return remove_archive_extension(normalized).lower() == "addons"


def is_addons_subpath(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    return normalized == "addons" or normalized.startswith("addons/")


def apply_frickbears3_addons_from_mod_source(
    mod_source_dir: str,
    *,
    data_dir: str | None,
    backup_or_mark: Callable[[str], object],
    logger,
    extract_archive,
) -> bool:
    source_addons_dir = os.path.join(mod_source_dir, "addons")
    source_archives = [
        os.path.join(mod_source_dir, entry)
        for entry in os.listdir(mod_source_dir)
        if os.path.isfile(os.path.join(mod_source_dir, entry))
        and is_top_level_addons_archive(entry)
    ]
    if not os.path.isdir(source_addons_dir) and not source_archives:
        return True
    if not data_dir:
        logger.error("FRICKBEARS3 data folder is not configured")
        return False
    addons_dir = os.path.join(data_dir, "addons")
    os.makedirs(addons_dir, exist_ok=True)

    if os.path.isdir(source_addons_dir):
        if not _copy_tree_contents(source_addons_dir, addons_dir, backup_or_mark):
            return False
        logger.debug("Applied FRICKBEARS3 addons directory into %s", addons_dir)

    for source_path in source_archives:
        if not _extract_archive_contents(source_path, addons_dir, backup_or_mark, extract_archive):
            return False
        logger.debug("Applied FRICKBEARS3 addons archive %s into %s", source_path, addons_dir)
    return True
