"""Pure filesystem planning for validated operation mod configs."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import cast

from utils.mod.archive import (
    ArchiveValidationError,
    ArchiveVirtualPath,
    archive_write_supported,
    list_archive_members,
    materialize_archive,
    split_archive_virtual_path,
)
from utils.mod.config import (
    ModConfigValidationError,
    is_direct_absolute_path,
    iter_mod_config_leaves,
    parse_mod_config,
)
from utils.mod.hashing import HashValidationError, sha256_path

_PLACEHOLDER_RE = re.compile(r"^\$\{(?P<name>[A-Za-z][A-Za-z0-9_]*)\}(?P<suffix>/.*)$")
_CHAPTER_PLATFORM_RE = re.compile(r"^chapter\d+_(?:windows|mac)$")


def section_target_root(game: str, section_id: str) -> str:
    """Return the current game root for a named game section."""
    prefix, _, chapter = section_id.rpartition("_")
    if game == "deltarune" and prefix == "deltarune" and chapter.isdecimal() and chapter != "0":
        return f"${{game_path}}/chapter{chapter}_windows"
    return "${game_path}"


@dataclass(frozen=True, slots=True)
class ModPathContext:
    """Resolved runtime roots available to one mod plan."""

    mod_path: Path
    game_path: Path | None
    game_data_path: Path | None
    user_path: Path
    platform: str = sys.platform
    runtime: str | None = None

    @classmethod
    def create(
        cls,
        *,
        mod_path: str | Path,
        game_path: str | Path | None,
        game_data_path: str | Path | None,
        user_path: str | Path,
        platform: str = sys.platform,
        runtime: str | None = None,
    ) -> ModPathContext:
        def resolved(value: str | Path | None) -> Path | None:
            return Path(value).resolve(strict=False) if value else None

        return cls(
            mod_path=Path(mod_path).resolve(strict=False),
            game_path=resolved(game_path),
            game_data_path=resolved(game_data_path),
            user_path=Path(user_path).resolve(strict=False),
            platform=platform,
            runtime=runtime,
        )


def is_inside_trusted_root(path: str | Path | ArchiveVirtualPath | None, context: ModPathContext) -> bool:
    """Whether a path lies in a folder the user chose: the game folder, the game data folder or the mod folder."""
    if path is None:
        return False
    if isinstance(path, ArchiveVirtualPath):
        path = path.archive
    selected = Path(path).resolve(strict=False)
    for root in (context.game_path, context.game_data_path, context.mod_path):
        if root is None:
            continue
        try:
            selected.relative_to(root.resolve(strict=False))
        except ValueError:
            continue
        return True
    return False


def portable_operation_path(path: str | Path, context: ModPathContext) -> str:
    """Use the most specific standard root, matching complete path components."""
    selected = Path(path).resolve(strict=False)
    roots = (
        ("mod_path", context.mod_path),
        ("game_path", context.game_path),
        ("game_data_path", context.game_data_path),
        ("user_path", context.user_path),
    )
    for name, root in sorted(roots, key=lambda pair: len(pair[1].parts) if pair[1] else -1, reverse=True):
        if root is None:
            continue
        try:
            relative = selected.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        return f"${{{name}}}/" + (relative if relative != "." else "")
    return selected.as_posix()


@dataclass(frozen=True, slots=True)
class PlanFinding:
    """A non-mutating issue discovered while resolving an operation."""

    severity: str
    code: str
    operation_index: int
    message: str
    detail: str = ""  # the path, name or reason the localized text names


@dataclass(frozen=True, slots=True)
class PlannedModOperation:
    """One fully resolved operation in observable config order."""

    index: int
    group_path: tuple[str, ...]
    type: str
    source: Path | ArchiveVirtualPath
    source_is_directory: bool
    target: Path | ArchiveVirtualPath | None
    target_is_directory: bool
    source_hash: str | None
    target_hash: str | None
    mod_id: str | None = None
    merge_group: int | None = None
    merge_priority: int = 0


@dataclass(frozen=True, slots=True)
class ModOperationPlan:
    """Ordered operations and all current-state findings."""

    operations: tuple[PlannedModOperation, ...]
    findings: tuple[PlanFinding, ...]

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)


def build_profile_operation_plan(
    configs: Mapping[str, Mapping[str, object]],
    contexts: Mapping[str, ModPathContext],
    ordered_mod_ids: Sequence[str],
    *,
    merge_steps: Sequence[Sequence[str]] = (),
) -> ModOperationPlan:
    """Build the selected profile's visible operation order without mutations."""
    operations: list[PlannedModOperation] = []
    findings: list[PlanFinding] = []
    offset = 0
    seen: set[str] = set()
    merge_details: dict[str, tuple[int, int]] = {}
    for group, step in enumerate(merge_steps):
        mod_ids = tuple(mod_id for mod_id in step if isinstance(mod_id, str) and mod_id)
        if len(mod_ids) < 2:
            continue
        for priority, mod_id in enumerate(reversed(mod_ids)):
            merge_details.setdefault(mod_id, (group, priority))
    produced_targets: set[str] = set()
    for mod_id in ordered_mod_ids:
        if mod_id in seen:
            continue
        seen.add(mod_id)
        config = configs.get(mod_id)
        context = contexts.get(mod_id)
        if config is None:
            findings.append(
                PlanFinding("error", "config_missing", 0, f"{mod_id}: configuration is unavailable", mod_id)
            )
            continue
        if context is None:
            findings.append(
                PlanFinding("error", "path_context_missing", 0, f"{mod_id}: path context is unavailable", mod_id)
            )
            continue
        try:
            plan = build_mod_operation_plan(
                config, context, produced_targets=produced_targets
            )
        except ModConfigValidationError as error:
            findings.extend(
                PlanFinding("error", issue.code, 0, f"{mod_id}: {issue.path}: {issue.message}", f"{mod_id}: {issue.message}")
                for issue in error.issues
            )
            continue
        merge_group, merge_priority = merge_details.get(mod_id, (None, 0))
        operations.extend(
            replace(
                operation,
                index=offset + operation.index,
                mod_id=mod_id,
                merge_group=merge_group,
                merge_priority=merge_priority,
            )
            for operation in plan.operations
        )
        findings.extend(
            replace(
                finding,
                operation_index=offset + finding.operation_index,
                message=f"{mod_id}: {finding.message}",
            )
            for finding in plan.findings
        )
        offset += max(
            [operation.index for operation in plan.operations]
            + [finding.operation_index for finding in plan.findings],
            default=0,
        )
    return ModOperationPlan(tuple(operations), tuple(findings))


def _root_paths(context: ModPathContext) -> dict[str, Path | None]:
    return {
        "mod_path": context.mod_path,
        "game_path": context.game_path,
        "game_data_path": context.game_data_path,
        "user_path": context.user_path,
    }


def _expand_custom_placeholder(
    value: str, custom_placeholders: Mapping[str, object]
) -> str:
    match = _PLACEHOLDER_RE.fullmatch(value)
    if not match or match.group("name") not in custom_placeholders:
        return value
    placeholder_value = custom_placeholders[match.group("name")]
    if not isinstance(placeholder_value, str):
        return value
    return f"{placeholder_value}{match.group('suffix')}"


def _resolve_path(
    stored_path: str,
    *,
    context: ModPathContext,
    custom_placeholders: Mapping[str, object],
    is_target: bool,
) -> tuple[Path | ArchiveVirtualPath | None, str | None]:
    expanded = _expand_custom_placeholder(stored_path, custom_placeholders)
    match = _PLACEHOLDER_RE.fullmatch(expanded)
    if not match:
        is_windows = context.platform.startswith(("win", "cygwin"))
        if PureWindowsPath(expanded).is_absolute() and not is_windows:
            return None, "Windows absolute paths are unavailable on this operating system"
        if PurePosixPath(expanded).is_absolute() and is_windows:
            return None, "POSIX absolute paths are unavailable on Windows"
        candidate = Path(expanded)
    else:
        root_name = match.group("name")
        root = _root_paths(context).get(root_name)
        if root is None:
            return None, f"{root_name} is not configured"
        candidate = root.joinpath(*match.group("suffix").strip("/").split("/"))
        try:
            candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            if not (is_target and candidate.is_symlink()):
                return None, f"{root_name} path escapes its configured root"
    try:
        virtual_candidate = f"{candidate}/" if stored_path.endswith("/") else candidate
        return split_archive_virtual_path(virtual_candidate) or candidate, None
    except ArchiveValidationError as error:
        return None, str(error)


def resolve_operation_path(
    stored_path: str,
    *,
    context: ModPathContext,
    custom_placeholders: Mapping[str, object] | None = None,
    is_target: bool = False,
    game: str = "",
) -> Path | ArchiveVirtualPath | None:
    """Resolve one operation path without checking or reading its contents."""
    resolved, error = _resolve_path(
        stored_path,
        context=context,
        custom_placeholders=custom_placeholders or {},
        is_target=is_target,
    )
    if resolved is None or error:
        return None
    return (
        _rewrite_target_archive_path(resolved, game=game, context=context)
        if is_target
        else resolved
    )


def _context_runtime(context: ModPathContext) -> str:
    if context.runtime in {"windows", "linux", "macos"}:
        return context.runtime
    if context.platform == "darwin":
        return "macos"
    if context.platform.startswith("linux"):
        return "linux"
    return "windows"


def _rewrite_target_for_runtime(target: Path, *, game: str, context: ModPathContext) -> Path:
    parts = list(target.parts)
    runtime = _context_runtime(context)
    if game == "deltarune" and runtime == "macos":
        parts = [
            part.replace("_windows", "_mac") if _CHAPTER_PLATFORM_RE.fullmatch(part) else part
            for part in parts
        ]
    elif game == "deltarune":
        parts = [
            part.replace("_mac", "_windows") if _CHAPTER_PLATFORM_RE.fullmatch(part) else part
            for part in parts
        ]
    if parts:
        stem, suffix = Path(parts[-1]).stem, Path(parts[-1]).suffix.casefold()
        extension = {"windows": ".win", "linux": ".unx", "macos": ".ios"}[runtime]
        if suffix in {".win", ".unx", ".ios"}:
            if stem.casefold() == "data" or (stem.casefold() == "game" and suffix != extension):
                parts[-1] = "data.win" if runtime == "windows" else f"game{extension}"
            else:
                parts[-1] = f"{stem}{extension}"
    return Path(*parts)


def _rewrite_target_archive_path(
    target: Path | ArchiveVirtualPath, *, game: str, context: ModPathContext
) -> Path | ArchiveVirtualPath:
    if isinstance(target, Path):
        return _rewrite_target_for_runtime(target, game=game, context=context)
    rewritten_member = _rewrite_target_for_runtime(
        Path(target.member), game=game, context=context
    ).as_posix()
    return ArchiveVirtualPath(
        archive=_rewrite_target_for_runtime(target.archive, game=game, context=context),
        member=rewritten_member,
        directory=target.directory,
        format=target.format,
    )


def _resolved_path_state(
    path: Path | ArchiveVirtualPath,
) -> tuple[bool, bool | None, str | None]:
    if isinstance(path, Path):
        return path.exists(), path.is_dir() if path.exists() else None, None
    if not path.archive.exists():
        return False, None, None
    try:
        members = list_archive_members(path.archive)
    except (ArchiveValidationError, OSError, ValueError) as error:
        return False, None, str(error)
    if not path.member:
        return True, True, None
    exact = next((member for member in members if member.name.rstrip("/") == path.member), None)
    if exact is not None:
        return True, exact.directory, None
    prefix = f"{path.member}/"
    return any(member.name.startswith(prefix) for member in members), True, None


def _resolved_path_text(path: Path | ArchiveVirtualPath) -> str:
    if isinstance(path, ArchiveVirtualPath):
        suffix = f"/{path.member}" if path.member else "/"
        return f"{path.archive}{suffix}"
    return str(path)


def _planned_target_key(path: Path | ArchiveVirtualPath) -> str:
    """Identify a target produced earlier in this ordered plan."""
    if isinstance(path, ArchiveVirtualPath):
        archive = os.path.normcase(str(path.archive.resolve(strict=False)))
        return f"{archive}!/{path.member}"
    return os.path.normcase(str(path.resolve(strict=False)))


def resolved_sha256(path: Path | ArchiveVirtualPath) -> str:
    if isinstance(path, Path):
        return sha256_path(path)
    with tempfile.TemporaryDirectory(prefix="g3m_hash_") as temporary_name:
        temporary = Path(temporary_name)
        materialize_archive(path.archive, temporary)
        target = temporary.joinpath(*path.member.split("/")) if path.member else temporary
        return sha256_path(target)


def _operation_overlap(
    source: Path | ArchiveVirtualPath,
    target: Path | ArchiveVirtualPath,
    *,
    source_is_directory: bool,
    target_is_directory: bool,
) -> str | None:
    if isinstance(source, Path) and isinstance(target, Path):
        source_path = source.resolve(strict=False)
        target_path = target.resolve(strict=False)
        if source_path == target_path:
            return "source and target are the same path"
        if source_is_directory and target_path.is_relative_to(source_path):
            return "target is inside the source directory"
        if target_is_directory and source_path.is_relative_to(target_path):
            return "source is inside the target directory"
        return None
    if not isinstance(source, ArchiveVirtualPath) or not isinstance(target, ArchiveVirtualPath):
        return None
    if source.archive.resolve(strict=False) != target.archive.resolve(strict=False):
        return None
    if source.member == target.member:
        return "source and target are the same archive member"
    if source_is_directory and target.member.startswith(f"{source.member}/"):
        return "target is inside the source archive directory"
    if target_is_directory and source.member.startswith(f"{target.member}/"):
        return "source is inside the target archive directory"
    return None


def build_mod_operation_plan(
    config: object,
    context: ModPathContext,
    *,
    produced_targets: set[str] | None = None,
) -> ModOperationPlan:
    """Resolve a strict operation config without changing any filesystem state."""
    parsed = parse_mod_config(config)
    placeholders = parsed.get("placeholders")
    custom_placeholders = placeholders if isinstance(placeholders, Mapping) else {}
    game = str(parsed["game"])
    operations: list[PlannedModOperation] = []
    findings: list[PlanFinding] = []
    produced_targets = produced_targets if produced_targets is not None else set()
    files = cast(list[object], parsed["files"])

    for index, (group_path, leaf) in enumerate(
        iter_mod_config_leaves(files), start=1
    ):
        source_value = cast(str, leaf["source"])
        operation_type = cast(str, leaf["type"])
        source_hash = leaf.get("source_hash")
        target_hash = leaf.get("target_hash")
        source, source_error = _resolve_path(
            source_value,
            context=context,
            custom_placeholders=custom_placeholders,
            is_target=False,
        )
        if source_error:
            findings.append(PlanFinding("error", "source_root", index, source_error, source_error))
            continue
        if source is None:
            continue
        if is_direct_absolute_path(source_value) and not is_inside_trusted_root(source, context):
            findings.append(
                PlanFinding(
                    "warning",
                    "direct_absolute_source",
                    index,
                    f"source uses a direct absolute path: {source_value}",
                    source_value,
                )
            )
        source_is_directory = source_value.endswith("/")
        target: Path | ArchiveVirtualPath | None = None
        target_is_directory = False
        if operation_type != "info":
            target_value = leaf["target"]
            target_value = cast(str, target_value)
            target, target_error = _resolve_path(
                target_value,
                context=context,
                custom_placeholders=custom_placeholders,
                is_target=True,
            )
            if target_error:
                findings.append(PlanFinding("error", "target_root", index, target_error, target_error))
                continue
            if target is None:
                continue
            target = _rewrite_target_archive_path(
                target, game=game, context=context
            )
            if is_direct_absolute_path(target_value) and not is_inside_trusted_root(target, context):
                findings.append(
                    PlanFinding(
                        "warning",
                        "direct_absolute_target",
                        index,
                        f"target uses a direct absolute path: {target_value}",
                        target_value,
                    )
                )
            target_is_directory = target_value.endswith("/")
            overlap = _operation_overlap(
                source,
                target,
                source_is_directory=source_value.endswith("/"),
                target_is_directory=target_is_directory,
            )
            if overlap:
                findings.append(PlanFinding("error", "source_target_overlap", index, overlap, overlap))

        source_exists, source_kind, source_state_error = _resolved_path_state(source)
        if source_state_error:
            findings.append(
                PlanFinding("error", "source_archive", index, source_state_error, source_state_error)
            )
        elif not source_exists:
            findings.append(
                PlanFinding(
                    "error",
                    "source_missing",
                    index,
                    f"source does not exist: {_resolved_path_text(source)}",
                    _resolved_path_text(source),
                )
            )
        elif source_is_directory != source_kind:
            expected = "directory" if source_is_directory else "file"
            findings.append(
                PlanFinding(
                    "error",
                    "source_kind",
                    index,
                    f"source must be a {expected}: {_resolved_path_text(source)}",
                    _resolved_path_text(source),
                )
            )
        elif isinstance(source, Path) and source.is_symlink():
            findings.append(
                PlanFinding(
                    "warning",
                    "source_link",
                    index,
                    "source link will be copied as its resolved contents",
                    _resolved_path_text(source),
                )
            )
        if source_exists and source_is_directory == source_kind and isinstance(source_hash, str):
            try:
                if resolved_sha256(source) != source_hash:
                    findings.append(
                        PlanFinding("error", "source_hash", index, "source hash does not match", _resolved_path_text(source))
                    )
            except (ArchiveValidationError, HashValidationError, OSError, ValueError) as error:
                findings.append(PlanFinding("error", "source_hash", index, str(error), _resolved_path_text(source)))
        if target is not None:
            if isinstance(target, Path) and target.is_symlink():
                findings.append(
                    PlanFinding(
                        "warning",
                        "target_link",
                        index,
                        "target link will be temporarily replaced and restored after the game closes",
                        _resolved_path_text(target),
                    )
                )
            if isinstance(target, ArchiveVirtualPath) and not archive_write_supported(target.archive):
                findings.append(
                    PlanFinding(
                        "error",
                        "target_archive_write",
                        index,
                        f"archive format cannot be written: {target.archive}",
                        str(target.archive),
                    )
                )
            target_was_produced = _planned_target_key(target) in produced_targets
            target_exists, _, target_state_error = _resolved_path_state(target)
            target_exists = target_exists or target_was_produced
            if target_state_error:
                findings.append(
                    PlanFinding("error", "target_archive", index, target_state_error, target_state_error)
                )
            elif not target_exists and operation_type != "patch" and not isinstance(target_hash, str) and is_inside_trusted_root(
                target, context
            ):
                pass  # a new file in the game, data or mod folder is expected, not a risk
            elif not target_exists:
                severity = "error" if operation_type == "patch" or isinstance(target_hash, str) else "warning"
                action = "cannot patch" if operation_type == "patch" else "will be created"
                findings.append(
                    PlanFinding(
                        severity,
                        "target_missing" if severity == "error" else "target_created",
                        index,
                        f"target {action}: {_resolved_path_text(target)}",
                        _resolved_path_text(target),
                    )
                )
            elif isinstance(target_hash, str) and not target_was_produced:
                try:
                    if resolved_sha256(target) != target_hash:
                        findings.append(
                            PlanFinding("error", "target_hash", index, "target hash does not match", _resolved_path_text(target))
                        )
                except (ArchiveValidationError, HashValidationError, OSError, ValueError) as error:
                    findings.append(PlanFinding("error", "target_hash", index, str(error), _resolved_path_text(target)))
        operations.append(
            PlannedModOperation(
                index=index,
                group_path=group_path,
                type=operation_type,
                source=source,
                source_is_directory=source_is_directory,
                target=target,
                target_is_directory=target_is_directory,
                source_hash=source_hash if isinstance(source_hash, str) else None,
                target_hash=target_hash if isinstance(target_hash, str) else None,
            )
        )
        if target is not None and operation_type != "info":
            produced_targets.add(_planned_target_key(target))
    return ModOperationPlan(tuple(operations), tuple(findings))
