from types import SimpleNamespace

import pytest

from models.mod_models import BrowserModInfo, LocalModInfo, ModFileData
from services.mod_service import ModManager
from utils.file_utils import save_json


def test_create_mod_object_from_info_refreshes_existing_local_mod_fields_and_playtime():
    """Checks that creating mod object from info refreshes existing local mod fields and playtime."""
    manager = ModManager.__new__(ModManager)
    manager._BROWSER_ONLY_DATE_FIELD = "_".join(("created", "date"))
    existing_mod = LocalModInfo(
        id="gb_wip_94809",
        name="Test Mod",
        version="1.0.0",
        author="Author",
        description="Desc",
        game_version="1.0",
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


def test_create_mod_object_from_info_does_not_mutate_existing_browser_mod():
    """Checks that creating mod object from info does not mutate existing browser mod."""
    manager = ModManager.__new__(ModManager)
    manager._BROWSER_ONLY_DATE_FIELD = "_".join(("created", "date"))
    existing_mod = BrowserModInfo(
        id="gb_wip_94809",
        name="Remote Name",
        version="1.0.0",
        author="Author",
        description="Remote Desc",
        game_version="1.0",
        description_url="",
        downloads=10,
        game="deltarune",
        files={},
        last_updated="2025-01-01",
    )

    result = manager.create_mod_object_from_info(
        {
            "id": "gb_wip_94809",
            "name": "Local Name",
            "version": "2.0.0",
            "files": {"deltarune_1": {"data_file_url": "patch.xdelta"}},
        },
        [existing_mod],
    )

    assert result is not existing_mod
    assert existing_mod.name == "Remote Name"
    assert existing_mod.last_updated == "2025-01-01"
    assert result.name == "Local Name"


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


def test_get_installed_mods_list_uses_config_name_not_folder_name(app_state, feedback_service):
    """Checks that getting installed mods list uses config name not folder name."""
    import os

    mod_folder = os.path.join(app_state.mods_dir, "archive_name")
    os.makedirs(mod_folder, exist_ok=True)
    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        {
            "id": "test_mod",
            "name": "Configured Mod Name",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "patch.xdelta"}},
        },
        indent=4,
    )

    mods = ModManager(app_state, feedback_service).get_installed_mods_list()

    assert [mod["name"] for mod in mods] == ["Configured Mod Name"]
    assert [mod["folder_name"] for mod in mods] == ["archive_name"]


def test_get_mod_folder_path_and_source_dir_do_not_depend_on_sanitized_name(
    app_state, feedback_service
):
    """Checks that mod folder resolution uses mod id instead of sanitized display name."""
    import logging
    import os

    from utils.patching.mod_resolve_utils import get_mod_source_dir

    mod_folder = os.path.join(app_state.mods_dir, "downloaded_zip_name")
    chapter_dir = os.path.join(mod_folder, "chapter_1")
    os.makedirs(chapter_dir, exist_ok=True)
    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        {
            "id": "test_mod",
            "name": "Completely Different Display Name",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_1": {"data_file_path": "patch.xdelta"}},
        },
        indent=4,
    )

    manager = ModManager(app_state, feedback_service)

    assert manager.get_mod_folder_path("test_mod") == mod_folder
    assert (
        get_mod_source_dir(
            SimpleNamespace(id="test_mod", name="Completely Different Display Name", game="deltarune"),
            "deltarune_1",
            manager,
            app_state,
            logging.getLogger("test"),
        )
        == chapter_dir
    )


def test_load_local_mods_refreshes_existing_local_mod_files_after_edit(
    app_state, feedback_service
):
    """Checks that reloading local mods refreshes chapter/file mappings in memory."""
    import os

    mod_folder = os.path.join(app_state.mods_dir, "sigma")
    os.makedirs(mod_folder, exist_ok=True)
    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        {
            "id": "local_sigma",
            "name": "sigma",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_0": {"data_file_path": "BOSSRUSH.win"}},
        },
        indent=4,
    )
    with open(os.path.join(mod_folder, "BOSSRUSH.win"), "wb") as f:
        f.write(b"menu")

    manager = ModManager(app_state, feedback_service)
    existing_mod = LocalModInfo(
        id="local_sigma",
        name="sigma",
        version="1.0.0",
        author="Author",
        description="Desc",
        game="deltarune",
        files={
            "deltarune_0": ModFileData(
                data_file_path=os.path.join(mod_folder, "BOSSRUSH.win")
            )
        },
    )
    app_state.all_mods = [existing_mod]

    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        {
            "id": "local_sigma",
            "name": "sigma",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_4": {"data_file_path": "BOSSRUSH.win"}},
        },
        indent=4,
    )

    manager.invalidate_mods_cache()
    manager.load_local_mods()

    assert app_state.all_mods[0] is existing_mod
    assert existing_mod.get_chapter_data("deltarune_0") is None
    refreshed = existing_mod.get_chapter_data("deltarune_4")
    assert refreshed is not None
    assert refreshed.data_file_path == os.path.join(mod_folder, "BOSSRUSH.win")


def test_load_local_mods_refreshes_existing_installed_mod_files_after_edit_without_restart(
    app_state, feedback_service
):
    """Checks that reloading installed mods refreshes chapter mappings for existing in-memory objects."""
    import logging
    import os

    from utils.patching.mod_resolve_utils import get_mod_configured_data_file

    mod_folder = os.path.join(app_state.mods_dir, "chapter_swap")
    os.makedirs(mod_folder, exist_ok=True)
    data_file = os.path.join(mod_folder, "DATA.win")
    with open(data_file, "wb") as handle:
        handle.write(b"patched")
    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        {
            "id": "chapter_swap_mod",
            "name": "Chapter Swap",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_4": {"data_file_path": "DATA.win"}},
        },
        indent=4,
    )

    manager = ModManager(app_state, feedback_service)
    existing_mod = LocalModInfo(
        id="chapter_swap_mod",
        name="Chapter Swap",
        version="1.0.0",
        author="Author",
        description="Desc",
        game="deltarune",
        files={
            "deltarune_4": ModFileData(
                data_file_path=data_file,
            )
        },
    )
    app_state.all_mods = [existing_mod]

    save_json(
        os.path.join(mod_folder, "mod_config.json"),
        {
            "id": "chapter_swap_mod",
            "name": "Chapter Swap",
            "author": "Author",
            "version": "1.0.0",
            "game": "deltarune",
            "files": {"deltarune_0": {"data_file_path": "DATA.win"}},
        },
        indent=4,
    )

    manager.invalidate_mods_cache()
    manager.load_local_mods()

    assert app_state.all_mods[0] is existing_mod
    assert existing_mod.get_chapter_data("deltarune_4") is None
    refreshed = existing_mod.get_chapter_data("deltarune_0")
    assert refreshed is not None
    assert refreshed.data_file_path == "DATA.win"
    assert (
        get_mod_configured_data_file(
            existing_mod,
            "deltarune_0",
            manager,
            app_state,
            logging.getLogger("test"),
        )
        == data_file
    )


def test_fetch_mods_thread_keeps_remote_card_object_separate_from_local_state():
    """Checks that fetching mods keeps remote card object separate from local state."""
    from unittest.mock import Mock, patch

    from models.app_state import AppState
    from workers.fetch_mods_worker import FetchModsThread

    app_state = AppState()
    app_state.local_config = {"selected_search_game": "deltarune", "search_sort_index": 0}
    local_mod = LocalModInfo(
        id="gb_mod_1",
        name="Library Name",
        version="1.0.0",
        author="Author",
        description="Local",
        game="deltarune",
        files={"deltarune_1": ModFileData(data_file_url="patch.xdelta")},
        last_updated="N/A",
    )
    app_state.all_mods = [local_mod]
    emitted = []
    app_state.all_mods_updated.connect(lambda mods: emitted.append(mods))
    main_window = SimpleNamespace(
        app_state=app_state,
        settings_service=None,
        mod_service=Mock(
            get_installed_mods_list=Mock(
                return_value=[
                    {
                        "id": "gb_mod_1",
                        "name": "Library Name",
                        "game": "deltarune",
                        "files": {"deltarune_1": {"data_file_path": "patch.xdelta"}},
                    }
                ]
            )
        ),
    )
    remote_mod = BrowserModInfo(
        id="gb_mod_1",
        name="Remote Name",
        version="2.0.0",
        author="Remote Author",
        description="Remote Desc",
        game="deltarune",
        downloads=42,
        last_updated="2026-03-01",
    )

    with patch(
        "workers.fetch_mods_worker.get_gamebanana_game_ids",
        return_value={"deltarune": 1},
    ), patch(
        "adapters.gamebanana_adapter.GameBananaAPI.get_game_mods",
        return_value=([remote_mod], []),
    ):
        FetchModsThread(main_window).run()

    result_mod = emitted[-1][0]
    assert result_mod is remote_mod
    assert result_mod is not local_mod
    assert result_mod.name == "Remote Name"
    assert result_mod.last_updated == "2026-03-01"
    assert result_mod.files["deltarune_1"].data_file_url == "patch.xdelta"
    assert local_mod.name == "Library Name"
    assert local_mod.last_updated == "N/A"
