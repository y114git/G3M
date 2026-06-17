"""Unit tests for test update flow."""

import logging
import os
import sys
import types
from types import SimpleNamespace
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


def test_check_for_updates_suppresses_status_update_failure_on_error(app_state, monkeypatch):
    """Checks that a broken status label does not crash failed update checks."""
    from services.updatecheck_service import UpdateChecker

    feedback_service = Mock()
    feedback_service.update_status.side_effect = RuntimeError("status failed")
    checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)
    monkeypatch.setattr(
        checker,
        "get_update_info",
        Mock(side_effect=RuntimeError("settings unavailable")),
    )

    checker.check_for_updates()

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


def test_prompt_for_update_reject_ignores_broken_status_feedback():
    """Checks that declining an update is not broken by a dead status widget."""
    from presentation.update_presenter import prompt_for_update

    app = Mock()
    app.app_state.update_in_progress = False
    app.app_state.game_is_running = False
    app.app_state.pending_announce_check = False
    app.feedback_service.ask_question.return_value = False
    app.feedback_service.update_status.side_effect = RuntimeError("status deleted")
    app._localized_value.return_value = "Notes"

    prompt_for_update(app, {"version": "9.9.9", "message": "Notes"})

    assert app.app_state.update_in_progress is False
    app.feedback_service.update_status.assert_called_once()
    app.update_checker.perform_update.assert_not_called()


def test_announce_poll_warning_failure_returns_false(monkeypatch, caplog):
    """Checks that poll submit failure is not hidden by a broken warning dialog."""
    from presentation.update_presenter import check_and_show_announce

    created = {}

    class _Signal:
        def connect(self, callback):
            self.callback = callback

    class _AnnounceDialog:
        def __init__(self, announce, parent, on_submit_poll) -> None:
            created["dialog"] = self
            self.announce = announce
            self.parent = parent
            self.on_submit_poll = on_submit_poll
            self.accepted_with_ok = _Signal()
            self.finished = _Signal()

        def setWindowModality(self, _modality):  # noqa: N802
            return None

        def show(self):
            return None

    monkeypatch.setitem(
        sys.modules,
        "ui.dialogs.announce_dialog",
        SimpleNamespace(AnnounceDialog=_AnnounceDialog),
    )
    app = Mock()
    app.app_state.initialization_completed = True
    app.app_state.is_shown_to_user = True
    app.app_state.global_settings = {
        "announce": {
            "version": 2,
            "messages": {"message_en": "Vote"},
        }
    }
    app.app_state.local_config = {"announce_version": 1}
    app.app_state.active_announce_dialog = None
    app.isVisible.return_value = True
    app._localized_value.return_value = "Vote"
    app.announce_service.submit_poll_vote.return_value = (False, "Nope")

    check_and_show_announce(app)

    with (
        monkeypatch.context() as m,
        caplog.at_level(logging.ERROR),
    ):
        m.setattr(
            "presentation.update_presenter.QMessageBox.warning",
            Mock(side_effect=RuntimeError("dialog deleted")),
        )
        assert created["dialog"].on_submit_poll(["a"]) is False

    assert "Update presenter: warning dialog failed" in caplog.text


def test_windows_installer_forced_exit_is_logged(app_state, monkeypatch, caplog):
    """Checks that the updater logs before using os._exit after launching installer."""
    from services import updatecheck_service
    from services.updatecheck_service import UpdateChecker

    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())
    monkeypatch.setattr(
        checker,
        "_find_windows_installer",
        Mock(return_value="C:/Temp/G3M-Installer.exe"),
    )
    monkeypatch.setitem(
        sys.modules,
        "ctypes",
        types.SimpleNamespace(
            windll=types.SimpleNamespace(
                shell32=types.SimpleNamespace(ShellExecuteW=Mock(return_value=33))
            )
        ),
    )
    timer_callbacks = []

    class _Timer:
        daemon = False

        def __init__(self, _delay, callback) -> None:
            timer_callbacks.append(callback)

        def start(self):
            return None

    monkeypatch.setattr(updatecheck_service.threading, "Timer", _Timer)
    exit_mock = Mock()
    monkeypatch.setattr(updatecheck_service.os, "_exit", exit_mock)

    assert checker._launch_windows_installer("C:/Temp/extracted") is True
    with caplog.at_level(logging.INFO):
        timer_callbacks[0]()

    exit_mock.assert_called_once_with(0)
    assert "Forced process exit after launching updater installer" in caplog.text
