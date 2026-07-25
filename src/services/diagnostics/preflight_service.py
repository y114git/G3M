"""Exact launch-result diagnostics and portable report export."""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from models.execution_plan import PatchPlan
from utils.patching import mod_content_utils as mod_content


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

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


def _report_html(report: PreflightReport) -> str:
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    step_rows = "".join(
        "<tr>"
        f"<td>{esc(item.section_id)}</td><td>{esc(item.step_index)}</td>"
        f"<td>{esc(', '.join(item.mod_ids))}</td><td>{esc(item.success)}</td>"
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
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>G3M Diagnostics</title><style>
body{{font:14px system-ui,sans-serif;margin:24px;color:#202124;background:#fff}}
h1,h2{{margin:.4em 0}} .summary{{display:flex;gap:16px;flex-wrap:wrap}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}th,td{{border:1px solid #bbb;padding:7px;text-align:left;vertical-align:top}}
th{{background:#eee;position:sticky;top:0}}code{{overflow-wrap:anywhere}}
</style></head><body><h1>G3M Diagnostics</h1>
<div class="summary"><b>Success: {esc(report.success)}</b><b>Cancelled: {esc(report.cancelled)}</b><b>Duration: {report.duration_seconds:.2f}s</b></div>
<h2>Steps</h2><table><thead><tr><th>Section</th><th>Step</th><th>Mods</th><th>Success</th><th>Duration</th><th>Error</th></tr></thead><tbody>{step_rows}</tbody></table>
<h2>Resources</h2><table><thead><tr><th>Section</th><th>Step</th><th>Type</th><th>Operation</th><th>Name</th><th>Mods</th><th>Files</th><th>Details</th></tr></thead><tbody>{resource_rows}</tbody></table>
<h2>Files</h2><table><thead><tr><th>Path</th><th>Operation</th><th>Section</th><th>Step</th><th>Mods</th><th>Before</th><th>After</th><th>Before SHA-256</th><th>After SHA-256</th></tr></thead><tbody>{file_rows}</tbody></table>
<h2>Issues</h2><ul>{issues}</ul></body></html>"""


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


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_files(root: str) -> tuple[dict[str, tuple[int, str]], list[str]]:
    snapshot = {}
    errors = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in files:
            path = os.path.join(current, name)
            if os.path.islink(path):
                continue
            relative = os.path.relpath(path, root).replace("\\", "/")
            try:
                snapshot[relative] = (os.path.getsize(path), _file_digest(path))
            except OSError as error:
                errors.append(f"Cannot inspect {relative}: {error}")
    return snapshot, errors


def _validate_staging_tree(root: str) -> None:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = os.path.join(current, name)
            if os.path.islink(path) or is_junction(path):
                raise OSError(f"Preflight staging refuses link or junction: {path}")


def _probe_write_access(directory: str, data_path: str | None) -> str:
    probe_path = ""
    failure = ""
    try:
        descriptor, probe_path = tempfile.mkstemp(prefix=".g3m-preflight-", dir=directory)
        os.close(descriptor)
        if data_path:
            with open(data_path, "rb+"):
                pass
    except OSError as error:
        failure = f"Cannot write launch target {directory}: {error}"
    finally:
        if probe_path:
            try:
                os.unlink(probe_path)
            except OSError as error:
                if not failure:
                    failure = f"Cannot remove write probe {probe_path}: {error}"
    return failure


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
        operation = "added" if previous is None else "removed" if current is None else "modified"
        changes.append(
            PreflightFileChange(
                relative_path=relative_path,
                operation=operation,
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


def _default_data_file_locator(root: str, section_id: str, app_state) -> str | None:
    from utils.path_utils import find_chapter_resource_dir

    game_mode = getattr(app_state, "game_mode", None)
    target = find_chapter_resource_dir(
        root,
        section_id,
        getattr(game_mode, "macos_app_names", ("DELTARUNE.app",)),
    )
    if not target:
        target = root
    return mod_content.find_data_win(
        target,
        game_id=getattr(game_mode, "game_id", ""),
        preferred_name=getattr(game_mode, "data_file_name", "") or "",
    )


def _manifest_resources(
    manifest: dict[str, Any],
    section_id: str,
    step_index: int,
    mod_ids: tuple[str, ...],
) -> tuple[PreflightResourceChange, ...]:
    resources = manifest.get("resources") if isinstance(manifest, dict) else None
    if not isinstance(resources, dict):
        return ()
    changes = []
    for resource_type, operations in resources.items():
        if not isinstance(operations, dict):
            continue
        for operation in ("new", "changed", "deleted"):
            items = operations.get(operation) or operations.get(operation.capitalize()) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    name = str(item.get("name") or "")
                    raw_files = item.get("files") or []
                    file_values = raw_files.values() if isinstance(raw_files, dict) else raw_files
                    files = tuple(str(value) for value in file_values if value)
                else:
                    name = str(item)
                    files = ()
                changes.append(
                    PreflightResourceChange(
                        section_id=section_id,
                        step_index=step_index,
                        resource_type=str(resource_type),
                        operation=operation,
                        name=name,
                        mod_ids=mod_ids,
                        files=files,
                        details=(
                            json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True)
                            if isinstance(item, dict)
                            else ""
                        ),
                    )
                )
    return tuple(changes)


class DiagnosticsPreflightService:
    """Execute a launch plan in a disposable game copy and inspect actual changes."""

    def __init__(
        self,
        app_state,
        mod_service,
        *,
        patcher_factory=None,
        data_file_locator=None,
        resource_diff_builder=None,
    ) -> None:
        self.app_state = app_state
        self.mod_service = mod_service
        self._patcher_factory = patcher_factory
        self._data_file_locator = data_file_locator
        self._resource_diff_builder = resource_diff_builder
        self._cancelled = False
        self._patcher = None

    def cancel(self) -> None:
        self._cancelled = True
        if self._patcher is not None:
            self._patcher.cancel()

    def _new_patcher(self):
        if self._patcher_factory is not None:
            return self._patcher_factory(self.app_state, self.mod_service, None)
        from services.g3mtool_patching_service import G3MToolPatchingService

        return G3MToolPatchingService(self.app_state, self.mod_service, None)

    def _locate_data(self, root: str, section_id: str) -> str | None:
        if self._data_file_locator is not None:
            return self._data_file_locator(root, section_id)
        return _default_data_file_locator(root, section_id, self.app_state)

    def _resource_diff(
        self,
        before_path: str,
        after_path: str,
        section_id: str,
        step_index: int,
        mod_ids: tuple[str, ...],
        temp_dir: str,
    ) -> tuple[tuple[PreflightResourceChange, ...], str]:
        if self._resource_diff_builder is not None:
            return tuple(
                self._resource_diff_builder(
                    before_path, after_path, section_id, step_index, mod_ids
                )
            ), ""
        patch_path = os.path.join(temp_dir, f"resources_{section_id}_{step_index}.g3mpatch")
        returncode, _stdout, _stderr = self._patcher.g3mtool.patch_create(
            before_path, after_path, patch_path
        )
        if returncode != 0 or not os.path.isfile(patch_path):
            return (), f"G3MTool resource diff failed for {section_id} step {step_index}: {_stderr or _stdout}"
        import zipfile

        try:
            with (
                zipfile.ZipFile(patch_path) as archive,
                archive.open("g3mpatch.json") as handle,
            ):
                manifest = json.loads(handle.read().decode("utf-8"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            return (), f"Cannot read resource diff for {section_id} step {step_index}"
        return _manifest_resources(manifest, section_id, step_index, mod_ids), ""

    def run(
        self,
        plan: PatchPlan,
        resolver: Callable[[str], Any | None],
        game_path: str,
        progress: Callable[[int, str], None] | None = None,
    ) -> PreflightReport:
        started = time.monotonic()
        steps: list[PreflightStepResult] = []
        resources: list[PreflightResourceChange] = []
        files: list[PreflightFileChange] = []
        issues: list[str] = []
        success = True
        if self._cancelled:
            return PreflightReport(False, True, time.monotonic() - started)
        resolved = plan.resolve(resolver)
        total_steps = sum(len(section_steps) for section_steps in resolved.values())
        completed = 0

        def emit(value: int, message: str) -> None:
            if progress:
                progress(max(0, min(value, 100)), message)

        checked_targets: set[tuple[str, str]] = set()
        for section_id in resolved:
            data_path = self._locate_data(game_path, section_id)
            directory = os.path.dirname(data_path) if data_path else game_path
            target = (os.path.normcase(os.path.abspath(directory)), data_path or "")
            if target in checked_targets:
                continue
            checked_targets.add(target)
            permission_error = _probe_write_access(directory, data_path)
            if permission_error:
                return PreflightReport(
                    False,
                    False,
                    time.monotonic() - started,
                    issues=(permission_error,),
                )

        with tempfile.TemporaryDirectory(prefix="g3m_diagnostics_") as workspace:
            staged_game = os.path.join(workspace, "game")
            emit(2, "staging_game")
            _validate_staging_tree(game_path)
            shutil.copytree(game_path, staged_game, symlinks=False)
            patcher = self._new_patcher()
            self._patcher = patcher
            try:
                patch_messages: list[str] = []

                def reject_warning(event, details: str, _report_path: str | None) -> bool:
                    message = details or event.fallback_message or event.warning_id
                    patch_messages.append(message)
                    return False

                patcher.strict_warning_handler = reject_warning
                status_signal = getattr(patcher, "status_update", None)
                if status_signal is not None:
                    status_signal.connect(
                        lambda message, severity: patch_messages.append(
                            f"{severity}: {message}"
                        )
                    )
                patcher.set_override_game_path(staged_game)
                patcher.set_backup_root_override(os.path.join(workspace, "backups"))
                for section_id, section_steps in resolved.items():
                    for step_index, mods in enumerate(section_steps, 1):
                        if self._cancelled:
                            success = False
                            break
                        mod_ids = tuple(
                            str(getattr(mod, "id", "") or (mod.get("id") if isinstance(mod, dict) else ""))
                            for mod in mods
                        )
                        before_files, scan_errors = _snapshot_files(staged_game)
                        if scan_errors:
                            issues.extend(scan_errors)
                            success = False
                            break
                        before_data = self._locate_data(staged_game, section_id)
                        before_copy = ""
                        if before_data and os.path.isfile(before_data):
                            before_copy = os.path.join(
                                workspace, f"before_{section_id}_{step_index}{Path(before_data).suffix}"
                            )
                            shutil.copy2(before_data, before_copy)
                        step_started = time.monotonic()
                        emit(
                            8 + int(completed / max(total_steps, 1) * 72),
                            f"patching_step:{section_id}:{completed + 1}:{total_steps}",
                        )
                        step_plan = PatchPlan.from_runtime({section_id: [list(mods)]})
                        patch_messages.clear()
                        step_success = patcher.process_patch_plan(
                            step_plan, resolver, is_modpack=False
                        )
                        error = "" if step_success else "\n".join(patch_messages) or "Patch failed without diagnostic output"
                        steps.append(
                            PreflightStepResult(
                                section_id=section_id,
                                step_index=step_index,
                                mod_ids=mod_ids,
                                success=step_success,
                                duration_seconds=time.monotonic() - step_started,
                                error=error,
                            )
                        )
                        if not step_success:
                            issues.append(
                                f"{section_id} step {step_index}: {error}"
                            )
                            success = False
                            break
                        after_files, scan_errors = _snapshot_files(staged_game)
                        if scan_errors:
                            issues.extend(scan_errors)
                            success = False
                            break
                        files.extend(
                            _compare_snapshots(
                                before_files,
                                after_files,
                                section_id=section_id,
                                step_index=step_index,
                                mod_ids=mod_ids,
                            )
                        )
                        after_data = self._locate_data(staged_game, section_id)
                        if before_copy and after_data and os.path.isfile(after_data):
                            resource_changes, resource_error = self._resource_diff(
                                    before_copy,
                                    after_data,
                                    section_id,
                                    step_index,
                                    mod_ids,
                                    workspace,
                                )
                            resources.extend(resource_changes)
                            if resource_error:
                                issues.append(resource_error)
                                success = False
                                break
                        completed += 1
                    if self._cancelled or not success:
                        break
                emit(94, "building_report")
            finally:
                try:
                    patcher.cleanup(force=True)
                finally:
                    self._patcher = None
        emit(100, "completed" if success else "cancelled" if self._cancelled else "failed")
        return PreflightReport(
            success=success and not self._cancelled,
            cancelled=self._cancelled,
            duration_seconds=time.monotonic() - started,
            steps=tuple(steps),
            resources=tuple(resources),
            files=tuple(files),
            issues=tuple(issues),
        )
