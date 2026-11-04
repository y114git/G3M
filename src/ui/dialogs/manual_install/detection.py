"""Conservative file assignments for manual imports. Never writes to game files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

from config.config import MOD_DOCUMENTATION_EXTENSIONS
from utils.mod.hashing import sha256_path
from utils.mod.operation_plan import (
    ModPathContext,
    portable_operation_path,
    resolve_operation_path,
)

_EXECUTABLE_SUFFIXES = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".csx",
    ".py",
}
PATCH_SUFFIXES = frozenset({".xdelta", ".vcdiff", ".g3mpatch"})
_CHUNK = 1024 * 1024
_AUTO_PROBE_LIMIT = 64
_AUTO_PROBE_SECONDS = 30


def _iter_files(
    root: Path, *, include_directories: bool = False,
    cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[tuple[str, str]]:
    """Exclude directory links too, including Windows junctions."""
    if cancelled():
        raise InterruptedError
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        return

    def fail(error: OSError) -> None:
        raise error

    for folder, directories, filenames in os.walk(
        root, onerror=fail, followlinks=False
    ):
        if cancelled():
            raise InterruptedError
        directories[:] = [
            name
            for name in directories
            if not (Path(folder) / name).is_symlink()
            and not (Path(folder) / name).is_junction()
        ]
        if include_directories:
            for name in directories:
                if cancelled():
                    raise InterruptedError
                path = Path(folder) / name
                yield str(path), path.relative_to(root).as_posix() + "/"
        directories.sort(key=str.casefold)
        for name in sorted(filenames, key=str.casefold):
            if cancelled():
                raise InterruptedError
            path = Path(folder) / name
            if path.is_file() and not path.is_symlink():
                yield str(path), path.relative_to(root).as_posix()


def default_action(relative: str) -> str:
    """Patch files default to patching their destination; everything else replaces it."""
    is_patch = not relative.endswith("/") and Path(relative).suffix.casefold() in PATCH_SUFFIXES
    return "patch" if is_patch else "overwrite"


def scan_files(root: Path, *, include_directories: bool = False) -> list[tuple[str, str]]:
    return sorted(_iter_files(root, include_directories=include_directories), key=lambda item: item[1].casefold())


def patch_kind(path: Path) -> str | None:
    if path.is_dir():
        return "g3mpatch" if (path / "g3mpatch.json").is_file() else None
    with path.open("rb") as handle:
        header = handle.read(4)
    if header == b"\xd6\xc3\xc4\x00":
        return "xdelta"
    if header.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                archive.getinfo("g3mpatch.json")
            return "g3mpatch"
        except KeyError, zipfile.BadZipFile:
            pass
    return None


def scan_import_files(root: Path) -> list[tuple[str, str]]:
    files = scan_files(root)
    containers: list[Path] = []
    for source, _relative in sorted(files, key=lambda item: len(Path(item[0]).parts)):
        path = Path(source)
        if path.name == "g3mpatch.json" and not any(
            path.is_relative_to(folder) for folder in containers
        ):
            containers.append(path.parent)
    result = [
        (source, relative)
        for source, relative in files
        if not any(Path(source).is_relative_to(folder) for folder in containers)
    ]
    used = {relative.casefold() for _source, relative in result}
    for folder in containers:
        relative = folder.relative_to(root).as_posix()
        relative = f"{relative}.g3mpatch" if relative != "." else "patch.g3mpatch"
        while relative.casefold() in used:
            relative = f"{relative.removesuffix('.g3mpatch')}_patch.g3mpatch"
        used.add(relative.casefold())
        result.append((str(folder), relative))
    normalized = []
    for source, relative in result:
        kind = patch_kind(Path(source))
        suffix = Path(relative).suffix.casefold()
        if kind and suffix not in (
            {".xdelta", ".vcdiff"} if kind == "xdelta" else {".g3mpatch"}
        ):
            relative = f"{relative}.{kind}"
            while relative.casefold() in used:
                relative = f"{relative.removesuffix(f'.{kind}')}_patch.{kind}"
            used.add(relative.casefold())
        normalized.append((source, relative))
    return sorted(normalized, key=lambda item: item[1].casefold())


def pack_patch(
    folder: Path, output: Path, cancelled: Callable[[], bool] = lambda: False
) -> None:
    """Keep an unpacked G3MPatch together as one portable source archive."""
    output_path = output.resolve()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, relative in _iter_files(folder, cancelled=cancelled):
            if Path(source).resolve() == output_path:
                continue
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            with (
                open(source, "rb") as original,
                archive.open(info, "w", force_zip64=True) as destination,
            ):
                while chunk := original.read(_CHUNK):
                    if cancelled():
                        raise InterruptedError
                    destination.write(chunk)


def _xdelta_metadata(path: Path) -> tuple[list[tuple[int, int]], int]:
    """Read window checksums without decoding. Unchecked/custom-code-table streams stay manual."""
    with path.open("rb") as handle:

        def byte() -> int:
            value = handle.read(1)
            if not value:
                raise ValueError("truncated VCDIFF")
            return value[0]

        def integer() -> int:
            value = 0
            for _ in range(10):
                part = byte()
                value = (value << 7) | (part & 127)
                if not part & 128:
                    return value
            raise ValueError("invalid VCDIFF integer")

        if handle.read(4) != b"\xd6\xc3\xc4\x00":
            return [], 0
        flags = byte()
        if flags & ~5:
            return [], 0
        if flags & 1:
            byte()
        if flags & 4:
            header_size = integer()
            handle.seek(header_size, 1)
        checksums = []
        minimum_base_size = 0
        size = path.stat().st_size
        while handle.tell() < size:
            window = byte()
            if window & ~7 or not window & 4 or window & 3 == 3:
                return [], 0
            if window & 3:
                source_size, source_position = integer(), integer()
                if window & 1:
                    minimum_base_size = max(
                        minimum_base_size, source_position + source_size
                    )
            delta_size = integer()
            end = handle.tell() + delta_size
            target_size = integer()
            if byte() & ~7:
                return [], 0
            lengths = [integer() for _ in range(3)]
            checksum = handle.read(4)
            if len(checksum) != 4 or handle.tell() + sum(lengths) != end or end > size:
                return [], 0
            checksums.append((target_size, int.from_bytes(checksum, "big")))
            handle.seek(end)
        return checksums, minimum_base_size


def _output_matches(
    output: Path, checksums: list[tuple[int, int]],
    cancelled: Callable[[], bool] = lambda: False,
) -> bool:
    with output.open("rb") as handle:
        for size, expected in checksums:
            actual = 1
            while size:
                if cancelled():
                    raise InterruptedError
                chunk = handle.read(min(size, _CHUNK))
                if not chunk:
                    return False
                size -= len(chunk)
                actual = zlib.adler32(chunk, actual)
            if actual != expected:
                return False
        return not handle.read(1)


def _manifest(path: Path) -> dict:
    if path.is_dir():
        manifest = path / "g3mpatch.json"
        if manifest.stat().st_size > 8 * 1024 * 1024:
            return {}
        return json.loads(manifest.read_text(encoding="utf-8-sig"))
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("g3mpatch.json")
        if info.file_size > 8 * 1024 * 1024:
            return {}
        return json.loads(archive.read(info).decode("utf-8-sig"))


def _md5(path: Path, cancelled: Callable[[], bool]) -> str:
    if cancelled():
        raise InterruptedError
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            if cancelled():
                raise InterruptedError
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, target: Path, cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise InterruptedError
    with source.open("rb") as original, target.open("wb") as output:
        while chunk := original.read(_CHUNK):
            if cancelled():
                raise InterruptedError
            output.write(chunk)


def _game_data(path: Path) -> bool:
    if path.suffix.casefold() not in {".win", ".unx", ".ios"}:
        return False
    with path.open("rb") as handle:
        header = handle.read(12)
    return (
        len(header) == 12
        and header[:4] == b"FORM"
        and int.from_bytes(header[4:8], "little") == path.stat().st_size - 8
        and header[8:] == b"GEN8"
    )


def detect_operations(
    files: list[tuple[str, str]],
    context: ModPathContext,
    apply_patch: Callable[[str, Path, Path, Path], bool | None],
    *,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int], None] = lambda _done, _total: None,
    docs_as_info: bool = True,
) -> dict[str, dict]:
    assignments: dict[str, dict] = {}
    roots = list(dict.fromkeys(root for root in (context.game_path, context.game_data_path) if root))
    cached_files: dict[Path, list[Path]] = {root: [] for root in roots}
    walkers = {root: _iter_files(root, cancelled=cancelled) for root in roots}

    def installed_files(root: Path) -> Iterator[Path]:
        yield from cached_files[root]
        try:
            for source, _relative in walkers[root]:
                candidate = Path(source)
                cached_files[root].append(candidate)
                yield candidate
        except InterruptedError:
            raise
        except OSError:
            return

    hashes: dict[Path, str] = {}
    all_parts = [Path(relative).parts for _source, relative in files]
    wrapper = (
        all_parts[0][0]
        if all_parts
        and all(len(parts) > 1 and parts[0] == all_parts[0][0] for parts in all_parts)
        else None
    )
    with tempfile.TemporaryDirectory(prefix="g3m_manual_probe_") as temporary:
        temporary_path = Path(temporary)
        for index, (source, relative) in enumerate(files):
            if cancelled():
                return {}
            path = Path(source)
            try:
                kind = patch_kind(path)
                if kind:
                    manifest = _manifest(path) if kind == "g3mpatch" else {}
                    if not isinstance(manifest, dict):
                        continue
                    original = manifest.get("original", {})
                    modified = manifest.get("modified", {})
                    modified_hash = (
                        modified.get("md5", "") if isinstance(modified, dict) else ""
                    )
                    expected = (
                        original.get("md5", "") if isinstance(original, dict) else ""
                    )
                    checksums, minimum_base_size = (
                        _xdelta_metadata(path) if kind == "xdelta" else ([], 0)
                    )
                    if kind != "xdelta":
                        if not isinstance(expected, str) or not re.fullmatch(
                            r"[0-9a-fA-F]{32}", expected
                        ):
                            continue
                    elif not checksums or not minimum_base_size:
                        # A stream that never refers to its base cannot identify a destination.
                        continue
                    match = None
                    deadline = time.monotonic() + _AUTO_PROBE_SECONDS
                    def interrupted(limit=deadline) -> bool:
                        return cancelled() or time.monotonic() >= limit
                    patch = path
                    if path.is_dir():
                        patch = temporary_path / f"input-{index}.g3mpatch"
                        pack_patch(path, patch, interrupted)
                    source_hash = sha256_path(patch, cancelled=interrupted)
                    seen = set()
                    for root in roots:
                        attempts = 0
                        for candidate in installed_files(root):
                            if interrupted():
                                raise InterruptedError
                            if not expected and attempts >= _AUTO_PROBE_LIMIT:
                                break
                            if candidate in seen:
                                continue
                            seen.add(candidate)
                            try:
                                size = candidate.stat().st_size
                                if expected:
                                    if size != original.get("size", size):
                                        continue
                                    if candidate not in hashes:
                                        hashes[candidate] = _md5(candidate, interrupted)
                                    if hashes[candidate].casefold() != expected.casefold():
                                        continue
                            except InterruptedError:
                                raise
                            except OSError:
                                continue
                            if not expected and size < minimum_base_size:
                                continue
                            attempts += 1
                            # Each trial receives a private base and output, even if a backend misbehaves.
                            base = temporary_path / "base"
                            copy_file(candidate, base, interrupted)
                            if expected and _md5(base, interrupted).casefold() != expected.casefold():
                                continue
                            base_hash = sha256_path(base, cancelled=interrupted)
                            output = temporary_path / "output"
                            output.unlink(missing_ok=True)
                            applied = apply_patch(kind, base, patch, output)
                            if applied is None or interrupted():
                                raise InterruptedError
                            if not applied or not output.is_file():
                                continue
                            if kind == "xdelta" and not _output_matches(output, checksums, interrupted):
                                continue
                            if modified_hash and (
                                not isinstance(modified_hash, str)
                                or _md5(output, interrupted).casefold() != modified_hash.casefold()
                            ):
                                continue
                            if sha256_path(candidate, cancelled=interrupted) != base_hash:
                                continue
                            match = candidate, base_hash
                            break
                        if match:
                            break
                    if (
                        match
                        and not interrupted()
                        and sha256_path(patch, cancelled=interrupted) == source_hash
                    ):
                        candidate, base_hash = match
                        assignments[relative] = {
                            "type": "patch",
                            "target": portable_operation_path(candidate, context),
                            "target_hash": base_hash,
                            "source_hash": source_hash,
                        }
                elif (
                    path.suffix.casefold() not in _EXECUTABLE_SUFFIXES
                    and path.suffix.casefold() not in PATCH_SUFFIXES
                    and not zipfile.is_zipfile(path)
                ):
                    possible = [relative]
                    if wrapper:
                        possible.append(Path(relative).relative_to(wrapper).as_posix())
                    match = None
                    is_data = _game_data(path)
                    for root in roots:
                        for value in possible:
                            if cancelled():
                                return {}
                            candidate = root / value
                            components = (candidate, *candidate.parents[:len(Path(value).parts) - 1])
                            if candidate.is_file() and not any(part.is_symlink() or part.is_junction() for part in components):
                                if path.suffix.casefold() in {".win", ".unx", ".ios"} and not (is_data and _game_data(candidate)):
                                    continue
                                match = candidate
                                break
                        if not match and is_data and path.name.casefold() in {"data.win", "game.unx", "game.ios"}:
                            data_files = []
                            for candidate in installed_files(root):
                                if cancelled():
                                    return {}
                                if _game_data(candidate):
                                    data_files.append(candidate)
                                    if len(data_files) > 1:
                                        break
                            if len(data_files) == 1:
                                match = data_files[0]
                        if match:
                            break
                    if match:
                        assignments[relative] = {
                            "type": "overwrite",
                            "target": portable_operation_path(match, context),
                        }
                    elif docs_as_info and path.suffix.casefold() in MOD_DOCUMENTATION_EXTENSIONS:
                        assignments[relative] = {"type": "info"}
            except InterruptedError:
                if cancelled():
                    return {}
            except OSError, ValueError, KeyError, zipfile.BadZipFile:
                # Corrupt files or unsuccessful probes need an explicit user choice.
                pass
            finally:
                progress(index + 1, len(files))
    # Alternative versions in one archive must not all modify the same destination.
    destinations = Counter(
        entry.get("target") for entry in assignments.values() if entry.get("target")
    )
    return {
        relative: entry
        for relative, entry in assignments.items()
        if not entry.get("target") or destinations[entry["target"]] == 1
    }


def verify_operations(
    files, context, assignments, apply_patch, cancelled=lambda: False, *, game=""
) -> dict[str, dict]:
    """Check the selected order on private copies, including overwrite-then-patch chains."""
    verified = {}
    targets: dict[Path, Path] = {}
    target_counts = Counter(
        resolve_operation_path(
            entry["target"], context=context, is_target=True, game=game
        )
        for entry in assignments.values()
        if entry.get("target") and entry.get("type") in {"patch", "overwrite"}
    )
    with tempfile.TemporaryDirectory(prefix="g3m_manual_validate_") as temporary:
        root = Path(temporary)
        for index, (source, relative) in enumerate(files):
            if cancelled():
                raise InterruptedError
            entry = assignments.get(relative, {})
            action = entry.get("type")
            if action not in {"patch", "overwrite"} or not entry.get("target"):
                continue
            target = resolve_operation_path(
                entry["target"], context=context, is_target=True, game=game
            )
            if not isinstance(target, Path):
                raise ValueError(f"{relative}: select a destination file")
            output = root / f"output-{index}"
            path = Path(source)
            if action == "overwrite":
                targets[target] = path
                verified[relative] = dict(entry, source_hash=sha256_path(path, cancelled=cancelled))
                continue
            base = targets.get(target, target)
            if not base.is_file():
                raise ValueError(f"{relative}: destination file does not exist")
            private_base = root / f"base-{index}"
            copy_file(base, private_base, cancelled)
            patch = path
            if path.is_dir():
                patch = root / f"patch-{index}.g3mpatch"
                pack_patch(path, patch, cancelled)
            kind = patch_kind(patch)
            if not kind:
                raise ValueError(f"{relative}: not an xdelta or G3MPatch file")
            base_hash, source_hash = sha256_path(private_base, cancelled=cancelled), sha256_path(patch, cancelled=cancelled)
            if (
                target not in targets
                and entry.get("target_hash") == base_hash
                and entry.get("source_hash") == source_hash
            ):
                verified[relative] = dict(entry)
                # A following patch still needs this patch's output as its input.
                if target_counts[target] == 1:
                    continue
            if (
                not apply_patch(kind, private_base, patch, output)
                or not output.is_file()
            ):
                raise ValueError(
                    f"{relative}: patch cannot be applied to the selected file"
                )
            if sha256_path(patch, cancelled=cancelled) != source_hash:
                raise ValueError(f"{relative}: patch changed during validation")
            checksums = _xdelta_metadata(patch)[0] if kind == "xdelta" else []
            if checksums and not _output_matches(output, checksums, cancelled):
                raise ValueError(
                    f"{relative}: patched output does not match its checksums"
                )
            if kind == "g3mpatch":
                manifest = _manifest(patch)
                original = manifest.get("original", {})
                modified = manifest.get("modified", {})
                expected = original.get("md5") if isinstance(original, dict) else None
                result_hash = (
                    modified.get("md5") if isinstance(modified, dict) else None
                )
                if (
                    expected
                    and result_hash
                    and _md5(private_base, cancelled).casefold()
                    == str(expected).casefold()
                    and _md5(output, cancelled).casefold()
                    != str(result_hash).casefold()
                ):
                    raise ValueError(
                        f"{relative}: patched output does not match the expected file"
                    )
            if sha256_path(base, cancelled=cancelled) != base_hash:
                raise ValueError(f"{relative}: destination changed during validation")
            targets[target] = output
            verified[relative] = dict(
                entry, source_hash=source_hash, target_hash=base_hash
            )
    return verified
