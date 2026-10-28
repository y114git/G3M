"""Safe archive primitives shared by operation planning and execution."""

from __future__ import annotations

import lzma
import ntpath
import os
import platform
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Iterable
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from utils.mod.filesystem import DirectoryTraversalError, iter_directory_tree
from utils.path_utils import resource_path

ARCHIVE_MAX_MEMBERS = 100_000
ARCHIVE_MAX_MEMBER_BYTES = 1024 * 1024 * 1024
ARCHIVE_MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
ARCHIVE_MAX_COMPRESSION_RATIO = 1_000
ARCHIVE_MAX_MEMBER_PATH_LENGTH = 1024

ARCHIVE_SUFFIXES = (
    ".tar.lzma",
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tbz2",
    ".tgz",
    ".txz",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".lzma",
)


def _get_unrar_path() -> str:
    name = "UnRAR.exe" if platform.system() == "Windows" else "unrar"
    return resource_path(os.path.join("assets", "bin", "unrar", name))


def _ensure_unrar_available() -> None:
    import rarfile

    bundled = _get_unrar_path()
    if os.path.exists(bundled):
        rarfile.UNRAR_TOOL = bundled
        return
    for tool in ([rarfile.UNRAR_TOOL] if rarfile.UNRAR_TOOL else []) + ["unrar"]:
        try:
            subprocess.run([tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rarfile.UNRAR_TOOL = tool
            return
        except FileNotFoundError:
            continue
    expected = "UnRAR.exe" if os.name == "nt" else "unrar"
    raise FileNotFoundError(
        f"UnRAR binary not found. Place {expected} in src/assets/bin/unrar/ for local development."
    )


class ArchiveValidationError(ValueError):
    """Raised before an unsafe archive can be read or rewritten."""


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """One validated archive entry."""

    name: str
    directory: bool
    size: int
    compressed_size: int | None
    link: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveVirtualPath:
    """A non-nested member path inside a supported archive."""

    archive: Path
    member: str
    directory: bool
    format: str


def archive_format(path: str | Path) -> str | None:
    """Return the configured archive format based on its longest extension."""
    if Path(path).is_dir():
        return None
    value = os.fspath(path).replace("\\", "/").casefold()
    for suffix in ARCHIVE_SUFFIXES:
        if value.endswith(suffix):
            return _format_for_suffix(suffix)
    return None


_ARCHIVE_SIGNATURES = (
    (b"PK\x03\x04", ".zip"),
    (b"PK\x05\x06", ".zip"),
    (b"7z\xbc\xaf\x27\x1c", ".7z"),
    (b"Rar!\x1a\x07", ".rar"),
)


def archive_suffix_from_content(path: str | Path) -> str | None:
    """Name the archive type of a file by its first bytes, for downloads whose name has no extension."""
    try:
        with open(path, "rb") as source:
            head = source.read(8)
    except OSError:
        return None
    return next((suffix for signature, suffix in _ARCHIVE_SIGNATURES if head.startswith(signature)), None)


def split_archive_virtual_path(path: str | Path) -> ArchiveVirtualPath | None:
    """Split ``archive.ext/member`` without treating ordinary files as archives."""
    value = os.fspath(path).replace("\\", "/")
    lower_value = value.casefold()
    candidates: list[tuple[int, str]] = []
    for suffix in ARCHIVE_SUFFIXES:
        marker = f"{suffix}/"
        position = lower_value.find(marker)
        while position >= 0 and Path(value[: position + len(suffix)]).is_dir():
            position = lower_value.find(marker, position + len(marker))
        if position >= 0:
            candidates.append((position, suffix))
    if not candidates:
        return None
    position, suffix = min(candidates, key=lambda candidate: (candidate[0], -len(candidate[1])))
    archive_value = value[: position + len(suffix)]
    member = value[position + len(suffix) + 1 :]
    format_name = _format_for_suffix(suffix)
    if format_name == "lzma":
        raise ArchiveValidationError("LZMA streams do not have virtual members")
    if member:
        _validate_member_name(member.rstrip("/"))
    return ArchiveVirtualPath(
        archive=Path(archive_value),
        member=member.rstrip("/"),
        directory=value.endswith("/"),
        format=format_name,
    )


def archive_write_supported(path: str | Path) -> bool:
    """Return whether a whole archive can be safely rebuilt."""
    return archive_format(path) not in {None, "rar"}


def _damage_errors(format_name: str | None) -> tuple[type[BaseException], ...]:
    errors: tuple[type[BaseException], ...] = (
        zipfile.BadZipFile,
        tarfile.TarError,
        lzma.LZMAError,
        zlib.error,
        EOFError,
    )
    if format_name == "7z":
        import py7zr.exceptions

        errors += (py7zr.exceptions.ArchiveError,)
    elif format_name == "rar":
        import rarfile

        errors += (rarfile.Error,)
    return errors


@contextmanager
def _named_damage(archive_path: Path):
    """Name the file in errors raised by the archive libraries, which only describe the format."""
    format_name = archive_format(archive_path)
    try:
        yield
    except ArchiveValidationError:
        raise
    except _damage_errors(format_name) as error:
        raise ArchiveValidationError(
            f"{archive_path} is damaged or is not a valid {format_name} archive ({error}); "
            "delete or replace this file"
        ) from error


def list_archive_members(path: str | Path) -> tuple[ArchiveMember, ...]:
    """List a bounded, validated archive tree without extracting it."""
    with _named_damage(Path(path)):
        return _list_archive_members(path)


def materialize_archive(path: str | Path, destination: str | Path) -> tuple[ArchiveMember, ...]:
    """Extract a validated archive into an empty private directory."""
    with _named_damage(Path(path)):
        return _materialize_archive(path, destination)


def _list_archive_members(path: str | Path) -> tuple[ArchiveMember, ...]:
    """List a bounded, validated archive tree without extracting it."""
    archive_path = Path(path)
    format_name = archive_format(archive_path)
    if format_name is None:
        raise ArchiveValidationError("unsupported archive format")
    if format_name == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            if any(info.flag_bits & 1 for info in archive.infolist()):
                raise ArchiveValidationError("encrypted ZIP archives are unsupported")
            return _validate_members(
                ArchiveMember(
                    info.filename,
                    info.is_dir(),
                    info.file_size,
                    info.compress_size,
                    _zip_member_is_link(info),
                )
                for info in archive.infolist()
            )
    if format_name.startswith("tar"):
        with _open_tar(archive_path, "r") as archive:
            return _validate_members(
                ArchiveMember(
                    info.name,
                    info.isdir(),
                    info.size,
                    None,
                    info.issym() or info.islnk(),
                )
                for info in archive.getmembers()
            )
    if format_name == "7z":
        import py7zr

        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            if archive.needs_password():
                raise ArchiveValidationError("encrypted 7z archives are unsupported")
            return _validate_members(
                ArchiveMember(
                    info.filename,
                    info.is_directory,
                    info.uncompressed,
                    info.compressed,
                    info.is_symlink,
                )
                for info in archive.list()
            )
    if format_name == "rar":
        import rarfile

        _ensure_unrar_available()
        with rarfile.RarFile(archive_path) as archive:
            if archive.needs_password():
                raise ArchiveValidationError("encrypted RAR archives are unsupported")
            return _validate_members(
                ArchiveMember(
                    info.filename,
                    info.isdir(),
                    info.file_size,
                    info.compress_size,
                    info.is_symlink(),
                )
                for info in archive.infolist()
            )
    if format_name == "lzma":
        size = archive_path.stat().st_size
        return (ArchiveMember(archive_path.stem, False, size, size),)
    raise ArchiveValidationError("unsupported archive format")


def _materialize_archive(path: str | Path, destination: str | Path) -> tuple[ArchiveMember, ...]:
    """Extract a validated archive into an empty private directory."""
    archive_path = Path(path)
    destination_path = Path(destination)
    if destination_path.exists() and any(destination_path.iterdir()):
        raise ArchiveValidationError("archive destination must be empty")
    destination_path.mkdir(parents=True, exist_ok=True)
    members = list_archive_members(archive_path)
    format_name = archive_format(archive_path)
    if format_name == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            for info, member in zip(archive.infolist(), members, strict=True):
                _extract_stream(destination_path, member, archive.open(info))
        return members
    if format_name and format_name.startswith("tar"):
        with _open_tar(archive_path, "r") as archive:
            for info, member in zip(archive.getmembers(), members, strict=True):
                if member.directory:
                    _member_destination(destination_path, member.name).mkdir(parents=True, exist_ok=True)
                    continue
                source = archive.extractfile(info)
                if source is None:
                    raise ArchiveValidationError(f"cannot read archive member {member.name!r}")
                with source:
                    _extract_stream(destination_path, member, source)
        return members
    if format_name == "7z":
        import py7zr

        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extract(path=destination_path, targets=[member.name for member in members])
        _assert_no_links(destination_path)
        return members
    if format_name == "rar":
        import rarfile

        with rarfile.RarFile(archive_path) as archive:
            for info, member in zip(archive.infolist(), members, strict=True):
                if member.directory:
                    _member_destination(destination_path, member.name).mkdir(parents=True, exist_ok=True)
                    continue
                with archive.open(info) as source:
                    _extract_stream(destination_path, member, source)
        return members
    if format_name == "lzma":
        with lzma.open(archive_path, "rb") as source:
            extraction_limit = min(
                ARCHIVE_MAX_MEMBER_BYTES,
                archive_path.stat().st_size * ARCHIVE_MAX_COMPRESSION_RATIO,
            )
            _extract_stream(
                destination_path,
                members[0],
                source,
                max_bytes=extraction_limit,
                limit_name=(
                    "size limit"
                    if extraction_limit == ARCHIVE_MAX_MEMBER_BYTES
                    else "compression ratio limit"
                ),
            )
        return members
    raise ArchiveValidationError("unsupported archive format")


def rebuild_archive(path: str | Path, source: str | Path) -> None:
    """Atomically rebuild a writable archive from a resolved directory tree."""
    archive_path = Path(path)
    source_path = Path(source)
    format_name = archive_format(archive_path)
    if format_name is None or format_name == "rar":
        raise ArchiveValidationError("archive format does not support writing")
    if not source_path.is_dir():
        raise ArchiveValidationError("archive source must be a directory")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        archive_source = source_path
        if _tree_contains_link(source_path):
            archive_source = Path(
                stack.enter_context(
                    tempfile.TemporaryDirectory(
                        prefix=f".{archive_path.name}.input.", dir=archive_path.parent
                    )
                )
            )
            _materialize_tree(source_path, archive_source)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{archive_path.name}.", suffix=".tmp", dir=archive_path.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            if format_name == "zip":
                with zipfile.ZipFile(
                    temporary_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9
                ) as archive:
                    _write_zip_tree(archive, archive_source)
            elif format_name.startswith("tar"):
                with _open_tar(temporary_path, "w", format_name) as archive:
                    _write_tar_tree(archive, archive_source)
            elif format_name == "7z":
                import py7zr

                with py7zr.SevenZipFile(temporary_path, mode="w") as archive:
                    _write_7z_tree(archive, archive_source)
            elif format_name == "lzma":
                files = [path for path in archive_source.iterdir() if path.is_file()]
                if len(files) != 1 or any(path.is_dir() for path in archive_source.iterdir()):
                    raise ArchiveValidationError("LZMA output requires exactly one file")
                with files[0].open("rb") as source_file, lzma.open(temporary_path, "wb", format=lzma.FORMAT_ALONE) as archive:
                    shutil.copyfileobj(source_file, archive)
            else:
                raise ArchiveValidationError("unsupported archive format")
            with temporary_path.open("rb+") as temporary:
                os.fsync(temporary.fileno())
            os.replace(temporary_path, archive_path)
        finally:
            with suppress(FileNotFoundError):
                temporary_path.unlink()


def _format_for_suffix(suffix: str) -> str:
    return {
        ".zip": "zip",
        ".7z": "7z",
        ".rar": "rar",
        ".tar": "tar",
        ".tar.gz": "tar-gz",
        ".tgz": "tar-gz",
        ".tar.bz2": "tar-bz2",
        ".tbz2": "tar-bz2",
        ".tar.xz": "tar-xz",
        ".txz": "tar-xz",
        ".tar.lzma": "tar-lzma",
        ".lzma": "lzma",
    }[suffix]


def _validate_members(entries: Iterable[ArchiveMember]) -> tuple[ArchiveMember, ...]:
    members = tuple(entries)
    if len(members) > ARCHIVE_MAX_MEMBERS:
        raise ArchiveValidationError("archive contains too many members")
    total = 0
    names: set[str] = set()
    for member in members:
        normalized = _validate_member_name(member.name)
        identity = normalized.casefold()
        if identity in names:
            raise ArchiveValidationError(f"archive has duplicate member {member.name!r}")
        names.add(identity)
        if member.link:
            raise ArchiveValidationError(f"archive member {member.name!r} is a link")
        if member.size < 0 or member.size > ARCHIVE_MAX_MEMBER_BYTES:
            raise ArchiveValidationError(f"archive member {member.name!r} exceeds the size limit")
        total += member.size
        if total > ARCHIVE_MAX_TOTAL_BYTES:
            raise ArchiveValidationError("archive exceeds the uncompressed size limit")
        if member.compressed_size not in (None, 0) and member.size > (
            member.compressed_size * ARCHIVE_MAX_COMPRESSION_RATIO
        ):
            raise ArchiveValidationError(f"archive member {member.name!r} exceeds the compression ratio limit")
    return members


def _validate_member_name(name: str) -> str:
    if not name or len(name) > ARCHIVE_MAX_MEMBER_PATH_LENGTH or "\\" in name or "\x00" in name:
        raise ArchiveValidationError("archive member path is invalid")
    normalized = name.rstrip("/")
    if not normalized or normalized.startswith("/") or normalized != posixpath.normpath(normalized):
        raise ArchiveValidationError(f"archive member path {name!r} is unsafe")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ArchiveValidationError(f"archive member path {name!r} is unsafe")
    if ":" in normalized or ntpath.isreserved(normalized):
        raise ArchiveValidationError(f"archive member path {name!r} is unsafe")
    return normalized


def _zip_member_is_link(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _member_destination(root: Path, name: str) -> Path:
    target = root.joinpath(*_validate_member_name(name).split("/"))
    if not target.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
        raise ArchiveValidationError(f"archive member path {name!r} escapes its destination")
    return target


def _extract_stream(
    destination: Path,
    member: ArchiveMember,
    source,
    *,
    max_bytes: int = ARCHIVE_MAX_MEMBER_BYTES,
    limit_name: str = "size limit",
) -> None:
    target = _member_destination(destination, member.name)
    if member.directory:
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with target.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ArchiveValidationError(
                        f"archive member {member.name!r} exceeds the {limit_name}"
                    )
                output.write(chunk)
    except Exception:
        with suppress(FileNotFoundError):
            target.unlink()
        raise


@contextmanager
def _open_tar(path: Path, mode: str, format_name: str | None = None):
    if format_name == "tar-lzma":
        stream_mode = "rb" if mode == "r" else "wb"
        with lzma.open(path, stream_mode, format=lzma.FORMAT_AUTO if mode == "r" else lzma.FORMAT_ALONE) as stream, tarfile.open(
            fileobj=cast(Any, stream), mode=cast(Any, "r:" if mode == "r" else "w:")
        ) as archive:
            yield archive
        return
    write_modes: dict[str, Literal["w:", "w:gz", "w:bz2", "w:xz"]] = {
        "tar": "w:",
        "tar-gz": "w:gz",
        "tar-bz2": "w:bz2",
        "tar-xz": "w:xz",
    }
    tar_mode = "r:*" if mode == "r" else write_modes[format_name or "tar"]
    with tarfile.open(path, tar_mode) as archive:
        yield archive


def _relative_paths(root: Path) -> Iterable[tuple[Path, str]]:
    try:
        for path, relative, _directory in iter_directory_tree(root):
            yield path, relative
    except DirectoryTraversalError as error:
        raise ArchiveValidationError(str(error)) from error


def _write_zip_tree(archive: zipfile.ZipFile, root: Path) -> None:
    for path, relative in _relative_paths(root):
        if path.is_dir():
            archive.mkdir(f"{relative}/")
        else:
            archive.write(path, relative)


def _write_tar_tree(archive: tarfile.TarFile, root: Path) -> None:
    for path, relative in _relative_paths(root):
        archive.add(path, arcname=relative, recursive=False)


def _write_7z_tree(archive, root: Path) -> None:
    for path, relative in _relative_paths(root):
        archive.write(path, arcname=relative)


def _assert_no_links(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ArchiveValidationError(f"archive extraction created a link: {path}")


def _tree_contains_link(root: Path) -> bool:
    return root.is_symlink() or any(path.is_symlink() for path in root.rglob("*"))


def _materialize_tree(source: Path, destination: Path) -> None:
    try:
        for path, relative, directory in iter_directory_tree(source):
            target = destination.joinpath(*relative.split("/"))
            if directory:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    except DirectoryTraversalError as error:
        raise ArchiveValidationError(str(error)) from error
