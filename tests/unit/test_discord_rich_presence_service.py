"""Unit tests for built-in Discord Rich Presence service."""

from __future__ import annotations

from types import SimpleNamespace

from services.localization_service import localization_service


class _FakeDiscordClient:
    def __init__(self) -> None:
        self.client_id = "test-client-id"
        self.activities = []
        self.cleared = 0
        self.closed = 0

    def set_activity(self, activity):
        self.activities.append(activity)
        return True

    def clear_activity(self):
        self.cleared += 1
        return True

    def close(self):
        self.closed += 1


def _service(**overrides):
    from services.discord_rich_presence_service import DiscordRichPresenceService

    app_state = SimpleNamespace(
        local_config={"disable_discord_rich_presence": False},
        game_mode=SimpleNamespace(display_name="DELTARUNE"),
        is_settings_view=False,
        search_text="",
        library_search_text="",
    )
    used_mods_service = SimpleNamespace(
        get_active_mod_selections=lambda: {},
        get_active_mods_count=lambda: 0,
    )
    service = DiscordRichPresenceService(
        app_state=overrides.get("app_state", app_state),
        used_mods_service=overrides.get("used_mods_service", used_mods_service),
        parent=overrides.get("parent"),
        client=overrides.get("client", _FakeDiscordClient()),
        time_provider=overrides.get("time_provider", lambda: 100),
    )
    return service


def test_start_enables_presence_by_default():
    service = _service()

    service.start()

    assert service._client.activities[-1]["details"] == "Preparing game to launch"


def test_start_without_client_id_does_not_publish_presence():
    service = _service()
    service._client.client_id = ""

    service.start()

    assert service._client.activities == []


def test_disable_setting_clears_presence_and_blocks_updates():
    client = _FakeDiscordClient()
    app_state = SimpleNamespace(
        local_config={"disable_discord_rich_presence": True},
        game_mode=SimpleNamespace(display_name="DELTARUNE"),
        is_settings_view=False,
        search_text="",
        library_search_text="",
    )
    service = _service(app_state=app_state, client=client)

    service.start()
    service.on_after_game_started()

    assert client.activities == []
    assert client.cleared == 1


def test_playing_status_uses_mod_count_from_active_selections():
    client = _FakeDiscordClient()
    used_mods_service = SimpleNamespace(
        get_active_mod_selections=lambda: {
            "deltarune_1": ["a"],
            "deltarune_2": ["b"],
            "deltarune_3": ["c"],
        }
    )
    service = _service(client=client, used_mods_service=used_mods_service)

    service.start()
    service.on_after_game_started()

    activity = client.activities[-1]
    assert activity["details"] == "Playing DELTARUNE with 3 mods"
    assert activity["timestamps"]["start"] == 100


def test_playing_status_without_mods_uses_plain_game_line():
    client = _FakeDiscordClient()
    service = _service(client=client)

    service.start()
    service.on_after_game_started()

    assert client.activities[-1]["details"] == "Playing DELTARUNE"


def test_semantic_state_detects_create_modpack_dialog(monkeypatch):
    service = _service()
    dialog = type("CreateModpackDialog", (), {})()
    dialog.isVisible = lambda: True
    monkeypatch.setattr(service, "_iter_visible_windows", lambda: [dialog])

    payload = service._resolve_semantic_presence()

    assert payload["key"] == "creating_modpack"


def test_semantic_state_detects_appearance_settings(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        service,
        "_main_window",
        lambda: SimpleNamespace(
            settings_widget=SimpleNamespace(isVisible=lambda: True),
            settings_tab_widget=SimpleNamespace(currentIndex=lambda: 1),
            plugins_tab=object(),
        ),
    )
    monkeypatch.setattr(service, "_iter_visible_windows", lambda: [])
    service.app_state.is_settings_view = True

    payload = service._resolve_semantic_presence()

    assert payload["key"] == "appearance"


def test_shutdown_clears_and_closes_client():
    client = _FakeDiscordClient()
    service = _service(client=client)
    service.start()

    service.shutdown()

    assert client.cleared == 1
    assert client.closed == 1


def test_localizations_resolve_runtime_strings():
    original_language = localization_service.get_current_language()
    status_kwargs = {
        "playing": {"game": "DELTARUNE"},
        "playing_with_mods": {"game": "DELTARUNE", "mods_amount": 3},
    }
    status_keys = (
        "configuring",
        "appearance",
        "plugins",
        "browsing_mods",
        "mod_details",
        "preparing_launch",
        "mod_editor",
        "game_backup",
        "mod_backup",
        "creating_modpack",
        "converting_mods",
        "diff_report",
        "modding_tools",
        "downloads",
        "blacklist",
        "searching",
        "restoring",
        "playing",
        "playing_with_mods",
        "unknown_game",
    )

    try:
        for language_code in localization_service.get_available_languages():
            assert localization_service.load_language(language_code)
            assert (
                localization_service.get_text("ui.disable_discord_rich_presence")
                != "ui.disable_discord_rich_presence"
            )
            for status_key in status_keys:
                text = localization_service.get_text(
                    f"discord_rich_presence.status.{status_key}",
                    **status_kwargs.get(status_key, {}),
                )
                assert text != f"[discord_rich_presence.status.{status_key}]"
                assert text != f"discord_rich_presence.status.{status_key}"
    finally:
        assert localization_service.load_language(original_language)
