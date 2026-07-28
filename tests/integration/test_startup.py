"""Integration tests for startup flows and packaged-launch validation."""

import contextlib
import faulthandler
import importlib.util
import logging
import os
import pathlib
import platform
import subprocess
import sys
import tempfile
import threading
import types
import zipfile
from typing import cast
from unittest.mock import Mock, patch

import pytest

TEST_TIMEOUT = 10
PACKAGED_BINARY_STARTUP_GRACE_SECONDS = 4


def _project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _load_main_module():
    project_root = _project_root()
    main_path = project_root / "src" / "main.py"
    spec = importlib.util.spec_from_file_location("g3m_src_main", main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load main module from {main_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _contains_startup_errors(output: str) -> bool:
    error_markers = [
        "STARTUP ERROR",
        "CRITICAL ERROR",
        "Fatal error",
        "An error occurred during startup",
        "Traceback (most recent call last):",
    ]
    return any(marker in output for marker in error_markers)


def _run_packaged_binary_smoke(
    target: pathlib.Path, cwd: str, env: dict[str, str]
) -> tuple[int, str]:
    process = subprocess.Popen(
        [str(target), "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(
            timeout=PACKAGED_BINARY_STARTUP_GRACE_SECONDS
        )
        return process.returncode, (stdout or "") + (stderr or "")
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        output = (stdout or "") + (stderr or "")
        if _contains_startup_errors(output):
            return 1, output
        return 0, output


def test_startup_from_environment():
    """Checks that startup from environment."""
    if "ARCHIVE_PATH" not in os.environ or "STARTUP_TARGET" not in os.environ:
        project_root = _project_root()
        main_py = project_root / "src" / "main.py"
        if not main_py.exists():
            pytest.skip("Neither CI env vars nor local main.py available")
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, str(main_py), "--help"],
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            cwd=str(project_root),
            env=env,
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, output
        assert not _contains_startup_errors(output), (
            "Application startup failed with startup error(s)"
        )
        return

    archive_path = pathlib.Path(os.environ["ARCHIVE_PATH"])
    startup_target = os.environ["STARTUP_TARGET"]

    launch_target = os.environ.get("STARTUP_LAUNCH_TARGET")
    success = _test_startup_with_archive(
        archive_path,
        startup_target,
        pathlib.Path(launch_target).resolve() if launch_target else None,
    )
    assert success, f"Startup test failed for {startup_target}"


def test_startup_with_sample_archive(tmp_path):
    """Checks that startup with sample archive."""
    project_root = _project_root()
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
    """Checks that local startup."""
    project_root = _project_root()
    main_py_path = project_root / "src" / "main.py"

    if not main_py_path.exists():
        pytest.skip(f"main.py not found at {main_py_path}")

    try:
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, str(main_py_path), "--help"],
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            cwd=str(project_root),
            env=env,
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
    """Checks that running app startup path imports."""
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
    monkeypatch.setattr(
        startup_module.QLocalServer, "removeServer", lambda *_args: None
    )
    monkeypatch.setattr(startup_module, "check_game_processes", lambda: None)
    monkeypatch.setattr(startup_module, "register_url_protocol", lambda: None)
    monkeypatch.setattr(startup_module, "BootstrapCoordinator", _Coordinator)
    monkeypatch.setattr(
        startup_module, "resolve_user_data_root_with_migration", lambda: ""
    )
    monkeypatch.setattr(startup_module, "configure_logging", lambda *_args: "")
    monkeypatch.setattr(startup_module, "install_crash_diagnostics", lambda *_args: "")
    monkeypatch.setattr(startup_module, "install_excepthook", lambda: None)
    monkeypatch.setattr(startup_module, "cleanup_old_temp_directories", lambda: None)
    monkeypatch.setitem(
        sys.modules, "app.window", types.SimpleNamespace(AppWindow=object)
    )

    assert startup_module.run_app([]) == 0


def test_install_crash_diagnostics_uses_main_log(temp_dir):
    from app import startup as startup_module

    log_dir = os.path.join(temp_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "g3m.log")
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write("existing log\n")

    diagnostics_path = startup_module.install_crash_diagnostics("G3M", log_path)

    assert diagnostics_path == log_path
    assert faulthandler.is_enabled()
    assert startup_module._fault_log_handle
    assert not startup_module._fault_log_handle.closed
    assert threading.excepthook is not threading.__excepthook__
    with open(log_path, encoding="utf-8") as handle:
        assert "G3M crash diagnostics start" in handle.read()
    faulthandler.disable()
    if startup_module._fault_log_handle:
        startup_module._fault_log_handle.close()
        startup_module._fault_log_handle = None


def test_install_crash_diagnostics_logs_unraisable_exceptions(temp_dir):
    from app import startup as startup_module

    log_dir = os.path.join(temp_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "g3m.log")
    startup_module.configure_logging("G3M", temp_dir)
    original_unraisablehook = sys.unraisablehook
    try:
        startup_module.install_crash_diagnostics("G3M", log_path)

        class BrokenFinalizer:
            def __repr__(self) -> str:
                return "<BrokenFinalizer>"

        args = types.SimpleNamespace(
            exc_type=RuntimeError,
            exc_value=RuntimeError("unraisable logging probe"),
            exc_traceback=None,
            err_msg=None,
            object=BrokenFinalizer(),
        )
        sys.unraisablehook(cast("types.UnraisableHookArgs", args))
        for handler in logging.getLogger().handlers:
            handler.flush()

        with open(log_path, encoding="utf-8") as handle:
            log_text = handle.read()
        assert "Unraisable exception" in log_text
        assert "unraisable logging probe" in log_text
    finally:
        sys.unraisablehook = original_unraisablehook
        faulthandler.disable()
        if startup_module._fault_log_handle:
            startup_module._fault_log_handle.close()
            startup_module._fault_log_handle = None


def test_configure_logging_writes_uncaught_exceptions_when_root_handler_exists(temp_dir):
    from app import startup as startup_module

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    foreign_handler = logging.StreamHandler()
    root.handlers = [foreign_handler]
    root.setLevel(logging.WARNING)
    try:
        log_path = startup_module.configure_logging("G3M", temp_dir)
        startup_module.install_excepthook()

        try:
            raise RuntimeError("startup logging probe")
        except RuntimeError:
            exctype, value, tb = sys.exc_info()
            assert exctype is not None
            assert value is not None
            sys.excepthook(exctype, value, tb)

        for handler in root.handlers:
            handler.flush()
        with open(log_path, encoding="utf-8") as handle:
            log_text = handle.read()
        assert "Uncaught exception" in log_text
        assert "startup logging probe" in log_text
    finally:
        for handler in root.handlers:
            with contextlib.suppress(Exception):
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_run_app_installs_process_exit_logging(monkeypatch):
    from app import startup as startup_module

    registered = []
    app = Mock()
    app.exec.return_value = 0
    monkeypatch.setattr(startup_module, "setup_app", lambda: app)
    monkeypatch.setattr(
        startup_module,
        "resolve_user_data_root_with_migration",
        lambda: "C:/Users/Test/AppData/Roaming/G3M",
    )
    monkeypatch.setattr(startup_module, "configure_logging", lambda *_args: "g3m.log")
    monkeypatch.setattr(startup_module, "install_crash_diagnostics", lambda *_args: "")
    monkeypatch.setattr(startup_module, "install_excepthook", Mock())
    monkeypatch.setattr(startup_module, "cleanup_old_temp_directories", Mock())
    monkeypatch.setattr(startup_module.atexit, "register", lambda callback: registered.append(callback))
    monkeypatch.setattr(startup_module, "check_game_processes", lambda: None)
    monkeypatch.setattr(startup_module, "register_url_protocol", Mock())
    monkeypatch.setattr(startup_module.QLocalServer, "removeServer", Mock())

    class _Socket:
        def connectToServer(self, *_args, **_kwargs):  # noqa: N802
            return None

        def waitForConnected(self, *_args, **_kwargs):  # noqa: N802
            return False

    class _Coordinator:
        def __init__(self, **_kwargs) -> None:
            pass

        def launch(self):
            return None

    monkeypatch.setattr(startup_module, "QLocalSocket", _Socket)
    monkeypatch.setattr(startup_module, "BootstrapCoordinator", _Coordinator)

    startup_module.run_app(["--force-start"])

    assert registered


def test_run_app_creates_qapplication_before_user_data_migration(monkeypatch):
    from app import startup as startup_module

    call_order = []
    app = Mock()
    app.exec.return_value = 0
    monkeypatch.setattr(
        startup_module,
        "setup_app",
        lambda: call_order.append("setup_app") or app,
    )
    monkeypatch.setattr(
        startup_module,
        "resolve_user_data_root_with_migration",
        lambda: call_order.append("resolve") or "C:/Users/Test/AppData/Local/G3M",
    )
    monkeypatch.setattr(
        startup_module, "configure_logging", lambda *_args: "g3m.log"
    )
    monkeypatch.setattr(
        startup_module, "install_crash_diagnostics", lambda *_args: ""
    )
    monkeypatch.setattr(startup_module, "install_process_exit_logging", Mock())
    monkeypatch.setattr(startup_module, "install_excepthook", Mock())
    monkeypatch.setattr(startup_module, "cleanup_old_temp_directories", Mock())
    monkeypatch.setattr(startup_module, "check_game_processes", lambda: None)
    monkeypatch.setattr(startup_module, "register_url_protocol", Mock())
    monkeypatch.setattr(startup_module.QLocalServer, "removeServer", Mock())

    class _Socket:
        def connectToServer(self, *_args, **_kwargs):  # noqa: N802
            return None

        def waitForConnected(self, *_args, **_kwargs):  # noqa: N802
            return False

    class _Coordinator:
        def __init__(self, **_kwargs) -> None:
            pass

        def launch(self):
            return None

    monkeypatch.setattr(startup_module, "QLocalSocket", _Socket)
    monkeypatch.setattr(startup_module, "BootstrapCoordinator", _Coordinator)

    assert startup_module.run_app(["--force-start"]) == 0
    assert call_order[:2] == ["setup_app", "resolve"]


def test_run_app_legacy_user_data_migration_path_runs_after_qapplication_setup(
    monkeypatch,
):
    from app import startup as startup_module

    call_order = []
    app = Mock()
    app.exec.return_value = 0
    monkeypatch.setattr(
        startup_module,
        "setup_app",
        lambda: call_order.append("setup_app") or app,
    )

    def _resolve_user_root():
        call_order.append("resolve")
        return "C:/Users/Test/AppData/Local/G3M"

    monkeypatch.setattr(
        startup_module,
        "resolve_user_data_root_with_migration",
        _resolve_user_root,
    )
    monkeypatch.setattr(
        startup_module, "configure_logging", lambda *_args: "g3m.log"
    )
    monkeypatch.setattr(
        startup_module, "install_crash_diagnostics", lambda *_args: ""
    )
    monkeypatch.setattr(startup_module, "install_process_exit_logging", Mock())
    monkeypatch.setattr(startup_module, "install_excepthook", Mock())
    monkeypatch.setattr(startup_module, "cleanup_old_temp_directories", Mock())
    monkeypatch.setattr(startup_module, "check_game_processes", lambda: None)
    monkeypatch.setattr(startup_module, "register_url_protocol", Mock())
    monkeypatch.setattr(startup_module.QLocalServer, "removeServer", Mock())

    class _Socket:
        def connectToServer(self, *_args, **_kwargs):  # noqa: N802
            return None

        def waitForConnected(self, *_args, **_kwargs):  # noqa: N802
            return False

    class _Coordinator:
        def __init__(self, **_kwargs) -> None:
            call_order.append("coordinator")

        def launch(self):
            call_order.append("launch")
            return None

    monkeypatch.setattr(startup_module, "QLocalSocket", _Socket)
    monkeypatch.setattr(startup_module, "BootstrapCoordinator", _Coordinator)

    assert startup_module.run_app(["--force-start"]) == 0
    assert call_order[:4] == ["setup_app", "resolve", "coordinator", "launch"]


def test_run_app_returns_error_when_qapplication_setup_fails(monkeypatch):
    from app import startup as startup_module

    call_order = []
    monkeypatch.setattr(
        startup_module,
        "resolve_user_data_root_with_migration",
        lambda: call_order.append("resolve") or "C:/Users/Test/AppData/Roaming/G3M",
    )
    monkeypatch.setattr(
        startup_module,
        "configure_logging",
        lambda *_args: call_order.append("logging") or "g3m.log",
    )
    monkeypatch.setattr(
        startup_module,
        "install_crash_diagnostics",
        lambda *_args: call_order.append("diagnostics"),
    )
    monkeypatch.setattr(startup_module, "install_process_exit_logging", Mock())
    monkeypatch.setattr(startup_module, "install_excepthook", Mock())
    monkeypatch.setattr(
        startup_module,
        "setup_app",
        Mock(side_effect=RuntimeError("qt setup failed")),
    )

    assert startup_module.run_app([]) == 1
    assert call_order == []


def test_process_exit_logging_writes_final_log_line(temp_dir, monkeypatch):
    from app import startup as startup_module

    registered = []
    log_path = startup_module.configure_logging("G3M", temp_dir)
    monkeypatch.setattr(
        startup_module.atexit,
        "register",
        lambda callback: registered.append(callback),
    )

    startup_module.install_process_exit_logging("G3M")
    registered[0]()

    with open(log_path, encoding="utf-8") as handle:
        log_text = handle.read()
    assert "G3M process exiting after" in log_text


def _connected_socket_factory():
    writes = []

    class _Socket:
        def __getattr__(self, name) -> object:
            if name in {"waitForConnected", "waitForBytesWritten"}:
                return lambda *_args, **_kwargs: True
            if name == "writeData":
                return lambda data: writes.append(data.decode("utf-8"))
            return lambda *_args, **_kwargs: None

    return _Socket, writes


def test_run_app_second_instance_activates_without_error_dialog(monkeypatch):
    from app import startup as startup_module

    socket_factory, writes = _connected_socket_factory()
    monkeypatch.setattr(startup_module, "setup_app", lambda: Mock())
    monkeypatch.setattr(startup_module, "QLocalSocket", socket_factory)

    with patch("app.startup.QMessageBox.warning") as warning:
        assert startup_module.run_app([]) == 0

    assert writes == [startup_module.SINGLE_INSTANCE_ACTIVATE]
    warning.assert_not_called()


def test_run_app_repeated_second_instances_activate_without_dialogs(monkeypatch):
    from app import startup as startup_module

    socket_factory, writes = _connected_socket_factory()
    monkeypatch.setattr(startup_module, "setup_app", lambda: Mock())
    monkeypatch.setattr(startup_module, "QLocalSocket", socket_factory)

    with patch("app.startup.QMessageBox.warning") as warning:
        assert startup_module.run_app([]) == 0
        assert startup_module.run_app([]) == 0

    assert writes == [
        startup_module.SINGLE_INSTANCE_ACTIVATE,
        startup_module.SINGLE_INSTANCE_ACTIVATE,
    ]
    warning.assert_not_called()


def test_run_app_protocol_handoff_does_not_show_duplicate_instance_error(monkeypatch):
    from app import startup as startup_module

    socket_factory, writes = _connected_socket_factory()
    monkeypatch.setattr(startup_module, "setup_app", lambda: Mock())
    monkeypatch.setattr(startup_module, "QLocalSocket", socket_factory)

    with patch("app.startup.QMessageBox.warning") as warning:
        assert startup_module.run_app(["g3m://https://example.com/mod.zip"]) == 0

    assert writes == ["g3m://https://example.com/mod.zip"]
    warning.assert_not_called()


def test_run_app_game_running_starts_with_external_process_state(monkeypatch):
    from app import startup as startup_module

    class _DisconnectedSocket:
        def connectToServer(self, *_args, **_kwargs):  # noqa: N802
            return None

        def waitForConnected(self, *_args, **_kwargs):  # noqa: N802
            return False

    created = {}

    class _Coordinator:
        def __init__(self, **kwargs) -> None:
            created.update(kwargs)

        def launch(self):
            return None

    app = Mock()
    app.exec.return_value = 0
    monkeypatch.setattr(startup_module, "setup_app", lambda: app)
    monkeypatch.setattr(startup_module, "QLocalSocket", _DisconnectedSocket)
    monkeypatch.setattr(startup_module.QLocalServer, "removeServer", Mock())
    monkeypatch.setattr(startup_module, "check_game_processes", lambda: "DELTARUNE")
    monkeypatch.setattr(startup_module, "register_url_protocol", Mock())
    monkeypatch.setattr(startup_module, "BootstrapCoordinator", _Coordinator)

    with patch("app.startup.QMessageBox.critical") as critical:
        assert startup_module.run_app([]) == 0

    critical.assert_not_called()
    assert created["initial_external_game_process"] == "DELTARUNE"


def test_main_routes_shortcut_without_startup(monkeypatch):
    """Checks that main routes shortcut without startup."""
    main_module = _load_main_module()

    calls = []
    resolve_root = Mock(side_effect=lambda **_kwargs: calls.append("resolve"))
    run_shortcut = Mock(side_effect=lambda *_args: calls.append("run"))
    monkeypatch.setitem(
        sys.modules,
        "bootstrap.user_data_bootstrap",
        types.SimpleNamespace(resolve_user_data_root_with_migration=resolve_root),
    )
    monkeypatch.setitem(
        sys.modules,
        "services.game_runner",
        types.SimpleNamespace(run_shortcut=run_shortcut),
    )

    assert main_module.main(["main.py", "--shortcut", "cfg"]) == 0
    resolve_root.assert_called_once_with(interactive=False)
    run_shortcut.assert_called_once_with("cfg")
    assert calls == ["resolve", "run"]


def test_main_shortcut_reports_unavailable_data_root(monkeypatch, capsys):
    main_module = _load_main_module()
    run_shortcut = Mock()
    monkeypatch.setitem(
        sys.modules,
        "bootstrap.user_data_bootstrap",
        types.SimpleNamespace(
            resolve_user_data_root_with_migration=Mock(
                side_effect=RuntimeError("configured drive is unavailable")
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "services.game_runner",
        types.SimpleNamespace(run_shortcut=run_shortcut),
    )

    assert main_module.main(["main.py", "--shortcut", "cfg"]) == 1
    assert "configured drive is unavailable" in capsys.readouterr().err
    run_shortcut.assert_not_called()


def test_main_shortcut_requires_argument(capsys):
    """Checks that main shortcut requires argument."""
    main_module = _load_main_module()

    assert main_module.main(["main.py", "--shortcut"]) == 2
    assert "--shortcut requires a config argument" in capsys.readouterr().err


def test_main_runs_startup_with_cleaned_argv(monkeypatch):
    """Checks that main runs startup with cleaned argv."""
    main_module = _load_main_module()

    cleanup_old_updater_files = Mock()
    run_app = Mock(return_value=7)
    monkeypatch.setitem(
        sys.modules,
        "utils.path_utils",
        types.SimpleNamespace(cleanup_old_updater_files=cleanup_old_updater_files),
    )
    monkeypatch.setitem(
        sys.modules, "app.startup", types.SimpleNamespace(run_app=run_app)
    )

    assert main_module.main(["main.py", "--force-start"]) == 7
    cleanup_old_updater_files.assert_called_once_with()
    run_app.assert_called_once_with(["--force-start"])


def test_main_prepares_process_runtime_before_startup(monkeypatch):
    """Checks that main prepares multiprocessing runtime before startup."""
    main_module = _load_main_module()

    call_order = []
    cleanup_old_updater_files = Mock(side_effect=lambda: call_order.append("cleanup"))
    run_app = Mock(side_effect=lambda _: call_order.append("run_app") or 0)
    freeze_support = Mock(side_effect=lambda: call_order.append("freeze_support"))
    monkeypatch.setattr(main_module.multiprocessing, "freeze_support", freeze_support)
    monkeypatch.setitem(
        sys.modules,
        "utils.path_utils",
        types.SimpleNamespace(cleanup_old_updater_files=cleanup_old_updater_files),
    )
    monkeypatch.setitem(
        sys.modules, "app.startup", types.SimpleNamespace(run_app=run_app)
    )

    assert main_module.main(["main.py"]) == 0
    freeze_support.assert_called_once_with()
    cleanup_old_updater_files.assert_called_once_with()
    run_app.assert_called_once_with([])
    assert call_order == ["freeze_support", "cleanup", "run_app"], (
        f"Expected freeze_support to be called first, got: {call_order}"
    )


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
    """Checks that finalizing window reveal closes splash after front refresh."""
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


def test_finalize_window_reveal_restores_hidden_window_before_closing_splash():
    """Checks that finalize window reveal restores hidden window before closing splash."""
    from PyQt6.QtCore import Qt

    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    instance = Mock()
    instance.isVisible.return_value = False
    instance.windowState.return_value = Qt.WindowState.WindowNoState
    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = instance

    with (
        patch.object(coordinator, "_close_splash") as close_splash,
        patch.object(coordinator, "_bring_launcher_to_front") as bring_to_front,
    ):
        coordinator._finalize_window_reveal()

    instance.show.assert_called()
    close_splash.assert_called_once_with()
    bring_to_front.assert_called_once_with()


def test_finalize_window_reveal_restores_hidden_maximized_window_as_maximized():
    """Checks that saved maximized startup state is not downgraded to normal."""
    from PyQt6.QtCore import Qt

    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    instance = Mock()
    instance.isVisible.return_value = False
    instance.windowState.return_value = Qt.WindowState.WindowMaximized
    instance.settings_service.was_window_maximized.return_value = True
    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = instance

    with (
        patch.object(coordinator, "_close_splash"),
        patch.object(coordinator, "_bring_launcher_to_front"),
    ):
        coordinator._finalize_window_reveal()

    instance.showMaximized.assert_called_once_with()
    instance.showNormal.assert_not_called()


def test_verify_window_visible_after_reveal_closes_splash_once_window_is_visible():
    """Checks that reveal verification closes splash when main window is visible."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    splash = Mock()
    splash.isVisible.return_value = True
    instance = Mock()
    instance.isVisible.return_value = True
    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = instance
    coordinator.splash = splash

    with patch.object(coordinator, "_close_splash") as close_splash:
        coordinator._verify_window_visible_after_reveal()

    close_splash.assert_called_once_with()


def test_abort_stuck_startup_shows_error_and_quits_when_window_never_appears():
    """Checks that stuck startup aborts instead of lingering invisibly."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    app = Mock()
    splash = Mock()
    instance = Mock()
    instance.isVisible.return_value = False
    coordinator = BootstrapCoordinator(
        app=app,
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = instance
    coordinator.splash = splash

    with patch("bootstrap.bootstrap_coordinator.QMessageBox.critical") as critical:
        coordinator._abort_stuck_startup()

    splash.close.assert_called_once_with()
    critical.assert_called_once()
    app.quit.assert_called_once_with()


def test_abort_stuck_startup_quits_when_error_dialog_fails():
    """Checks that a broken stuck-startup dialog still exits via app.quit."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    app = Mock()
    splash = Mock()
    instance = Mock()
    instance.isVisible.return_value = False
    coordinator = BootstrapCoordinator(
        app=app,
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(),
    )
    coordinator.instance = instance
    coordinator.splash = splash

    with patch(
        "bootstrap.bootstrap_coordinator.QMessageBox.critical",
        side_effect=RuntimeError("critical dialog deleted"),
    ):
        coordinator._abort_stuck_startup()

    splash.close.assert_called_once_with()
    app.quit.assert_called_once_with()


def test_bootstrap_startup_error_exits_even_if_error_dialog_fails():
    """Checks that startup error dialogs cannot replace the controlled exit."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    splash = Mock()

    def create_window(*_args, **_kwargs):
        raise RuntimeError("window failed")

    def fail_critical(*_args, **_kwargs):
        raise RuntimeError("dialog failed")

    coordinator = BootstrapCoordinator(
        app=Mock(),
        user_root="",
        initial_url=None,
        window_factory=create_window,
        server_factory=Mock(),
    )
    coordinator.splash = splash

    with (
        patch("bootstrap.bootstrap_coordinator.QMessageBox.critical", fail_critical),
        pytest.raises(SystemExit) as exc_info,
    ):
        coordinator._create_launcher()

    assert exc_info.value.code == 1
    splash.close.assert_called_once_with()


def test_bootstrap_server_collision_quits_without_error_dialog():
    """A late second-instance race exits quietly after losing the server claim."""
    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    app = Mock()
    splash = Mock()
    server = Mock()
    server.listen.return_value = False
    coordinator = BootstrapCoordinator(
        app=app,
        user_root="",
        initial_url=None,
        window_factory=Mock(),
        server_factory=Mock(return_value=server),
    )
    coordinator.splash = splash

    with (
        patch("bootstrap.bootstrap_coordinator.QMessageBox.critical") as critical,
        patch("bootstrap.bootstrap_coordinator.QTimer.singleShot") as single_shot,
    ):
        coordinator._create_launcher()

    splash.close.assert_called_once_with()
    single_shot.assert_called_once_with(0, app.quit)
    critical.assert_not_called()


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

    with patch(
        "bootstrap.bootstrap_coordinator._audio_service.play_g3m_sound"
    ) as play_sound:
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

    with patch(
        "bootstrap.bootstrap_coordinator._audio_service.play_g3m_sound"
    ) as play_sound:
        coordinator._play_startup_sound()

    play_sound.assert_called_once_with()


def test_network_init_thread_emits_offline_when_connectivity_check_fails(qapp):
    """Checks that network init failures do not kill the startup worker."""
    from bootstrap import bootstrap_coordinator as bootstrap_module

    app_state = Mock()
    thread = bootstrap_module._NetworkInitThread(app_state)
    emissions = []
    thread.done.connect(lambda has_internet, settings: emissions.append((has_internet, settings)))

    with patch(
        "bootstrap.bootstrap_coordinator.check_internet_connection",
        side_effect=OSError("network probe failed"),
    ):
        thread.run()

    assert emissions == [(False, {})]


def test_show_launcher_window_schedules_post_show_after_reveal_delay():
    """Checks that showing launcher window schedules post show after reveal delay."""
    from PyQt6.QtCore import Qt

    from bootstrap.bootstrap_coordinator import BootstrapCoordinator

    app = Mock()
    instance = Mock()
    instance.app_state = types.SimpleNamespace(
        game_is_running=False, is_shown_to_user=False
    )
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
        patch.object(
            coordinator,
            "_play_startup_sound",
            side_effect=lambda: order.append("sound"),
        ) as play_sound,
        patch.object(
            coordinator,
            "_bring_launcher_to_front",
            side_effect=lambda: order.append("front"),
        ) as bring_to_front,
        patch(
            "bootstrap.bootstrap_coordinator.QApplication.instance", return_value=app
        ),
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
        (
            (
                coordinator._WINDOW_VISIBILITY_GRACE_MS,
                coordinator._verify_window_visible_after_reveal,
            ),
        ),
    ]


def test_startup_window_creation_smoke(qapp, tmp_path):
    """Checks that startup window creation smoke."""
    from app.window import AppWindow

    user_root = tmp_path / "user"
    profiles_dir = tmp_path / "profiles"
    themes_dir = tmp_path / "themes"
    for path in (user_root, profiles_dir, themes_dir):
        path.mkdir(parents=True, exist_ok=True)
    mock_presence_response = Mock()
    mock_presence_response.status_code = 200
    mock_presence_response.json.return_value = {"online": 0}
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
            "workers.presence_worker.cloud_function_request",
            return_value=mock_presence_response,
        ),
    ):
        window = AppWindow()
        try:
            assert window is not None
            assert window.windowTitle() == "G3M"
        finally:
            window.close()


def _test_startup_with_archive(
    archive_path: pathlib.Path,
    startup_target: str,
    launch_target: pathlib.Path | None = None,
) -> bool:
    try:
        archive_parent = archive_path.resolve().parent
        with tempfile.TemporaryDirectory(dir=archive_parent) as extract_dir:
            extract_path = pathlib.Path(extract_dir)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_path)

            target = extract_path / startup_target
            if not target.exists():
                sys.stderr.write(f"Startup target not found: {target}\n")
                return False
            target_to_run = launch_target or target
            if not target_to_run.is_file():
                sys.stderr.write(f"Startup launch target not found: {target_to_run}\n")
                return False

            if platform.system() != "Windows":
                target_to_run.chmod(target_to_run.stat().st_mode | 0o111)
            cwd = str(extract_path)

            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"

            if startup_target.endswith(".py"):
                result = subprocess.run(
                    [sys.executable, str(target_to_run), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=cwd,
                    env=env,
                )
                output = (result.stdout or "") + (result.stderr or "")
            else:
                returncode, output = _run_packaged_binary_smoke(
                    target_to_run, cwd, env
                )
            if startup_target.endswith(".py") and result.returncode != 0:
                sys.stderr.write(
                    f"Startup command failed for {startup_target} with code {result.returncode}\n"
                )
                sys.stderr.write(output)
                return False
            if not startup_target.endswith(".py") and returncode != 0:
                sys.stderr.write(
                    f"Startup command failed for {startup_target} with code {returncode}\n"
                )
                sys.stderr.write(output)
                return False
            if _contains_startup_errors(output):
                sys.stderr.write(f"Startup error markers found for {startup_target}\n")
                sys.stderr.write(output)
                return False
            return True

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

    launch_target = os.environ.get("STARTUP_LAUNCH_TARGET")
    success = _test_startup_with_archive(
        archive_path,
        startup_target,
        pathlib.Path(launch_target).resolve() if launch_target else None,
    )
    if not success:
        sys.stderr.write(f"Startup test failed for {startup_target}\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
