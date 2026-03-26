import pytest

from models.mod_models import ModFileData, ModInfo
from services.mod_service import ModManager


def test_create_mod_object_from_info_keeps_existing_files_and_updates_playtime():
    manager = ModManager.__new__(ModManager)
    manager._BROWSER_ONLY_DATE_FIELD = "_".join(("created", "date"))
    existing_mod = ModInfo(
        id="gb_wip_94809",
        name="Test Mod",
        version="1.0.0",
        author="Author",
        description="Desc",
        game_version="1.0",
        description_url="",
        downloads=0,
        game="deltarune",
        is_verified=False,
        files={"1": ModFileData(data_file_url="data.win")},
        playtime_hours=0.0,
    )

    result = manager.create_mod_object_from_info(
        {
            "id": "gb_wip_94809",
            "added_date": "2026-03-26 18:57:01",
            "playtime_hours": 0.5178,
            "files": {"1": {"data_file_url": "data.win"}},
        },
        [existing_mod],
    )

    assert result is existing_mod
    assert result.playtime_hours == pytest.approx(0.5178)
    assert result.added_date == "2026-03-26 18:57:01"
