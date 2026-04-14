import time
from types import SimpleNamespace
from unittest.mock import patch

from services.analytics_service import AnalyticsService


class _Response:
    status_code = 200


def test_analytics_service_respects_opt_in_and_flushes_batch(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    service.count("always_event")
    service.count("opt_event", scope="opt_in")
    assert any(key.startswith("always_event") for key in service._always_on)
    assert not service._opt_in

    service.set_opt_in_enabled(True)
    service.count("opt_event", scope="opt_in")
    assert any(key.startswith("opt_event") for key in service._opt_in)

    with patch("services.analytics_service.cloud_function_request", return_value=_Response()) as request:
        assert service.flush(force=True) is False
        deadline = time.time() + 2
        while service._upload_thread is not None and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

    assert request.call_count == 1
    assert service._pending == []
    assert not service._always_on
    assert not service._opt_in


def test_analytics_service_records_mods_browser_search_bucket(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    service.record_mods_browser_search("roaring edition")

    assert any(
        key.startswith("search_mods_browser") and "query_len=13_plus" in key
        for key in service._always_on
    )


def test_analytics_service_records_single_character_mods_browser_search_bucket(
    qapp, tmp_path
):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    service.record_mods_browser_search("a")

    assert any(
        key.startswith("search_mods_browser") and "query_len=1" in key
        for key in service._always_on
    )


def test_analytics_service_does_not_persist_local_counters_between_instances(qapp, tmp_path):
    app_state = SimpleNamespace(
        local_config={
            "language": "en",
            "ui_scale": 1.0,
            "analytics_opt_in_enabled": True,
        }
    )
    service = AnalyticsService(app_state)

    service.record_launch_started(
        mode="subprocess",
        with_mods=True,
        game="deltarune",
        mod_count=2,
        mod_refs=[{"ref": "gb_mod_123", "name": "Roaring Patch"}],
    )
    restored = AnalyticsService(app_state)

    assert not any(key.startswith("game_launch_started") for key in restored._always_on)
    assert not any(key.startswith("launch_mod_selected") for key in restored._opt_in)


def test_analytics_service_keeps_stable_pending_payload_ids_in_memory(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    service.count("always_event")
    service._enqueue_session_payload()
    first_payload_id = service._pending[0]["id"]

    recomputed_id = service._payload_id(service._pending[0])
    assert recomputed_id == first_payload_id


def test_analytics_service_never_creates_analytics_dir(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    service.count("always_event")
    service._save_state()

    assert not (tmp_path / "analytics").exists()


def test_analytics_service_records_download_use_completion_details(qapp, tmp_path):
    app_state = SimpleNamespace(
        local_config={
            "language": "en",
            "ui_scale": 1.0,
            "analytics_opt_in_enabled": True,
        }
    )
    service = AnalyticsService(app_state)
    record = SimpleNamespace(
        id="rec1",
        source_kind="gamebanana",
        target_kind="mod",
        auto_use=True,
        delete_after_use=False,
        download_status="downloaded",
        use_status="ready_to_use",
        ever_installed=True,
        bytes_total=12_000_000,
        bytes_received=12_000_000,
        metadata={
            "game": "deltarune",
            "gb_mod_id": 123,
            "item_type": "mod",
            "name": "Roaring Patch",
            "gb_file_id": 456,
            "file_name": "roaring_patch.zip",
            "compatibility": "g3m",
            "category": "Gameplay",
        },
    )

    service._on_download_record_updated(record)

    assert any(key.startswith("use_completed") for key in service._always_on)
    assert any(
        key.startswith("use_completed_detail") and "ref=gb_mod_123" in key
        for key in service._opt_in
    )


def test_analytics_service_shutdown_waits_for_upload_completion(qapp, tmp_path, monkeypatch):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)
    service.count("always_event")
    wait_calls = []
    real_wait_for_upload_shutdown = service._wait_for_upload_shutdown

    def tracked_wait(timeout_ms=1500):
        wait_calls.append(timeout_ms)
        return real_wait_for_upload_shutdown(timeout_ms)

    monkeypatch.setattr(service, "_wait_for_upload_shutdown", tracked_wait)

    with patch("services.analytics_service.cloud_function_request", return_value=_Response()):
        service.shutdown()

    assert wait_calls == [1500]
    assert service._upload_thread is None


def test_analytics_service_shutdown_uses_less_aggressive_fallback_timeout(
    qapp, tmp_path, monkeypatch
):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    class _StuckThread:
        def wait(self, _timeout):
            return False

        def isRunning(self):  # noqa: N802
            return True

    service._upload_thread = _StuckThread()
    fallback_calls = []
    monkeypatch.setattr(
        "services.analytics_service.safe_stop_thread",
        lambda thread, timeout, blocking: fallback_calls.append(
            (thread, timeout, blocking)
        ),
    )

    service._wait_for_upload_shutdown(timeout_ms=0)

    assert fallback_calls == [(service._upload_thread, 750, True)]


def test_analytics_service_shutdown_async_completes_immediately_when_idle(
    qapp, tmp_path
):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)
    callbacks = []

    with patch("services.analytics_service.cloud_function_request", return_value=_Response()):
        done = service.shutdown_async(lambda: callbacks.append("done"))

        assert done is False
        deadline = time.time() + 2
        while not callbacks and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

    assert callbacks == ["done"]


def test_analytics_service_shutdown_async_defers_callback_until_upload_finishes(
    qapp, tmp_path
):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)
    service.count("always_event")
    callbacks = []

    with patch(
        "services.analytics_service.cloud_function_request", return_value=_Response()
    ):
        done = service.shutdown_async(lambda: callbacks.append("done"))
        assert done is False
        deadline = time.time() + 2
        while not callbacks and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

    assert callbacks == ["done"]
