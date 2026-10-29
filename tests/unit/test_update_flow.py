"""Unit tests for test update flow."""

import logging
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

from config.config import APP_VERSION


def test_get_update_info_returns_platform_specific_payload(app_state, monkeypatch):
    """Checks that getting update info returns platform specific payload."""
    from services.updatecheck_service import UpdateChecker

    app_state.global_settings = {
        "launcher_files": {
            "version": "9.9.9",
            "urls": {"linux-x86_64": "https://example.com/g3m.tar.gz"},
            "message": "Update",
        }
    }
    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())
    monkeypatch.setattr("services.updatecheck_service.ARCH", "x86_64")

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
            "urls": {"linux-x86_64": "https://example.com/g3m.tar.gz"},
        }
    }
    checker = UpdateChecker(app_state=app_state, feedback_service=feedback_service)

    assert checker.get_update_info(system="Linux", beta_enabled=False) is None
    feedback_service.update_status.assert_called_once()


def test_get_platform_key_normalizes_windows_and_linux_arm64(app_state, monkeypatch):
    """Update URLs use the native architecture for every supported system."""
    from services.updatecheck_service import UpdateChecker

    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())
    monkeypatch.setattr("services.updatecheck_service.ARCH", "AMD64")
    assert checker._get_platform_key("Windows") == "windows-x86_64"
    monkeypatch.setattr("services.updatecheck_service.ARCH", "aarch64")
    assert checker._get_platform_key("Linux") == "linux-arm64"
    monkeypatch.setattr("services.updatecheck_service.ARCH", "arm64")
    assert checker._get_platform_key("Darwin") == "macos-arm64"


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


def test_windows_installer_waits_for_clean_launcher_exit(app_state, monkeypatch, tmp_path):
    """The elevated helper starts setup only after the launcher has exited."""
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
    monkeypatch.setattr(updatecheck_service.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updatecheck_service.time, "monotonic_ns", lambda: 1)

    assert checker._launch_windows_installer("C:/Temp/extracted") is True
    script_path = tmp_path / f"g3m_updater_{os.getpid()}_1.cmd"
    script = script_path.read_text(encoding="ascii")
    shell_execute = sys.modules["ctypes"].windll.shell32.ShellExecuteW
    assert shell_execute.call_args.args == (
        None,
        "runas",
        os.environ.get("COMSPEC", "cmd.exe"),
        f'/d /c ""{script_path}" "C:/Temp/G3M-Installer.exe" "C:/Temp""',
        "C:/Temp",
        0,
    )
    assert f'set "G3M_PID={os.getpid()}"' in script
    assert 'set "INSTALLER=%~1"' in script
    assert 'set "UPDATE_DIR=%~2"' in script
    assert "C:/Temp/G3M-Installer.exe" not in script
    assert ":wait_for_g3m" in script
    assert 'start "" /wait "%INSTALLER%"' in script
    assert 'rmdir /s /q "%UPDATE_DIR%"' in script
    assert not hasattr(checker, "_force_exit_after_installer_launch")


def test_windows_update_keeps_installer_staging_for_its_helper(
    app_state, monkeypatch, tmp_path
):
    """The helper, not the update worker, owns cleanup after setup starts."""
    from services import updatecheck_service
    from services.updatecheck_service import UpdateChecker

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())
    checker._download_archive = Mock(return_value=str(staging_dir / "update.zip"))
    checker._extract_archive = Mock()
    checker._launch_windows_installer = Mock(return_value=True)
    monkeypatch.setattr(updatecheck_service.platform, "system", lambda: "Windows")
    monkeypatch.setattr(updatecheck_service.tempfile, "mkdtemp", lambda **_kwargs: str(staging_dir))

    checker._update_worker({"version": "9.9.9"})

    checker._launch_windows_installer.assert_called_once_with(str(staging_dir / "extracted"))
    assert staging_dir.is_dir()


def test_update_check_before_server_settings_is_repeated_when_they_arrive(app_state):
    from services.updatecheck_service import UpdateChecker

    checker = UpdateChecker(app_state=app_state, feedback_service=Mock())
    app_state.global_settings = {}

    assert checker.get_update_info(system="Linux", beta_enabled=False) is None
    assert checker.awaiting_settings

    app_state.global_settings = {"launcher_files": {"version": APP_VERSION, "urls": {}}}
    checker.get_update_info(system="Linux", beta_enabled=False)

    assert not checker.awaiting_settings
