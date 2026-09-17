"""Exercise process exit and restoration through the Qt event loop."""

import subprocess
import sys
import time

from PyQt6.QtCore import QObject

from services.backup_service import BackupManager
from services.launch_service import GameLauncher
from services.launch_transaction import LaunchState
from services.mod.service import ModManager
from utils.file_utils import load_json, save_json
from workers.game_monitor_worker import GameMonitorWorker


def test_repeated_process_exit_restores_files(
    qtbot, app_state, feedback_service, tmp_path, monkeypatch
):
    monkeypatch.setattr(GameMonitorWorker, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(GameMonitorWorker, "_RUNNING_POLL_INTERVAL_SECONDS", 0.01)
    parent = QObject()
    mod_service = ModManager(app_state, feedback_service)
    parent.mod_service = mod_service
    launcher = GameLauncher(app_state, feedback_service, mod_service, parent)
    target = tmp_path / "data.win"
    target.write_bytes(b"ORIGINAL")
    completed = []
    launcher.game_launch_finished.connect(lambda: completed.append(True))

    for run in range(3):
        save_json(app_state.mods_metadata_path, {"mod": None})
        launcher._launch_mod_ids = ["mod"]
        launcher._launch_started_at = time.monotonic()
        manager = BackupManager(str(tmp_path / f"backup-{run}"))
        launcher.mod_patcher.backup_service = manager
        assert manager.backup_file("undertale", str(target))
        target.write_bytes(f"MOD-{run}".encode())
        assert manager.save_backups_to_manifest(str(tmp_path / "session.lock"))
        assert manager.capture_deployed_state()
        launcher.launch_transaction.begin()
        launcher.launch_transaction.mark_launching()
        launcher.launch_transaction.mark_running()
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            launcher._game_process = process
            launcher._start_game_monitor(process, False, (), set())
            qtbot.waitUntil(lambda: launcher.monitor_thread.isRunning())
            qtbot.wait(100)
            process.terminate()
            process.wait(timeout=5)
            qtbot.waitUntil(
                lambda expected=run + 1: len(completed) == expected, timeout=5000
            )
            assert target.read_bytes() == b"ORIGINAL"
            assert launcher.launch_transaction.state == LaunchState.COMPLETED
            assert launcher.monitor_thread is None
            assert app_state.is_patching is False
            assert not (tmp_path / "session.lock").exists()
            assert load_json(app_state.mods_metadata_path) == {"mod": None}
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            launcher._stop_monitor_thread()
