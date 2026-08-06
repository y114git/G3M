from utils.mod.config_parser import (
    normalize_mod_config_data,
    parse_extra_file_entries_raw,
    parse_extra_files_raw,
)
from utils.mod.scan_utils import validate_mod_config


def test_dependency_extra_files_are_preserved_but_not_installed():
    raw = [
        "lang.txt",
        {"file_path": "main.csx", "status": "dependency"},
    ]

    assert parse_extra_files_raw(raw) == ["lang.txt"]
    assert parse_extra_file_entries_raw(raw) == [
        {"file_path": "lang.txt", "status": "install"},
        {"file_path": "main.csx", "status": "dependency"},
    ]

    config = {"game": "deltarune", "files": {"deltarune_1": {"extra_files": raw}}}
    normalize_mod_config_data(config)
    assert config["files"]["deltarune_1"]["extra_files"] == raw


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


def test_invalid_extra_file_fields_are_ignored_or_normalized():
    raw = [
        {"file_path": ["not", "a", "path"], "status": "dependency"},
        {"file_path": "fallback.txt", "status": None},
    ]

    assert parse_extra_file_entries_raw(raw) == [
        {"file_path": "fallback.txt", "status": "install"}
    ]


def test_dependency_extra_file_passes_library_scan_validation(tmp_path):
    config = {
        "id": "dependency-mod",
        "name": "Dependency Mod",
        "version": "1.0.0",
        "game": "deltarune",
        "files": {
            "deltarune_1": {
                "data_file_path": "build.csx",
                "extra_files": [{"file_path": "scripts/", "status": "dependency"}],
            }
        },
    }
    normalize_mod_config_data(config)

    assert validate_mod_config(
        config, str(tmp_path / "mod_config.json"), "dependency-mod"
    )
