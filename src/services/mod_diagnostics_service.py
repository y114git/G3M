"""Read-only diagnostics for planned mod patching and file overrides."""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from config.config import (
    ARCHIVE_EXTENSIONS,
    MOD_TYPE_CSX,
    MOD_TYPE_DATAFILE,
    MOD_TYPE_G3MPATCH,
    MOD_TYPE_OVERRIDES_ONLY,
    MOD_TYPE_XDELTA,
    SKIP_FILES,
)
from utils.mod.utils import get_mod_id, get_mod_name
from utils.patching import mod_content_utils as mod_content
from utils.patching.file_override_utils import (
    _iter_configured_override_entries,
)
from utils.patching.mod_resolve_utils import (
    get_mod_configured_data_file,
    get_mod_configured_extra_files,
    get_mod_source_dir,
    get_target_dir,
    has_mod_configured_chapter_entry,
)


@dataclass(frozen=True)
class DiagnosticsSummary:
    selected_mods: int = 0
    new_files: int = 0
    modified_files: int = 0
    conflicts: int = 0
    data_files: int = 0
    deep_analyzable_data_files: int = 0
    issues: int = 0


@dataclass(frozen=True)
class DiagnosticIssue:
    severity: str
    title: str
    explanation: str
    affected_mods: tuple[str, ...] = ()
    target_path: str = ""
    resource: str = ""
    recommendation: str = ""


@dataclass(frozen=True)
class FileImpact:
    chapter_id: str
    mod_id: str
    mod_name: str
    source_path: str
    target_root: str
    target_relative_path: str
    target_path: str
    operation: str
    existing: bool
    analyzable: bool = True
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataImpact:
    chapter_id: str
    mod_id: str
    mod_name: str
    patch_path: str | None
    patch_type: str
    target_data_path: str | None
    deep_analysis_available: bool
    manifest: dict[str, Any] = field(default_factory=dict)
    resource_summary: dict[str, dict[str, int]] = field(default_factory=dict)
    resource_entries: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticsReport:
    summary: DiagnosticsSummary
    file_impacts: tuple[FileImpact, ...]
    data_impacts: tuple[DataImpact, ...]
    issues: tuple[DiagnosticIssue, ...]


class _NullLogger:
    def debug(self, *_args, **_kwargs) -> None:
        return

    def warning(self, *_args, **_kwargs) -> None:
        return

    def info(self, *_args, **_kwargs) -> None:
        return


class ModDiagnosticsService:
    """Builds diagnostics reports without mutating game or mod files."""

    def __init__(
        self,
        app_state,
        mod_service,
        *,
        target_dir_resolver: Callable[..., str | None] | None = None,
        logger=None,
    ) -> None:
        self.app_state = app_state
        self.mod_service = mod_service
        self._target_dir_resolver = target_dir_resolver or get_target_dir
        self._logger = logger or _NullLogger()

    def build_report(self, chapter_mods: dict[str, list[Any]]) -> DiagnosticsReport:
        file_impacts: list[FileImpact] = []
        data_impacts: list[DataImpact] = []
        issues: list[DiagnosticIssue] = []
        selected_mod_ids = set()

        for chapter_id, mods in (chapter_mods or {}).items():
            target_dir = self._resolve_target_dir(chapter_id)
            if not target_dir:
                issues.append(
                    DiagnosticIssue(
                        severity="error",
                        title="Target folder not found",
                        explanation=f"Game target folder for {chapter_id} is not configured or does not exist.",
                        recommendation="Check the game path in settings.",
                    )
                )
                continue
            target_data_path = mod_content.find_data_win(
                target_dir,
                game_id=getattr(getattr(self.app_state, "game_mode", None), "game_id", ""),
            )
            for mod_data in mods or []:
                mod_id = str(get_mod_id(mod_data) or "")
                selected_mod_ids.add(mod_id)
                data_impacts.extend(
                    self._collect_data_impacts(
                        chapter_id, mod_data, target_dir, target_data_path, issues
                    )
                )
                file_impacts.extend(
                    self._collect_file_impacts(chapter_id, mod_data, target_dir, issues)
                )

        file_impacts, conflict_issues = self._mark_file_conflicts(file_impacts)
        issues.extend(conflict_issues)
        summary = DiagnosticsSummary(
            selected_mods=len([mod_id for mod_id in selected_mod_ids if mod_id]),
            new_files=sum(1 for impact in file_impacts if impact.operation == "add")
            + sum(
                counts.get("new", 0)
                for impact in data_impacts
                for counts in impact.resource_summary.values()
            ),
            modified_files=sum(
                1 for impact in file_impacts if impact.operation in {"modify", "replace"}
            )
            + len(data_impacts),
            conflicts=len(conflict_issues),
            data_files=len(data_impacts),
            deep_analyzable_data_files=sum(
                1 for impact in data_impacts if impact.deep_analysis_available
            ),
            issues=len(issues),
        )
        return DiagnosticsReport(
            summary=summary,
            file_impacts=tuple(file_impacts),
            data_impacts=tuple(data_impacts),
            issues=tuple(issues),
        )

    def _resolve_target_dir(self, chapter_id: str) -> str | None:
        try:
            return self._target_dir_resolver(
                chapter_id,
                self.app_state,
                self._logger,
            )
        except TypeError:
            return self._target_dir_resolver(chapter_id)

    def _collect_data_impacts(
        self,
        chapter_id: str,
        mod_data,
        target_dir: str,
        target_data_path: str | None,
        issues: list[DiagnosticIssue],
    ) -> list[DataImpact]:
        patch_path = get_mod_configured_data_file(
            mod_data,
            chapter_id,
            self.mod_service,
            self.app_state,
            self._logger,
        )
        mod_source_dir = get_mod_source_dir(
            mod_data, chapter_id, self.mod_service, self.app_state, self._logger
        )
        patch_type = MOD_TYPE_OVERRIDES_ONLY
        if patch_path and os.path.exists(patch_path):
            patch_path, patch_type = mod_content.classify_patch_file(patch_path)
        elif mod_source_dir:
            patch_path, patch_type = self._classify_mod_source(mod_source_dir)
        elif patch_path:
            issues.append(
                DiagnosticIssue(
                    severity="error",
                    title="Configured DATA patch is missing",
                    explanation=f"{get_mod_name(mod_data)} references a missing DATA patch.",
                    affected_mods=(get_mod_name(mod_data),),
                    target_path=patch_path,
                    recommendation="Reinstall or edit the mod files.",
                )
            )
        if patch_type == MOD_TYPE_OVERRIDES_ONLY:
            return []
        manifest = self._read_g3mpatch_manifest(patch_path) if patch_path else {}
        return [
            DataImpact(
                chapter_id=chapter_id,
                mod_id=str(get_mod_id(mod_data) or ""),
                mod_name=get_mod_name(mod_data),
                patch_path=patch_path,
                patch_type=patch_type,
                target_data_path=target_data_path or os.path.join(target_dir, "data.win"),
                deep_analysis_available=patch_type == MOD_TYPE_G3MPATCH,
                manifest=manifest,
                resource_summary=self._resource_summary_from_manifest(manifest),
                resource_entries=self._resource_entries_from_manifest(manifest),
                notes=()
                if patch_type == MOD_TYPE_G3MPATCH
                else ("Deep resource analysis is only available for .g3mpatch files.",),
            )
        ]

    def _classify_mod_source(self, mod_source_dir: str) -> tuple[str | None, str]:
        g3m_patches = mod_content.find_g3m_patches(mod_source_dir)
        if g3m_patches:
            return g3m_patches[0], MOD_TYPE_G3MPATCH
        for filename in os.listdir(mod_source_dir):
            if filename.lower().endswith((".xdelta", ".vcdiff")):
                return os.path.join(mod_source_dir, filename), MOD_TYPE_XDELTA
        csx_scripts = mod_content.find_csx_scripts(mod_source_dir)
        if csx_scripts:
            return csx_scripts[0], MOD_TYPE_CSX
        ready_files = mod_content.find_ready_data_win_files(mod_source_dir)
        if ready_files:
            return ready_files[0], MOD_TYPE_DATAFILE
        return mod_content.classify_patch_file(None)

    def _collect_file_impacts(
        self,
        chapter_id: str,
        mod_data,
        target_dir: str,
        issues: list[DiagnosticIssue],
    ) -> list[FileImpact]:
        mod_source_dir = get_mod_source_dir(
            mod_data, chapter_id, self.mod_service, self.app_state, self._logger
        )
        if not mod_source_dir:
            return []
        has_config_entry = has_mod_configured_chapter_entry(
            mod_data,
            chapter_id,
            self.mod_service,
            self.app_state,
            self._logger,
        )
        configured_paths = (
            get_mod_configured_extra_files(
                mod_data,
                chapter_id,
                self.mod_service,
                self.app_state,
                self._logger,
            )
            if has_config_entry
            else None
        )
        if configured_paths is not None:
            mod_root_dir = self.mod_service.get_mod_folder_path(get_mod_id(mod_data))
            return self._collect_configured_file_impacts(
                chapter_id,
                mod_data,
                target_dir,
                mod_root_dir or mod_source_dir,
                configured_paths,
                issues,
            )
        return self._collect_directory_file_impacts(
            chapter_id, mod_data, target_dir, mod_source_dir
        )

    def _collect_configured_file_impacts(
        self,
        chapter_id: str,
        mod_data,
        target_dir: str,
        mod_root_dir: str,
        configured_paths: list[str],
        issues: list[DiagnosticIssue],
    ) -> list[FileImpact]:
        game_id = self._resolve_mod_game_id(mod_data)
        impacts: list[FileImpact] = []
        for entry in _iter_configured_override_entries(
            mod_root_dir, configured_paths, chapter_id, game_id
        ):
            source = entry["source"]
            target_root = self._safe_target_root(entry.get("target_root"), target_dir)
            target_relative = entry["target_relative"]
            if entry["is_directory"]:
                if not os.path.isdir(source):
                    issues.append(self._missing_issue(mod_data, source, is_directory=True))
                    continue
                for root, _dirs, files in os.walk(source):
                    rel_root = os.path.relpath(root, source)
                    for file_name in files:
                        if file_name.lower() in SKIP_FILES:
                            continue
                        rel_file = file_name if rel_root == "." else os.path.join(rel_root, file_name)
                        impacts.append(
                            self._make_file_impact(
                                chapter_id,
                                mod_data,
                                os.path.join(root, file_name),
                                target_root,
                                os.path.join(target_relative.rstrip("/"), rel_file),
                            )
                        )
                continue
            if not os.path.isfile(source):
                issues.append(self._missing_issue(mod_data, source, is_directory=False))
                continue
            impacts.append(
                self._make_file_impact(
                    chapter_id,
                    mod_data,
                    source,
                    target_root,
                    target_relative,
                )
            )
        return impacts

    @staticmethod
    def _safe_target_root(target_root: str | None, default_target_dir: str) -> str:
        if not target_root:
            return default_target_dir
        try:
            target_root_abs = os.path.abspath(target_root)
            default_abs = os.path.abspath(default_target_dir)
            if os.path.commonpath([target_root_abs, default_abs]) == default_abs:
                return target_root
            if os.path.commonpath([target_root_abs, default_abs]) == target_root_abs:
                return default_target_dir
        except ValueError:
            return default_target_dir
        return default_target_dir

    def _collect_directory_file_impacts(
        self, chapter_id: str, mod_data, target_dir: str, mod_source_dir: str
    ) -> list[FileImpact]:
        impacts: list[FileImpact] = []
        for root, _dirs, files in os.walk(mod_source_dir):
            for file_name in files:
                if file_name.lower() in SKIP_FILES:
                    continue
                source_path = os.path.join(root, file_name)
                lower = source_path.lower()
                if lower.endswith((".xdelta", ".vcdiff")) or lower.endswith(ARCHIVE_EXTENSIONS):
                    continue
                if mod_content.classify_patch_file(source_path)[1] != MOD_TYPE_OVERRIDES_ONLY:
                    continue
                rel_path = os.path.relpath(source_path, mod_source_dir)
                impacts.append(
                    self._make_file_impact(
                        chapter_id, mod_data, source_path, target_dir, rel_path
                    )
                )
        return impacts

    def _make_file_impact(
        self,
        chapter_id: str,
        mod_data,
        source_path: str,
        target_root: str,
        target_relative_path: str,
    ) -> FileImpact:
        target_relative_path = os.path.normpath(target_relative_path)
        target_path = os.path.normpath(os.path.join(target_root, target_relative_path))
        existing = os.path.exists(target_path)
        lower = source_path.lower()
        notes = ()
        analyzable = True
        if lower.endswith(ARCHIVE_EXTENSIONS):
            notes = ("Archive contents are not expanded during quick diagnostics.",)
            analyzable = False
        return FileImpact(
            chapter_id=chapter_id,
            mod_id=str(get_mod_id(mod_data) or ""),
            mod_name=get_mod_name(mod_data),
            source_path=source_path,
            target_root=target_root,
            target_relative_path=target_relative_path,
            target_path=target_path,
            operation="modify" if existing else "add",
            existing=existing,
            analyzable=analyzable,
            notes=notes,
        )

    def _mark_file_conflicts(
        self, impacts: list[FileImpact]
    ) -> tuple[list[FileImpact], list[DiagnosticIssue]]:
        by_target: dict[str, list[FileImpact]] = {}
        for impact in impacts:
            by_target.setdefault(os.path.normcase(os.path.abspath(impact.target_path)), []).append(impact)
        conflicts = {
            key: group
            for key, group in by_target.items()
            if len({impact.mod_id for impact in group}) > 1
        }
        if not conflicts:
            return impacts, []
        conflict_keys = set(conflicts)
        updated = [
            FileImpact(
                **{
                    **impact.__dict__,
                    "operation": "conflict"
                    if os.path.normcase(os.path.abspath(impact.target_path)) in conflict_keys
                    else impact.operation,
                }
            )
            for impact in impacts
        ]
        issues = [
            DiagnosticIssue(
                severity="error",
                title="File conflict",
                explanation="Multiple selected mods write to the same target path.",
                affected_mods=tuple(impact.mod_name for impact in group),
                target_path=group[0].target_path,
                recommendation="Disable one mod for this run or adjust priority if overwriting is intended.",
            )
            for group in conflicts.values()
        ]
        return updated, issues

    @staticmethod
    def _missing_issue(mod_data, path: str, *, is_directory: bool) -> DiagnosticIssue:
        kind = "directory" if is_directory else "file"
        return DiagnosticIssue(
            severity="error",
            title=f"Missing extra {kind}",
            explanation=f"{get_mod_name(mod_data)} references an extra {kind} that does not exist.",
            affected_mods=(get_mod_name(mod_data),),
            target_path=path,
            recommendation="Reinstall the mod or remove the missing entry from its config.",
        )

    @staticmethod
    def _read_g3mpatch_manifest(path: str | None) -> dict[str, Any]:
        if not path:
            return {}
        try:
            with zipfile.ZipFile(path) as archive:
                with archive.open("g3mpatch.json") as handle:
                    data = json.loads(handle.read().decode("utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _resource_summary_from_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, int]]:
        resources = manifest.get("resources") if isinstance(manifest, dict) else None
        if not isinstance(resources, dict):
            return {}
        summary: dict[str, dict[str, int]] = {}
        for resource_type, value in resources.items():
            if not isinstance(value, dict):
                continue
            changed = value.get("changed") or value.get("Changed") or []
            new = value.get("new") or value.get("New") or []
            deleted = value.get("deleted") or value.get("Deleted") or []
            summary[str(resource_type)] = {
                "changed": len(changed) if isinstance(changed, list) else int(bool(changed)),
                "new": len(new) if isinstance(new, list) else int(bool(new)),
                "deleted": len(deleted) if isinstance(deleted, list) else int(bool(deleted)),
            }
        return summary

    @staticmethod
    def _resource_entries_from_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        resources = manifest.get("resources") if isinstance(manifest, dict) else None
        if not isinstance(resources, dict):
            return ()
        entries: list[dict[str, Any]] = []
        for resource_type, value in resources.items():
            if not isinstance(value, dict):
                continue
            for operation in ("new", "changed", "deleted"):
                items = value.get(operation) or value.get(operation.capitalize()) or []
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        name = str(item.get("name") or "")
                        raw_files = item.get("files") or []
                        files = raw_files.values() if isinstance(raw_files, dict) else raw_files
                    else:
                        name = str(item)
                        files = []
                    entries.append(
                        {
                            "type": str(resource_type),
                            "operation": operation,
                            "name": name,
                            "files": tuple(str(file) for file in files if file),
                        }
                    )
        return tuple(entries)

    @staticmethod
    def _resolve_mod_game_id(mod_data) -> str | None:
        game = getattr(mod_data, "game", None)
        if isinstance(mod_data, dict):
            game = mod_data.get("game")
        return str(game).strip().lower() if game else None
