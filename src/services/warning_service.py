"""Typed warning registry and preference helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class WarningSeverity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


@dataclass(frozen=True)
class WarningDefinition:
    warning_id: str
    severity: WarningSeverity
    label_key: str
    title_key: str
    body_key: str
    tooltip_key: str
    enabled_by_default: bool = True


@dataclass(frozen=True)
class WarningEvent:
    warning_id: str
    context: dict[str, Any] = field(default_factory=dict)
    details: str = ""
    report_path: str | None = None
    fallback_message: str = ""


WARNING_DEFINITIONS: dict[str, WarningDefinition] = {
    "xdelta_apply_failed": WarningDefinition(
        "xdelta_apply_failed",
        WarningSeverity.CRITICAL,
        "warnings.items.xdelta_apply_failed",
        "warnings.messages.xdelta_apply_failed.title",
        "warnings.messages.xdelta_apply_failed.body",
        "warnings.tooltips.xdelta_apply_failed",
    ),
    "g3mpatch_apply_failed": WarningDefinition(
        "g3mpatch_apply_failed",
        WarningSeverity.CRITICAL,
        "warnings.items.g3mpatch_apply_failed",
        "warnings.messages.g3mpatch_apply_failed.title",
        "warnings.messages.g3mpatch_apply_failed.body",
        "warnings.tooltips.g3mpatch_apply_failed",
    ),
    "merge_failed": WarningDefinition(
        "merge_failed",
        WarningSeverity.CRITICAL,
        "warnings.items.merge_failed",
        "warnings.messages.merge_failed.title",
        "warnings.messages.merge_failed.body",
        "warnings.tooltips.merge_failed",
    ),
    "steam_launch_with_mods": WarningDefinition(
        "steam_launch_with_mods",
        WarningSeverity.MAJOR,
        "warnings.items.steam_launch_with_mods",
        "warnings.messages.steam_launch_with_mods.title",
        "warnings.messages.steam_launch_with_mods.body",
        "warnings.tooltips.steam_launch_with_mods",
    ),
    "missing_dependencies": WarningDefinition(
        "missing_dependencies",
        WarningSeverity.MAJOR,
        "warnings.items.missing_dependencies",
        "dialogs.patching_warning.title",
        "dialogs.patching_warning.dependency_manual_required",
        "warnings.tooltips.missing_dependencies",
    ),
    "patching_warning": WarningDefinition(
        "patching_warning",
        WarningSeverity.MAJOR,
        "warnings.items.patching_warning",
        "warnings.messages.patching_warning.title",
        "warnings.messages.patching_warning.body",
        "warnings.tooltips.patching_warning",
    ),
    "direct_absolute_operation_paths": WarningDefinition(
        "direct_absolute_operation_paths",
        WarningSeverity.MAJOR,
        "warnings.items.direct_absolute_operation_paths",
        "warnings.messages.direct_absolute_operation_paths.title",
        "warnings.messages.direct_absolute_operation_paths.body",
        "warnings.tooltips.direct_absolute_operation_paths",
    ),
    "inactive_dependencies": WarningDefinition(
        "inactive_dependencies",
        WarningSeverity.MINOR,
        "warnings.items.inactive_dependencies",
        "dialogs.patching_warning.title",
        "dialogs.patching_warning.dependency_activation",
        "warnings.tooltips.inactive_dependencies",
    ),
    "mod_order_suggestion": WarningDefinition(
        "mod_order_suggestion",
        WarningSeverity.MINOR,
        "warnings.items.mod_order_suggestion",
        "dialogs.patching_warning.title",
        "dialogs.patching_warning.relation_review",
        "warnings.tooltips.mod_order_suggestion",
    ),
}


def iter_warning_definitions() -> tuple[WarningDefinition, ...]:
    return tuple(WARNING_DEFINITIONS.values())


def get_warning_definition(warning_id: str) -> WarningDefinition:
    return WARNING_DEFINITIONS.get(
        warning_id, WARNING_DEFINITIONS["patching_warning"]
    )


def create_warning_event(
    warning_id: str,
    *,
    context: dict[str, Any] | None = None,
    details: str = "",
    report_path: str | None = None,
    fallback_message: str = "",
) -> WarningEvent:
    definition = get_warning_definition(warning_id)
    if definition.warning_id != warning_id:
        logger.warning(
            "Unknown warning id %r resolved to %r with context %r",
            warning_id,
            definition.warning_id,
            context or {},
        )
    return WarningEvent(
        definition.warning_id,
        dict(context or {}),
        details,
        report_path,
        fallback_message,
    )


def normalize_warning_preferences(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        config = {}
    prefs = config.get("warning_preferences")
    if not isinstance(prefs, dict):
        prefs = {}
        config["warning_preferences"] = prefs
    prefs.setdefault("skip_all", bool(config.get("skip_patching_warnings", False)))
    if not isinstance(prefs.get("warning_overrides"), dict):
        prefs["warning_overrides"] = {}
    prefs.pop("section_overrides", None)
    return prefs


def is_warning_enabled(warning_id: str, config: dict[str, Any] | None) -> bool:
    prefs = normalize_warning_preferences(config if config is not None else {})
    if prefs.get("skip_all", False):
        return False
    definition = get_warning_definition(warning_id)
    warning_overrides = prefs.get("warning_overrides", {})
    if definition.warning_id in warning_overrides:
        return bool(warning_overrides[definition.warning_id])
    return definition.enabled_by_default
