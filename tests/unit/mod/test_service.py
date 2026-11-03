"""Unit tests for strict installed-mod state."""

import os
from types import SimpleNamespace

import pytest

from models.exceptions import ModUninstallationError
from models.mod_models import BrowserModInfo, LocalModInfo
from services.mod.service import ModManager
from utils.file_utils import load_json, save_json
from utils.mod.config import MOD_CONFIG_VERSION


def _config(mod_id="local_operation", target="${game_path}/chapter2_windows/data.win"):
    return {
        "config_version": MOD_CONFIG_VERSION,
        "id": mod_id,
        "name": "Operation Mod",
        "version": "1.0.0",
        "authors": ["Author"],
        "game": "deltarune",
        "files": [
            {
                "source": "${mod_path}/patch.xdelta",
                "target": target,
                "type": "patch",
            }
        ],
    }


def test_operation_mods_are_visible_in_the_sections_targeted_by_operations():
    config = _config()
    manager = ModManager.__new__(ModManager)
    local_mod = LocalModInfo.from_dict(config)
    vars(manager)["_get_mods_cache"] = lambda: {
        "local_operation": SimpleNamespace(config_data=config)
    }

    assert local_mod.sections == frozenset({"deltarune_2"})
    assert manager.mod_has_files_for_chapter(local_mod, "deltarune_2")
    assert not manager.mod_has_files_for_chapter(local_mod, "deltarune_3")
    assert manager.get_mod_status(local_mod, "deltarune_2") == "ready"


def test_create_mod_object_refreshes_the_existing_local_operation_model():
    manager = ModManager.__new__(ModManager)
    manager._BROWSER_ONLY_DATE_FIELD = "created_date"
    existing = LocalModInfo.from_dict(_config())

    refreshed = manager.create_mod_object_from_info(
        _config(target="${game_path}/chapter4_windows/data.win")
        | {"name": "Updated", "playtime_hours": 0.5},
        [existing],
    )

    assert refreshed is existing
    assert existing.name == "Updated"
    assert existing.sections == frozenset({"deltarune_4"})
    assert existing.playtime_hours == pytest.approx(0.5)


def test_create_mod_object_keeps_remote_listing_separate():
    manager = ModManager.__new__(ModManager)
    manager._BROWSER_ONLY_DATE_FIELD = "created_date"
    remote = BrowserModInfo(
        id="gb_mod_1",
        name="Remote",
        version="1.0.0",
        authors=["Author"],
        description="Description",
        game="deltarune",
    )

    imported = manager.create_mod_object_from_info(_config("gb_mod_1"), [remote])

    assert imported is not remote
    assert remote.name == "Remote"
    assert imported is not None
    assert imported.sections == frozenset({"deltarune_2"})


def test_load_local_mods_refreshes_sections_after_config_edit(app_state, feedback_service):
    mod_folder = os.path.join(app_state.mods_dir, "operation")
    os.makedirs(mod_folder, exist_ok=True)
    save_json(os.path.join(mod_folder, "mod_config.json"), _config("local_operation"))
    manager = ModManager(app_state, feedback_service)
    existing = LocalModInfo.from_dict(_config("local_operation"))
    app_state.all_mods = [existing]

    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        _config("local_operation", "${game_path}/chapter4_windows/data.win"),
    )
    assert manager.load_local_mods()

    assert app_state.all_mods == [existing]
    assert existing.sections == frozenset({"deltarune_4"})


def test_load_local_mods_treats_every_installed_id_alike(app_state, feedback_service):
    for mod_id in ("dojo_plus", "local_operation"):
        folder = os.path.join(app_state.mods_dir, mod_id)
        os.makedirs(folder, exist_ok=True)
        save_json(os.path.join(folder, "mod_config.json"), {**_config(mod_id), "tags": ["gameplay"]})
    manager = ModManager(app_state, feedback_service)
    app_state.all_mods = []

    assert manager.load_local_mods()
    assert manager.load_local_mods()  # a second pass refreshes the mods it already holds

    assert {mod.id: mod.tags for mod in app_state.all_mods} == {
        "dojo_plus": ["gameplay"],
        "local_operation": ["gameplay"],
    }


def test_uninstall_preserves_uninstall_error_when_feedback_fails(
    app_state, feedback_service, monkeypatch
):
    manager = ModManager(app_state, feedback_service)
    monkeypatch.setattr(
        manager,
        "delete_mod_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError(13, "Permission denied", "C:/mods/ghost_mod")
        ),
    )
    monkeypatch.setattr(feedback_service, "show_message", lambda *_args: None)

    with pytest.raises(ModUninstallationError):
        manager.uninstall_mod(SimpleNamespace(id="ghost_mod", name="Ghost Mod"))


def test_record_playtime_quarantines_corrupt_metadata(app_state):
    manager = ModManager.__new__(ModManager)
    manager.app_state = app_state
    with open(app_state.mods_metadata_path, "w", encoding="utf-8") as file:
        file.write('{"mod":')

    manager.add_playtime_hours(["mod"], 1.0)

    assert load_json(app_state.mods_metadata_path) == {"mod": {"playtime_hours": 1.0}}


def test_record_playtime_keeps_metadata_when_the_file_is_locked(app_state, monkeypatch):
    manager = ModManager.__new__(ModManager)
    manager.app_state = app_state
    with open(app_state.mods_metadata_path, "w", encoding="utf-8") as file:
        file.write('{"other": {"playtime_hours": 5}}')
    real_open = open

    def locked(path, *args, **kwargs):
        if str(path) == str(app_state.mods_metadata_path):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", locked)
    manager.add_playtime_hours(["mod"], 1.0)
    monkeypatch.undo()

    assert load_json(app_state.mods_metadata_path) == {"other": {"playtime_hours": 5}}


def test_uninstall_reports_a_folder_that_could_not_be_removed(app_state, feedback_service, monkeypatch, tmp_path):
    folder = tmp_path / "stuck_mod"
    folder.mkdir()
    manager = ModManager(app_state, feedback_service)
    monkeypatch.setattr("utils.file_utils.safe_rmtree", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(feedback_service, "show_message", lambda *_args: None)

    with pytest.raises(ModUninstallationError):
        manager.uninstall_mod(SimpleNamespace(id="stuck_mod", name="Stuck", folder_path=str(folder)))

    assert folder.exists()
