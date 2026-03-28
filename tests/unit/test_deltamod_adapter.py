from adapters.deltamod_adapter import DeltamodConverter
from defusedxml import ElementTree


def _make_converter(metadata: dict, gamebanana_metadata: dict | None = None) -> DeltamodConverter:
    converter = DeltamodConverter("source", "mods", gamebanana_metadata=gamebanana_metadata)
    converter.deltamod_info = metadata
    converter.modding_xml = object()
    return converter


def test_generate_config_uses_deltamod_game_mapping_for_supported_single_tab_games():
    converter = _make_converter(
        {
            "metadata": {
                "name": "UT Mod",
                "author": ["Author"],
                "game": "toby.undertale",
            }
        }
    )

    config = converter._generate_config_json()

    assert config["game"] == "undertale"
    assert config["files"] == {}
    assert "game_version" not in config


def test_generate_config_uses_deltamod_game_mapping_for_pizzatower():
    converter = _make_converter(
        {
            "metadata": {
                "name": "PT Mod",
                "author": ["Author"],
                "game": "other.pizzatower",
            }
        }
    )

    config = converter._generate_config_json()

    assert config["game"] == "pizzatower"
    assert "game_version" not in config


def test_generate_config_keeps_deltarune_target_version_only_for_deltarune():
    converter = _make_converter(
        {
            "metadata": {
                "name": "DR Mod",
                "author": ["Author"],
                "game": "toby.deltarune",
            },
            "deltaruneTargetVersion": "1.04",
        }
    )

    config = converter._generate_config_json()

    assert config["game"] == "deltarune"
    assert config["game_version"] == "1.04"


def test_generate_files_structure_uses_single_tab_game_key():
    converter = _make_converter(
        {
            "metadata": {
                "name": "UTY Mod",
                "author": ["Author"],
                "game": "fans.utyellow",
            }
        }
    )
    converter._target_game = "undertaleyellow"
    patches = [
        {
            "to": "./data.win",
            "patch": "./patch.xdelta",
            "type": "xdelta",
        }
    ]

    files = converter._generate_files_structure(patches)

    assert list(files) == ["undertaleyellow"]
    assert files["undertaleyellow"]["data_file_url"] == "patch.xdelta"


def test_generate_config_ignores_gamebanana_metadata_game():
    converter = _make_converter(
        {
            "metadata": {
                "name": "Imported Mod",
                "author": ["Author"],
                "game": "toby.undertale",
            }
        },
        gamebanana_metadata={"game": "pizzatower"},
    )

    config = converter._generate_config_json()

    assert config["game"] == "undertale"


def test_process_files_copies_root_docs(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "README.md").write_text("# Guide", encoding="utf-8")
    (source_dir / "notes.txt").write_text("hello", encoding="utf-8")
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    converter = DeltamodConverter(str(source_dir), str(tmp_path / "mods"))
    converter.modding_xml = ElementTree.fromstring("<patches />")

    converter._process_files(str(target_dir))

    assert (target_dir / "README.md").read_text(encoding="utf-8") == "# Guide"
    assert (target_dir / "notes.txt").read_text(encoding="utf-8") == "hello"
