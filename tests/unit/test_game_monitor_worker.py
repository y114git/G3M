"""Unit tests for game process monitor worker."""

from unittest.mock import Mock, patch

from services.game_detection_service import GameProcessTracker
from workers.game_monitor_worker import GameMonitorWorker


def test_monitor_waits_long_enough_for_wrapped_process_to_spawn_game(qapp):
    """Checks that wrapper process exit does not end monitoring before game appears."""
    process = Mock(pid=1234)
    checks = [False] * 12 + [True, True, False, False, False, False]
    seen_checks = []

    def fake_refresh():
        seen_checks.append(True)
        return checks.pop(0) if checks else False

    with patch("workers.game_monitor_worker.GameProcessTracker"):
        worker = GameMonitorWorker(process, False)
    worker._refresh_tracked_processes = fake_refresh
    finished = []
    worker.finished.connect(lambda vanilla: finished.append(vanilla))

    with patch("workers.game_monitor_worker.time.sleep"):
        worker.run()

    assert len(seen_checks) > 12
    assert finished == [False]
    process.wait.assert_not_called()


def test_monitor_restores_promptly_after_confirmed_exit(qapp):
    process = Mock(pid=1234)
    with patch("workers.game_monitor_worker.GameProcessTracker"):
        worker = GameMonitorWorker(process, False)
    worker._refresh_tracked_processes = Mock(
        side_effect=[True, False, False, False, False]
    )
    finished = []
    sleeps = []
    worker.finished.connect(lambda vanilla: finished.append(vanilla))

    with patch(
        "workers.game_monitor_worker.time.sleep",
        side_effect=lambda seconds: sleeps.append(seconds),
    ):
        worker.run()

    assert finished == [False]
    assert sleeps == [worker._POLL_INTERVAL_SECONDS] * 3
    process.wait.assert_not_called()


def test_monitor_keeps_session_open_while_game_keeps_running(qapp):
    process = Mock(pid=1234)
    checks = [True] + [True] * 120 + [False] * 4
    seen_checks = []

    def fake_refresh():
        seen_checks.append(True)
        return checks.pop(0) if checks else False

    with patch("workers.game_monitor_worker.GameProcessTracker"):
        worker = GameMonitorWorker(process, False)
    worker._refresh_tracked_processes = fake_refresh
    finished = []
    worker.finished.connect(lambda vanilla: finished.append(vanilla))

    sleeps = []
    with patch(
        "workers.game_monitor_worker.time.sleep",
        side_effect=sleeps.append,
    ):
        worker.run()

    assert len(seen_checks) > 100
    assert finished == [False]
    assert sleeps.count(worker._RUNNING_POLL_INTERVAL_SECONDS) == 120
    assert sleeps.count(worker._POLL_INTERVAL_SECONDS) == 3


def test_monitor_suppresses_finished_emit_failure(qapp, caplog):
    """Checks that monitor completion cannot crash if the receiver is gone."""

    class _FailingSignal:
        def emit(self, *_args, **_kwargs):
            raise RuntimeError("receiver deleted")

    with patch("workers.game_monitor_worker.GameProcessTracker"):
        worker = GameMonitorWorker(None, False)
    worker.finished = _FailingSignal()
    worker._refresh_tracked_processes = Mock(return_value=False)

    with patch("workers.game_monitor_worker.time.sleep"):
        worker.run()

    assert "GameMonitorWorker: failed to emit" in caplog.text


def test_monitor_ignores_preexisting_matching_process(qapp):
    existing = (100, 1.0)
    new_game = (200, 2.0)
    with (
        patch(
            "services.game_detection_service.get_matching_process_identities",
            side_effect=[{existing}, {existing, new_game}],
        ),
        patch(
            "services.game_detection_service.get_process_tree_identities",
            return_value=set(),
        ),
    ):
        tracker = GameProcessTracker(None, ("DELTARUNE.exe",))
        assert tracker.discover() == {new_game}


def test_monitor_keeps_child_after_launcher_handoff(qapp):
    launcher = (100, 1.0)
    game = (200, 2.0)
    with (
        patch(
            "services.game_detection_service.get_matching_process_identities",
            return_value=set(),
        ),
        patch(
            "services.game_detection_service.get_process_tree_identities",
            side_effect=[{launcher, game}, set()],
        ),
        patch(
            "services.game_detection_service.is_process_identity_running",
            side_effect=lambda identity: identity == game,
        ),
    ):
        tracker = GameProcessTracker(100, ("DELTARUNE.exe",))
        assert tracker.refresh() is True
        assert tracker.tracked == {game}


def test_monitor_uses_known_process_names_when_none_are_supplied():
    game = (200, 2.0)
    with (
        patch(
            "services.game_detection_service.get_all_process_names",
            return_value=("game.exe",),
        ),
        patch(
            "services.game_detection_service.get_matching_process_identities",
            side_effect=[set(), {game}],
        ) as matching,
        patch(
            "services.game_detection_service.get_process_tree_identities",
            return_value=set(),
        ),
    ):
        tracker = GameProcessTracker(None, ())

        assert tracker.discover() == {game}
        assert matching.call_args_list[0].args == (("game.exe",),)
        assert matching.call_args_list[1].args == (("game.exe",),)
