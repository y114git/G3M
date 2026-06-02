from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PLUGIN_PATH = (
    Path(__file__).resolve().parents[2]
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
