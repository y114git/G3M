from PyQt6.QtCore import Qt

from services.warning_service import WarningSeverity
from ui.dialogs.warning_preferences_dialog import WarningPreferencesDialog


def test_warning_preferences_dialog_ignores_legacy_section_overrides(qapp):
    config = {"warning_preferences": {"section_overrides": {"major": False}}}
    dialog = WarningPreferencesDialog(config)
    try:
        child = dialog.warning_checkboxes["g3mpatch_original_hash_mismatch"]
        skip_all_index = dialog.layout().indexOf(dialog.skip_all_checkbox)
        skip_all_item = dialog.layout().itemAt(skip_all_index)

        assert dialog.minimumWidth() >= 680
        assert skip_all_item.alignment() == Qt.AlignmentFlag.AlignCenter
        assert child.isEnabled() is True
        assert dialog.warning_help_buttons["g3mpatch_original_hash_mismatch"].text() == "?"
        tooltip = dialog.warning_help_buttons[
            "g3mpatch_original_hash_mismatch"
        ].toolTip()
        assert tooltip
        assert "{severity}" not in tooltip
        assert "Severity:" not in tooltip
    finally:
        dialog.close()


def test_warning_preferences_dialog_sections_collapse(qapp):
    config = {}
    dialog = WarningPreferencesDialog(config)
    try:
        dialog.app_state = type(
            "AppState", (), {"local_config": {"disable_animations": True}}
        )()
        section = dialog.section_content_widgets[WarningSeverity.MAJOR]

        assert section.isHidden() is False
        assert dialog.section_arrows[WarningSeverity.MAJOR].text() == "▼"

        dialog._toggle_section(WarningSeverity.MAJOR)

        assert section.isHidden() is True
        assert dialog.section_arrows[WarningSeverity.MAJOR].text() == "▶"
    finally:
        dialog.close()


def test_warning_preferences_dialog_skip_all_disables_warning_items(qapp):
    config = {"warning_preferences": {"skip_all": True}}
    dialog = WarningPreferencesDialog(config)
    try:
        assert dialog.skip_all_checkbox.isChecked() is True
        assert all(not checkbox.isEnabled() for checkbox in dialog.warning_checkboxes.values())
        assert all(button.isEnabled() for button in dialog.warning_help_buttons.values())
    finally:
        dialog.close()


def test_warning_preferences_dialog_accept_writes_preferences(qapp):
    config = {}
    dialog = WarningPreferencesDialog(config)
    try:
        dialog.warning_checkboxes["g3mpatch_newer_tool"].setChecked(False)
        dialog.accept()

        overrides = config["warning_preferences"]["warning_overrides"]
        assert overrides["g3mpatch_newer_tool"] is False
        assert "section_overrides" not in config["warning_preferences"]
    finally:
        dialog.close()
