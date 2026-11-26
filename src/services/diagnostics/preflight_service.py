"""Execute current mod operations in a disposable staging area for diagnostics."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from services.localization_service import localization_service, tr
from services.mod_operation_executor import (
    ModOperationCancelledError,
    ModOperationExecutionError,
    ModOperationExecutor,
)
from services.mod_operation_support import create_g3mtool_merger, create_g3mtool_patcher
from utils.mod.archive import ArchiveVirtualPath
from utils.mod.filesystem import DirectoryTraversalError, iter_directory_tree
from utils.mod.operation_plan import ModOperationPlan, PlannedModOperation
from utils.problem_text import describe_finding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreflightStepResult:
    section_id: str
    step_index: int
    mod_ids: tuple[str, ...]
    success: bool
    duration_seconds: float
    error: str = ""


@dataclass(frozen=True)
class PreflightResourceChange:
    section_id: str
    step_index: int
    resource_type: str
    operation: str
    name: str
    mod_ids: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    details: str = ""


@dataclass(frozen=True)
class PreflightFileChange:
    relative_path: str
    operation: str
    before_size: int | None
    after_size: int | None
    before_hash: str = ""
    after_hash: str = ""
    section_id: str = ""
    step_index: int = 0
    mod_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightReport:
    success: bool
    cancelled: bool
    duration_seconds: float
    steps: tuple[PreflightStepResult, ...] = ()
    resources: tuple[PreflightResourceChange, ...] = ()
    files: tuple[PreflightFileChange, ...] = ()
    issues: tuple[str, ...] = ()
    conflict_count: int = 0

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


def _report_html(report: PreflightReport) -> str:
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    def yes_no(value) -> str:
        return esc(tr("problems.report.yes" if value else "problems.report.no"))

    step_rows = "".join(
        "<tr>"
        f"<td>{esc(item.section_id)}</td><td>{esc(item.step_index)}</td>"
        f"<td>{esc(', '.join(item.mod_ids))}</td><td>{yes_no(item.success)}</td>"
        f"<td>{esc(item.duration_seconds)}</td><td>{esc(item.error)}</td></tr>"
        for item in report.steps
    )
    resource_rows = "".join(
        "<tr>"
        f"<td>{esc(item.section_id)}</td><td>{item.step_index}</td>"
        f"<td>{esc(item.resource_type)}</td><td>{esc(item.operation)}</td>"
        f"<td>{esc(item.name)}</td><td>{esc(', '.join(item.mod_ids))}</td>"
        f"<td>{esc(', '.join(item.files))}</td><td><pre>{esc(item.details)}</pre></td>"
        "</tr>"
        for item in report.resources
    )
    file_rows = "".join(
        "<tr>"
        f"<td>{esc(item.relative_path)}</td><td>{esc(item.operation)}</td>"
        f"<td>{esc(item.section_id)}</td><td>{esc(item.step_index)}</td>"
        f"<td>{esc(', '.join(item.mod_ids))}</td>"
        f"<td>{esc(item.before_size)}</td><td>{esc(item.after_size)}</td>"
        f"<td>{esc(item.before_hash)}</td><td>{esc(item.after_hash)}</td>"
        "</tr>"
        for item in report.files
    )
    issues = "".join(f"<li>{esc(issue)}</li>" for issue in report.issues)

    def head(*keys: str) -> str:
        return "<tr>" + "".join(f"<th>{esc(tr('problems.report.' + key))}</th>" for key in keys) + "</tr>"

    title = esc(tr("problems.report.title"))
    return f"""<!doctype html>
<html lang="{esc(localization_service.current_language)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>
body{{font:14px system-ui,sans-serif;margin:24px;color:#202124;background:#fff}}
h1,h2{{margin:.4em 0}} .summary{{display:flex;gap:16px;flex-wrap:wrap}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}th,td{{border:1px solid #bbb;padding:7px;text-align:left;vertical-align:top}}
th{{background:#eee;position:sticky;top:0}}code{{overflow-wrap:anywhere}}
</style></head><body><h1>{title}</h1>
<div class="summary"><b>{esc(tr("problems.report.success"))}: {yes_no(report.success)}</b><b>{esc(tr("problems.report.cancelled"))}: {yes_no(report.cancelled)}</b><b>{esc(tr("problems.report.conflicts"))}: {report.conflict_count}</b><b>{esc(tr("problems.report.duration"))}: {report.duration_seconds:.2f} s</b></div>
<h2>{esc(tr("problems.report.steps"))}</h2><table><thead>{head("col_section", "col_step", "col_mods", "col_success", "col_duration", "col_error")}</thead><tbody>{step_rows}</tbody></table>
<h2>{esc(tr("problems.report.resources"))}</h2><table><thead>{head("col_section", "col_step", "col_type", "col_operation", "col_name", "col_mods", "col_files", "col_details")}</thead><tbody>{resource_rows}</tbody></table>
<h2>{esc(tr("problems.report.files"))}</h2><table><thead>{head("col_path", "col_operation", "col_section", "col_step", "col_mods", "col_before", "col_after", "col_before_hash", "col_after_hash")}</thead><tbody>{file_rows}</tbody></table>
<h2>{esc(tr("problems.report.issues"))}</h2><ul>{issues}</ul></body></html>"""


def export_preflight_report(report: PreflightReport, html_path: str) -> tuple[str, str]:
    """Write matching human-readable HTML and structured JSON reports."""
    html_path = os.path.abspath(html_path)
    root, _extension = os.path.splitext(html_path)
    json_path = f"{root}.json"
    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    with open(html_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_report_html(report))
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return html_path, json_path


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_files(root: Path, label: str) -> tuple[dict[str, tuple[int, str]], list[str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    errors: list[str] = []
    if not root.exists():
        return snapshot, errors
    for current, directories, files in os.walk(root):
        directories[:] = [
            name for name in directories if not (Path(current) / name).is_symlink()
        ]
        for name in files:
            path = Path(current) / name
            if path.is_symlink():
                continue
            relative = f"{label}/{path.relative_to(root).as_posix()}"
            try:
                snapshot[relative] = (path.stat().st_size, _file_digest(path))
            except OSError as error:
                errors.append(f"Cannot inspect {relative}: {error}")
    return snapshot, errors


def _compare_snapshots(
    before: dict[str, tuple[int, str]],
    after: dict[str, tuple[int, str]],
    *,
    section_id: str,
    step_index: int,
    mod_ids: tuple[str, ...],
) -> tuple[PreflightFileChange, ...]:
    changes = []
    for relative_path in sorted(before.keys() | after.keys()):
        previous = before.get(relative_path)
        current = after.get(relative_path)
        if previous == current:
            continue
        changes.append(
            PreflightFileChange(
                relative_path=relative_path,
                operation="added" if previous is None else "removed" if current is None else "modified",
                before_size=previous[0] if previous else None,
                after_size=current[0] if current else None,
                before_hash=previous[1] if previous else "",
                after_hash=current[1] if current else "",
                section_id=section_id,
                step_index=step_index,
                mod_ids=mod_ids,
            )
        )
    return tuple(changes)


class DiagnosticsPreflightService:
    """Run resolved operations against copies of the paths they are allowed to change."""

    def __init__(self, app_state) -> None:
        self.app_state = app_state
        self._cancelled = False
        self._patcher = create_g3mtool_patcher(
            app_state, is_cancelled=lambda: self._cancelled
        )
        self._merger = create_g3mtool_merger(
            app_state, is_cancelled=lambda: self._cancelled
        )

    def cancel(self) -> None:
        self._cancelled = True

    @staticmethod
    def _map_path(path: Path, roots: tuple[tuple[Path, Path], ...], *, target: bool) -> Path:
        resolved_path = path.resolve(strict=False)
        for original, staged in roots:
            try:
                return staged / resolved_path.relative_to(original.resolve(strict=False))
            except ValueError:
                continue
        if target:
            parts = resolved_path.parts
            root_id = hashlib.sha256(str(resolved_path.anchor).encode("utf-8")).hexdigest()[:16]
            return roots[0][1].parent / "custom" / root_id / Path(*parts[1:])
        return path

    @classmethod
    def _map_operation(
        cls,
        operation: PlannedModOperation,
        roots: tuple[tuple[Path, Path], ...],
    ) -> PlannedModOperation:
        def map_value(value, *, target: bool):
            if isinstance(value, ArchiveVirtualPath):
                return ArchiveVirtualPath(
                    archive=cls._map_path(value.archive, roots, target=target),
                    member=value.member,
                    directory=value.directory,
                    format=value.format,
                )
            return cls._map_path(value, roots, target=target)

        source = map_value(operation.source, target=False)
        target = map_value(operation.target, target=True) if operation.target else None
        return replace(operation, source=source, target=target)

    @staticmethod
    def _copy_to_stage(source: Path, destination: Path) -> None:
        if not source.exists():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            try:
                for path, relative, directory in iter_directory_tree(source):
                    target = destination.joinpath(*relative.split("/"))
                    if directory:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            shutil.copy2(path, target)
            except DirectoryTraversalError as error:
                raise ModOperationExecutionError(str(error)) from error
        elif not destination.exists():
            shutil.copy2(source, destination)

    @classmethod
    def _stage_inputs(
        cls,
        plan: ModOperationPlan,
        roots: tuple[tuple[Path, Path], ...],
    ) -> ModOperationPlan:
        for operation in plan.operations:
            target = operation.target
            if isinstance(target, ArchiveVirtualPath):
                target = target.archive
            if target is not None and not any(target.is_relative_to(original) for original, _staged in roots):
                roots = (*roots, (target, cls._map_path(target, roots, target=True)))
        for operation in plan.operations:
            if (
                operation.type == "hard-overwrite"
                and not operation.target_is_directory
                and isinstance(operation.target, Path)
            ):
                staged_target = cls._map_path(operation.target, roots, target=True)
                cls._copy_to_stage(operation.target.parent, staged_target.parent)
        staged_operations = []
        for operation in plan.operations:
            staged = cls._map_operation(operation, roots)
            pairs = ((operation.source, staged.source), (operation.target, staged.target))
            for original, copied in pairs:
                if original is None or copied is None:
                    continue
                original_path = original.archive if isinstance(original, ArchiveVirtualPath) else original
                copied_path = copied.archive if isinstance(copied, ArchiveVirtualPath) else copied
                if original_path != copied_path:
                    cls._copy_to_stage(original_path, copied_path)
            staged_operations.append(staged)
        return ModOperationPlan(tuple(staged_operations), plan.findings)

    @staticmethod
    def _snapshot_roots(roots: tuple[tuple[Path, Path], ...]) -> tuple[dict[str, tuple[int, str]], list[str]]:
        snapshot: dict[str, tuple[int, str]] = {}
        errors: list[str] = []
        for _original, staged in roots:
            files, file_errors = _snapshot_files(staged, staged.name)
            snapshot.update(files)
            errors.extend(file_errors)
        return snapshot, errors

    def run(
        self,
        plan: ModOperationPlan,
        game_path: str,
        game_data_path: str | None = None,
        user_path: str | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> PreflightReport:
        started = time.monotonic()
        issues = [describe_finding(finding) for finding in plan.findings]
        if self._cancelled:
            return PreflightReport(False, True, time.monotonic() - started)
        if plan.has_errors:
            return PreflightReport(False, False, time.monotonic() - started, issues=tuple(issues))
        game_root = Path(game_path)
        if not game_root.is_dir():
            return PreflightReport(False, False, time.monotonic() - started, issues=(f"game path does not exist: {game_root}",))

        def emit(value: int, message: str) -> None:
            if progress:
                progress(max(0, min(value, 100)), message)

        with tempfile.TemporaryDirectory(prefix="g3m_diagnostics_") as temporary_name:
            temporary = Path(temporary_name).resolve(strict=False)
            game_root = game_root.resolve(strict=False)
            roots = [(game_root, temporary / "game")]
            if game_data_path:
                roots.append((Path(game_data_path).resolve(strict=False), temporary / "game_data"))
            if user_path:
                roots.append((Path(user_path).resolve(strict=False), temporary / "user"))
            roots.sort(key=lambda item: len(item[0].parts), reverse=True)
            root_pairs = (*roots, (temporary / "__custom__", temporary / "custom"))
            if any(
                operation.target is not None
                and not any(
                    (operation.target.archive if isinstance(operation.target, ArchiveVirtualPath) else operation.target).resolve(strict=False).is_relative_to(root.resolve(strict=False))
                    for root, _staged in roots
                )
                for operation in plan.operations
            ):
                issues.append(
                    "Custom targets are staged in isolation; launch will use their exact configured paths."
                )
            try:
                staged_plan = self._stage_inputs(plan, root_pairs)
            except ModOperationExecutionError as error:
                return PreflightReport(False, False, time.monotonic() - started, issues=(*issues, str(error)))

            executor = ModOperationExecutor(
                temporary / "journal", patcher=self._patcher, merger=self._merger
            )
            steps: list[PreflightStepResult] = []
            files: list[PreflightFileChange] = []
            total = sum(1 for operation in staged_plan.operations if operation.type != "info")
            completed = 0
            handled: set[int] = set()
            for operation in staged_plan.operations:
                if id(operation) in handled or operation.type == "info":
                    continue
                if self._cancelled:
                    return PreflightReport(False, True, time.monotonic() - started, tuple(steps), files=tuple(files), issues=tuple(issues))
                operation_group = executor.merge_operations(staged_plan.operations, operation)
                operation_group = operation_group or (operation,)
                before, errors = self._snapshot_roots(root_pairs)
                if errors:
                    return PreflightReport(False, False, time.monotonic() - started, tuple(steps), files=tuple(files), issues=(*issues, *errors))
                step_started = time.monotonic()
                section = "/".join(operation.group_path) or "global"
                mod_ids = tuple(
                    item.mod_id for item in operation_group if item.mod_id
                )
                try:
                    executor.execute(
                        ModOperationPlan(operation_group, ()),
                        is_cancelled=lambda: self._cancelled,
                        step_progress=lambda _overall, _done, _count, _operation, percent, group=operation_group, base=completed, name=section: emit(
                            8 + int((base + len(group) * percent / 100) * 86 / max(total, 1)),
                            f"patching_step:{name}:{base + len(group)}:{total}",
                        ),
                    )
                except ModOperationExecutionError as error:
                    if self._cancelled or isinstance(error, ModOperationCancelledError):
                        return PreflightReport(False, True, time.monotonic() - started, tuple(steps), files=tuple(files), issues=tuple(issues))
                    logger.error("Preflight step failed: %s", error)
                    shown = error.user_message or str(error)
                    steps.append(PreflightStepResult(section, operation.index, mod_ids, False, time.monotonic() - step_started, shown))
                    return PreflightReport(False, False, time.monotonic() - started, tuple(steps), files=tuple(files), issues=(*issues, shown))
                after, errors = self._snapshot_roots(root_pairs)
                files.extend(_compare_snapshots(before, after, section_id=section, step_index=operation.index, mod_ids=mod_ids))
                if errors:
                    issues.extend(errors)
                    return PreflightReport(False, False, time.monotonic() - started, tuple(steps), files=tuple(files), issues=tuple(issues))
                steps.append(PreflightStepResult(section, operation.index, mod_ids, True, time.monotonic() - step_started))
                handled.update(id(item) for item in operation_group)
                completed += len(operation_group)
                emit(
                    8 + int(completed * 86 / max(total, 1)),
                    f"patching_step:{section}:{completed}:{total}",
                )
            emit(100, "complete")
            return PreflightReport(True, False, time.monotonic() - started, tuple(steps), files=tuple(files), issues=tuple(issues))
