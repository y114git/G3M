"""Unit tests for test presence worker."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from workers.presence_worker import PresenceWorker


def test_presence_worker_keeps_last_known_online_count_on_network_error():
    worker = PresenceWorker("session-1", SimpleNamespace(has_internet=True))
    emitted = []
    worker.update_online_count.connect(emitted.append)

    ok_response = Mock()
    ok_response.status_code = 200
    ok_response.json.return_value = {"online": 17}

    with patch("workers.presence_worker.cloud_function_request", return_value=ok_response):
        worker.run()

    worker._last_heartbeat_at = 0.0
    worker._last_sync_at = 0.0

    with patch(
        "workers.presence_worker.cloud_function_request",
        side_effect=__import__("requests").Timeout("timeout"),
    ):
        worker.run()

    assert emitted == [17, 17]


def test_presence_worker_reports_question_mark_until_first_success():
    worker = PresenceWorker("session-1", SimpleNamespace(has_internet=True))
    emitted = []
    worker.update_online_count.connect(emitted.append)

    with patch("workers.presence_worker.cloud_function_request", return_value=None):
        worker.run()

    assert emitted == [-1]
    assert worker._last_sync_at == 0.0


def test_presence_worker_retries_read_without_heartbeat_after_rate_limit():
    worker = PresenceWorker("session-1", SimpleNamespace(has_internet=True))
    emitted = []
    worker.update_online_count.connect(emitted.append)
    limited = Mock(status_code=429)
    successful = Mock(status_code=200)
    successful.json.return_value = {"online": 23}

    with patch(
        "workers.presence_worker.cloud_function_request",
        side_effect=[limited, successful],
    ) as request:
        worker.run()

    assert [call.kwargs["json"] for call in request.call_args_list] == [
        {"sessionId": "session-1"},
        {},
    ]
    assert emitted == [23]
    assert worker._last_heartbeat_at == 0.0


def test_presence_worker_syncs_often_but_heartbeats_sparsely():
    worker = PresenceWorker("session-1", SimpleNamespace(has_internet=True))
    responses = []
    settings = []
    worker.global_settings_received.connect(settings.append)

    response = Mock()
    response.status_code = 200
    response.json.return_value = {"online": 5, "globals": {"version": 2}}

    with (
        patch(
            "workers.presence_worker.cloud_function_request",
            return_value=response,
        ) as request,
        patch("workers.presence_worker.time.time", side_effect=[2000, 2300]),
    ):
        worker.run()
        worker.run()
        responses.extend(call.kwargs["json"] for call in request.call_args_list)

    assert responses == [{"sessionId": "session-1"}, {}]
    assert settings == [{"version": 2}, {"version": 2}]


def test_presence_worker_logs_unexpected_heartbeat_error_without_crashing():
    worker = PresenceWorker("session-1", SimpleNamespace(has_internet=True))
    emitted = []
    worker.update_online_count.connect(emitted.append)

    with patch(
        "workers.presence_worker.cloud_function_request",
        side_effect=RuntimeError("firebase failed"),
    ):
        worker.run()

    assert emitted == [-1]
