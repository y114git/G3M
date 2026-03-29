import pytest

from models.mod_models import BrowserModInfo, ModFileData
from services.mod_service import ModManager
from utils.file_utils import save_json


def test_create_mod_object_from_info_refreshes_existing_mod_fields_and_playtime():
    """Checks that creating mod object from info refreshes existing mod fields and playtime."""
    manager = ModManager.__new__(ModManager)
    manager._BROWSER_ONLY_DATE_FIELD = "_".join(("created", "date"))
    existing_mod = BrowserModInfo(
        id="gb_wip_94809",
        name="Test Mod",
        version="1.0.0",
        author="Author",
        description="Desc",
        game_version="1.0",
        description_url="",
        downloads=0,
        game="deltarune",
        files={"1": ModFileData(data_file_url="data.win")},
        playtime_hours=0.0,
    )

    result = manager.create_mod_object_from_info(
        {
            "id": "gb_wip_94809",
            "name": "Updated Mod",
            "version": "2.0.0",
            "added_date": "2026-03-26 18:57:01",
            "playtime_hours": 0.5178,
            "files": {"deltarune_1": {"data_file_url": "patch.xdelta"}},
        },
        [existing_mod],
    )

    assert result is existing_mod
    assert result.name == "Updated Mod"
    assert result.version == "2.0.0"
    assert result.playtime_hours == pytest.approx(0.5178)
    assert result.added_date == "2026-03-26 18:57:01"
    assert result.files["deltarune_1"].data_file_url == "patch.xdelta"


def test_get_installed_mods_list_handles_iter_and_cache_paths_without_folder_path_error(
    app_state, feedback_service
):
    """Checks that getting installed mods list handles iter and cache paths without folder path error."""
    import os
    mod_folder = os.path.join(app_state.mods_dir, "test_mod")
    config_path = os.path.join(mod_folder, "mod_config.json")

    os.makedirs(mod_folder, exist_ok=True)
    save_json(
        config_path,
        {
            "id": "test_mod",
            "name": "Test Mod",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "patch.xdelta"}},
        },
        indent=4,
    )

    manager = ModManager(app_state, feedback_service)

    uncached_mods = manager.get_installed_mods_list()
    manager.load_local_mods()
    cached_mods = manager.get_installed_mods_list()

    assert [mod["id"] for mod in uncached_mods] == ["test_mod"]
    assert [mod["id"] for mod in cached_mods] == ["test_mod"]
