"""Reversible sequential executor for resolved mod operations."""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack, suppress
from dataclasses import asdict, dataclass
from pathlib import Path

from services.mod_usage import hold_mods
from utils.mod.archive import (
    ArchiveVirtualPath,
    archive_format,
    materialize_archive,
    rebuild_archive,
)
from utils.mod.filesystem import DirectoryTraversalError, iter_directory_tree
from utils.mod.hashing import sha256_path
from utils.mod.operation_plan import ModOperationPlan, PlannedModOperation

# (target, patch, output) plus an optional ``progress`` percent callback, passed only when the
# caller of ``execute`` asked for step progress.
PatchFunction = Callable[..., bool | None]
MergeFunction = Callable[..., bool | None]
ProgressFunction = Callable[[int, int, PlannedModOperation], None]
# overall fraction 0..1, operations finished before the step, total operations, the step's first
# operation, percent of the step the patch backend has reported
StepProgressFunction = Callable[[float, int, int, PlannedModOperation, int], None]
logger = logging.getLogger(__name__)
_MERGEABLE_DATA_SUFFIXES = frozenset({".win", ".ios", ".droid", ".unx"})


def _is_mergeable_target(target: Path | ArchiveVirtualPath | None) -> bool:
    if isinstance(target, Path):
        return target.suffix.casefold() in _MERGEABLE_DATA_SUFFIXES
    return (
        isinstance(target, ArchiveVirtualPath)
        and not target.directory
        and Path(target.member).suffix.casefold() in _MERGEABLE_DATA_SUFFIXES
    )


class ModOperationExecutionError(RuntimeError):
    """An operation cannot safely be applied."""


class ModPatchMismatchError(ModOperationExecutionError):
    """A patch was made for another file than the one it met: another game version or another mod's earlier patch."""

    def __init__(self, mod_id: str | None, patch: str) -> None:
        super().__init__(f"{mod_id or 'a mod'}: patch {patch} does not match the file it was applied to")
        self.mod_id = mod_id
        self.patch = patch


class ModOperationCancelledError(ModOperationExecutionError):
    """The caller cancelled the operation plan."""


class ModRecoveryConflictError(ModOperationExecutionError):
    """A deployed path changed outside the active session."""


@dataclass(slots=True)
class JournalEntry:
    path: str
    kind: str
    backup: str | None
    deployed_hash: str | None = None
    preserve_external: bool = False
    controlled_paths: tuple[str, ...] = ()


class ModOperationJournal:
    """Durable snapshots for one operation overlay session."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.backups = self.root / "backups"
        self.manifest = self.root / "manifest.json"
        if self.manifest.is_file():
            previous = self.load(self.root)
            if previous.state not in {"restored", "retired"}:
                raise ModOperationExecutionError("a previous operation session requires recovery")
            remove_tree(self.backups, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.backups.mkdir(exist_ok=True)
        self.entries: list[JournalEntry] = []
        self._by_path: set[str] = set()
        self.state = "active"
        self._write_manifest("active")

    @classmethod
    def load(cls, root: str | Path) -> ModOperationJournal:
        """Load an interrupted session without changing its manifest."""
        journal_root = Path(root)
        manifest = journal_root / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            state = payload["state"]
            raw_entries = payload["entries"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ModOperationExecutionError(f"cannot load recovery journal: {error}") from error
        if state not in {"active", "applied", "restored", "retired"} or not isinstance(raw_entries, list):
            raise ModOperationExecutionError("recovery journal is invalid")
        instance = cls.__new__(cls)
        instance.root = journal_root
        instance.backups = journal_root / "backups"
        instance.manifest = manifest
        instance.entries = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ModOperationExecutionError("recovery journal entry is invalid")
            controlled_paths = raw_entry.get("controlled_paths", [])
            if not isinstance(controlled_paths, list) or any(
                not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
                for path in controlled_paths
            ):
                raise ModOperationExecutionError("recovery journal entry is invalid")
            try:
                entry = JournalEntry(
                    path=raw_entry["path"],
                    kind=raw_entry["kind"],
                    backup=raw_entry.get("backup"),
                    deployed_hash=raw_entry.get("deployed_hash"),
                    preserve_external=raw_entry.get("preserve_external", False),
                    controlled_paths=tuple(controlled_paths),
                )
            except (KeyError, TypeError) as error:
                raise ModOperationExecutionError("recovery journal entry is invalid") from error
            if (
                entry.kind not in {"file", "directory", "link", "missing"}
                or not isinstance(entry.path, str)
                or not Path(entry.path).is_absolute()
                or (entry.kind != "missing" and not _valid_backup_path(entry.backup))
                or (entry.deployed_hash is not None and not isinstance(entry.deployed_hash, str))
                or not isinstance(entry.preserve_external, bool)
            ):
                raise ModOperationExecutionError("recovery journal entry is invalid")
            instance.entries.append(entry)
        instance._by_path = {entry.path for entry in instance.entries}
        instance.state = state
        return instance

    def capture(
        self,
        path: str | Path,
        *,
        preserve_external: bool = False,
        controlled_path: str | Path | None = None,
        controlled_paths: tuple[str, ...] = (),
    ) -> None:
        """Snapshot an object and each missing parent once, before mutation."""
        target = Path(os.path.abspath(os.fspath(path)))
        _assert_target_parents_safe(target)
        relative_paths = tuple(controlled_paths)
        if controlled_path is not None:
            controlled = Path(os.path.abspath(os.fspath(controlled_path)))
            try:
                relative_paths += (str(controlled.relative_to(target)),)
            except ValueError as error:
                raise ModOperationExecutionError("controlled path is outside its journal target") from error
        missing: list[Path] = []
        cursor = target
        while not _path_exists(cursor):
            missing.append(cursor)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        for candidate in reversed(missing):
            self._capture_one(candidate)
        self._capture_one(
            target,
            preserve_external=preserve_external,
            controlled_paths=relative_paths,
        )
        if preserve_external:
            for entry in tuple(self.entries):
                ancestor = Path(entry.path)
                if entry.kind == "missing" and target.is_relative_to(ancestor):
                    self._capture_one(
                        ancestor,
                        preserve_external=True,
                        controlled_paths=tuple(
                            str(target.relative_to(ancestor) / relative)
                            for relative in relative_paths
                        ),
                    )

    def seal(self) -> None:
        """Record exactly what this session deployed before launching a game."""
        self.checkpoint()

    def checkpoint(self) -> None:
        """Record G3M-controlled changes before external processes run."""
        for entry in self.entries:
            path = Path(entry.path)
            entry.deployed_hash = _path_hash(path)
        self.state = "applied"
        self._write_manifest("applied")

    def restore(self, *, force: bool = False) -> None:
        """Restore snapshots in reverse order without overwriting external edits."""
        if self.state == "retired":
            raise ModOperationExecutionError("recovery journal was retired by the user")
        if not force:
            self.verify_deployed()
        for entry in reversed(self.entries):
            target = Path(entry.path)
            _assert_target_parents_safe(target)
            if (
                force
                and entry.preserve_external
                and entry.kind in {"directory", "missing"}
                and entry.deployed_hash is not None
                and _path_hash(target) != entry.deployed_hash
            ):
                if entry.kind == "directory":
                    _restore_directory_preserving_external(
                        self.root / str(entry.backup), target, entry.controlled_paths
                    )
                else:
                    _remove_controlled_paths(target, entry.controlled_paths)
                continue
            remove_path(target)
            if entry.kind == "file":
                backup = self.root / str(entry.backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            elif entry.kind == "directory":
                backup = self.root / str(entry.backup)
                shutil.copytree(backup, target, symlinks=True)
            elif entry.kind == "link":
                backup = self.root / str(entry.backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                _copy_link(backup, target)
        self.state = "restored"
        self._write_manifest("restored")

    def verify_deployed(self) -> None:
        """Fail when a deployed path differs from G3M's last known state."""
        if self.state != "applied":
            return
        changed = [
            entry.path
            for entry in self.entries
            if _path_hash(Path(entry.path)) != entry.deployed_hash
        ]
        if changed:
            raise ModRecoveryConflictError(
                f"deployed paths changed outside G3M: {', '.join(changed)}"
            )

    def retire(self) -> None:
        """Keep external changes and mark this recovery session as resolved."""
        self._write_manifest("retired")
        remove_tree(self.backups, ignore_errors=True)

    def discard(self) -> None:
        """Forget a successfully committed permanent operation and its backups."""
        remove_tree(self.root)

    def _capture_one(
        self,
        target: Path,
        *,
        preserve_external: bool = False,
        controlled_paths: tuple[str, ...] = (),
    ) -> None:
        key = str(target)
        if key in self._by_path:
            entry = next(entry for entry in self.entries if entry.path == key)
            if preserve_external and not entry.preserve_external:
                entry.preserve_external = True
                self._write_manifest("active")
            if controlled_paths:
                entry.controlled_paths = tuple(dict.fromkeys((*entry.controlled_paths, *controlled_paths)))
                self._write_manifest("active")
            return
        backup_relative = f"backups/{len(self.entries):08d}"
        backup = self.root / backup_relative
        remove_tree(backup, ignore_errors=True)  # a leftover from an earlier session must not block this copy
        if _path_exists(target):
            if _is_link(target):
                backup.parent.mkdir(parents=True, exist_ok=True)
                _copy_link(target, backup)
                kind = "link"
            elif target.is_dir():
                shutil.copytree(target, backup, symlinks=True)
                kind = "directory"
            elif target.is_file():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                kind = "file"
            else:
                raise ModOperationExecutionError(f"unsupported target object: {target}")
        else:
            backup_relative = None
            kind = "missing"
        self.entries.append(
            JournalEntry(
                key,
                kind,
                backup_relative,
                preserve_external=preserve_external,
                controlled_paths=controlled_paths,
            )
        )
        self._by_path.add(key)
        self._write_manifest("active")

    def _write_manifest(self, state: str) -> None:
        self.state = state
        payload = json.dumps(
            {"state": state, "entries": [asdict(entry) for entry in self.entries]},
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".manifest.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.manifest)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)


def _discard_temporary(path: Path) -> None:
    """Remove a temp file; a just-killed backend may still hold it for a moment."""
    for attempt in range(10):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 9:
                # the real failure (a cancel or a backend error) is already propagating
                logger.warning("Could not remove the temporary file %s", path)
                return
            time.sleep(0.2)
        else:
            return


def _accepts_progress(backend: Callable[..., object]) -> bool:
    try:
        parameters = inspect.signature(backend).parameters
    except (TypeError, ValueError):
        return False
    return "progress" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


class ModOperationExecutor:
    """Apply a validated plan in its visible order and keep a recovery journal."""

    def __init__(
        self,
        journal_root: str | Path,
        *,
        patcher: PatchFunction | None = None,
        merger: MergeFunction | None = None,
    ) -> None:
        self.journal = ModOperationJournal(journal_root)
        self.patcher = patcher
        self.merger = merger
        self._hard_reset_roots: set[str] = set()
        self._tool_progress: Callable[[int], None] | None = None

    def execute(
        self,
        plan: ModOperationPlan,
        *,
        progress: ProgressFunction | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        step_progress: StepProgressFunction | None = None,
    ) -> ModOperationJournal:
        with hold_mods(operation.mod_id for operation in plan.operations):
            return self._execute(plan, progress, is_cancelled, step_progress)

    def _execute(
        self,
        plan: ModOperationPlan,
        progress: ProgressFunction | None,
        is_cancelled: Callable[[], bool] | None,
        step_progress: StepProgressFunction | None,
    ) -> ModOperationJournal:
        if plan.has_errors:
            raise ModOperationExecutionError("operation plan contains unresolved errors")
        try:
            # Info entries only document a mod; they change nothing, so they are no step.
            total = sum(1 for operation in plan.operations if operation.type != "info")
            completed = 0
            handled: set[int] = set()
            for operation in plan.operations:
                if id(operation) in handled or operation.type == "info":
                    continue
                if is_cancelled is not None and is_cancelled():
                    raise ModOperationCancelledError("operation cancelled")
                merge_operations = self.merge_operations(plan.operations, operation)
                weight = len(merge_operations) or 1
                self._tool_progress = self._step_reporter(
                    step_progress, completed, total, weight, operation
                )
                try:
                    if merge_operations:
                        self._execute_merge(merge_operations)
                        handled.update(id(item) for item in merge_operations)
                    else:
                        self._execute_operation(operation)
                        handled.add(id(operation))
                finally:
                    self._tool_progress = None
                completed += weight
                if progress is not None:
                    progress(completed, total, operation)
            self.journal.seal()
            return self.journal
        except Exception:
            self.journal.restore(force=True)
            raise

    def _call_backend(self, backend: Callable[..., bool | None], *arguments: object) -> bool | None:
        """Run a patch or merge backend, handing it the step progress when it can take it."""
        if self._tool_progress is not None and _accepts_progress(backend):
            return backend(*arguments, progress=self._tool_progress)
        return backend(*arguments)

    @staticmethod
    def _step_reporter(
        step_progress: StepProgressFunction | None,
        completed: int,
        total: int,
        weight: int,
        operation: PlannedModOperation,
    ) -> Callable[[int], None] | None:
        """Turn the percent a patch backend reports for one step into overall progress."""
        if step_progress is None:
            return None
        reported = 0

        def report(percent: int) -> None:
            nonlocal reported
            reported = max(reported, min(int(percent), 100))
            step_progress(
                (completed + weight * reported / 100) / max(total, 1),
                completed,
                total,
                operation,
                reported,
            )

        report(0)
        return report

    @staticmethod
    def merge_operations(
        operations: tuple[PlannedModOperation, ...], operation: PlannedModOperation
    ) -> tuple[PlannedModOperation, ...]:
        """Return matching data patches from one simultaneous profile step."""
        target = operation.target
        if (
            operation.merge_group is None
            or operation.type != "patch"
            or not _is_mergeable_target(target)
        ):
            return ()
        matches = tuple(
            candidate
            for candidate in operations
            if candidate.merge_group == operation.merge_group
            and candidate.type == "patch"
            and candidate.target == target
            and isinstance(candidate.source, Path)
            and not candidate.source_is_directory
        )
        return tuple(sorted(matches, key=lambda candidate: candidate.merge_priority)) if len(matches) > 1 else ()

    def _execute_merge(self, operations: tuple[PlannedModOperation, ...]) -> None:
        if self.merger is None:
            raise ModOperationExecutionError("no patch merge backend is configured")
        target = operations[0].target
        if (
            not isinstance(target, (Path, ArchiveVirtualPath))
            or not _is_mergeable_target(target)
        ):
            raise ModOperationExecutionError("patch merge requires a supported data file")
        with ExitStack() as stack:
            if isinstance(target, ArchiveVirtualPath):
                _assert_target_parents_safe(target.archive)
                self.journal.capture(target.archive)
                archive_root = Path(
                    stack.enter_context(
                        tempfile.TemporaryDirectory(prefix="g3m_archive_merge_")
                    )
                )
                if target.archive.exists():
                    materialize_archive(target.archive, archive_root)
                resolved_target = archive_root.joinpath(*target.member.split("/"))
            else:
                _assert_target_parents_safe(target)
                self.journal.capture(target)
                archive_root = None
                resolved_target = target
            if not resolved_target.is_file():
                raise ModOperationExecutionError("patch merge requires an existing data file")
            patches: list[Path] = []
            for operation in operations:
                source = self._source_path(operation, stack)
                self._verify_hash(resolved_target, operation.target_hash, "target")
                patches.append(source)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{resolved_target.name}.",
                suffix=resolved_target.suffix or ".tmp",
                dir=resolved_target.parent,
            )
            os.close(descriptor)
            output = Path(temporary_name)
            try:
                output.unlink()
                result = self._call_backend(self.merger, resolved_target, patches, output)
                if result is False or not output.is_file():
                    raise ModOperationExecutionError(
                        "patch merge backend did not produce an output file"
                    )
                replace_file(output, resolved_target)
            finally:
                _discard_temporary(output)
            if isinstance(target, ArchiveVirtualPath):
                if archive_root is None:
                    raise ModOperationExecutionError("archive merge workspace is unavailable")
                target.archive.parent.mkdir(parents=True, exist_ok=True)
                rebuild_archive(target.archive, archive_root)

    def _execute_operation(self, operation: PlannedModOperation) -> None:
        if operation.type == "info":
            return
        if operation.target is None:
            raise ModOperationExecutionError("operation target is missing")
        with ExitStack() as stack:
            source = self._source_path(operation, stack)
            if isinstance(operation.target, ArchiveVirtualPath):
                _assert_target_parents_safe(operation.target.archive)
                self.journal.capture(operation.target.archive)
                temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="g3m_archive_")))
                if operation.target.archive.exists():
                    materialize_archive(operation.target.archive, temporary)
                target = (
                    temporary.joinpath(*operation.target.member.split("/"))
                    if operation.target.member
                    else temporary
                )
                self._apply(operation, source, target)
                operation.target.archive.parent.mkdir(parents=True, exist_ok=True)
                rebuild_archive(operation.target.archive, temporary)
                return
            target = operation.target
            _assert_target_parents_safe(target)
            preserve_external = operation.type in {"hard-overwrite", "hard-extract"}
            if operation.type == "hard-overwrite":
                journal_target = target.parent if not operation.target_is_directory else target
                deployed_root = (
                    target / source.name if operation.target_is_directory else target
                )
            else:
                journal_target = target
                deployed_root = target
            controlled_paths = (
                _controlled_paths(source, deployed_root, journal_target)
                if preserve_external
                else ()
            )
            self.journal.capture(
                journal_target,
                preserve_external=preserve_external,
                controlled_paths=controlled_paths,
            )
            if operation.type.endswith("extract") and archive_format(target) == "lzma":
                self._write_lzma_extract(operation, source, target, stack)
                return
            self._apply(operation, source, target)

    def _source_path(self, operation: PlannedModOperation, stack: ExitStack) -> Path:
        source = operation.source
        if isinstance(source, ArchiveVirtualPath):
            temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="g3m_archive_")))
            materialize_archive(source.archive, temporary)
            resolved = temporary.joinpath(*source.member.split("/")) if source.member else temporary
            self._verify_hash(resolved, operation.source_hash, "source")
            return resolved
        self._verify_hash(source, operation.source_hash, "source")
        if operation.type.endswith("extract") and archive_format(source) is not None:
            temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="g3m_archive_")))
            materialize_archive(source, temporary)
            return temporary
        return source

    def _apply(self, operation: PlannedModOperation, source: Path, target: Path) -> None:
        if not source.exists():
            raise ModOperationExecutionError(f"source does not exist: {source}")
        if operation.type == "patch":
            self._apply_patch(operation, source, target)
            return
        if operation.type.endswith("extract"):
            self._apply_extract(operation, source, target)
            return
        self._apply_overwrite(operation, source, target)

    def _apply_patch(self, operation: PlannedModOperation, source: Path, target: Path) -> None:
        if source.is_dir() or target.is_dir() or not target.exists():
            raise ModOperationExecutionError("patch requires existing source and target files")
        self._verify_hash(target, operation.target_hash, "target")
        if self.patcher is None:
            raise ModOperationExecutionError("no patch backend is configured")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=target.suffix or ".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.unlink()
            try:
                result = self._call_backend(self.patcher, target, source, temporary)
            except ModOperationExecutionError as error:
                if "checksum mismatch" in str(error):  # xdelta3: the patch expects a different source file
                    raise ModPatchMismatchError(operation.mod_id, source.name) from error
                raise
            if result is False or not temporary.is_file():
                raise ModOperationExecutionError("patch backend did not produce an output file")
            replace_file(temporary, target)
        finally:
            _discard_temporary(temporary)

    def _apply_overwrite(self, operation: PlannedModOperation, source: Path, target: Path) -> None:
        soft = operation.type == "soft-overwrite"
        hard = operation.type == "hard-overwrite"
        self._verify_hash_if_present(target, operation.target_hash, "target")
        if source.is_dir():
            destination = target / source.name if operation.target_is_directory else target
            if hard:
                if operation.target_is_directory:
                    remove_path(destination)
                else:
                    self._clear_hard_root(operation, target.parent)
            _copy_tree(source, destination, soft=soft)
            return
        if not source.is_file():
            raise ModOperationExecutionError(f"source is not a regular file: {source}")
        if hard:
            self._clear_hard_root(
                operation, target if operation.target_is_directory else target.parent
            )
            destination = target / source.name if operation.target_is_directory else target
        else:
            destination = target / source.name if operation.target_is_directory else target
        _copy_file(source, destination, soft=soft)

    def _apply_extract(self, operation: PlannedModOperation, source: Path, target: Path) -> None:
        if not operation.target_is_directory:
            raise ModOperationExecutionError("extract requires a directory target")
        if not source.is_dir():
            raise ModOperationExecutionError("extract requires a directory or archive source")
        self._verify_hash_if_present(target, operation.target_hash, "target")
        if operation.type == "hard-extract":
            self._clear_hard_root(operation, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
        _extract_tree(source, target, soft=operation.type == "soft-extract")

    def _clear_hard_root(self, operation: PlannedModOperation, root: Path) -> None:
        target = operation.target
        if isinstance(target, ArchiveVirtualPath):
            member = target.member.rstrip("/")
            if not operation.type.endswith("extract") and not operation.target_is_directory:
                member = member.rpartition("/")[0]
            key = f"{target.archive.resolve(strict=False)}!/{member}"
        else:
            key = os.path.normcase(str(root.resolve(strict=False)))
        if key in self._hard_reset_roots:
            return
        _clear_directory(root)
        self._hard_reset_roots.add(key)

    def _write_lzma_extract(
        self,
        operation: PlannedModOperation,
        source: Path,
        target: Path,
        stack: ExitStack,
    ) -> None:
        if operation.type == "hard-extract" or source.is_dir():
            raise ModOperationExecutionError("LZMA extract requires one file and cannot be hard")
        self._verify_hash_if_present(target, operation.target_hash, "target")
        if operation.type == "soft-extract" and target.exists():
            return
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="g3m_lzma_")))
        _copy_file(source, temporary / source.name, soft=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        rebuild_archive(target, temporary)

    @staticmethod
    def _verify_hash(path: Path, expected: str | None, label: str) -> None:
        if expected is not None and sha256_path(path) != expected:
            raise ModOperationExecutionError(f"{label} hash does not match")

    def _verify_hash_if_present(self, path: Path, expected: str | None, label: str) -> None:
        if expected is None:
            return
        if not path.exists():
            raise ModOperationExecutionError(f"{label} required by hash does not exist")
        self._verify_hash(path, expected, label)


def _copy_file(source: Path, target: Path, *, soft: bool) -> None:
    _assert_target_parents_safe(target)
    if _path_exists(target):
        if soft:
            return
        remove_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path, *, soft: bool) -> None:
    if not _ensure_directory(target, soft=soft):
        return
    skipped: list[str] = []
    try:
        entries = iter_directory_tree(source)
        for child, relative, directory in entries:
            if any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in skipped):
                continue
            destination = target.joinpath(*relative.split("/"))
            if directory:
                if not _ensure_directory(destination, soft=soft):
                    skipped.append(relative)
            else:
                _copy_file(child, destination, soft=soft)
    except DirectoryTraversalError as error:
        raise ModOperationExecutionError(str(error)) from error


def _extract_tree(source: Path, target: Path, *, soft: bool) -> None:
    for child in sorted(source.iterdir(), key=lambda path: path.name.casefold()):
        destination = target / child.name
        if child.is_dir():
            _copy_tree(child, destination, soft=soft)
        else:
            _copy_file(child, destination, soft=soft)


def _clear_directory(path: Path) -> None:
    _assert_target_parents_safe(path)
    if _is_link(path) or (_path_exists(path) and not path.is_dir()):
        remove_path(path)
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        remove_path(child)


def remove_path(path: Path) -> None:
    if not _path_exists(path):
        return
    _assert_target_parents_safe(path)
    if _is_link(path):
        _unlink_link(path)
        return
    if path.is_dir():
        remove_tree(path)
        return
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def replace_file(source: Path, target: Path) -> None:
    """os.replace that copes with a read-only target and a file another program holds for a moment."""
    for attempt in range(4):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 3:
                raise
            with contextlib.suppress(OSError):
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            time.sleep(0.2 * (attempt + 1))


def remove_tree(path: Path, *, ignore_errors: bool = False) -> None:
    """Remove a tree whose folders may be read-only, as Windows game folders often are."""

    def clear_read_only(function: Callable[[str], object], name: str, error: BaseException) -> None:
        try:
            os.chmod(name, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            function(name)
        except FileNotFoundError:
            return
        except OSError:
            if not ignore_errors:
                raise error from None

    if _is_link(path):
        try:
            _unlink_link(path)
        except OSError:
            if not ignore_errors:
                raise
    elif path.exists():
        shutil.rmtree(path, onexc=clear_read_only)


def _restore_directory_preserving_external(
    backup: Path, target: Path, controlled_paths: tuple[str, ...]
) -> None:
    """Restore original files without deleting data created after deployment."""
    if not _path_exists(target):
        shutil.copytree(backup, target, symlinks=True)
    elif _is_link(target) or not target.is_dir():
        remove_path(target)
        shutil.copytree(backup, target, symlinks=True)
    else:
        for source in backup.iterdir():
            destination = target / source.name
            if source.is_dir() and not _is_link(source) and destination.is_dir() and not _is_link(destination):
                _restore_directory_preserving_external(source, destination, ())
            else:
                remove_path(destination)
                if _is_link(source):
                    _copy_link(source, destination)
                elif source.is_dir():
                    shutil.copytree(source, destination, symlinks=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    _remove_controlled_paths(target, tuple(
        path for path in controlled_paths if not _path_exists(backup / path)
    ))


def _controlled_paths(source: Path, destination: Path, root: Path) -> tuple[str, ...]:
    """List deployed files so forced recovery can keep later external files."""
    try:
        destination_relative = destination.relative_to(root)
    except ValueError as error:
        raise ModOperationExecutionError("controlled path is outside its journal target") from error
    if source.is_file():
        return (str(destination_relative),)
    if not source.is_dir():
        return ()
    try:
        return tuple(
            str(destination_relative / relative)
            for _path, relative, directory in iter_directory_tree(source)
            if not directory
        )
    except DirectoryTraversalError as error:
        raise ModOperationExecutionError(str(error)) from error


def _remove_controlled_paths(target: Path, controlled_paths: tuple[str, ...]) -> None:
    for relative_path in controlled_paths:
        remove_path(target / relative_path)


def _path_hash(path: Path) -> str | None:
    if not _path_exists(path):
        return None
    return sha256_path(path)


def _valid_backup_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = Path(value).parts
    return bool(parts) and parts[0] == "backups" and ".." not in parts and not Path(value).is_absolute()


def _ensure_directory(path: Path, *, soft: bool) -> bool:
    _assert_target_parents_safe(path)
    if _is_link(path) or (_path_exists(path) and not path.is_dir()):
        if soft:
            return False
        remove_path(path)
    path.mkdir(parents=True, exist_ok=True)
    return True


def _path_exists(path: Path) -> bool:
    return path.exists() or _is_link(path)


def _is_link(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_point)


def _unlink_link(path: Path) -> None:
    try:
        path.unlink()
    except IsADirectoryError:
        path.rmdir()


def _copy_link(source: Path, target: Path) -> None:
    try:
        destination = os.readlink(source)
    except OSError as error:
        raise ModOperationExecutionError(f"cannot preserve link: {source}") from error
    try:
        os.symlink(destination, target, target_is_directory=source.is_dir())
    except OSError as error:
        raise ModOperationExecutionError(f"cannot restore link: {target}") from error


_DARWIN_SYSTEM_LINKS = (
    frozenset(Path("/") / name for name in ("var", "tmp", "etc"))
    if sys.platform == "darwin"
    else frozenset()
)


def _assert_target_parents_safe(path: Path) -> None:
    current = path.parent
    while True:
        if _is_link(current) and current not in _DARWIN_SYSTEM_LINKS:
            raise ModOperationExecutionError(
                f"target is inside a link or reparse point: {current}"
            )
        if current.parent == current:
            return
        current = current.parent
