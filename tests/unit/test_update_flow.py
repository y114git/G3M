import os
from unittest.mock import Mock

from config.config import APP_VERSION


def test_get_update_info_returns_platform_specific_payload(app_state):
    """Checks that getting update info returns platform specific payload."""
    from services.updatecheck_service import UpdateChecker

    app_state.global_settings = {
        "launcher_files": {
            "version": "9.9.9",
            "urls": {"linux": "https://example.com/g3m.tar.gz"},
            "message": "Update",
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
