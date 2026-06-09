"""Managed file/storage helpers for ModEditorDialog."""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from pathlib import PureWindowsPath

from utils.file_utils import get_chapter_folder_name
from utils.mod.config_parser import parse_extra_files_raw, resolve_mod_file_path


def resolve_managed_mod_path(file_folder: str, stored_path) -> str | None:
    if not isinstance(stored_path, str):
        return None
    cleaned_path = stored_path.strip().replace("\\", "/").rstrip("/")
    if (
        not cleaned_path
        or os.path.isabs(cleaned_path)
        or PureWindowsPath(cleaned_path).is_absolute()
    ):
        return None
    candidate = resolve_mod_file_path(file_folder, cleaned_path)
    try:
        if os.path.commonpath(
            [os.path.abspath(file_folder), os.path.abspath(candidate)]
        ) != os.path.abspath(file_folder):
            return None
    except ValueError:
        return None
    return candidate


def collect_managed_file_paths(mod_dir: str, files_data, game: str) -> set[str]:
    managed_paths = set()
    for file_info in (files_data or {}).values():
        data_file = file_info.get("data_file_path") or file_info.get("data_file_url")
        if isinstance(data_file, str):
            managed_path = resolve_managed_mod_path(mod_dir, data_file)
            if managed_path:
                managed_paths.add(managed_path)
        for extra_file in parse_extra_files_raw(file_info.get("extra_files", [])):
            managed_path = resolve_managed_mod_path(mod_dir, extra_file)
            if managed_path:
                managed_paths.add(managed_path)
    return managed_paths


def remove_stale_managed_files(
    mod_dir: str, old_files, new_files, game: str
) -> None:
    previous_paths = collect_managed_file_paths(mod_dir, old_files, game)
    current_paths = collect_managed_file_paths(mod_dir, new_files, game)
    stale_paths = sorted(previous_paths - current_paths, key=len, reverse=True)
    for stale_path in stale_paths:
        if os.path.isdir(stale_path):
            shutil.rmtree(stale_path, ignore_errors=True)
        elif os.path.isfile(stale_path):
            with suppress(FileNotFoundError):
                os.remove(stale_path)
        parent_dir = os.path.dirname(stale_path)
        while parent_dir and os.path.abspath(parent_dir) != os.path.abspath(mod_dir):
            try:
                os.rmdir(parent_dir)
            except OSError:
                break
            parent_dir = os.path.dirname(parent_dir)


def copy_path_into_mod_dir(resolved: str, destination: str) -> None:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if os.path.abspath(resolved) == os.path.abspath(destination):
        return
    if os.path.exists(destination):
        if os.path.isdir(destination):
            shutil.rmtree(destination)
        else:
            os.remove(destination)
    if os.path.isdir(resolved):
        shutil.copytree(resolved, destination)
    else:
        shutil.copy2(resolved, destination)


def chapter_storage_root(file_key: str, game: str) -> str:
    normalized_key = str(file_key or "")
    if normalized_key.endswith("_0") or normalized_key == game:
        return ""
    folder_name = get_chapter_folder_name(normalized_key, game=game)
    return folder_name or ""


def build_storage_path(
    *,
    mod_dir: str,
    file_key: str,
    original_path: str,
    resolved: str,
    game: str,
    format_config_path,
) -> str:
    normalized_original = format_config_path(
        original_path,
        is_directory=os.path.isdir(resolved),
    )
    if not os.path.isabs(normalized_original):
        return normalized_original

    try:
        rel_from_mod = os.path.relpath(resolved, mod_dir).replace("\\", "/")
        if not rel_from_mod.startswith("../") and rel_from_mod != "..":
            return format_config_path(
                rel_from_mod,
                is_directory=os.path.isdir(resolved),
            )
    except ValueError:
        pass

    root = chapter_storage_root(file_key, game)
    target_name = os.path.basename(resolved.rstrip("\\/"))
    if root:
        return format_config_path(
            f"{root}/{target_name}",
            is_directory=os.path.isdir(resolved),
        )
    return format_config_path(target_name, is_directory=os.path.isdir(resolved))


def copy_files_to_mod_dir(
    *,
    mod_dir: str,
    files_data,
    game: str,
    resolve_file_path,
    format_config_path,
) -> dict:
    processed = {}
    for file_key, file_data in files_data.items():
        new_file_data = {}
        data_path = file_data.get("data_file_path") or file_data.get("data_file_url")
        if data_path:
            resolved = resolve_file_path(data_path)
            if os.path.exists(resolved):
                stored_path = build_storage_path(
                    mod_dir=mod_dir,
                    file_key=file_key,
                    original_path=data_path,
                    resolved=resolved,
                    game=game,
                    format_config_path=format_config_path,
                )
                destination = resolve_mod_file_path(mod_dir, stored_path)
                copy_path_into_mod_dir(resolved, destination)
                new_file_data["data_file_path"] = stored_path
        for path in parse_extra_files_raw(file_data.get("extra_files", [])):
            if not path:
                continue
            resolved = resolve_file_path(path)
            if not os.path.exists(resolved):
                continue
            stored_path = build_storage_path(
                mod_dir=mod_dir,
                file_key=file_key,
                original_path=path,
                resolved=resolved,
                game=game,
                format_config_path=format_config_path,
            )
            destination = resolve_mod_file_path(mod_dir, stored_path)
            copy_path_into_mod_dir(resolved, destination)
            new_file_data.setdefault("extra_files", []).append(stored_path)
        if new_file_data:
            processed[file_key] = new_file_data
    return processed
