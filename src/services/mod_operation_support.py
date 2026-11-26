"""Shared planning, confirmation, and patch-backend helpers for mod operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.mod_operation_executor import (
    ModOperationCancelledError,
    ModOperationExecutionError,
)
from services.warning_service import (
    create_warning_event,
    is_warning_enabled,
    normalize_warning_preferences,
)
from utils.mod.config import (
    MOD_CONFIG_VERSION,
    iter_direct_operation_paths,
)
from utils.mod.operation_plan import (
    ModOperationPlan,
    ModPathContext,
    PlanFinding,
    build_profile_operation_plan,
)
from utils.mod.utils import get_mod_id
from utils.problem_text import (
    describe_finding,
    friendly_merge_error,
    friendly_patch_error,
)
from utils.process_utils import (
    SCROLL_DIALOG_MAX_CHARS,
    SCROLL_DIALOG_MAX_LINES,
    bounded_output_preview,
    limit_dialog_text,
)

_DIRECT_ABSOLUTE_CODES = frozenset({"direct_absolute_source", "direct_absolute_target"})


def _bounded_warning_lines(lines: list[str]) -> str:
    return limit_dialog_text("\n".join(lines), SCROLL_DIALOG_MAX_LINES, SCROLL_DIALOG_MAX_CHARS)


def direct_operation_paths_preapproved(local_config: dict | None) -> bool:
    """Return whether the user explicitly disabled this specific warning."""
    preferences = normalize_warning_preferences(local_config)
    return preferences["warning_overrides"].get("direct_absolute_operation_paths") is False


@dataclass(frozen=True, slots=True)
class ProfileOperationInputs:
    configs: dict[str, dict[str, object]]
    contexts: dict[str, ModPathContext]
    findings: tuple[PlanFinding, ...]

    def build_plan(
        self,
        ordered_mod_ids: Sequence[str],
        *,
        merge_steps: Sequence[Sequence[str]] = (),
    ) -> ModOperationPlan:
        plan = build_profile_operation_plan(
            self.configs, self.contexts, ordered_mod_ids, merge_steps=merge_steps
        )
        return ModOperationPlan(plan.operations, (*self.findings, *plan.findings))


def collect_selected_mod_ids(chapter_mods: Mapping[str, list[Any]]) -> tuple[str, ...]:
    """Return every selected mod once, in the order used by an operation."""
    selected: list[str] = []
    seen: set[str] = set()
    for values in chapter_mods.values():
        steps = values if values and isinstance(values[0], list) else (values,)
        for step in steps:
            for mod in step:
                mod_id = str(get_mod_id(mod) or "")
                if mod_id and mod_id not in seen:
                    seen.add(mod_id)
                    selected.append(mod_id)
    return tuple(selected)


def collect_selected_merge_steps(chapter_mods: Mapping[str, list[Any]]) -> tuple[tuple[str, ...], ...]:
    """Keep simultaneous profile rows distinct from successive patch steps."""
    groups = []
    for values in chapter_mods.values():
        steps = values if values and isinstance(values[0], list) else (values,)
        for step in steps:
            mod_ids = collect_selected_mod_ids({"step": step})
            if len(mod_ids) > 1 and mod_ids not in groups:
                groups.append(mod_ids)
    return tuple(groups)


def collect_profile_operation_inputs(
    mod_service,
    mod_ids: Sequence[str],
    *,
    game_id: str,
    game_path: str | Path | None,
    game_data_path: str | Path | None,
    runtime: str,
    user_path: str | Path | None = None,
) -> ProfileOperationInputs:
    """Load current configs and contexts once for every profile-plan consumer."""
    configs: dict[str, dict[str, object]] = {}
    contexts: dict[str, ModPathContext] = {}
    findings: list[PlanFinding] = []
    for mod_id in dict.fromkeys(mod_ids):
        config = mod_service.get_mod_config(mod_id)
        if not isinstance(config, dict) or config.get("config_version") != MOD_CONFIG_VERSION:
            findings.append(
                PlanFinding(
                    "error",
                    "config_version",
                    0,
                    f"{mod_id}: must be migrated to the current config format before use",
                    mod_id,
                )
            )
            continue
        if game_id and config.get("game") != game_id:
            findings.append(
                PlanFinding("error", "game_mismatch", 0, f"{mod_id}: belongs to a different game", mod_id)
            )
            continue
        mod_path = mod_service.get_mod_folder_path(mod_id)
        if not mod_path:
            findings.append(
                PlanFinding("error", "mod_path_missing", 0, f"{mod_id}: mod folder is unavailable", mod_id)
            )
            continue
        configs[mod_id] = config
        contexts[mod_id] = ModPathContext.create(
            mod_path=mod_path,
            game_path=game_path,
            game_data_path=game_data_path,
            user_path=user_path or Path.home(),
            runtime=runtime,
        )
    return ProfileOperationInputs(configs, contexts, tuple(findings))


def format_direct_operation_paths(
    config: Mapping[str, object], *, mod_id: str = ""
) -> str:
    """Make literal operation paths clear enough for a confirmation dialog."""
    entries: list[str] = []
    for path in iter_direct_operation_paths(config):
        group = " / ".join(path.group_path) or "global"
        prefix = f"{mod_id}: " if mod_id else ""
        entries.append(
            f"{prefix}operation {path.operation_index} ({group}), {path.field}: {path.value}"
        )
    return _bounded_warning_lines(entries)


def format_direct_operation_plan_paths(plan: ModOperationPlan) -> str:
    return _bounded_warning_lines(
        [
            describe_finding(finding)
            for finding in plan.findings
            if finding.code in _DIRECT_ABSOLUTE_CODES
        ]
    )


def confirm_direct_operation_paths(
    feedback_service,
    local_config: dict | None,
    config: Mapping[str, object],
    *,
    mod_id: str = "",
) -> bool:
    """Ask for explicit consent before trusting literal filesystem paths."""
    details = format_direct_operation_paths(config, mod_id=mod_id)
    return confirm_direct_operation_path_details(feedback_service, local_config, details)


def confirm_direct_operation_path_details(
    feedback_service,
    local_config: dict | None,
    details: str,
) -> bool:
    """Ask once for already-collected literal filesystem paths."""
    if not details or direct_operation_paths_preapproved(local_config):
        return True
    ask = getattr(feedback_service, "ask_patching_warning", None)
    if not callable(ask):
        return False
    return bool(
        ask(create_warning_event("direct_absolute_operation_paths", details=details))
    )


def confirm_operation_plan(
    plan: ModOperationPlan,
    feedback_service,
    local_config: dict | None,
) -> ModOperationPlan | None:
    """Review a plan consistently, permitting only missing-source/target skips."""
    direct = [finding for finding in plan.findings if finding.code in _DIRECT_ABSOLUTE_CODES]
    if direct and not direct_operation_paths_preapproved(local_config):
        ask = getattr(feedback_service, "ask_patching_warning", None)
        if not callable(ask) or not ask(
            create_warning_event(
                "direct_absolute_operation_paths",
                details=format_direct_operation_plan_paths(plan),
            )
        ):
            return None

    skippable = {
        finding.operation_index
        for finding in plan.findings
        if finding.severity == "error" and finding.code in {"source_missing", "target_missing"}
    }
    if any(
        finding.severity == "error" and finding.code not in {"source_missing", "target_missing"}
        for finding in plan.findings
    ):
        return plan
    review = [
        finding
        for finding in plan.findings
        if finding.severity == "warning" and finding.code not in _DIRECT_ABSOLUTE_CODES
    ]
    review.extend(finding for finding in plan.findings if finding.operation_index in skippable)
    if review and is_warning_enabled("patching_warning", local_config):
        ask = getattr(feedback_service, "ask_patching_warning", None)
        if not callable(ask) or not ask(
            create_warning_event(
                "patching_warning",
                details=_bounded_warning_lines(
                    [
                        describe_finding(finding)
                        for finding in review
                    ]
                ),
            )
        ):
            return None
    if not skippable:
        return plan
    return ModOperationPlan(
        tuple(operation for operation in plan.operations if operation.index not in skippable),
        tuple(
            PlanFinding(
                "warning",
                f"{finding.code}_skipped",
                finding.operation_index,
                f"{finding.message} The operation was skipped by the user.",
            )
            if finding.operation_index in skippable and finding.severity == "error"
            else finding
            for finding in plan.findings
        ),
    )


def _progress_arguments(progress: Callable[[int], None] | None) -> dict[str, Any]:
    """Keyword for G3MTool calls: its (percent, label) reports, passed only when someone listens."""
    return {"progress_callback": lambda percent, _label: progress(percent)} if progress else {}


def create_g3mtool_patcher(
    app_state=None, *, is_cancelled: Callable[[], bool] | None = None
) -> Callable[..., bool]:
    """Create one lazy G3MTool patch adapter with consistent failures."""
    tool = None

    def apply_patch(
        target: Path, patch: Path, output: Path, progress: Callable[[int], None] | None = None
    ) -> bool:
        nonlocal tool
        if is_cancelled is not None and is_cancelled():
            return False
        if tool is None:
            from adapters.g3mtool_adapter import G3MToolManager

            tool = G3MToolManager(app_state) if app_state is not None else G3MToolManager()
            tool.is_cancelled = is_cancelled
        if not tool.is_available():
            raise ModOperationExecutionError(tool.get_unavailable_reason())
        apply = tool.xpatch_apply if patch.suffix.casefold() in {".xdelta", ".vcdiff"} else tool.apply_patch
        returncode, stdout, stderr = apply(
            str(target), str(patch), str(output), **_progress_arguments(progress)
        )
        if is_cancelled is not None and is_cancelled():
            raise ModOperationCancelledError("operation cancelled")
        if returncode:
            output = stderr or stdout or str(returncode)
            raise ModOperationExecutionError(
                f"patch backend failed: {bounded_output_preview(output)}", friendly_patch_error(output, patch, target)
            )
        return True

    return apply_patch


def create_g3mtool_merger(
    app_state=None, *, is_cancelled: Callable[[], bool] | None = None
) -> Callable[..., bool]:
    """Create the G3MTool merge backend used for one simultaneous profile step."""
    tool = None

    def merge_patches(
        target: Path,
        patches: list[Path],
        output: Path,
        progress: Callable[[int], None] | None = None,
    ) -> bool:
        nonlocal tool
        if is_cancelled is not None and is_cancelled():
            return False
        if tool is None:
            from adapters.g3mtool_adapter import G3MToolManager

            tool = G3MToolManager(app_state) if app_state is not None else G3MToolManager()
            tool.is_cancelled = is_cancelled
        if not tool.is_available():
            raise ModOperationExecutionError(tool.get_unavailable_reason())
        config = getattr(app_state, "local_config", {}) if app_state is not None else {}
        returncode, stdout, stderr = tool.merge_patches(
            str(target),
            [str(patch) for patch in patches],
            str(output),
            merge_code=bool(config.get("merge_code")) if isinstance(config, dict) else False,
            merge_properties=(
                bool(config.get("merge_properties")) if isinstance(config, dict) else False
            ),
            **_progress_arguments(progress),
        )
        if is_cancelled is not None and is_cancelled():
            raise ModOperationCancelledError("operation cancelled")
        if returncode:
            output = stderr or stdout or str(returncode)
            raise ModOperationExecutionError(
                f"patch merge failed: {bounded_output_preview(output)}", friendly_merge_error(output, patches, target)
            )
        return True

    return merge_patches
