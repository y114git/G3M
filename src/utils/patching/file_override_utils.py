"""File override and archive extraction utilities for mod patching."""

import logging
import os
import shutil
import tempfile

from config.config import ARCHIVE_EXTENSIONS, DATA_FILE_EXTENSIONS, SKIP_FILES
from services.localization_service import tr
from utils.frickbears3_addons_utils import (
    apply_frickbears3_addons_from_mod_source,
    get_frickbears3_addons_dir,
    is_addons_subpath,
    is_top_level_addons_archive,
)
from utils.patching import mod_content_utils as mod_content
from utils.pizzatower_afom_utils import (
    apply_afom_towers_from_mod_source,
    is_top_level_towers_archive,
    is_towers_subpath,
)

logger = logging.getLogger(__name__)


def _normalize_override_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return ""
    if str(path).rstrip().endswith(("/", "\\")):
        normalized = normalized.rstrip("/")
        return f"{normalized}/" if normalized else ""
    return normalized.rstrip("/")


def _chapter_path_prefixes(
    chapter_id: str, game_id: str | None = None
) -> tuple[str, ...]:
    prefixes: list[str] = []
    chapter_name = str(chapter_id or "")
    if chapter_name.startswith("deltarune_"):
        chapter_suffix = chapter_name.rsplit("_", 1)[-1]
        if chapter_suffix.isdigit():
            prefixes.extend(
                (
                    f"chapter_{chapter_suffix}/",
                    f"chapter{chapter_suffix}/",
                    f"chapter{chapter_suffix}_windows/",
                    f"chapter_{chapter_suffix}_windows/",
                )
            )
    elif chapter_name == "deltarunedemo":
        prefixes.extend(("demo/",))
    elif chapter_name == "undertale":
        prefixes.extend(("undertale/", "chapter_0/"))
    elif chapter_name == "pizzatower":
        prefixes.extend(("pizzatower/",))
    elif chapter_name:
        prefixes.extend((f"{chapter_name}/",))
    if game_id == "deltarune" and chapter_name.endswith("_0"):
        prefixes.extend(("menu/",))
    return tuple(dict.fromkeys(prefixes))


def _target_relative_override_path(
    stored_path: str, chapter_id: str | None, game_id: str | None = None
) -> str:
    normalized = _normalize_override_path(stored_path)
    if not normalized:
        return ""
    for prefix in _chapter_path_prefixes(str(chapter_id or ""), game_id):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def _iter_configured_override_entries(
    mod_root_dir: str,
    configured_paths: list[str] | None,
    chapter_id: str | None,
    game_id: str | None = None,
):
    for stored_path in configured_paths or []:
        normalized = _normalize_override_path(stored_path)
        if not normalized:
            continue
        source_path = os.path.normpath(
            os.path.join(mod_root_dir, normalized.rstrip("/"))
        )
        target_relative = _target_relative_override_path(
            normalized, chapter_id, game_id
        )
        if not target_relative:
            continue
        target_root = None
        if (game_id or "").strip().lower() == "frickbears3" and (
            is_addons_subpath(normalized) or is_top_level_addons_archive(normalized)
        ):
            target_root = get_frickbears3_addons_dir()
            if is_addons_subpath(normalized):
                target_relative = "" if normalized == "addons/" else normalized[len("addons/") :]
            else:
                target_relative = ""
        yield {
            "source": source_path,
            "target_relative": target_relative,
            "is_directory": normalized.endswith("/"),
            "display_name": normalized,
            "target_root": target_root,
        }


def _count_entry_files(entries) -> int:
    total = 0
    for entry in entries:
        source_path = entry["source"]
        if entry["is_directory"]:
            if not os.path.isdir(source_path):
                continue
            for _root, _dirs, files in os.walk(source_path):
                total += sum(1 for file in files if file.lower() not in SKIP_FILES)
        elif os.path.isfile(source_path):
            total += 1
    return total


def _copy_override_file(
    patcher,
    source_path: str,
    target_path: str,
    target_dir: str,
    chapter_id: int | None,
    is_modpack: bool,
    processed_archives: set,
    progress_callback,
    progress_state: dict[str, int],
    mod_name: str,
    allow_data_file_copy: bool = False,
):
    file = os.path.basename(source_path)
    file_lower = file.lower()
    progress_state["processed"] += 1
    if progress_callback:
        progress_callback(
            progress_state["processed"] / max(progress_state["total"], 1),
            tr(
                "status.applying_file_overrides",
                mod=mod_name,
                current=progress_state["processed"],
                total=progress_state["total"],
            ),
        )

    if file_lower.endswith((".xdelta", ".vcdiff")):
        if not is_modpack:
            xdelta_chapter_id = (
                chapter_id
                if chapter_id is not None
                else mod_content.extract_chapter_id_from_path(target_dir)
            )
            patch_result = apply_xdelta_override(
                patcher,
                file,
                source_path,
                target_dir,
                xdelta_chapter_id,
            )
            if (patch_result is False) and (
                not patcher._request_warning(
                    tr(
                        "dialogs.patching_warning.xdelta_override_skipped",
                        patch=file,
                        target=target_dir,
                    ),
                    warning_id="extra_xdelta_apply_failed",
                    context={
                        "patch": file,
                        "target": target_dir,
                        "mod_name": mod_name,
                    },
                )
            ):
                return False
        elif patcher.xdelta_modpack:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            try:
                shutil.copy2(source_path, target_path)
            except Exception as e:
                patcher.patching_logger.warning(
                    f"Failed to copy xdelta file {source_path}: {e}"
                )
                return False
        return True

    if file_lower.endswith(DATA_FILE_EXTENSIONS) and not allow_data_file_copy:
        return True

    if file_lower.endswith(ARCHIVE_EXTENSIONS):
        normalized_source = os.path.normpath(source_path)
        if normalized_source in processed_archives:
            return True
        processed_archives.add(normalized_source)
        if is_modpack:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            try:
                shutil.copy2(source_path, target_path)
            except Exception as e:
                patcher.patching_logger.error(
                    f"Failed to copy archive {source_path}: {e}"
                )
                return patcher._request_warning(
                    tr(
                        "dialogs.patching_warning.extra_file_copy_failed",
                        file=file,
                        target=target_path,
                    ),
                    details=str(e),
                    warning_id="extra_file_copy_failed",
                    context={
                        "file": file,
                        "target": target_path,
                        "mod_name": mod_name,
                    },
                )
        else:
            if not extract_archive_to_target(
                patcher,
                source_path,
                os.path.dirname(target_path) if target_path else target_dir,
                chapter_id,
                progress_callback=progress_callback,
                mod_name=mod_name,
            ):
                return False
        return True

    if not is_modpack:
        patcher._backup_or_mark_file(chapter_id, target_path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        shutil.copy2(source_path, target_path)
    except Exception as e:
        patcher.patching_logger.error(
            f"Failed to copy override file {source_path}: {e}"
        )
        return patcher._request_warning(
            tr(
                "dialogs.patching_warning.extra_file_copy_failed",
                file=file,
                target=target_path,
            ),
            details=str(e),
            warning_id="extra_file_copy_failed",
            context={
                "file": file,
                "target": target_path,
                "mod_name": mod_name,
            },
        )
    return True


def _apply_configured_override_entries(
    patcher,
    entries,
    target_dir: str,
    chapter_id: int | None,
    is_modpack: bool,
    progress_callback=None,
    mod_name: str = "",
) -> bool:
    total_files = _count_entry_files(entries)
    progress_state = {"processed": 0, "total": total_files}
    processed_archives = set()
    for entry in entries:
        source_path = entry["source"]
        target_relative = entry["target_relative"]
        entry_target_dir = entry.get("target_root") or target_dir
        if entry["is_directory"]:
            if not os.path.isdir(source_path):
                patcher.patching_logger.warning(
                    "Configured extra directory not found, skipping: %s",
                    source_path,
                )
                if not patcher._request_warning(
                    tr(
                        "dialogs.patching_warning.extra_directory_missing",
                        path=source_path,
                    ),
                    warning_id="extra_directory_missing",
                    context={
                        "path": source_path,
                        "mod_name": mod_name,
                    },
                ):
                    return False
                continue
            for root, _dirs, files in os.walk(source_path):
                rel_root = os.path.relpath(root, source_path)
                for file in files:
                    if file.lower() in SKIP_FILES:
                        continue
                    file_source = os.path.join(root, file)
                    rel_file = file if rel_root == "." else os.path.join(rel_root, file)
                    target_path = os.path.join(
                        entry_target_dir,
                        target_relative.rstrip("/"),
                        rel_file,
                    )
                    if not _copy_override_file(
                        patcher,
                        file_source,
                        target_path,
                        entry_target_dir,
                        chapter_id,
                        is_modpack,
                        processed_archives,
                        progress_callback,
                        progress_state,
                        mod_name,
                        allow_data_file_copy=True,
                    ):
                        return False
            continue
        if not os.path.isfile(source_path):
            patcher.patching_logger.warning(
                "Configured extra file not found, skipping: %s",
                source_path,
            )
            if not patcher._request_warning(
                tr("dialogs.patching_warning.extra_file_missing", path=source_path),
                warning_id="extra_file_missing",
                context={
                    "path": source_path,
                    "mod_name": mod_name,
                },
            ):
                return False
            continue
        target_path = os.path.join(entry_target_dir, target_relative)
        if not _copy_override_file(
            patcher,
            source_path,
            target_path,
            entry_target_dir,
            chapter_id,
            is_modpack,
            processed_archives,
            progress_callback,
            progress_state,
            mod_name,
            allow_data_file_copy=True,
        ):
            return False
    if progress_callback and total_files == 0:
        progress_callback(
            1.0,
            tr("status.applying_file_overrides", mod=mod_name, current=0, total=0),
        )
    return True


def apply_xdelta_override(
    patcher,
    file_name: str,
    source_path: str,
    target_dir: str,
    chapter_id: int | None,
    fallback_target: str | None = None,
    label: str = "",
) -> bool | None:
    """Apply xdelta patch to matching target files. On failure, copies to fallback_target if provided."""
    target_files = mod_content.find_target_files_for_xdelta(target_dir, file_name)
    if not target_files:
        patcher.patching_logger.debug(
            f"No target files found for xdelta patch {file_name}{label}, skipping (expected filename: {os.path.splitext(file_name)[0]})"
        )
        if not fallback_target and not patcher._request_warning(
            tr(
                "dialogs.patching_warning.xdelta_override_no_target",
                patch=file_name,
                target=target_dir,
            ),
            warning_id="extra_xdelta_no_target",
            context={
                "patch": file_name,
                "target": target_dir,
            },
        ):
            return False
        if fallback_target:
            patcher._backup_or_mark_file(chapter_id, fallback_target)
            shutil.copy2(source_path, fallback_target)
        return None
    patch_applied = False
    for tf in target_files:
        if chapter_id is not None and patcher.backup_service and os.path.exists(tf):
            patcher.backup_service.backup_file(chapter_id, tf)
        if patcher._apply_xdelta_to_file(tf, source_path):
            patcher.patching_logger.info(
                f"Applied xdelta patch {file_name}{label} to {os.path.relpath(tf, target_dir)}"
            )
            patch_applied = True
        else:
            patcher.patching_logger.warning(
                f"Failed to apply xdelta patch {file_name}{label} to {os.path.relpath(tf, target_dir)}, skipping"
            )
    if not patch_applied:
        if fallback_target:
            patcher.patching_logger.warning(
                f"Xdelta patch {file_name}{label} could not be applied to any target files, copying as regular file"
            )
            patcher._backup_or_mark_file(chapter_id, fallback_target)
            shutil.copy2(source_path, fallback_target)
        else:
            patcher.patching_logger.warning(
                f"Xdelta patch {file_name}{label} could not be applied to any target files, skipping"
            )
    return patch_applied


def extract_archive_to_target(
    patcher,
    archive_path: str,
    target_dir: str,
    chapter_id: int | None = None,
    progress_callback=None,
    mod_name: str = "",
) -> bool:
    try:
        from utils.archive_utils import extract_any_archive

        if chapter_id is None:
            chapter_id = mod_content.extract_chapter_id_from_path(target_dir)
        if progress_callback:
            progress_callback(
                0.0,
                tr("status.applying_file_overrides", mod=mod_name, current=0, total=0),
            )
        with tempfile.TemporaryDirectory(prefix="mm_extract_") as temp_extract_dir:
            extract_any_archive(archive_path, temp_extract_dir)
            extracted_files = [
                os.path.join(root, file)
                for root, _dirs, files in os.walk(temp_extract_dir)
                for file in files
            ]
            total_files = len(extracted_files)
            processed_files = 0
            for root, _dirs, files in os.walk(temp_extract_dir):
                rel_root = os.path.relpath(root, temp_extract_dir)
                for file in files:
                    source_file = os.path.join(root, file)
                    target_file = (
                        os.path.join(target_dir, file)
                        if rel_root == "."
                        else os.path.join(target_dir, rel_root, file)
                    )
                    target_dirname = os.path.dirname(target_file)
                    os.makedirs(target_dirname, exist_ok=True)
                    file_lower = file.lower()
                    processed_files += 1
                    if progress_callback:
                        progress_callback(
                            processed_files / max(total_files, 1),
                            tr(
                                "status.applying_file_overrides",
                                mod=mod_name,
                                current=processed_files,
                                total=total_files,
                            ),
                        )
                    if file_lower.endswith((".xdelta", ".vcdiff")):
                        apply_xdelta_override(
                            patcher,
                            file,
                            source_file,
                            target_dir,
                            chapter_id,
                            fallback_target=target_file,
                            label=" from archive",
                        )
                        continue
                    patcher._backup_or_mark_file(chapter_id, target_file)
                    shutil.copy2(source_file, target_file)
        patcher.patching_logger.debug(f"Extracted archive: {archive_path}")
        return True
    except Exception as e:
        patcher.patching_logger.error(
            f"Failed to extract archive {archive_path}: {e}", exc_info=True
        )
        return patcher._request_warning(
            tr(
                "dialogs.patching_warning.archive_extract_failed",
                archive=os.path.basename(archive_path),
                target=target_dir,
            ),
            details=str(e),
            warning_id="extra_archive_extract_failed",
            context={
                "archive": os.path.basename(archive_path),
                "target": target_dir,
                "mod_name": mod_name,
            },
        )


def apply_file_overrides(
    patcher,
    mod_source_dir: str,
    target_dir: str,
    used_archive_names: set,
    is_modpack: bool,
    chapter_id: int | None = None,
    progress_callback=None,
    mod_name: str = "",
    game_id: str | None = None,
    configured_paths: list[str] | None = None,
    mod_root_dir: str | None = None,
) -> bool:
    if not os.path.isdir(mod_source_dir):
        return True
    if used_archive_names is None:
        used_archive_names = set()
    from config.config import DATA_FILE_EXTENSIONS

    xdelta_extensions = DATA_FILE_EXTENSIONS
    archive_extensions = ARCHIVE_EXTENSIONS
    processed_archives = set()
    skip_files = SKIP_FILES
    if chapter_id is None:
        chapter_id = mod_content.extract_chapter_id_from_path(target_dir)
    if (not is_modpack) and (game_id or "").strip().lower() == "pizzatower":
        from utils.archive_utils import extract_any_archive

        if not apply_afom_towers_from_mod_source(
            mod_source_dir,
            backup_or_mark=lambda target_file: patcher._backup_or_mark_file(
                chapter_id, target_file
            ),
            logger=patcher.patching_logger,
            extract_archive=extract_any_archive,
        ):
            return False
    if (not is_modpack) and (game_id or "").strip().lower() == "frickbears3":
        from utils.archive_utils import extract_any_archive

        if not apply_frickbears3_addons_from_mod_source(
            mod_source_dir,
            backup_or_mark=lambda target_file: patcher._backup_or_mark_file(
                chapter_id, target_file
            ),
            logger=patcher.patching_logger,
            extract_archive=extract_any_archive,
        ):
            return False
    if configured_paths is not None:
        configured_entries = list(
            _iter_configured_override_entries(
                mod_root_dir or mod_source_dir,
                configured_paths,
                str(chapter_id or ""),
                game_id,
            )
        )
        return _apply_configured_override_entries(
            patcher,
            configured_entries,
            target_dir,
            chapter_id,
            is_modpack,
            progress_callback=progress_callback,
            mod_name=mod_name,
        )
    total_files = 0
    for root, _dirs, files in os.walk(mod_source_dir):
        for file in files:
            if file.lower() in skip_files:
                continue
            source_file = os.path.join(root, file)
            source_rel_path = os.path.relpath(source_file, mod_source_dir)
            if source_file.lower().endswith(xdelta_extensions):
                continue
            if is_addons_subpath(source_rel_path):
                continue
            if is_top_level_addons_archive(source_rel_path):
                continue
            if is_towers_subpath(source_rel_path):
                continue
            if is_top_level_towers_archive(source_rel_path):
                continue
            total_files += 1
    processed_files = 0
    for root, _dirs, files in os.walk(mod_source_dir):
        rel_path = os.path.relpath(root, mod_source_dir)
        for file in files:
            if file.lower() in skip_files:
                continue
            source_path = os.path.join(root, file)
            file_lower = file.lower()
            source_rel_path = os.path.relpath(source_path, mod_source_dir)
            if is_addons_subpath(source_rel_path) or is_top_level_addons_archive(
                source_rel_path
            ):
                continue
            if is_towers_subpath(source_rel_path) or is_top_level_towers_archive(
                source_rel_path
            ):
                continue
            processed_files += 1
            if progress_callback:
                progress_callback(
                    processed_files / max(total_files, 1),
                    tr(
                        "status.applying_file_overrides",
                        mod=mod_name,
                        current=processed_files,
                        total=total_files,
                    ),
                )
            if file_lower.endswith((".xdelta", ".vcdiff")):
                if not is_modpack:
                    xdelta_chapter_id = (
                        chapter_id
                        if chapter_id is not None
                        else mod_content.extract_chapter_id_from_path(target_dir)
                    )
                    patch_result = apply_xdelta_override(
                        patcher, file, source_path, target_dir, xdelta_chapter_id
                    )
                    if (patch_result is False) and (
                        not patcher._request_warning(
                            tr(
                                "dialogs.patching_warning.xdelta_override_skipped",
                                patch=file,
                                target=target_dir,
                            ),
                            warning_id="extra_xdelta_apply_failed",
                            context={
                                "patch": file,
                                "target": target_dir,
                                "mod_name": mod_name,
                            },
                        )
                    ):
                        return False
                elif patcher.xdelta_modpack:
                    rel_path = os.path.relpath(source_path, mod_source_dir)
                    target_path = os.path.join(target_dir, rel_path)
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    try:
                        shutil.copy2(source_path, target_path)
                        patcher.patching_logger.debug(
                            f"Copied xdelta file {file} to modpack (xdelta_modpack enabled)"
                        )
                    except Exception as e:
                        patcher.patching_logger.warning(
                            f"Failed to copy xdelta file {source_path}: {e}"
                        )
                else:
                    patcher.patching_logger.debug(
                        f"Skipping xdelta file {file} (xdelta_modpack disabled)"
                    )
                continue
            if file_lower.endswith(xdelta_extensions):
                continue
            if file_lower.endswith(archive_extensions):
                normalized_path = os.path.normpath(source_path)
                if normalized_path in processed_archives:
                    continue
                processed_archives.add(normalized_path)
                if is_modpack:
                    archive_name = os.path.basename(file)
                    target_archive_path = os.path.join(target_dir, archive_name)
                    if os.path.exists(target_archive_path):
                        from utils.file_utils import remove_archive_extension

                        base_name = remove_archive_extension(archive_name)
                        archive_name_lower = archive_name.lower()
                        if archive_name_lower.endswith(".tar.gz"):
                            ext = ".tar.gz"
                        elif archive_name_lower.endswith(".tar.lzma"):
                            ext = ".tar.lzma"
                        else:
                            ext = os.path.splitext(archive_name)[1]
                        mod_index = 1
                        while os.path.exists(target_archive_path):
                            target_archive_name = f"{base_name}_mod{mod_index}{ext}"
                            target_archive_path = os.path.join(
                                target_dir, target_archive_name
                            )
                            mod_index += 1
                    patcher.patching_logger.debug(
                        f"Copying archive: {archive_name} -> {os.path.basename(target_archive_path)}"
                    )
                    try:
                        shutil.copy2(source_path, target_archive_path)
                    except Exception as e:
                        patcher.patching_logger.error(
                            f"Failed to copy archive {source_path}: {e}"
                        )
                        return False
                else:
                    patcher.patching_logger.debug(
                        f"Extracting archive contents: {os.path.basename(file)}"
                    )
                    if not extract_archive_to_target(
                        patcher,
                        source_path,
                        target_dir,
                        chapter_id,
                        progress_callback=progress_callback,
                        mod_name=mod_name,
                    ):
                        return False
                continue
            rel_path = os.path.relpath(source_path, mod_source_dir)
            target_path = os.path.join(target_dir, rel_path)
            if os.path.normpath(source_path) in processed_archives:
                continue
            if not is_modpack:
                patcher._backup_or_mark_file(chapter_id, target_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            try:
                shutil.copy2(source_path, target_path)
            except Exception as e:
                patcher.patching_logger.error(
                    f"Failed to copy override file {source_path}: {e}"
                )
                return False
    return True
