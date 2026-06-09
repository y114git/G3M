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
