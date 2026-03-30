import time
from types import SimpleNamespace
from unittest.mock import patch

from services.analytics_service import AnalyticsService


class _Response:
    status_code = 200


def test_analytics_service_respects_opt_in_and_flushes_batch(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state, str(tmp_path))

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


def test_analytics_service_records_search_bucket(qapp, tmp_path):
    app_state = SimpleNamespace(local_config={"language": "en", "ui_scale": 1.0})
    service = AnalyticsService(app_state, str(tmp_path))

    service.record_search_results("mods_browser", 12)

    assert any(
        key.startswith("search_results") and "count=10_49" in key
        for key in service._always_on
    )
