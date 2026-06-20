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
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
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
