from utils.mod_config_parser import (
    MOD_CONFIG_VERSION,
    build_mod_config_data,
    normalize_files_data,
    normalize_mod_config_data,
)


def test_build_mod_config_data_uses_default_order_for_new_payload():
    config = build_mod_config_data(
        {
            "files": {"1": {}},
            "game_version": "1.0",
            "name": "Test",
            "id": "mod",
            "tags": ["other"],
            "author": "Author",
            "description": "Desc",
            "game": "deltarune",
            "homepage": "https://example.com",
            "version": "1.0.0",
            "icon": "icon.png",
        }
    )

    assert list(config)[:12] == [
        "config_version",
        "id",
        "name",
        "version",
        "author",
        "description",
        "homepage",
        "icon",
        "game",
        "game_version",
        "tags",
        "files",
    ]
    assert config["config_version"] == MOD_CONFIG_VERSION


def test_normalize_mod_config_data_migrates_to_canonical_order():
    config = {
        "id": "mod",
        "name": "Test",
        "files": {"1": {}},
        "description": "Desc",
        "icon": "icon.png",
        "external_url": "https://example.com/mod",
        "game": "deltarune",
    }

    assert normalize_mod_config_data(config) is True
    assert list(config) == [
        "config_version",
        "id",
        "name",
        "version",
        "description",
        "homepage",
        "icon",
        "game",
        "files",
    ]
    assert config["homepage"] == "https://example.com/mod"
    assert list(config["files"]) == ["deltarune_1"]


def test_normalize_files_data_converts_tab_ids_to_file_keys():
    files = normalize_files_data(
        {
            "deltarune_4": {
                "data_file_url": "DATA.win",
                "extra_files": {"extras": ["bonus.zip"]},
            }
        }
    )

    assert list(files) == ["deltarune_4"]
    assert files["deltarune_4"]["data_file_url"] == "DATA.win"
    assert files["deltarune_4"]["extra_files"] == [
        {"key": "extras", "url": "bonus.zip"}
    ]


def test_normalize_files_data_with_game_prefix_normalizes_chapter_ids():
    files = normalize_files_data(
        {
            "4": {
                "data_file_url": "DATA.win",
                "extra_files": {"extras": ["bonus.zip"]},
            }
        },
        game="deltarune"
    )

    assert list(files) == ["deltarune_4"]
    assert files["deltarune_4"]["data_file_url"] == "DATA.win"
    assert files["deltarune_4"]["extra_files"] == [
        {"key": "extras", "url": "bonus.zip"}
    ]


def test_normalize_mod_config_data_normalizes_file_keys_to_chapter_ids():
    config = {
        "game": "deltarune",
        "files": {"4": {"data_file_url": "DATA.win"}},
    }

    assert normalize_mod_config_data(config) is True
    assert list(config["files"]) == ["deltarune_4"]


def test_normalize_mod_config_data_filters_invalid_tags_and_trims_fields():
    config = {
        "id": "x" * 80,
        "name": "n" * 80,
        "version": "v" * 40,
        "description": "d" * 250,
        "game": "g" * 80,
        "tags": ["other", "invalid", "OTHER"],
        "files": {
            "1": {
                "data_file_url": "a" * 1200,
                "extra_files": [{"key": "k" * 1200, "url": "u" * 1200}],
            }
        },
    }

    assert normalize_mod_config_data(config) is True
    assert config["id"] == "x" * 50
    assert config["name"] == "n" * 50
    assert config["version"] == "v" * 20
    assert config["description"] == "d" * 200
    assert config["game"] == "g" * 30
    assert config["tags"] == ["other"]
    file_info = config["files"]["g" * 30]
    assert len(file_info["data_file_url"]) == 1000
    assert file_info["extra_files"] == [{"key": "k" * 1000, "url": "u" * 1000}]
