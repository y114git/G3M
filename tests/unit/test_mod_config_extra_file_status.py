from services.migration_service import build_extra_file_entry
from utils.mod.config_parser import (
    normalize_mod_config_data,
    parse_extra_file_entries_raw,
    parse_extra_files_raw,
)
from utils.mod.scan_utils import validate_mod_config


def test_legacy_extra_file_statuses_migrate_to_targets():
    raw = [
        "lang.txt",
        {"file_path": "main.csx", "status": "dependency"},
    ]

    assert parse_extra_files_raw(raw) == ["lang.txt"]
    assert parse_extra_file_entries_raw(raw) == [
        {"file_path": "lang.txt", "target": "game_folder"},
        {"file_path": "main.csx", "target": "none"},
    ]

    config = {"game": "deltarune", "files": {"deltarune_1": {"extra_files": raw}}}
    normalize_mod_config_data(config)
    assert config["files"]["deltarune_1"]["extra_files"] == [
        {"file_path": "lang.txt", "target": "game_folder"},
        {"file_path": "main.csx", "target": "none"},
    ]


def test_dependency_folder_does_not_change_active_child_status():
    raw = [
        {"file_path": "resources/", "status": "dependency"},
        "resources/active.txt",
        "resources/active-folder/",
    ]

    assert parse_extra_files_raw(raw) == [
        "resources/active.txt",
        "resources/active-folder/",
    ]


def test_legacy_game_data_folder_is_migrated_to_target():
    config = {
        "game": "pizzatower",
        "files": {"pizzatower": {"extra_files": ["towers/"]}},
    }

    normalize_mod_config_data(config)

    assert config["files"]["pizzatower"]["extra_files"] == [
        {"file_path": "towers/", "target": "game_data_folder"}
    ]


def test_invalid_extra_file_fields_are_ignored_or_normalized():
    raw = [
        {"file_path": ["not", "a", "path"], "status": "dependency"},
        {"file_path": "fallback.txt", "status": None},
    ]

    assert parse_extra_file_entries_raw(raw) == [
        {"file_path": "fallback.txt", "target": "game_folder"}
    ]


def test_unknown_extra_file_target_is_not_installed():
    assert build_extra_file_entry("readme.txt", "   ") == {
        "file_path": "readme.txt",
        "target": "none",
    }


def test_custom_extra_file_target_is_preserved_and_validated(tmp_path):
    config = {
        "id": "custom-target-mod",
        "name": "Custom Target Mod",
        "version": "1.0.0",
        "game": "deltarune",
        "files": {
            "deltarune_1": {
                "extra_files": [
                    build_extra_file_entry(
                        "tools/helper.exe", "custom", str(tmp_path)
                    )
                ]
            }
        },
    }

    normalize_mod_config_data(config)

    assert config["files"]["deltarune_1"]["extra_files"] == [
        {
            "file_path": "tools/helper.exe",
            "target": "custom",
            "target_path": str(tmp_path),
        }
    ]
    assert validate_mod_config(
        config, str(tmp_path / "mod_config.json"), "custom-target-mod"
    )


def test_dependency_extra_file_passes_library_scan_validation(tmp_path):
    config = {
        "id": "dependency-mod",
        "name": "Dependency Mod",
        "version": "1.0.0",
        "game": "deltarune",
        "files": {
            "deltarune_1": {
                "data_file_path": "build.csx",
                "extra_files": [{"file_path": "scripts/", "target": "none"}],
            }
        },
    }
    normalize_mod_config_data(config)

    assert validate_mod_config(
        config, str(tmp_path / "mod_config.json"), "dependency-mod"
    )
