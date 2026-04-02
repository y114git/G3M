import os
from unittest.mock import Mock

import pytest

from config.config import APP_VERSION


def test_get_update_info_returns_platform_specific_payload(app_state):
    """Checks that getting update info returns platform specific payload."""
    from services.updatecheck_service import UpdateChecker

    app_state.global_settings = {
        "launcher_files": {
            "version": "9.9.9",
            "urls": {"linux": "https://example.com/g3m.tar.gz"},
            "message": "Update",
            "sha256": {"linux": "abc123"},
        }
    }
    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())

    update_info = checker.get_update_info(system="Linux", beta_enabled=False)

    assert update_info == {
        "version": "9.9.9",
        "url": "https://example.com/g3m.tar.gz",
        "message": "Update",
        "message_ru": None,
        "message_en": None,
        "sha256": "abc123",
    }


def test_get_update_info_skips_current_version(app_state):
    """Checks that getting update info skips current version."""
    from services.updatecheck_service import UpdateChecker

    feedback_service = Mock()
    app_state.global_settings = {
        "launcher_files": {
            "version": APP_VERSION,
            "urls": {"linux": "https://example.com/g3m.tar.gz"},
        }
    }
    checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)

    assert checker.get_update_info(system="Linux", beta_enabled=False) is None
    feedback_service.update_status.assert_called_once()


def test_verify_archive_checksum_rejects_mismatch(app_state, temp_dir):
    """Checks that verifying archive checksum rejects mismatch."""
    from models.exceptions import AppError
    from services.updatecheck_service import UpdateChecker

    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())
    archive_path = os.path.join(temp_dir, "update.zip")
    with open(archive_path, "wb") as file_obj:
        file_obj.write(b"invalid")

    with pytest.raises(AppError) as exc_info:
        checker._verify_archive_checksum(archive_path, "0" * 64)
    assert "Checksum mismatch" in exc_info.value.kwargs["error"]


def test_build_unix_updater_script_contains_backup_restore(app_state):
    """Checks that building unix updater script contains backup restore."""
    from services.updatecheck_service import UpdateChecker

    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())

    _, script = checker._build_unix_updater_script(
        "/app/G3M", os.path.join("tmp", "G3M.new"), "Linux"
    )

    assert 'BACKUP_PATH="${OLD_PATH}.old"' in script
    assert 'mv "$OLD_PATH" "$BACKUP_PATH"' in script
    assert 'mv -f "$BACKUP_PATH" "$OLD_PATH"' in script


def test_prompt_for_update_queues_when_game_is_running():
    """Checks that prompting for update queues when game is running."""
    from presentation.update_presenter import prompt_for_update

    app = Mock()
    app.app_state.update_in_progress = False
    app.app_state.game_is_running = True
    app.app_state.pending_dialogs = []

    prompt_for_update(app, {"version": "9.9.9"})

    assert app.app_state.pending_dialogs == [("update", {"version": "9.9.9"})]
    app.update_checker.perform_update.assert_not_called()
