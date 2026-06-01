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
    "g3mtool_unavailable": WarningDefinition(
        "g3mtool_unavailable",
        WarningSeverity.CRITICAL,
        "warnings.items.g3mtool_unavailable",
        "warnings.messages.g3mtool_unavailable.title",
        "warnings.messages.g3mtool_unavailable.body",
        "warnings.tooltips.g3mtool_unavailable",
    ),
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
    "patched_output_missing": WarningDefinition(
        "patched_output_missing",
        WarningSeverity.CRITICAL,
        "warnings.items.patched_output_missing",
        "warnings.messages.patched_output_missing.title",
        "warnings.messages.patched_output_missing.body",
        "warnings.tooltips.patched_output_missing",
    ),
    "data_file_missing": WarningDefinition(
        "data_file_missing",
        WarningSeverity.CRITICAL,
        "warnings.items.data_file_missing",
        "warnings.messages.data_file_missing.title",
        "warnings.messages.data_file_missing.body",
        "warnings.tooltips.data_file_missing",
    ),
    "g3mpatch_original_hash_mismatch": WarningDefinition(
        "g3mpatch_original_hash_mismatch",
        WarningSeverity.MAJOR,
        "warnings.items.g3mpatch_original_hash_mismatch",
        "warnings.messages.g3mpatch_original_hash_mismatch.title",
        "warnings.messages.g3mpatch_original_hash_mismatch.body",
        "warnings.tooltips.g3mpatch_original_hash_mismatch",
    ),
    "g3mpatch_newer_tool": WarningDefinition(
        "g3mpatch_newer_tool",
        WarningSeverity.MAJOR,
        "warnings.items.g3mpatch_newer_tool",
        "warnings.messages.g3mpatch_newer_tool.title",
        "warnings.messages.g3mpatch_newer_tool.body",
        "warnings.tooltips.g3mpatch_newer_tool",
    ),
    "merge_conflicts_detected": WarningDefinition(
        "merge_conflicts_detected",
        WarningSeverity.MAJOR,
        "warnings.items.merge_conflicts_detected",
        "warnings.messages.merge_conflicts_detected.title",
        "warnings.messages.merge_conflicts_detected.body",
        "warnings.tooltips.merge_conflicts_detected",
    ),
    "steam_launch_with_mods": WarningDefinition(
        "steam_launch_with_mods",
        WarningSeverity.MAJOR,
        "warnings.items.steam_launch_with_mods",
        "warnings.messages.steam_launch_with_mods.title",
        "warnings.messages.steam_launch_with_mods.body",
        "warnings.tooltips.steam_launch_with_mods",
    ),
    "custom_binary_invalid": WarningDefinition(
        "custom_binary_invalid",
        WarningSeverity.MAJOR,
        "warnings.items.custom_binary_invalid",
        "warnings.messages.custom_binary_invalid.title",
        "warnings.messages.custom_binary_invalid.body",
        "warnings.tooltips.custom_binary_invalid",
    ),
    "extra_file_missing": WarningDefinition(
        "extra_file_missing",
        WarningSeverity.MAJOR,
        "warnings.items.extra_file_missing",
        "warnings.messages.extra_file_missing.title",
        "warnings.messages.extra_file_missing.body",
        "warnings.tooltips.extra_file_missing",
    ),
    "extra_directory_missing": WarningDefinition(
        "extra_directory_missing",
        WarningSeverity.MAJOR,
        "warnings.items.extra_directory_missing",
        "warnings.messages.extra_directory_missing.title",
        "warnings.messages.extra_directory_missing.body",
        "warnings.tooltips.extra_directory_missing",
    ),
    "extra_file_copy_failed": WarningDefinition(
        "extra_file_copy_failed",
        WarningSeverity.MAJOR,
        "warnings.items.extra_file_copy_failed",
        "warnings.messages.extra_file_copy_failed.title",
        "warnings.messages.extra_file_copy_failed.body",
        "warnings.tooltips.extra_file_copy_failed",
    ),
    "extra_archive_extract_failed": WarningDefinition(
        "extra_archive_extract_failed",
        WarningSeverity.MAJOR,
        "warnings.items.extra_archive_extract_failed",
        "warnings.messages.extra_archive_extract_failed.title",
        "warnings.messages.extra_archive_extract_failed.body",
        "warnings.tooltips.extra_archive_extract_failed",
    ),
    "extra_xdelta_no_target": WarningDefinition(
        "extra_xdelta_no_target",
        WarningSeverity.MINOR,
        "warnings.items.extra_xdelta_no_target",
        "warnings.messages.extra_xdelta_no_target.title",
        "warnings.messages.extra_xdelta_no_target.body",
        "warnings.tooltips.extra_xdelta_no_target",
        enabled_by_default=False,
    ),
    "extra_xdelta_apply_failed": WarningDefinition(
        "extra_xdelta_apply_failed",
        WarningSeverity.MAJOR,
        "warnings.items.extra_xdelta_apply_failed",
        "warnings.messages.extra_xdelta_apply_failed.title",
        "warnings.messages.extra_xdelta_apply_failed.body",
        "warnings.tooltips.extra_xdelta_apply_failed",
    ),
    "minor_file_overrides_only": WarningDefinition(
        "minor_file_overrides_only",
        WarningSeverity.MINOR,
        "warnings.items.minor_file_overrides_only",
        "warnings.messages.minor_file_overrides_only.title",
        "warnings.messages.minor_file_overrides_only.body",
        "warnings.tooltips.minor_file_overrides_only",
        enabled_by_default=False,
    ),
    "cache_rebuild_needed": WarningDefinition(
        "cache_rebuild_needed",
        WarningSeverity.MINOR,
        "warnings.items.cache_rebuild_needed",
        "warnings.messages.cache_rebuild_needed.title",
        "warnings.messages.cache_rebuild_needed.body",
        "warnings.tooltips.cache_rebuild_needed",
        enabled_by_default=False,
    ),
    "legacy_patching_warning": WarningDefinition(
        "legacy_patching_warning",
        WarningSeverity.MAJOR,
        "warnings.items.legacy_patching_warning",
        "warnings.messages.legacy_patching_warning.title",
        "warnings.messages.legacy_patching_warning.body",
        "warnings.tooltips.legacy_patching_warning",
    ),
}


def iter_warning_definitions() -> tuple[WarningDefinition, ...]:
    return tuple(WARNING_DEFINITIONS.values())


def get_warning_definition(warning_id: str) -> WarningDefinition:
    return WARNING_DEFINITIONS.get(
        warning_id, WARNING_DEFINITIONS["legacy_patching_warning"]
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
