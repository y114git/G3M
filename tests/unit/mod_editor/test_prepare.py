"""Unit tests for test prepare."""

from ui.dialogs.mod_editor.prepare import prepare_mod_save_payload


def test_prepare_mod_save_payload_builds_config_and_copies_inputs():
    calls = []
    data = {
        "name": "Prepared Mod",
        "version": "1.0.0",
        "description": "Desc",
        "author": "Author",
        "homepage": "",
        "game": "deltarune",
        "game_version": "1.04",
        "tags": ["other"],
        "info_files": {"README.md": "show"},
        "files": {"deltarune_1": {"data_file_path": "source.win"}},
    }

    result = prepare_mod_save_payload(
        mod_id="local_123",
        mod_dir="C:/mods/test",
        collect_mod_data=lambda: data,
        process_icon=lambda mod_dir: calls.append(("icon", mod_dir)) or "icon.png",
        copy_files_to_mod_dir=lambda mod_dir, files, game: calls.append(
            ("files", mod_dir, files, game)
        )
        or {"deltarune_1": {"data_file_path": "stored.win"}},
        copy_info_files_to_mod_dir=lambda mod_dir: calls.append(("info", mod_dir)),
    )

    returned_data, icon_val, processed_files, config = result

    assert returned_data is data
    assert icon_val == "icon.png"
    assert processed_files == {"deltarune_1": {"data_file_path": "stored.win"}}
    assert config["id"] == "local_123"
    assert config["icon"] == "icon.png"
    assert config["files"] == {"deltarune_1": {"data_file_path": "stored.win"}}
    assert calls == [
        ("icon", "C:/mods/test"),
        ("files", "C:/mods/test", {"deltarune_1": {"data_file_path": "source.win"}}, "deltarune"),
        ("info", "C:/mods/test"),
    ]
