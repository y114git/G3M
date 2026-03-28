import pytest

from models.mod_models import BrowserModInfo, ModFileData
from services.mod_service import ModManager


def test_create_mod_object_from_info_refreshes_existing_mod_fields_and_playtime():
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


