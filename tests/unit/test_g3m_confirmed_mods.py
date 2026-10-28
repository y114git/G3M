"""The list of mods the G3M creator confirmed install without Manual install."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from adapters.gamebanana_adapter import G3MConfirmedMod, GameBananaAPI
from config.config import GAMEBANANA_TOOL_ID_DELTAMOD
from models.game_modes import get_game
from services.mod.filter_service import filter_and_sort_mods


@pytest.fixture(autouse=True)
def _restore_ids():
    previous = (
        GameBananaAPI.g3m_confirmed,
        GameBananaAPI._g3m_confirmed_loaded_at,
        GameBananaAPI._g3m_confirmed_etag,
    )
    GameBananaAPI._g3m_confirmed_etag = ""
    yield
    (
        GameBananaAPI.g3m_confirmed,
        GameBananaAPI._g3m_confirmed_loaded_at,
        GameBananaAPI._g3m_confirmed_etag,
    ) = previous


def _fetch(monkeypatch, payload=None, error=None, status=200, etag="v1"):
    response = Mock(status_code=status, headers={"ETag": etag}, json=Mock(return_value=payload))
    response.raise_for_status.side_effect = error
    get = Mock(return_value=response)
    monkeypatch.setattr("adapters.gamebanana_adapter.requests.get", get)
    GameBananaAPI.load_g3m_confirmed()
    return get


def test_list_is_read_from_the_mods_array(monkeypatch):
    _fetch(
        monkeypatch,
        {
            "mods": [
                {"id": "gb_mod_1", "note": " Chapter 1 only ", "game": "deltarune", "game_version": "Ch4 v0.0.110"},
                {"id": "gb_mod_9"},
                {"name": "no id"},
                "junk",
            ]
        },
    )

    assert GameBananaAPI.g3m_confirmed == {
        "gb_mod_1": G3MConfirmedMod("Chapter 1 only", "deltarune", "Ch4 v0.0.110"),
        "gb_mod_9": G3MConfirmedMod(),
    }


def test_failed_fetch_keeps_the_previous_list(monkeypatch):
    GameBananaAPI.g3m_confirmed = {"gb_mod_1": G3MConfirmedMod()}

    _fetch(monkeypatch, error=OSError("offline"))

    assert GameBananaAPI.g3m_confirmed == {"gb_mod_1": G3MConfirmedMod()}


def test_fetch_is_a_single_short_attempt_and_reuses_an_unchanged_list(monkeypatch):
    get = _fetch(monkeypatch, {"mods": [{"id": "gb_mod_1"}]}, etag="v7")
    assert get.call_args.kwargs["timeout"] == (2, 3)

    get = _fetch(monkeypatch, status=304)

    assert get.call_args.kwargs["headers"] == {"If-None-Match": "v7"}
    assert GameBananaAPI.g3m_confirmed == {"gb_mod_1": G3MConfirmedMod()}


def test_filter_keeps_only_confirmed_mods():
    GameBananaAPI.g3m_confirmed = {"gb_mod_2": G3MConfirmedMod()}
    mods = [{"id": f"gb_mod_{number}", "game": "deltarune"} for number in (1, 2, 3)]

    result = filter_and_sort_mods(mods, {"only_g3m": True, "game": "deltarune"})

    assert [mod["id"] for mod in result] == ["gb_mod_2"]


def test_filter_ignores_entries_confirmed_for_another_game():
    GameBananaAPI.g3m_confirmed = {
        "gb_mod_1": G3MConfirmedMod(game="deltarune"),
        "gb_mod_2": G3MConfirmedMod(game="undertale"),
        "gb_mod_3": G3MConfirmedMod(),
    }
    mods = [{"id": f"gb_mod_{number}", "game": "deltarune"} for number in (1, 2, 3)]

    result = filter_and_sort_mods(mods, {"only_g3m": True, "game": "deltarune"})

    assert [mod["id"] for mod in result] == ["gb_mod_1", "gb_mod_3"]


def test_shipped_list_names_only_known_games():
    path = Path(__file__).resolve().parents[2] / "catalog" / "mods" / "mods.json"
    entries = json.loads(path.read_text(encoding="utf-8"))["mods"]

    unknown = {entry["game"] for entry in entries if entry.get("game") and get_game(entry["game"]) is None}

    assert not unknown


def test_game_of_a_mod_is_read_from_its_profile(monkeypatch):
    api = GameBananaAPI()
    monkeypatch.setattr(api, "get_mod_profile_page", lambda *_a, **_k: {"_aGame": {"_idRow": "4242"}})
    assert api.get_mod_game_id(1) == 4242

    monkeypatch.setattr(api, "get_mod_profile_page", lambda *_a, **_k: None)
    assert api.get_mod_game_id(1) is None


@pytest.mark.parametrize(
    ("tool_ids", "confirmed", "expected"),
    [
        ([20615], True, "g3m"),
        ([20615], False, ""),
        ([20615, 12345], False, ""),
        ([], True, ""),
    ],
)
def test_only_confirmed_or_deltamod_files_install_automatically(tool_ids, confirmed, expected):
    GameBananaAPI.g3m_confirmed = {"gb_mod_1": G3MConfirmedMod()} if confirmed else {}
    entry = {"_aModManagerIntegrations": [{"_idToolRow": tool_id} for tool_id in tool_ids]}

    file = GameBananaAPI()._build_file_metadata(5, entry, "gb_mod_1")

    assert file["compatibility"] == expected


def test_deltamod_file_installs_automatically_without_the_confirmed_list():
    GameBananaAPI.g3m_confirmed = {}
    entry = {"_aModManagerIntegrations": [{"_idToolRow": GAMEBANANA_TOOL_ID_DELTAMOD}]}

    assert GameBananaAPI()._build_file_metadata(5, entry, "gb_mod_1")["compatibility"] == "deltamod"
