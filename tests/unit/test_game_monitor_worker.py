"""Unit tests for game process monitor worker."""

from unittest.mock import Mock, patch

from workers.game_monitor_worker import GameMonitorWorker


def test_monitor_waits_long_enough_for_wrapped_process_to_spawn_game(qapp):
    """Checks that wrapper process exit does not end monitoring before game appears."""
    process = Mock(pid=1234)
    checks = [False] * 12 + [True, True, True, False, False]
    seen_checks = []

    def fake_is_game_running(_pid=None):
        seen_checks.append(True)
        return checks.pop(0) if checks else False

    worker = GameMonitorWorker(process, False)
    finished = []
    worker.finished.connect(lambda vanilla: finished.append(vanilla))

    with (
        patch("workers.game_monitor_worker.is_game_running", fake_is_game_running),
        patch("workers.game_monitor_worker.time.sleep"),
    ):
        worker.run()

    assert len(seen_checks) > 12
    assert finished == [False]


def test_monitor_keeps_session_open_while_game_keeps_running(qapp):
    process = Mock(pid=1234)
    checks = [True, True] + [True] * 120 + [False, False]
    seen_checks = []

    def fake_is_game_running(_pid=None):
        seen_checks.append(True)
        return checks.pop(0) if checks else False

    worker = GameMonitorWorker(process, False)
    finished = []
    worker.finished.connect(lambda vanilla: finished.append(vanilla))

    with (
        patch("workers.game_monitor_worker.is_game_running", fake_is_game_running),
        patch("workers.game_monitor_worker.time.sleep"),
    ):
        worker.run()

    assert len(seen_checks) > 100
    assert finished == [False]


def test_monitor_suppresses_finished_emit_failure(qapp, caplog):
    """Checks that monitor completion cannot crash if the receiver is gone."""

    class _FailingSignal:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError("receiver deleted")

    worker = GameMonitorWorker(None, False)
    worker.finished = _FailingSignal()

    with (
        patch("workers.game_monitor_worker.is_game_running", return_value=False),
        patch("workers.game_monitor_worker.time.sleep"),
    ):
        worker.run()

    assert "GameMonitorWorker: failed to emit" in caplog.text
