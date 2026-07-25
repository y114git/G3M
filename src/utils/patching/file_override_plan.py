"""Priority reduction for loose-file override candidates."""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OverrideCandidate:
    source: str
    target: str
    priority: int


def discover_directory_candidates(
    source_root: str,
    target_root: str,
    *,
    priority: int,
    excluded_extensions: tuple[str, ...] = (),
    excluded_names: set[str] | None = None,
    exclude_relative=None,
) -> list[OverrideCandidate]:
    """Enumerate safe regular files without following links or reading content."""
    source_root = os.path.abspath(source_root)
    resolved_root = os.path.normcase(os.path.realpath(source_root))
    excluded_names = {name.casefold() for name in (excluded_names or set())}
    excluded_extensions = tuple(ext.casefold() for ext in excluded_extensions)
    pending = [(source_root, "")]
    result: list[OverrideCandidate] = []
    while pending:
        directory, relative_dir = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError:
            continue
        for entry in entries:
            relative = os.path.join(relative_dir, entry.name) if relative_dir else entry.name
            try:
                if entry.is_symlink():
                    continue
                resolved = os.path.normcase(os.path.realpath(entry.path))
                if os.path.commonpath((resolved_root, resolved)) != resolved_root:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append((entry.path, relative))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except (OSError, ValueError):
                continue
            name = entry.name.casefold()
            if name in excluded_names or name.endswith(excluded_extensions):
                continue
            if exclude_relative and exclude_relative(relative):
                continue
            result.append(
                OverrideCandidate(
                    source=entry.path,
                    target=os.path.join(target_root, relative),
                    priority=priority,
                )
            )
    return result


def _destination_key(path: str, *, case_sensitive: bool) -> str:
    normalized = os.path.abspath(os.path.normpath(path))
    return normalized if case_sensitive else normalized.casefold()


def destination_is_case_sensitive(path: str) -> bool:
    """Probe the destination filesystem instead of inferring from the OS."""
    probe_root = path if os.path.isdir(path) else os.path.dirname(path)
    probe_root = probe_root or os.curdir
    probe_dir = tempfile.mkdtemp(prefix=".g3m-case-probe-", dir=probe_root)
    try:
        lower = os.path.join(probe_dir, "probe")
        Path(lower).touch()
        return not os.path.exists(os.path.join(probe_dir, "PROBE"))
    finally:
        import shutil

        shutil.rmtree(probe_dir, ignore_errors=True)


def build_override_plan(
    candidates: list[OverrideCandidate],
    *,
    case_sensitive: bool,
) -> list[OverrideCandidate]:
    """Return one highest-priority replacement per normalized destination."""
    winners: dict[str, OverrideCandidate] = {}
    for candidate in candidates:
        key = _destination_key(candidate.target, case_sensitive=case_sensitive)
        current = winners.get(key)
        if current is None or candidate.priority >= current.priority:
            winners[key] = candidate
    return sorted(
        winners.values(),
        key=lambda item: _destination_key(
            item.target, case_sensitive=case_sensitive
        ),
    )


def apply_override_plan(
    plan: list[OverrideCandidate],
    *,
    backup_or_mark,
    cancelled=lambda: False,
) -> bool:
    """Install planned replacements atomically, backing up each target once."""
    for candidate in plan:
        if cancelled():
            return False
        target = Path(candidate.target)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_or_mark(str(target))
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".g3m-tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            import shutil

            shutil.copy2(candidate.source, temporary)
            os.replace(temporary, target)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
    return True
