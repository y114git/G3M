"""Tests for runtime game registry service."""

import pytest

from models.game_modes import (
    BUILTIN_GAME_REGISTRY,
    GameEntry,
    get_game,
    replace_game_entries,
)
from services.game_registry_service import (
    GameRegistryService,
    GameRegistryValidationError,
)
from services.settings_service import SettingsManager


@pytest.fixture
def registry_service(app_state, feedback_service):
    settings_service = SettingsManager(app_state, feedback_service, None, parent=None)
    app_state.local_config = {}
    service = GameRegistryService(app_state, settings_service, parent=None)
    service.load()
    yield service
    replace_game_entries(
        [
            GameEntry(
                id=game_id,
                is_builtin=True,
                is_visible=True,
                sort_index=index,
                game_definition=game,
            )
            for index, (game_id, game) in enumerate(BUILTIN_GAME_REGISTRY.items())
        ]
    )


def test_create_custom_game_registers_runtime_definition(registry_service):
    """Checks that creating custom game registers runtime definition."""
    record = registry_service.create_custom_game(
        display_name="My Game",
        primary_executable="my_game.exe",
        data_file_name="data.win",
        steam_app_id="123456",
        gamebanana_id="9876",
    )
    game = get_game(record.id)
    assert game is not None
    assert game.game_id == record.id
    assert game.steam_app_id == "123456"
    assert game.gamebanana_id == 9876
    assert any(entry.id == record.id for entry in registry_service.list_visible_games())


def test_cannot_hide_last_visible_game(registry_service):
    """Checks that cannoting hide last visible game."""
    visible_ids = [entry.id for entry in registry_service.list_visible_games()]
    for game_id in visible_ids[1:]:
        registry_service.set_visibility(game_id, False)
    with pytest.raises(GameRegistryValidationError):
        registry_service.set_visibility(visible_ids[0], False)


def test_search_games_include_only_visible_searchable_entries(registry_service):
    """Checks that searching games include only visible searchable entries."""
    custom = registry_service.create_custom_game(
        display_name="Searchable Game",
        primary_executable="search.exe",
        data_file_name="data.win",
        gamebanana_id="7777",
    )
    registry_service.set_visibility("undertale", False)
    search_ids = [entry.id for entry in registry_service.list_search_games()]
    assert custom.id in search_ids
    assert "undertale" not in search_ids
    assert "deltarunedemo" not in search_ids


def test_custom_game_uses_explicit_executable_and_data_file(registry_service):
    """Checks that customing game uses explicit executable and data file."""
    record = registry_service.create_custom_game(
        display_name="Platform Test",
        primary_executable="platform_game.exe",
        data_file_name="game.unx",
    )
    game = get_game(record.id)
    assert game is not None
    assert game.get_executable_candidates("windows")[0] == "platform_game.exe"
    assert game.get_executable_candidates("linux")[0] == "platform_game.exe"
    assert game.get_executable_candidates("mac")[0] == "platform_game.exe"
    assert game.data_file_name == "game.unx"


def test_custom_game_load_defaults_linux_native_data_file_name(registry_service):
    """Checks that Linux-native custom games default to game.unx."""
    registry_service.settings_service.read_json = lambda _path: {
        "custom_games": [
            {
                "id": "custom_native",
                "display_name": "Native GameMaker Game",
                "primary_executable": "runner",
            }
        ]
    }

    registry_service.load()

    game = get_game("custom_native")
    assert game is not None
    assert game.data_file_name == "game.unx"


def test_custom_game_load_keeps_windows_exe_default_data_win(registry_service):
    """Checks that Windows custom games keep data.win as the default data file."""
    registry_service.settings_service.read_json = lambda _path: {
        "custom_games": [
            {
                "id": "custom_windows",
                "display_name": "Windows GameMaker Game",
                "primary_executable": "game.exe",
            }
        ]
    }

    registry_service.load()

    game = get_game("custom_windows")
    assert game is not None
    assert game.data_file_name == "data.win"
