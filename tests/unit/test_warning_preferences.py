"""Unit tests for test warning preferences."""

from services.warning_service import (
    WarningSeverity,
    create_warning_event,
    get_warning_definition,
    is_warning_enabled,
    normalize_warning_preferences,
)


def test_skip_patching_warnings_migrates_to_skip_all():
    config = {"skip_patching_warnings": True}

    prefs = normalize_warning_preferences(config)

    assert prefs["skip_all"] is True
    assert is_warning_enabled("g3mpatch_original_hash_mismatch", config) is False


def test_legacy_section_override_is_removed_and_ignored():
    config = {
        "warning_preferences": {
            "skip_all": False,
            "section_overrides": {"major": False},
            "warning_overrides": {"g3mpatch_original_hash_mismatch": True},
        }
    }
    prefs = normalize_warning_preferences(config)

    assert "section_overrides" not in prefs
    assert is_warning_enabled("g3mpatch_original_hash_mismatch", config) is True
    assert is_warning_enabled("xdelta_apply_failed", config) is True


def test_individual_warning_override_uses_registry_defaults():
    config = {
        "warning_preferences": {
            "warning_overrides": {
                "minor_file_overrides_only": True,
                "g3mpatch_newer_tool": False,
            }
        }
    }

    assert is_warning_enabled("minor_file_overrides_only", config) is True
    assert is_warning_enabled("g3mpatch_newer_tool", config) is False


def test_warning_event_keeps_severity_and_context():
    definition = get_warning_definition("xdelta_apply_failed")

    event = create_warning_event(
        "xdelta_apply_failed",
        context={"patch_name": "mod.xdelta", "reason": "checksum mismatch"},
    )

    assert definition.severity is WarningSeverity.CRITICAL
    assert event.warning_id == "xdelta_apply_failed"
    assert event.context["patch_name"] == "mod.xdelta"


def test_unknown_warning_event_logs_fallback(caplog):
    event = create_warning_event(
        "unknown_warning",
        context={"patch_name": "mod.xdelta"},
    )

    assert event.warning_id == "legacy_patching_warning"
    assert "unknown_warning" in caplog.text
    assert "legacy_patching_warning" in caplog.text


def test_extra_file_warning_definitions_are_registered():
    definition = get_warning_definition("extra_file_missing")

    assert definition.severity is WarningSeverity.MAJOR
    assert definition.enabled_by_default is True
    assert is_warning_enabled(
        "extra_file_missing",
        {"warning_preferences": {"warning_overrides": {"extra_file_missing": False}}},
    ) is False
    assert get_warning_definition("extra_xdelta_no_target").severity is WarningSeverity.MINOR


def test_missing_data_file_is_critical():
    assert get_warning_definition("data_file_missing").severity is WarningSeverity.CRITICAL
