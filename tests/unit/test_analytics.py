import importlib
import os
import sys
from pathlib import Path

import pytest

FUNCTIONS_DIR = Path(__file__).resolve().parents[2] / "functions"
ANALYTICS_MODULE = FUNCTIONS_DIR / "analytics.py"

pytestmark = pytest.mark.skipif(
    not ANALYTICS_MODULE.is_file(),
    reason="private functions analytics module is not present in this checkout",
)

if str(FUNCTIONS_DIR) not in sys.path:
    sys.path.insert(0, str(FUNCTIONS_DIR))


def _analytics():
    os.environ["G3M_FUNCTIONS_MEMORY_FIREBASE"] = "1"
    sys.modules.pop("firebase_compat", None)
    sys.modules.pop("analytics", None)
    module = importlib.import_module("analytics")
    module.reset_analytics_test_state()
    return module


def test_ingest_deduplicates_batches_and_sanitizes_local_files():
    analytics = _analytics()
    payload = {
        "schema": 1,
        "batch_id": "batch-1",
        "client": {
            "app_version": "3.1.0",
            "os_family": "Windows",
            "os_version": "11.0.22631",
            "arch": "AMD64",
            "locale": "ru",
            "timezone": "Europe/Oslo",
        },
        "session": {"id": "session-1", "opt_in": True},
        "always": [
            {
                "name": "app_launch",
                "ts": 1_700_000_000,
                "dims": {"game": "deltarune", "mode": "direct"},
            }
        ],
        "opt_in": [
            {
                "name": "local_import_completed",
                "ts": 1_700_000_001,
                "dims": {
                    "source": "file",
                    "local_file_name": "My Private Mod.zip",
                    "local_path": "C:/Users/Alice/Desktop/My Private Mod.zip",
                    "raw_query": "private search text",
                },
            }
        ],
    }

    first = analytics.ingest_analytics_payload(payload)
    duplicate = analytics.ingest_analytics_payload(payload)
    query = analytics.query_analytics({"view": "overview", "day": "2023-11-14"})
    raw_events = analytics.read_analytics_test_storage_events("2023-11-14")

    assert first["accepted"] is True
    assert duplicate["accepted"] is False
    assert query["kpis"]["events_total"] == 2
    assert query["events"]["app_launch"]["total"] == 1
    assert query["events"]["local_import_completed"]["total"] == 1
    assert len(raw_events[0]["dims"]["local_file_hash"]) > 0
    assert raw_events[0]["dims"]["file_ext"] == "zip"
    assert "My Private Mod" not in str(raw_events)
    assert "Alice" not in str(raw_events)
    assert "raw_query" not in str(raw_events)


def test_query_filters_by_session_and_event():
    analytics = _analytics()
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "batch-2",
            "client": {"app_version": "3.1.0", "os_family": "Linux"},
            "session": {"id": "session-a", "opt_in": True},
            "always": [
                {"name": "download_completed", "ts": 1_700_000_000, "dims": {"source": "gamebanana"}},
                {"name": "game_launch_started", "ts": 1_700_000_010, "dims": {"game": "deltarune"}},
            ],
            "opt_in": [
                {
                    "name": "game_launch_started",
                    "ts": 1_700_000_010,
                    "dims": {"game": "deltarune", "mod_ref": "gb_mod_123", "mod_name": "Roaring Patch"},
                }
            ],
        }
    )

    sessions = analytics.query_analytics({"view": "sessions", "day": "2023-11-14"})
    detail = analytics.query_analytics(
        {"view": "events", "day": "2023-11-14", "event": "game_launch_started"}
    )

    assert sessions["sessions"][0]["session_id"] == "session-a"
    assert sessions["sessions"][0]["events"] == 3
    assert detail["event"] == "game_launch_started"
    assert detail["total"] == 2
    assert detail["breakdowns"]["game"]["deltarune"] == 2


def test_admin_token_auth_accepts_bearer_and_rejects_missing_or_wrong_token():
    analytics = _analytics()

    assert analytics.is_admin_authorized(
        {"Authorization": "Bearer secret-token"}, {}, "secret-token"
    )
    assert analytics.is_admin_authorized({}, {"token": "secret-token"}, "secret-token")
    assert not analytics.is_admin_authorized({}, {}, "secret-token")
    assert not analytics.is_admin_authorized(
        {"Authorization": "Bearer wrong"}, {}, "secret-token"
    )
    assert not analytics.is_admin_authorized(
        {"Authorization": "Bearer anything"}, {}, ""
    )
