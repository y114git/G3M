from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = (
    Path(__file__).resolve().parents[3]
    / "catalog"
    / "plugins"
    / "deltarune_save_manager"
)
SAVE_MANAGER_PATH = PLUGIN_DIR / "save_manager.py"
SAVE_EDITOR_PATH = PLUGIN_DIR / "save_editor.py"


class _PluginSettings:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def get_config(self, key, default=None):
        return self.get(key, default)

    def set_config(self, key, value):
        self.set(key, value)


class _Feedback:
    def __init__(self) -> None:
        self.messages = []

    def show_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    def ask_question(self, *_args, **_kwargs):
        return True


class _SettingsManager:
    def __init__(self) -> None:
        self.picked_path = ""

    def pick_directory(self, *_args, **_kwargs):
        return self.picked_path


def _module():
    name = "_deltarune_save_manager_for_test"
    spec = importlib.util.spec_from_file_location(name, SAVE_MANAGER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _editor_module():
    name = "_deltarune_save_editor_for_test"
    spec = importlib.util.spec_from_file_location(name, SAVE_EDITOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _manager(module, tmp_path: Path):
    return module.SaveManager(
        app_state=SimpleNamespace(
            local_config={},
            game_mode=SimpleNamespace(game_id="deltarune", steam_app_id="1671210"),
        ),
        feedback_manager=_Feedback(),
        settings_manager=_SettingsManager(),
        plugin_api=_PluginSettings(),
        parent=None,
    )


def _write_save(path: Path, chapter: int = 1, slot: int = 0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / f"filech{chapter}_{slot}").write_text("KRIS\n", encoding="utf-8")


def test_find_and_validate_save_path_keeps_explicit_custom_path(tmp_path):
    module = _module()
    manager = _manager(module, tmp_path)
    custom_path = tmp_path / "custom_saves"
    _write_save(custom_path)
    manager.save_path = str(custom_path)

    assert manager.find_and_validate_save_path() is True
    assert Path(manager.save_path) == custom_path


def test_find_and_validate_save_path_resets_deleted_explicit_path(tmp_path):
    module = _module()
    manager = _manager(module, tmp_path)
    deleted_path = tmp_path / "missing_saves"
    manager.save_path = str(deleted_path)
    manager.settings_manager.picked_path = ""

    assert manager.find_and_validate_save_path() is False
    assert manager.save_path == ""


def test_launch_collection_prompt_skips_when_path_missing(tmp_path):
    module = _module()
    manager = _manager(module, tmp_path)
    manager.save_path = str(tmp_path / "missing_saves")

    assert manager.prompt_for_save_collection_on_launch() == -1


def test_current_tenna_data_includes_all_five_chapters_and_associations():
    module = _editor_module()
    data = module.load_simple_mode_data()

    assert set(data["chapters"]["meta"]) == {"1", "2", "3", "4", "5"}
    assert len(data["flags"]["ids"]) >= 1400
    assert len(data["rooms"]["ids"]) >= 1000
    assert data["storySections"]["5"]
    assert data["plotPoints"]["5"]["ids"]
    assert data["flagBitfields"]["meta"]


def test_v2_round_trip_preserves_extended_flag_tail():
    module = _editor_module()
    character = {
        "health": 1,
        "maxHealth": 1,
        "attack": 1,
        "defence": 1,
        "magic": 1,
        "guts": 1,
        "weapon": 0,
        "primaryArmor": 0,
        "secondaryArmor": 0,
        "weaponStyle": 0,
        "weaponStats": [
            {
                "attack": 0,
                "defence": 0,
                "magic": 0,
                "bolts": 0,
                "grazeAmount": 0,
                "grazeSize": 0,
                "boltSpeed": 0,
                "special": 0,
                "element": 0,
                "elementAmount": 0,
            }
            for _ in range(4)
        ],
        "spells": [0] * 12,
    }
    save = {
        "meta": {"format": 2, "chapter": 5, "slot": 0},
        "playerName": "KRIS",
        "vesselName": "",
        "party": [0, 1, 2],
        "money": 0,
        "xp": 0,
        "lv": 1,
        "inv": 0,
        "invc": 0,
        "inDarkWorld": True,
        "characters": [dict(character) for _ in range(5)],
        "battle": {
            "boltSpeed": 0,
            "grazeAmount": 0,
            "grazeSize": 0,
            "tension": 0,
            "maxTension": 100,
        },
        "inventory": {
            "consumables": [0] * 13,
            "keyItems": [0] * 13,
            "weapons": [0] * 48,
            "armors": [0] * 48,
            "storage": [0] * 72,
        },
        "lightWorld": {
            "weapon": 0,
            "armor": 0,
            "experience": 0,
            "level": 1,
            "money": 0,
            "health": 1,
            "maxHealth": 1,
            "attack": 1,
            "defence": 1,
            "weaponStrength": 0,
            "armorDefence": 0,
            "items": [0] * 8,
            "phone": [0] * 8,
        },
        "flags": [0] * 2509,
        "plot": 0,
        "room": 0,
        "time": 0,
    }
    save["flags"][-1] = 123

    lines = module.serialize_save_data(save)
    parsed = module.parse_save_lines(lines, 5, 0)

    assert len(parsed["flags"]) == 2509
    assert parsed["flags"][-1] == 123
    assert module.serialize_save_data(parsed) == lines
