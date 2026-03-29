#!/usr/bin/env python3
"""
Startup test script for DELTAHUB builds.
Extracts archive and verifies the binary can start successfully.
Can be used both as a standalone script and as pytest tests.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import types
import zipfile
from unittest.mock import Mock, patch

import pytest

TEST_TIMEOUT = 10


def _contains_startup_errors(output: str) -> bool:
    error_markers = [
        "STARTUP ERROR",
        "CRITICAL ERROR",
        "Fatal error",
        "An error occurred during startup",
        "Traceback (most recent call last):",
    ]
    return any(marker in output for marker in error_markers)


def test_startup_from_environment():
    """Checks that startuping  from environment."""
    if "ARCHIVE_PATH" not in os.environ or "STARTUP_TARGET" not in os.environ:
        project_root = pathlib.Path(__file__).parent.parent
        main_py = project_root / "src" / "main.py"
        if not main_py.exists():
            pytest.skip("Neither CI env vars nor local main.py available")
        result = subprocess.run(
            [sys.executable, str(main_py), "--help"],
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            cwd=str(project_root),
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, output
        assert not _contains_startup_errors(output), (
            "Application startup failed with startup error(s)"
        )
        return

    archive_path = pathlib.Path(os.environ["ARCHIVE_PATH"])
    startup_target = os.environ["STARTUP_TARGET"]

    success = _test_startup_with_archive(archive_path, startup_target)
    assert success, f"Startup test failed for {startup_target}"


def test_startup_with_sample_archive(tmp_path):
    """Checks that startuping  with sample archive."""
    project_root = pathlib.Path(__file__).parent.parent
    main_py_path = project_root / "src" / "main.py"

    if not main_py_path.exists():
        pytest.skip(f"main.py not found at {main_py_path}")

    sample_archive_path = tmp_path / "sample_app.zip"

    with zipfile.ZipFile(sample_archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(main_py_path, "main.py")

        src_dir = project_root / "src"
        if src_dir.exists():
            for file_path in src_dir.rglob("*.py"):
                if file_path.is_file():
                    arc_path = file_path.relative_to(src_dir)
                    if file_path.samefile(main_py_path):
                        continue
                    archive.write(file_path, arc_path)

    success = _test_startup_with_archive(sample_archive_path, "main.py")
    assert success, "Sample archive startup test failed"


def test_local_startup():
    """Checks that localing startup."""
    project_root = pathlib.Path(__file__).parent.parent
    main_py_path = project_root / "src" / "main.py"

    if not main_py_path.exists():
        pytest.skip(f"main.py not found at {main_py_path}")

    try:
        result = subprocess.run(
            [sys.executable, str(main_py_path), "--help"],
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            cwd=str(project_root),
        )

        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, output
        assert not _contains_startup_errors(output), (
            "Application startup failed with startup error(s)"
        )

    except subprocess.TimeoutExpired:
        pytest.fail(f"Application startup timed out after {TEST_TIMEOUT} seconds")
    except Exception as e:
        pytest.fail(f"Unexpected error during startup test: {e}")


def test_run_app_startup_path_imports(monkeypatch):
    """Checks that runing app startup path imports."""
    from app import startup as startup_module

    class _Socket:
        def __getattr__(self, name) -> object:
            if name == "waitForConnected":
                return lambda *_args, **_kwargs: False
            return lambda *_args, **_kwargs: None

    class _App:
        def __init__(self) -> None:
            self._bootstrap_coordinator = None

        def exec(self):
            return 0

    class _Coordinator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def launch(self):
            return None

    monkeypatch.setattr(startup_module, "setup_app", lambda: _App())
    monkeypatch.setattr(startup_module, "QLocalSocket", _Socket)
    monkeypatch.setattr(startup_module.QLocalServer, "removeServer", lambda *_args: None)
    monkeypatch.setattr(startup_module, "check_game_processes", lambda: None)
    monkeypatch.setattr(startup_module, "register_url_protocol", lambda: None)
    monkeypatch.setattr(startup_module, "BootstrapCoordinator", _Coordinator)
    monkeypatch.setattr(startup_module, "get_user_data_root", lambda: "")
    monkeypatch.setattr(startup_module, "configure_logging", lambda *_args: "")
    monkeypatch.setattr(startup_module, "install_excepthook", lambda: None)
    monkeypatch.setattr(startup_module, "cleanup_old_temp_directories", lambda: None)
    monkeypatch.setattr(startup_module.sys, "argv", ["main.py"])
    monkeypatch.setitem(sys.modules, "app.window", types.SimpleNamespace(AppWindow=object))

    with pytest.raises(SystemExit) as exc:
        startup_module.run_app()

    assert exc.value.code == 0


def test_close_splash_and_show_launcher_delays_splash_close():
    """Checks that closing splash and show launcher delays splash close."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )

    with (
        patch.object(coordinator, "_show_launcher_window") as show_window,
        patch("bootstrap.bootstrap_coordinator.QTimer.singleShot") as single_shot,
    ):
        coordinator._close_splash_and_show_launcher()

    show_window.assert_called_once_with()
    single_shot.assert_called_once_with(
        coordinator._WINDOW_REVEAL_DELAY_MS, coordinator._finalize_window_reveal
    )


def test_finalize_window_reveal_closes_splash_after_front_refresh():
    """Checks that finalizeing window reveal closes splash after front refresh."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )

    with (
        patch.object(coordinator, "_close_splash") as close_splash,
        patch.object(coordinator, "_bring_launcher_to_front") as bring_to_front,
    ):
        coordinator._finalize_window_reveal()

    close_splash.assert_called_once_with()
    bring_to_front.assert_called_once_with()


def test_play_startup_sound_skips_when_disabled():
    """Checks that playing startup sound skips when disabled."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = Mock()
    coordinator.instance.app_state.local_config = {"disable_startup_sound": True}

    with patch("bootstrap.bootstrap_coordinator._audio_service.play_deltahub_sound") as play_sound:
        coordinator._play_startup_sound()

    play_sound.assert_not_called()


def test_play_startup_sound_uses_enabled_flag():
    """Checks that playing startup sound uses enabled flag."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = Mock()
    coordinator.instance.app_state.local_config = {"disable_startup_sound": False}

    with patch("bootstrap.bootstrap_coordinator._audio_service.play_deltahub_sound") as play_sound:
        coordinator._play_startup_sound()

    play_sound.assert_called_once_with()


def test_show_launcher_window_schedules_post_show_after_reveal_delay():
    """Checks that showing launcher window schedules post show after reveal delay."""
    from PyQt6.QtCore import Qt

    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    app = Mock()
    instance = Mock()
    instance.app_state = types.SimpleNamespace(game_is_running=False, is_shown_to_user=False)
    instance.windowState.return_value = Qt.WindowState.WindowNoState
    coordinator = BootstrapCoordinator(
        app=app,
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = instance
    order = []

    with (
        patch.object(coordinator, "restore_ui_state_from_config"),
        patch.object(coordinator, "_play_startup_sound", side_effect=lambda: order.append("sound")) as play_sound,
        patch.object(
            coordinator,
            "_bring_launcher_to_front",
            side_effect=lambda: order.append("front"),
        ) as bring_to_front,
        patch("bootstrap.bootstrap_coordinator.QApplication.instance", return_value=app),
        patch("bootstrap.bootstrap_coordinator.QTimer.singleShot") as single_shot,
    ):
        coordinator._show_launcher_window()

    instance.show.assert_called_once_with()
    play_sound.assert_called_once_with()
    bring_to_front.assert_called_once_with()
    assert order == ["sound", "front"]
    assert single_shot.call_args_list == [
        ((coordinator._WINDOW_REVEAL_DELAY_MS, instance._post_show_initialization),),
        ((coordinator._WINDOW_REVEAL_DELAY_MS, bring_to_front),),
    ]


def test_startup_window_creation_smoke(qapp, tmp_path):
    """Checks that startuping window creation smoke."""
    from app.window import AppWindow

    user_root = tmp_path / "user"
    profiles_dir = tmp_path / "profiles"
    themes_dir = tmp_path / "themes"
    for path in (user_root, profiles_dir, themes_dir):
        path.mkdir(parents=True, exist_ok=True)
    mock_presence_response = Mock()
    mock_presence_response.status_code = 200
    mock_presence_response.json.return_value = {"online": 0}
    mock_presence_session = Mock()
    mock_presence_session.post.return_value = mock_presence_response
    with (
        patch(
            "app_context.application_context.get_user_data_root",
            return_value=str(user_root),
        ),
        patch(
            "app_context.application_context.get_launcher_dir",
            return_value=str(tmp_path),
        ),
        patch(
            "services.g3mtool_patching_service.get_user_data_root",
            return_value=str(user_root),
        ),
        patch(
            "services.blocklist_service.get_user_data_root",
            return_value=str(user_root),
        ),
        patch("utils.path_utils.get_user_themes_dir", return_value=str(themes_dir)),
        patch(
            "services.profile_service.get_user_profiles_dir",
            return_value=str(profiles_dir),
        ),
        patch(
            "workers.presence_worker.get_session",
            return_value=mock_presence_session,
        ),
    ):
        window = AppWindow()
        try:
            assert window is not None
            assert window.windowTitle() == "DELTAHUB"
        finally:
            window.close()


def _test_startup_with_archive(archive_path: pathlib.Path, startup_target: str) -> bool:
    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            extract_path = pathlib.Path(extract_dir)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_path)

            target = extract_path / startup_target
            if not target.exists():
                return False

            target.chmod(target.stat().st_mode | 0o111)
            cwd = str(extract_path)

            if startup_target.endswith(".py"):
                result = subprocess.run(
                    [sys.executable, str(target), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=cwd,
                )
            else:
                result = subprocess.run(
                    [str(target), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=cwd,
                )
            output = (result.stdout or "") + (result.stderr or "")
            return result.returncode == 0 and not _contains_startup_errors(output)

    except subprocess.TimeoutExpired:
        sys.stderr.write(
            f"Startup test timed out after {TEST_TIMEOUT} seconds for {startup_target}\n"
        )
        return False
    except Exception as e:
        sys.stderr.write(
            f"Startup test failed with exception for {startup_target}: {e}\n"
        )
        return False


def main():
    if "ARCHIVE_PATH" not in os.environ or "STARTUP_TARGET" not in os.environ:
        raise SystemExit(1)

    archive_path = pathlib.Path(os.environ["ARCHIVE_PATH"])
    startup_target = os.environ["STARTUP_TARGET"]

    success = _test_startup_with_archive(archive_path, startup_target)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
