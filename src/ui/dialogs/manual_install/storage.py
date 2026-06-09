"""Storage and file-assembly helpers for ManualModInstallDialog."""

from __future__ import annotations

import os
import shutil
import time

from config.config import MOD_DOCUMENTATION_EXTENSIONS
from utils.file_utils import get_chapter_folder_name, get_unique_mod_dir


def copy_file_to_relative_path(
    target_mod_dir: str,
    source_path: str,
    relative_path: str,
) -> str:
    normalized_relative = relative_path.replace("\\", "/").strip().strip("/")
    if not normalized_relative:
        normalized_relative = os.path.basename(source_path)
    target_path = os.path.join(target_mod_dir, normalized_relative.replace("/", os.sep))
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    base_name, extension = os.path.splitext(target_path)
    suffix = 1
    while os.path.exists(target_path):
        target_path = f"{base_name}_{suffix}{extension}"
        suffix += 1
    shutil.copy2(source_path, target_path)
    return os.path.relpath(target_path, target_mod_dir).replace("\\", "/")


def storage_prefix_for_chapter(chapter_id: str, *, game: str, is_multi_tab: bool) -> str:
    if is_multi_tab:
        return get_chapter_folder_name(chapter_id, game=game)
    return ""


def join_storage_path(
    chapter_id: str,
    *parts: str,
    game: str,
    is_multi_tab: bool,
) -> str:
    normalized_parts = []
    prefix = storage_prefix_for_chapter(
        chapter_id,
        game=game,
        is_multi_tab=is_multi_tab,
    )
    if prefix:
        normalized_parts.append(prefix)
    for part in parts:
        text = str(part or "").replace("\\", "/").strip("/")
        if text:
            normalized_parts.append(text)
    return "/".join(normalized_parts)


def copy_root_docs_to_mod(
    *,
    target_mod_dir: str,
    all_files: list[tuple[str, str]],
) -> None:
    for file_path, relative_path in all_files:
        if os.path.dirname(relative_path):
            continue
        if os.path.splitext(file_path)[1].lower() not in MOD_DOCUMENTATION_EXTENSIONS:
            continue
        if not os.path.isfile(file_path):
            continue
        shutil.copy2(file_path, os.path.join(target_mod_dir, os.path.basename(file_path)))


def build_manual_mod_identity(
    *,
    gamebanana_metadata: dict,
    source_file_path: str | None,
) -> tuple[str, str]:
    if gamebanana_metadata.get("mod_id"):
        item_type = gamebanana_metadata.get("item_type", "mod").lower()
        mod_id = f"gb_{item_type}_{gamebanana_metadata['mod_id']}"
    else:
        mod_id = f"local_manual_{int(time.time())}"

    if gamebanana_metadata.get("name"):
        mod_name = gamebanana_metadata["name"]
    elif source_file_path:
        from utils.file_utils import remove_archive_extension

        archive_name = os.path.basename(source_file_path)
        mod_name = remove_archive_extension(archive_name)
    else:
        mod_name = "Manual Mod"
    return mod_id, mod_name


def create_manual_mod_dir(*, mods_dir: str, mod_name: str) -> tuple[str, str]:
    folder_name = get_unique_mod_dir(mods_dir, mod_name)
    target_mod_dir = os.path.join(mods_dir, folder_name)
    os.makedirs(target_mod_dir, exist_ok=True)
    return folder_name, target_mod_dir
