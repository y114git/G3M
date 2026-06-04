import base64
import gzip
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.analytics_service import AnalyticsService, _AnalyticsUploadWorker


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


def test_analytics_service_records_mods_browser_search_opt_in_detail(qapp, tmp_path):
    app_state = SimpleNamespace(
        local_config={
            "language": "en",
            "ui_scale": 1.0,
            "analytics_opt_in_enabled": True,
        }
    )
    service = AnalyticsService(app_state)

    service.record_mods_browser_search("roaring edition")

    assert any(
        key.startswith("search_mods_browser_detail")
        and "area=mods_browser" in key
        and "query_len=13_plus" in key
        for key in service._opt_in
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
    first_payload_id = service._pending[0]["batch_id"]

    recomputed_id = service._payload_id(service._pending[0])
    assert recomputed_id == first_payload_id


def test_analytics_service_uploads_analytics_payload(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)
    service.count("always_event", area="test")

    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        encoded = kwargs["json"]["payload"]
        captured["payload"] = json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8"))
        return _Response()

    with patch("services.analytics_service.cloud_function_request", side_effect=fake_request):
        service.flush(force=True)
        deadline = time.time() + 2
        while service._upload_thread is not None and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

    assert captured["method"] == "post"
    assert captured["url"].endswith("/ingestAnalytics")
    assert captured["payload"]["schema"] == 1
    assert captured["payload"]["batch_id"]
    assert any(event["name"] == "always_event" for event in captured["payload"]["always"])


def test_analytics_upload_worker_preserves_session_context_when_merging(qapp):
    payloads = [
        {
            "schema": 1,
            "batch_id": "batch-a",
            "client": {"app_version": "1", "os_family": "windows"},
            "session": {"id": "session-a", "opt_in": True},
            "always": [{"name": "event_a", "ts": 1, "dims": {}, "value": 1}],
            "opt_in": [],
        },
        {
            "schema": 1,
            "batch_id": "batch-b",
            "client": {"app_version": "2", "os_family": "linux"},
            "session": {"id": "session-b", "opt_in": True},
            "always": [{"name": "event_b", "ts": 2, "dims": {}, "value": 1}],
            "opt_in": [],
        },
    ]
    captured = []

    def fake_request(_method, _url, **kwargs):
        encoded = kwargs["json"]["payload"]
        captured.append(
            json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8"))
        )
        return _Response()

    with patch("services.analytics_service.cloud_function_request", side_effect=fake_request):
        _AnalyticsUploadWorker(payloads).run()

    assert len(captured) == 1
    assert [item["session"]["id"] for item in captured[0]["batches"]] == [
        "session-a",
        "session-b",
    ]
    assert [item["client"]["os_family"] for item in captured[0]["batches"]] == [
        "windows",
        "linux",
    ]
    assert [item["always"][0]["name"] for item in captured[0]["batches"]] == [
        "event_a",
        "event_b",
    ]


def test_analytics_service_never_creates_analytics_dir(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)

    service.count("always_event")
    service._save_state()

    assert not (tmp_path / "analytics").exists()


def test_analytics_service_restores_pending_payloads(qapp, tmp_path):
    app_state = SimpleNamespace(
        local_config={"language": "en", "ui_scale": 1.0},
        config_dir=str(tmp_path),
    )
    service = AnalyticsService(app_state)
    service.count("always_event")
    service._enqueue_session_payload()

    restored = AnalyticsService(app_state)

    assert restored._pending
    assert restored._pending[0]["schema"] == 1
    assert restored._pending[0]["batch_id"] == service._pending[0]["batch_id"]


def test_analytics_service_filters_saved_pending_before_trimming(qapp, tmp_path, monkeypatch):
    app_state = SimpleNamespace(
        local_config={"language": "en", "ui_scale": 1.0},
        config_dir=str(tmp_path),
    )
    state_path = tmp_path / "analytics_pending.json"
    state_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "pending": [
                    {"schema": 1, "batch_id": "old-valid", "always": [{"name": "a"}]},
                    {"schema": 0, "batch_id": "invalid-a"},
                    {"schema": 0, "batch_id": "invalid-b"},
                    {"schema": 1, "batch_id": "new-valid", "always": [{"name": "b"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AnalyticsService, "_MAX_PENDING_PAYLOADS", 2)

    restored = AnalyticsService(app_state)

    assert [payload["batch_id"] for payload in restored._pending] == [
        "old-valid",
        "new-valid",
    ]


def test_analytics_service_timezone_bucket_preserves_fractional_offsets(qapp, monkeypatch):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)
    monkeypatch.setattr("services.analytics_service.time.timezone", -(5 * 3600 + 30 * 60))
    monkeypatch.setattr("services.analytics_service.time.daylight", 0)

    assert service._timezone_bucket() == "utc_plus_5_30"


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


def test_analytics_service_records_safe_opt_in_details_for_generic_actions(
    qapp, tmp_path
):
    app_state = SimpleNamespace(
        local_config={
            "language": "en",
            "ui_scale": 1.0,
            "analytics_opt_in_enabled": True,
        }
    )
    service = AnalyticsService(app_state)

    service.mark_ui_ready()
    service.record_dialog_opened("downloads")
    service.record_profile_switched()
    service.record_setting_changed("analytics_opt_in_enabled", True)
    service.record_update_check("available")
    service.record_plugin_imported(source="catalog")
    service.record_local_import(
        source="file",
        outcome="completed",
        file_ext="zip",
        merged=True,
        manual=False,
    )

    assert any(key.startswith("app_ready_detail|startup=") for key in service._opt_in)
    assert any(
        key.startswith("dialog_opened_detail|name=downloads") for key in service._opt_in
    )
    assert any(key.startswith("profile_switched_detail") for key in service._opt_in)
    assert any(
        key.startswith("setting_changed_detail")
        and "name=analytics_opt_in_enabled" in key
        and "state=on" in key
        for key in service._opt_in
    )
    assert any(
        key.startswith("update_check_detail|outcome=available") for key in service._opt_in
    )
    assert any(
        key.startswith("plugin_imported_detail|source=catalog") for key in service._opt_in
    )
    assert any(
        key.startswith("local_import_detail")
        and "source=file" in key
        and "outcome=completed" in key
        and "ext=zip" in key
        for key in service._opt_in
    )


def test_analytics_service_records_mod_and_plugin_action_details(qapp, tmp_path):
    app_state = SimpleNamespace(
        local_config={
            "language": "en",
            "ui_scale": 1.0,
            "analytics_opt_in_enabled": True,
        }
    )
    service = AnalyticsService(app_state)
    mod = {
        "id": "gb_mod_123",
        "name": "Roaring Patch",
        "game": "deltarune",
        "gamebanana_category": "Gameplay",
    }
    plugin = {
        "id": "plugin.demo",
        "name": "Demo Plugin",
        "version": "1.2.3",
        "source": "catalog",
    }

    service.record_mod_export_requested(mod)
    service.record_mod_folder_opened(mod)
    service.record_mod_homepage_opened(mod)
    service.record_plugin_details_opened(plugin)

    assert any(
        key.startswith("mod_export_requested") and "game=deltarune" in key
        for key in service._always_on
    )
    assert any(
        key.startswith("mod_export_requested_detail")
        and "ref=gb_mod_123" in key
        for key in service._opt_in
    )
    assert any(
        key.startswith("mod_folder_opened_detail") and "ref=gb_mod_123" in key
        for key in service._opt_in
    )
    assert any(
        key.startswith("mod_homepage_opened_detail") and "ref=gb_mod_123" in key
        for key in service._opt_in
    )
    assert any(key.startswith("plugin_details_opened") for key in service._always_on)
    assert any(
        key.startswith("plugin_details_opened_detail")
        and "plugin_id=plugin_demo" in key
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


def test_analytics_service_keeps_upload_thread_until_thread_finished(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state)
    service.count("always_event")
    callbacks = []

    with patch(
        "services.analytics_service.cloud_function_request", return_value=_Response()
    ):
        service.shutdown_async(lambda: callbacks.append("done"))
        deadline = time.time() + 2
        while service._upload_worker is not None and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert service._upload_thread is not None
        assert callbacks == []

        while not callbacks and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

    assert callbacks == ["done"]
    assert service._upload_thread is None


def test_analytics_upload_worker_uses_dedicated_session_and_bounded_timeout(qapp):
    payload = {
        "schema": 1,
        "batch_id": "batch-a",
        "client": {"app_version": "1", "os_family": "windows"},
        "session": {"id": "session-a", "opt_in": True},
        "always": [{"name": "event_a", "ts": 1, "dims": {}, "value": 1}],
        "opt_in": [],
    }
    session = Mock()

    with (
        patch("services.analytics_service.requests.Session", return_value=session),
        patch(
            "services.analytics_service.cloud_function_request", return_value=_Response()
        ) as request_call,
    ):
        _AnalyticsUploadWorker([payload]).run()

    request_call.assert_called_once()
    assert request_call.call_args.kwargs["session"] is session
    assert (
        request_call.call_args.kwargs["timeout"]
        == _AnalyticsUploadWorker._REQUEST_TIMEOUT_SECONDS
    )
    session.close.assert_called_once_with()
