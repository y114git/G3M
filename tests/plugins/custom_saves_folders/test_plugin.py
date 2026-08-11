"""Unit tests for test custom saves plugin."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PLUGIN_PATH = (
    Path(__file__).resolve().parents[3]
    / "catalog"
    / "plugins"
    / "custom_saves_folders"
    / "plugin.py"
)


class _Settings:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def _module():
    name = "_custom_saves_folders_plugin_for_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_disabled_folder_is_not_used_as_launch_fallback():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: []

    state._settings.set(
        "folders",
        [
            {"id": "folder_a", "enabled": False, "game_id": "deltarune", "profile": "", "name": "disabled_folder"},
            {"id": "folder_b", "enabled": True, "game_id": "deltarune", "profile": "", "name": "enabled_folder"},
        ],
    )
    state._settings.set("mod_rules", [])

    folder = state.resolve_launch_folder("deltarune", "Default", selections={})

    assert folder is not None
    assert folder["id"] == "folder_b"


def test_restore_hook_requests_host_state_refresh_after_successful_restore():
    module = _module()
    plugin = module.CustomSavesFoldersPlugin()
    backup_manager = Mock()
    backup_manager.restore_backups.return_value = True
    plugin._active_session = SimpleNamespace(
        game_id="deltarune", work_dir="", backup_manager=backup_manager
    )
    plugin._context = SimpleNamespace(
        feedback_service=Mock(),
        app_state=SimpleNamespace(local_config={}),
    )
    plugin._tr = lambda: lambda key, **_kwargs: key

    assert plugin.on_before_restore_after_exit(plugin._context) == {
        "refresh_host_deployed_state": True
    }
    backup_manager.restore_backups.assert_called_once_with("deltarune")
    backup_manager.clear_backup_dir.assert_called_once_with()


def test_restore_hook_keeps_session_when_restore_is_incomplete():
    module = _module()
    plugin = module.CustomSavesFoldersPlugin()
    backup_manager = Mock()
    backup_manager.restore_backups.return_value = False
    session = SimpleNamespace(
        game_id="deltarune", work_dir="", backup_manager=backup_manager
    )
    plugin._active_session = session
    plugin._context = SimpleNamespace(
        feedback_service=Mock(),
        app_state=SimpleNamespace(local_config={}),
    )
    plugin._tr = lambda: lambda key, **kwargs: f"{key}: {kwargs.get('error', '')}"

    with patch.object(module, "_show_translated_feedback_message") as show_message:
        assert plugin.on_before_restore_after_exit(plugin._context) is False

    assert plugin._active_session is session
    backup_manager.clear_backup_dir.assert_not_called()
    assert "errors.restore_incomplete" in show_message.call_args.args[-1]


def test_disabled_folder_can_still_be_used_by_enabled_rule_for_selected_mod():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_rule", "enabled": False, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"default": {"id": "mod_a"}},
    )

    assert folder is not None
    assert folder["id"] == "folder_rule"


def test_disabled_rule_does_not_apply_even_if_mod_is_selected():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": True, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": False,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"default": {"id": "mod_a"}},
    )

    assert folder is not None
    assert folder["id"] == "folder_fallback"


def test_rule_has_priority_over_enabled_fallback_folder():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": True, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"default": {"id": "mod_a"}},
    )

    assert folder is not None
    assert folder["id"] == "folder_rule"


def test_rule_matches_updated_gamebanana_mod_id_variant():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: [
        {"id": "gb_mod_123_file_456", "name": "Updated Mod", "game": game_id}
    ]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": True, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "gb_mod_123",
                "mod_name": "Original Mod",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"default": {"id": "gb_mod_123_file_456"}},
    )

    assert folder is not None
    assert folder["id"] == "folder_rule"


def test_gamebanana_rule_does_not_match_different_mod_with_similar_file_id():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: [
        {"id": "gb_mod_124_file_456", "name": "Different Mod", "game": game_id}
    ]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": True, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "gb_mod_123",
                "mod_name": "Original Mod",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"default": {"id": "gb_mod_124_file_456"}},
    )

    assert folder is not None
    assert folder["id"] == "folder_fallback"


def test_rule_does_not_apply_when_target_mod_is_not_selected():
    plugin = _module()
    state = plugin._StateStore(_Settings(), None, None, type("AppState", (), {"local_config": {"active_profile": "Default"}})())
    state.list_profile_mods = lambda profile, game_id: [
        {"id": "mod_a", "name": "Mod A", "game": game_id},
        {"id": "mod_b", "name": "Mod B", "game": game_id},
    ]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": True, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"default": {"id": "mod_b"}},
    )

    assert folder is not None
    assert folder["id"] == "folder_fallback"


def test_profile_specific_folder_beats_global_fallback_by_order_only():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "ProfileA"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: []

    state._settings.set(
        "folders",
        [
            {"id": "folder_global", "enabled": True, "game_id": "deltarune", "profile": "", "name": "global_folder"},
            {"id": "folder_profile", "enabled": True, "game_id": "deltarune", "profile": "ProfileA", "name": "profile_folder"},
        ],
    )
    state._settings.set("mod_rules", [])

    folder = state.resolve_launch_folder("deltarune", "ProfileA", selections={})

    assert folder is not None
    assert folder["id"] == "folder_global"


def test_profile_specific_rule_uses_global_folder():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "ProfileA"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_global", "enabled": False, "game_id": "deltarune", "profile": "", "name": "global_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "ProfileA",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_global",
            }
        ],
    )

    folder = state.resolve_launch_folder("deltarune", "ProfileA", selections={"slot": {"id": "mod_a"}})

    assert folder is not None
    assert folder["id"] == "folder_global"


def test_profile_specific_rule_does_not_apply_in_other_profile():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "ProfileB"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": True, "game_id": "deltarune", "profile": "ProfileA", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "ProfileA",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder("deltarune", "ProfileB", selections={"slot": {"id": "mod_a"}})

    assert folder is not None
    assert folder["id"] == "folder_fallback"


def test_rule_order_uses_first_matching_rule():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "Default"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: [
        {"id": "mod_a", "name": "Mod A", "game": game_id},
        {"id": "mod_b", "name": "Mod B", "game": game_id},
    ]

    state._settings.set(
        "folders",
        [
            {"id": "folder_a", "enabled": True, "game_id": "deltarune", "profile": "", "name": "folder_a"},
            {"id": "folder_b", "enabled": True, "game_id": "deltarune", "profile": "", "name": "folder_b"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_b",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_b",
                "mod_name": "Mod B",
                "folder_id": "folder_b",
            },
            {
                "id": "rule_a",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_a",
            },
        ],
    )

    folder = state.resolve_launch_folder(
        "deltarune",
        "Default",
        selections={"mods": [{"id": "mod_a"}, {"id": "mod_b"}]},
    )

    assert folder is not None
    assert folder["id"] == "folder_b"


def test_folder_order_uses_first_enabled_matching_fallback():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "Default"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: []

    state._settings.set(
        "folders",
        [
            {"id": "folder_disabled", "enabled": False, "game_id": "deltarune", "profile": "", "name": "disabled_folder"},
            {"id": "folder_first", "enabled": True, "game_id": "deltarune", "profile": "", "name": "first_folder"},
            {"id": "folder_second", "enabled": True, "game_id": "deltarune", "profile": "", "name": "second_folder"},
        ],
    )
    state._settings.set("mod_rules", [])

    folder = state.resolve_launch_folder("deltarune", "Default", selections={})

    assert folder is not None
    assert folder["id"] == "folder_first"


def test_other_game_rules_and_folders_are_ignored():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "Default"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_other_game", "enabled": True, "game_id": "undertale", "profile": "", "name": "other_game_folder"},
            {"id": "folder_target", "enabled": True, "game_id": "deltarune", "profile": "", "name": "target_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_other_game",
                "enabled": True,
                "profile": "Default",
                "game_id": "undertale",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_other_game",
            }
        ],
    )

    folder = state.resolve_launch_folder("deltarune", "Default", selections={"slot": {"id": "mod_a"}})

    assert folder is not None
    assert folder["id"] == "folder_target"


def test_selected_mods_can_be_read_from_local_config_when_selections_missing():
    plugin = _module()
    app_state = type(
        "AppState",
        (),
        {
            "local_config": {
                "active_profile": "Default",
                "used_mods_deltarune_profile_default": {
                    "chapter1": "mod_a",
                    "chapter2": ["mod_b", "mod_c"],
                },
            }
        },
    )()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: [
        {"id": "mod_a", "name": "Mod A", "game": game_id},
        {"id": "mod_b", "name": "Mod B", "game": game_id},
        {"id": "mod_c", "name": "Mod C", "game": game_id},
    ]

    state._settings.set(
        "folders",
        [
            {"id": "folder_fallback", "enabled": True, "game_id": "deltarune", "profile": "", "name": "fallback_folder"},
            {"id": "folder_rule", "enabled": False, "game_id": "deltarune", "profile": "", "name": "rule_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_b",
                "enabled": True,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_b",
                "mod_name": "Mod B",
                "folder_id": "folder_rule",
            }
        ],
    )

    folder = state.resolve_launch_folder("deltarune", "Default", selections=None)

    assert folder is not None
    assert folder["id"] == "folder_rule"


def test_nothing_applies_when_no_matching_enabled_rule_or_folder_exists():
    plugin = _module()
    app_state = type("AppState", (), {"local_config": {"active_profile": "Default"}})()
    state = plugin._StateStore(_Settings(), None, None, app_state)
    state.list_profile_mods = lambda profile, game_id: [{"id": "mod_a", "name": "Mod A", "game": game_id}]

    state._settings.set(
        "folders",
        [
            {"id": "folder_disabled", "enabled": False, "game_id": "deltarune", "profile": "", "name": "disabled_folder"},
        ],
    )
    state._settings.set(
        "mod_rules",
        [
            {
                "id": "rule_disabled",
                "enabled": False,
                "profile": "Default",
                "game_id": "deltarune",
                "mod_id": "mod_a",
                "mod_name": "Mod A",
                "folder_id": "folder_disabled",
            }
        ],
    )

    folder = state.resolve_launch_folder("deltarune", "Default", selections={"slot": {"id": "mod_a"}})

    assert folder is None
