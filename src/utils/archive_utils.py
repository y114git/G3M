"""Archive extraction utilities."""

import contextlib
import errno
import logging
import lzma
import os
import platform
import re
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from urllib.parse import unquote, urlparse

from utils.file_utils import (
    safe_move,
    safe_remove,
    safe_rmtree,
)
from utils.path_utils import resource_path

logger = logging.getLogger(__name__)


def _is_safe_path(path: str) -> bool:
    return not (".." in path or path.startswith("/"))


def _get_unrar_path() -> str:
    """Return path to the bundled unrar binary in src/assets/bin/unrar/."""
    name = "UnRAR.exe" if platform.system() == "Windows" else "unrar"
    return resource_path(os.path.join("assets", "bin", "unrar", name))


def _ensure_unrar_available():
    import rarfile

    bundled = _get_unrar_path()
    if os.path.exists(bundled):
        rarfile.UNRAR_TOOL = bundled
        return
    import subprocess

    for tool in ([rarfile.UNRAR_TOOL] if rarfile.UNRAR_TOOL else []) + (
        ["unrar"] if rarfile.UNRAR_TOOL != "unrar" else []
    ):
        try:
            subprocess.run([tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rarfile.UNRAR_TOOL = tool
            return
        except FileNotFoundError as error:
            logger.debug("Best-effort operation failed: %s", error, exc_info=True)
    expected = "UnRAR.exe" if os.name == "nt" else "unrar"
    raise FileNotFoundError(
        f"UnRAR binary not found. Place {expected} in src/assets/bin/unrar/ for local development."
    )


def _extract_lzma(tmp_path: str, target_dir: str, fname: str):
    with (
        lzma.open(tmp_path) as f_in,
        open(os.path.join(target_dir, os.path.splitext(fname)[0]), "wb") as f_out,
    ):
        shutil.copyfileobj(f_in, f_out)


def _detect_archive_format_by_signature(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            h = f.read(10)
        return (
            "zip"
            if h[:2] == b"PK"
            else (
                "rar" if h[:4] == b"Rar!" else ("7z" if h[:2] == b"7z" else "unknown")
            )
        )
    except Exception:
        return "unknown"


def _collect_safe_members(members, name_getter, label: str):
    return [
        m
        for m in members
        if _is_safe_path(name_getter(m))
        or not logger.warning(f"Skipping suspicious path in {label}: {name_getter(m)}")
    ]


def _extract_members_one_by_one(
    archive, members, out_dir_abs: str, is_cancelled: Callable[[], bool] | None = None
) -> None:
    for member in members:
        if is_cancelled and is_cancelled():
            return
        archive.extract(member, path=out_dir_abs)


def _extract_archive_raw(
    src_path: str,
    fname_lower: str,
    out_dir: str,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Extract archive file to directory with format detection.

    Args:
        src_path: Path to archive file.
        fname_lower: Lowercase filename for format detection.
        out_dir: Output directory.

    Raises:
        FileNotFoundError: If UnRAR binary is not available.
    """
    import rarfile

    try:
        import py7zr
    except Exception as e:
        logger.debug(f"_extract_archive_raw: py7zr import failed (not installed): {e}")
        py7zr = None
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    detected_format = _detect_archive_format_by_signature(src_path)
    if fname_lower.endswith(".zip") or detected_format == "zip":
        with zipfile.ZipFile(src_path, "r") as zf:
            targets = _collect_safe_members(zf.namelist(), lambda member: member, "ZIP")
            if targets:
                try:
                    _extract_members_one_by_one(zf, targets, out_dir_abs, is_cancelled)
                except (ValueError, OSError) as e:
                    logger.warning(
                        f"_extract_archive_raw: Failed to extract ZIP archive: {e}"
                    )
        return
    if fname_lower.endswith(
        (".tar.gz", ".tar.bz2", ".tar.xz", ".tar", ".tgz", ".tbz2", ".txz")
    ):
        try:
            with tarfile.open(src_path, "r:*") as tf:
                targets = _collect_safe_members(
                    tf.getmembers(), lambda member: member.name, "TAR"
                )
                if targets:
                    _extract_members_one_by_one(tf, targets, out_dir_abs, is_cancelled)
        except (ValueError, OSError, tarfile.TarError) as e:
            logger.warning(f"_extract_archive_raw: Failed to extract TAR archive: {e}")
        return
    if fname_lower.endswith(".rar") or detected_format == "rar":
        _ensure_unrar_available()
        with rarfile.RarFile(src_path, "r") as rf:
            targets = _collect_safe_members(rf.namelist(), lambda member: member, "RAR")
            if targets:
                try:
                    _extract_members_one_by_one(rf, targets, out_dir_abs, is_cancelled)
                except (ValueError, OSError, rarfile.RarCannotExec) as e:
                    logger.warning(
                        f"_extract_archive_raw: Failed to extract RAR archive: {e}"
                    )
        return
    if (fname_lower.endswith(".7z") or detected_format == "7z") and py7zr is not None:
        with py7zr.SevenZipFile(src_path, mode="r") as zf:
            targets = _collect_safe_members(zf.getnames(), lambda member: member, "7Z")
            if targets:
                try:
                    for target in targets:
                        if is_cancelled and is_cancelled():
                            break
                        zf.extract(path=out_dir_abs, targets=[target])
                except (ValueError, OSError) as e:
                    logger.warning(
                        f"_extract_archive_raw: Failed to extract 7z archive: {e}"
                    )
        return
    if fname_lower.endswith(".lzma"):
        _extract_lzma(src_path, out_dir, fname_lower)
        return
    shutil.copy2(src_path, os.path.join(out_dir, os.path.basename(src_path)))


def unwrap_single_directory_chain(root_dir: str) -> str:
    """Descend through nested single-directory layers until content branches."""

    current_dir = os.path.abspath(os.fspath(root_dir))
    visited = {os.path.realpath(current_dir)}
    while True:
        try:
            entries = os.listdir(current_dir)
        except OSError:
            return current_dir
        if len(entries) != 1:
            return current_dir
        next_dir = os.path.join(current_dir, entries[0])
        if not os.path.isdir(next_dir):
            return current_dir
        real_next_dir = os.path.realpath(next_dir)
        if real_next_dir in visited:
            return current_dir
        visited.add(real_next_dir)
        current_dir = next_dir


def _move_tree_safely(src_root: str, dst_root: str) -> None:
    """Safely move directory tree with path traversal protection.

    Args:
        src_root: Source directory.
        dst_root: Destination directory.
    """
    for root, _dirs, files in os.walk(src_root):
        rel_root = os.path.relpath(root, src_root)
        rel_root = "" if rel_root == "." else rel_root
        if os.path.isabs(rel_root):
            continue
        if len(rel_root) >= 2 and rel_root[1] == ":" and rel_root[0].isalpha():
            continue
        dst_dir = os.path.join(dst_root, rel_root) if rel_root else dst_root
        os.makedirs(dst_dir, exist_ok=True)
        for f in files:
            src_path = os.path.join(root, f)
            if os.path.islink(src_path):
                continue
            dst_path = os.path.join(dst_dir, f)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            try:
                shutil.move(src_path, dst_path)
            except (OSError, shutil.Error):
                try:
                    shutil.copy2(src_path, dst_path)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise


def _cleanup_extracted_archive(target_dir: str, is_game_installation: bool = False):
    if not is_game_installation:
        return
    try:
        single = unwrap_single_directory_chain(target_dir)
        if os.path.normcase(os.path.normpath(single)) != os.path.normcase(
            os.path.normpath(target_dir)
        ):
            for item in os.listdir(single):
                dst = os.path.join(target_dir, item)
                if os.path.exists(dst):
                    (safe_rmtree if os.path.isdir(dst) else safe_remove)(dst)
                safe_move(os.path.join(single, item), dst)
            current = single
            while os.path.normcase(os.path.normpath(current)) != os.path.normcase(
                os.path.normpath(target_dir)
            ):
                parent = os.path.dirname(current)
                with contextlib.suppress(OSError):
                    os.rmdir(current)
                current = parent
    except Exception as e:
        logger.warning(f"Failed to handle nested folder: {e}")
    pattern = re.compile(r"^chapter\d+_(windows|mac)$", re.I)
    for root, dirs, files in os.walk(target_dir, topdown=False):
        del files
        for d in dirs[:]:
            if pattern.match(d) and safe_rmtree(os.path.join(root, d)):
                dirs.remove(d)


class ArchiveExtractor:
    @staticmethod
    def extract(
        archive_path: str,
        target_dir: str,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        if not os.path.exists(archive_path):
            raise FileNotFoundError(f"Archive not found: {archive_path}")
        if not os.path.isfile(archive_path):
            raise ValueError(f"Path is not a file: {archive_path}")
        os.makedirs(target_dir, exist_ok=True)
        fname_lower = os.path.basename(archive_path).lower()
        try:
            _extract_archive_raw(archive_path, fname_lower, target_dir, is_cancelled)
            logger.debug(
                f"ArchiveExtractor: Successfully extracted {archive_path} to {target_dir}"
            )
        except Exception as e:
            error_msg = f"Failed to extract archive {archive_path}: {e}"
            logger.error(error_msg, exc_info=True)
            if isinstance(e, (FileNotFoundError, PermissionError, OSError, ValueError)):
                raise
            raise ValueError(error_msg) from e

    @staticmethod
    def extract_with_options(
        archive_path: str,
        target_dir: str,
        fname: str | None = None,
        is_game_installation: bool = False,
        size_cap_bytes: int | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        os.makedirs(target_dir, exist_ok=True)
        if size_cap_bytes is not None:
            with tempfile.TemporaryDirectory(prefix="g3m-extract-") as temp_out:
                ArchiveExtractor.extract(archive_path, temp_out, is_cancelled)
                total = 0
                for root, ignored_dirs, files in os.walk(temp_out):
                    if is_cancelled and is_cancelled():
                        return
                    del ignored_dirs
                    for f in files:
                        with contextlib.suppress(OSError):
                            total += os.path.getsize(os.path.join(root, f))
                if total > size_cap_bytes:
                    raise OSError("extracted_content_too_large")
                _move_tree_safely(temp_out, target_dir)
                _cleanup_extracted_archive(target_dir, is_game_installation)
        else:
            ArchiveExtractor.extract_with_backup(
                archive_path,
                target_dir,
                backup_temp_dir=None,
                backup_files=None,
                add_mod_dir_callback=None,
                backup_file_callback=None,
                update_manifest_callback=None,
                status_callback=None,
                is_cancelled=is_cancelled,
            )

    @staticmethod
    def extract_with_backup(
        archive_path: str,
        target_dir: str,
        backup_temp_dir: str | None = None,
        backup_files: dict | None = None,
        add_mod_dir_callback: Callable | None = None,
        backup_file_callback: Callable | None = None,
        update_manifest_callback: Callable | None = None,
        status_callback: Callable | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[str]:
        extracted_files = []
        try:
            with tempfile.TemporaryDirectory(prefix="g3m-extract-") as temp_dir:
                ArchiveExtractor.extract(archive_path, temp_dir, is_cancelled)
                if is_cancelled and is_cancelled():
                    return extracted_files
                _cleanup_extracted_archive(temp_dir, False)
                for root, _dirs, files in os.walk(temp_dir):
                    for file in files:
                        if is_cancelled and is_cancelled():
                            return extracted_files
                        source_file = os.path.join(root, file)
                        rel_path = os.path.relpath(source_file, temp_dir)
                        target_file = os.path.join(target_dir, rel_path)
                        file_lower = file.lower()
                        if platform.system() == "Darwin":
                            if file_lower.endswith(".win"):
                                name_without_ext = os.path.splitext(file)[0]
                                target_file = os.path.join(
                                    os.path.dirname(target_file),
                                    name_without_ext + ".ios",
                                )
                        elif file_lower.endswith(".ios"):
                            name_without_ext = os.path.splitext(file)[0]
                            target_file = os.path.join(
                                os.path.dirname(target_file), name_without_ext + ".win"
                            )
                        target_dirname = os.path.dirname(target_file)
                        os.makedirs(target_dirname, exist_ok=True)
                        if add_mod_dir_callback:
                            try:
                                add_mod_dir_callback(target_dirname)
                            except Exception as e:
                                logger.error(
                                    f"extract_archive_with_backup: add_mod_dir_callback failed: {e}",
                                    exc_info=True,
                                )
                        tmp_target = target_file + ".tmp"
                        try:
                            shutil.copy2(source_file, tmp_target)
                            if (
                                os.path.exists(target_file)
                                and backup_temp_dir
                                and (backup_files is not None)
                            ):
                                backup_rel_path = os.path.relpath(
                                    target_file, target_dir
                                )
                                backup_file_path = os.path.join(
                                    backup_temp_dir, backup_rel_path
                                )
                                os.makedirs(
                                    os.path.dirname(backup_file_path), exist_ok=True
                                )
                                shutil.move(target_file, backup_file_path)
                                backup_files[target_file] = backup_file_path
                                if backup_file_callback:
                                    try:
                                        backup_file_callback(
                                            target_file, backup_file_path
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"extract_archive_with_backup: backup_file_callback failed: {e}",
                                            exc_info=True,
                                        )
                                if update_manifest_callback:
                                    try:
                                        update_manifest_callback(
                                            {target_file: backup_file_path}, None, None
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"extract_archive_with_backup: update_manifest_callback failed: {e}",
                                            exc_info=True,
                                        )
                            os.replace(tmp_target, target_file)
                            extracted_files.append(target_file)
                        finally:
                            try:
                                if os.path.exists(tmp_target):
                                    os.remove(tmp_target)
                            except Exception as e:
                                logger.warning(
                                    f"extract_archive_with_backup: tmp cleanup failed: {e}",
                                    exc_info=True,
                                )
        except Exception as e:
            error_msg = f"Archive unpack error: {os.path.basename(archive_path)}: {e}"
            if status_callback:
                try:
                    status_callback(error_msg)
                except (RuntimeError, AttributeError) as e:
                    logger.warning(
                        f"extract_archive_with_backup: status_callback failed: {e}"
                    )
            logger.error(f"extract_archive_with_backup: {error_msg}", exc_info=True)
        return extracted_files

    @staticmethod
    def _matches_target(name: str, target: str) -> bool:
        n = name.replace("\\", "/").strip("/")
        return n == target or n.endswith(f"/{target}")

    @staticmethod
    def check_archive_has_file(archive_path: str, target_filename: str) -> bool:
        archive_lower = archive_path.lower()
        detected_format = _detect_archive_format_by_signature(archive_path)
        try:
            if archive_lower.endswith(".zip") or detected_format == "zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    return any(
                        ArchiveExtractor._matches_target(n, target_filename)
                        for n in zf.namelist()
                    )
            elif archive_lower.endswith(
                (".tar.gz", ".tar.bz2", ".tar.xz", ".tar", ".tgz", ".tbz2", ".txz")
            ):
                with tarfile.open(archive_path, "r:*") as tf:
                    return any(
                        ArchiveExtractor._matches_target(m.name, target_filename)
                        for m in tf.getmembers()
                    )
            elif archive_lower.endswith(".rar") or detected_format == "rar":
                _ensure_unrar_available()
                import rarfile

                with rarfile.RarFile(archive_path, "r") as rf:
                    return any(
                        ArchiveExtractor._matches_target(n, target_filename)
                        for n in rf.namelist()
                    )
            elif archive_lower.endswith(".7z") or detected_format == "7z":
                import py7zr

                with py7zr.SevenZipFile(archive_path, mode="r") as zf:
                    return any(
                        ArchiveExtractor._matches_target(n, target_filename)
                        for n in zf.getnames()
                    )
        except Exception as e:
            logger.error(
                f"ArchiveExtractor.check_archive_has_file: Error: {e}", exc_info=True
            )
        return False


def get_file_extension_from_url(url: str, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    filename = unquote(os.path.basename(parsed.path))
    if "." in filename:
        ext = os.path.splitext(filename)[1].lower()
        supported_exts = (
            ".zip",
            ".rar",
            ".7z",
            ".tar.gz",
            ".lzma",
            ".tar",
            ".bz2",
            ".xz",
        )
        if ext in supported_exts:
            return ext
    if content_type:
        content_type = content_type.lower()
        content_type_map = {
            "application/zip": ".zip",
            "application/x-rar-compressed": ".rar",
            "application/x-rar": ".rar",
            "application/x-7z-compressed": ".7z",
            "application/x-7z": ".7z",
            "application/x-tar": ".tar.gz",
            "application/gzip": ".tar.gz",
            "application/x-gzip": ".tar.gz",
            "application/x-bzip2": ".bz2",
            "application/x-xz": ".xz",
            "application/x-lzma": ".lzma",
        }
        if content_type in content_type_map:
            return content_type_map[content_type]
    return ".zip"


def get_file_extension_from_content(file_path: str) -> str:
    detected_format = _detect_archive_format_by_signature(file_path)
    format_extensions = {"zip": ".zip", "rar": ".rar", "7z": ".7z", "unknown": ".zip"}
    return format_extensions.get(detected_format, ".zip")


def extract_any_archive(archive_path: str, target_dir: str) -> None:
    ArchiveExtractor.extract(archive_path, target_dir)


def extract_archive(
    archive_path: str,
    target_dir: str,
    fname: str | None = None,
    is_game_installation: bool = False,
    size_cap_bytes: int | None = None,
) -> None:
    ArchiveExtractor.extract_with_options(
        archive_path, target_dir, fname, is_game_installation, size_cap_bytes
    )


def extract_archive_content_root(
    archive_path: str,
    target_dir: str,
    *,
    size_cap_bytes: int | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> str:
    """Safely extract an archive and return its unwrapped content root."""
    ArchiveExtractor.extract_with_options(
        archive_path,
        target_dir,
        size_cap_bytes=size_cap_bytes,
        is_cancelled=is_cancelled,
    )
    return unwrap_single_directory_chain(target_dir)


def extract_archive_with_backup(
    archive_path: str,
    target_dir: str,
    backup_temp_dir: str | None = None,
    backup_files: dict | None = None,
    add_mod_dir_callback=None,
    backup_file_callback=None,
    update_manifest_callback=None,
    status_callback=None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[str]:
    return ArchiveExtractor.extract_with_backup(
        archive_path,
        target_dir,
        backup_temp_dir,
        backup_files,
        add_mod_dir_callback,
        backup_file_callback,
        update_manifest_callback,
        status_callback,
        is_cancelled,
    )
