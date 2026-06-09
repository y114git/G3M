"""Unit tests for test analytics."""

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


def test_bundle_view_returns_precomputed_dashboard_sections():
    analytics = _analytics()
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "bundle-1",
            "client": {
                "app_version": "3.1.0",
                "os_family": "Windows",
                "locale": "en",
            },
            "session": {"id": "session-bundle", "opt_in": True},
            "always": [
                {"name": "app_launch", "ts": 1_700_000_000, "dims": {"os": "windows"}},
                {"name": "app_ready", "ts": 1_700_000_001, "dims": {"startup": "lt3s"}},
                {"name": "dialog_opened", "ts": 1_700_000_002, "dims": {"name": "downloads"}},
                {"name": "game_launch_started", "ts": 1_700_000_003, "dims": {"game": "deltarune", "mode": "direct"}},
                {"name": "mod_opened", "ts": 1_700_000_004, "dims": {"area": "library", "game": "deltarune"}},
            ],
            "opt_in": [],
        }
    )

    bundle = analytics.query_analytics({"view": "bundle", "day": "2023-11-14"})

    assert bundle["ok"] is True
    assert bundle["view"] == "bundle"
    assert bundle["funnel"]["app_launch"] == 1
    assert bundle["funnel"]["game_launch_started"] == 1
    assert bundle["overview"]["top_events"][0]["event"] == "app_launch"
    assert any(item["key"] == "downloads" for item in bundle["stories"]["dialogs"])
    assert any(item["event"] == "mod_opened" for item in bundle["features"])


def test_bundle_view_exposes_mod_names_from_detail_events():
    analytics = _analytics()
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "bundle-mod-names",
            "client": {"app_version": "3.1.0", "os_family": "Windows"},
            "session": {"id": "session-mod", "opt_in": True},
            "always": [
                {"name": "mod_opened", "ts": 1_700_000_000, "dims": {"game": "deltarune", "area": "library"}},
            ],
            "opt_in": [
                {"name": "mod_opened_detail", "ts": 1_700_000_000, "dims": {"game": "deltarune", "area": "library", "ref": "gb_mod_123", "name": "roaring_patch"}},
                {"name": "mod_install_completed_detail", "ts": 1_700_000_001, "dims": {"game": "deltarune", "mode": "one_click", "ref": "gb_mod_123", "name": "roaring_patch"}},
            ],
        }
    )

    bundle = analytics.query_analytics({"view": "bundle", "day": "2023-11-14"})

    assert any(item["key"] == "roaring_patch" for item in bundle["stories"]["mod_names_opened"])
    assert any(item["key"] == "roaring_patch" for item in bundle["stories"]["mod_names_installed"])


def test_bundle_view_exposes_mod_refs_from_always_events_without_opt_in():
    analytics = _analytics()
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "bundle-mod-refs",
            "client": {"app_version": "3.1.0", "os_family": "Windows"},
            "session": {"id": "session-mod-refs", "opt_in": False},
            "always": [
                {
                    "name": "mod_opened",
                    "ts": 1_700_000_000,
                    "dims": {
                        "game": "deltarune",
                        "area": "library",
                        "ref": "gb_mod_123",
                        "source": "gamebanana",
                    },
                },
                {
                    "name": "mod_install_completed",
                    "ts": 1_700_000_001,
                    "dims": {
                        "game": "deltarune",
                        "mode": "one_click",
                        "ref": "gb_mod_123",
                        "mod_version": "2_0",
                    },
                },
                {
                    "name": "download_completed",
                    "ts": 1_700_000_002,
                    "dims": {"target": "mod", "ref": "gb_mod_123"},
                },
                {
                    "name": "use_completed",
                    "ts": 1_700_000_003,
                    "dims": {"target": "mod", "local_ref": "local_abcdef123456"},
                },
                {
                    "name": "launch_mod_selected",
                    "ts": 1_700_000_004,
                    "dims": {"game": "deltarune", "ref": "gb_mod_123"},
                },
            ],
            "opt_in": [],
        }
    )

    bundle = analytics.query_analytics({"view": "bundle", "day": "2023-11-14"})

    assert any(
        item["key"] == "gb_mod_123"
        for item in bundle["stories"]["mod_refs_opened_always"]
    )
    assert any(
        item["key"] == "gb_mod_123"
        for item in bundle["stories"]["mod_refs_installed_always"]
    )
    assert any(
        item["key"] == "2_0"
        for item in bundle["stories"]["mod_versions_installed"]
    )
    assert any(
        item["key"] == "gb_mod_123"
        for item in bundle["stories"]["download_mod_refs_always"]
    )
    assert any(
        item["key"] == "local_abcdef123456"
        for item in bundle["stories"]["used_local_mods_always"]
    )
    assert any(
        item["key"] == "gb_mod_123"
        for item in bundle["stories"]["launch_mod_refs_always"]
    )


def test_range_query_merges_multiple_days_and_archives():
    analytics = _analytics()
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "range-1",
            "client": {"app_version": "3.1.0", "os_family": "Windows"},
            "session": {"id": "session-range-1", "opt_in": True},
            "always": [
                {"name": "app_launch", "ts": 1_700_000_000, "dims": {"os": "windows"}},
                {"name": "dialog_opened", "ts": 1_700_000_001, "dims": {"name": "downloads"}},
            ],
            "opt_in": [],
        }
    )
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "range-2",
            "client": {"app_version": "3.1.0", "os_family": "Linux"},
            "session": {"id": "session-range-2", "opt_in": True},
            "always": [
                {"name": "app_launch", "ts": 1_700_086_400, "dims": {"os": "linux"}},
                {"name": "dialog_opened", "ts": 1_700_086_401, "dims": {"name": "game_manager"}},
            ],
            "opt_in": [],
        }
    )
    analytics.materialize_analytics_day("2023-11-14")
    analytics.db.reference("analytics/hot/days/2023-11-14").delete()

    merged = analytics.query_analytics(
        {"view": "bundle", "start_day": "2023-11-14", "end_day": "2023-11-15"}
    )

    assert merged["ok"] is True
    assert merged["range"]["start_day"] == "2023-11-14"
    assert merged["range"]["end_day"] == "2023-11-15"
    assert merged["funnel"]["app_launch"] == 2
    assert any(item["key"] == "downloads" for item in merged["stories"]["dialogs"])
    assert any(item["key"] == "game_manager" for item in merged["stories"]["dialogs"])


def test_range_sessions_returns_rows_instead_of_empty_list():
    analytics = _analytics()
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "session-range-a",
            "client": {"app_version": "3.1.0", "os_family": "Windows"},
            "session": {"id": "session-a", "opt_in": True},
            "always": [{"name": "app_launch", "ts": 1_700_000_000, "dims": {"os": "windows"}}],
            "opt_in": [],
        }
    )
    analytics.ingest_analytics_payload(
        {
            "schema": 1,
            "batch_id": "session-range-b",
            "client": {"app_version": "3.1.0", "os_family": "Linux"},
            "session": {"id": "session-b", "opt_in": True},
            "always": [{"name": "app_launch", "ts": 1_700_086_400, "dims": {"os": "linux"}}],
            "opt_in": [],
        }
    )

    sessions = analytics.query_analytics(
        {"view": "sessions", "start_day": "2023-11-14", "end_day": "2023-11-15"}
    )

    ids = {row["session_id"] for row in sessions["sessions"]}
    assert "session-a" in ids
    assert "session-b" in ids
