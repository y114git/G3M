"""Read-only diagnostics for the validated current mod operations."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from services.localization_service import tr
from utils.mod.archive import ArchiveVirtualPath
from utils.mod.config import ModConfigValidationError
from utils.mod.operation_plan import (
    ModPathContext,
    PlanFinding,
    build_mod_operation_plan,
)
from utils.mod.relations import (
    RelationFinding,
    analyze_mod_relations,
    recommend_mod_arrangement,
)
from utils.problem_text import describe_finding


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
    code: str = ""
    field_path: str = ""


@dataclass(frozen=True)
class FileImpact:
    section_id: str
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
    section_id: str
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
    recommended_steps: tuple[tuple[str, ...], ...] = ()


class ModDiagnosticsService:
    """Build diagnostics from the same plan used to run selected mods."""

    def __init__(self, app_state, mod_service) -> None:
        self.app_state = app_state
        self.mod_service = mod_service

    def build_operation_report(
        self,
        configs: Mapping[str, Mapping[str, object]],
        steps: Sequence[Sequence[str]],
        path_contexts: Mapping[str, ModPathContext],
    ) -> DiagnosticsReport:
        file_impacts: list[FileImpact] = []
        data_impacts: list[DataImpact] = []
        issues: list[DiagnosticIssue] = []
        selected_ids = tuple(dict.fromkeys(mod_id for step in steps for mod_id in step))

        for mod_id in selected_ids:
            config = configs.get(mod_id)
            context = path_contexts.get(mod_id)
            if config is None or context is None:
                issues.append(
                    DiagnosticIssue(
                        "error",
                        tr("problems.diag.mod_unavailable"),
                        tr("problems.diag.mod_unavailable_text", mod=mod_id),
                        (mod_id,),
                        recommendation=tr("problems.diag.mod_unavailable_fix"),
                    )
                )
                continue
            name = str(config.get("name") or mod_id)
            try:
                plan = build_mod_operation_plan(config, context)
            except ModConfigValidationError as error:
                issues.extend(
                    DiagnosticIssue(
                        issue.severity,
                        f"{issue.path}: {issue.code.replace('_', ' ')}",
                        f"{name}: {issue.message}",
                        (mod_id,),
                        recommendation=issue.correction,
                        code=issue.code,
                        field_path=issue.path,
                    )
                    for issue in error.issues
                )
                continue
            issues.extend(self._plan_issue(name, mod_id, finding) for finding in plan.findings)
            for operation in plan.operations:
                if operation.type == "info":
                    continue
                section = "/".join(operation.group_path) or "global"
                source = str(operation.source)
                target = operation.target
                target_text = str(target) if target is not None else ""
                if operation.type == "patch":
                    data_impacts.append(
                        DataImpact(
                            section,
                            mod_id,
                            name,
                            source,
                            "patch",
                            target_text or None,
                            False,
                            notes=("The patch backend validates this operation during preflight.",),
                        )
                    )
                    continue
                target_path = target.archive if isinstance(target, ArchiveVirtualPath) else target
                existing = bool(target_path and target_path.exists())
                target_root = str(target_path.parent) if target_path else ""
                target_relative = target_path.name if target_path else ""
                file_impacts.append(
                    FileImpact(
                        section,
                        mod_id,
                        name,
                        source,
                        target_root,
                        target_relative,
                        target_text,
                        "modify" if existing else "add",
                        existing,
                        not operation.source_is_directory,
                        (operation.type,),
                    )
                )

        relation_findings = analyze_mod_relations(configs, steps)
        issues.extend(self._relation_issue(finding) for finding in relation_findings)
        arrangement = recommend_mod_arrangement(configs, steps)
        if arrangement.feasible and arrangement.steps != tuple(tuple(step) for step in steps if step):
            issues.append(
                DiagnosticIssue(
                    "warning",
                    tr("problems.diag.arrangement"),
                    tr("problems.diag.arrangement_text"),
                    tuple(mod_id for step in arrangement.steps for mod_id in step),
                    recommendation=tr("problems.diag.arrangement_fix"),
                    code="dependency_arrangement_recommended",
                    field_path="dependencies",
                )
            )
        file_impacts, file_conflicts = self._mark_file_conflicts(file_impacts)
        issues.extend(file_conflicts)
        data_conflicts = self._data_conflicts(data_impacts)
        issues.extend(data_conflicts)
        summary = DiagnosticsSummary(
            selected_mods=len(selected_ids),
            new_files=sum(impact.operation == "add" for impact in file_impacts),
            modified_files=sum(impact.operation == "modify" for impact in file_impacts) + len(data_impacts),
            conflicts=len(file_conflicts) + len(data_conflicts) + sum(finding.code == "conflict_active" for finding in relation_findings),
            data_files=len(data_impacts),
            issues=len(issues),
        )
        return DiagnosticsReport(summary, tuple(file_impacts), tuple(data_impacts), tuple(issues), arrangement.steps if arrangement.feasible else ())

    @staticmethod
    def unavailable_report(message: str) -> DiagnosticsReport:
        issue = DiagnosticIssue("error", tr("problems.diag.config_unavailable"), message, recommendation=tr("problems.diag.config_unavailable_fix"))
        return DiagnosticsReport(DiagnosticsSummary(issues=1), (), (), (issue,))

    @staticmethod
    def _plan_issue(name: str, mod_id: str, finding: PlanFinding) -> DiagnosticIssue:
        return DiagnosticIssue(
            finding.severity,
            tr("problems.plan.title"),
            f"{name}: {describe_finding(finding)}",
            (mod_id,),
            recommendation=tr("problems.plan.fix"),
            code=finding.code,
        )

    @staticmethod
    def _relation_issue(finding: RelationFinding) -> DiagnosticIssue:
        return DiagnosticIssue(
            finding.severity,
            finding.code.replace("_", " ").capitalize(),
            f"{finding.mod_id} and {finding.related_id}: {finding.message}",
            (finding.mod_id, finding.related_id),
            recommendation="Review the profile's enabled mods and priority steps.",
            code=finding.code,
            field_path="dependencies" if finding.code.startswith("dependency") else "conflicts",
        )

    @staticmethod
    def _mark_file_conflicts(
        impacts: list[FileImpact],
    ) -> tuple[list[FileImpact], list[DiagnosticIssue]]:
        by_target: dict[str, list[FileImpact]] = {}
        for impact in impacts:
            by_target.setdefault(os.path.normcase(os.path.abspath(impact.target_path)), []).append(impact)
        conflicts = [group for group in by_target.values() if len({impact.mod_id for impact in group}) > 1]
        if not conflicts:
            return impacts, []
        paths = {os.path.normcase(os.path.abspath(group[0].target_path)) for group in conflicts}
        marked = [
            FileImpact(
                **{
                    **impact.__dict__,
                    "operation": "conflict" if os.path.normcase(os.path.abspath(impact.target_path)) in paths else impact.operation,
                }
            )
            for impact in impacts
        ]
        issues = [
            DiagnosticIssue(
                "error",
                tr("problems.diag.file_conflict"),
                tr("problems.diag.file_conflict_text"),
                tuple(impact.mod_name for impact in group),
                target_path=group[0].target_path,
                recommendation=tr("problems.diag.file_conflict_fix"),
                code="file_conflict",
            )
            for group in conflicts
        ]
        return marked, issues

    @staticmethod
    def _data_conflicts(impacts: list[DataImpact]) -> list[DiagnosticIssue]:
        by_target: dict[str, list[DataImpact]] = {}
        for impact in impacts:
            by_target.setdefault(os.path.normcase(os.path.abspath(impact.target_data_path or impact.section_id)), []).append(impact)
        return [
            DiagnosticIssue(
                "warning",
                tr("problems.diag.data_overlap"),
                tr("problems.diag.data_overlap_text"),
                tuple(impact.mod_name for impact in group),
                target_path=group[0].target_data_path or "",
                recommendation=tr("problems.diag.data_overlap_fix"),
                code="data_overlap",
            )
            for group in by_target.values()
            if len({impact.mod_id for impact in group}) > 1
        ]
