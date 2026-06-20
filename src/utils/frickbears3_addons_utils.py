"""Shared helpers for FRICKBEARS3 addon install and launch flows."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from utils.file_utils import remove_archive_extension
from utils.pizzatower_afom_utils import _copy_tree_contents, _extract_archive_contents

logger = logging.getLogger(__name__)


def get_frickbears3_addons_dir() -> str:
    localappdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    return os.path.join(localappdata, "Frickbears3", "addons")


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
    backup_or_mark: Callable[[str], None],
    logger,
    extract_archive,
) -> bool:
    addons_dir = get_frickbears3_addons_dir()
    os.makedirs(addons_dir, exist_ok=True)

    source_addons_dir = os.path.join(mod_source_dir, "addons")
    if os.path.isdir(source_addons_dir):
        if not _copy_tree_contents(source_addons_dir, addons_dir, backup_or_mark):
            return False
        logger.debug("Applied FRICKBEARS3 addons directory into %s", addons_dir)

    for entry in os.listdir(mod_source_dir):
        source_path = os.path.join(mod_source_dir, entry)
        if not os.path.isfile(source_path):
            continue
        if not is_top_level_addons_archive(entry):
            continue
        if not _extract_archive_contents(source_path, addons_dir, backup_or_mark, extract_archive):
            return False
        logger.debug("Applied FRICKBEARS3 addons archive %s into %s", source_path, addons_dir)
    return True
