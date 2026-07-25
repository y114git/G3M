"""Unit tests for test deltamod adapter."""

import json

from defusedxml import ElementTree

from adapters.deltamod_adapter import DeltamodConverter


def _make_converter(metadata: dict, gamebanana_metadata: dict | None = None) -> DeltamodConverter:
    converter = DeltamodConverter("source", "mods", gamebanana_metadata=gamebanana_metadata)
    converter.deltamod_info = metadata
    converter.modding_xml = object()
    return converter


def test_generate_config_uses_deltamod_game_mapping_for_supported_single_tab_games():
    """Checks that generateing config uses deltamod game mapping for supported single tab games."""
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

    assert config["metadata"]["game"] == "undertale"


def test_generate_config_uses_deltamod_game_mapping_for_pizzatower():
    """Checks that generateing config uses deltamod game mapping for pizzatower."""
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

    assert config["metadata"]["game"] == "pizzatower"
    assert "game_version" not in config["metadata"]


def test_generate_config_keeps_deltarune_target_version_only_for_deltarune():
    """Checks that generateing config keeps deltarune target version only for deltarune."""
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

    assert config["metadata"]["game"] == "deltarune"
    assert config["metadata"]["game_version"] == "1.04"


def test_generate_files_structure_uses_single_tab_game_key():
    """Checks that generateing files structure uses single tab game key."""
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
    assert files["undertaleyellow"]["data_file_path"] == "patch.xdelta"


def test_generate_config_ignores_gamebanana_metadata_game():
    """Checks that generateing config ignores gamebanana metadata game."""
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

    assert config["metadata"]["game"] == "undertale"


def test_generate_config_uses_canonical_gamebanana_identity():
    converter = _make_converter(
        {
            "metadata": {
                "name": "Imported Mod",
                "author": ["Author"],
                "game": "toby.deltarune",
            }
        },
        gamebanana_metadata={"mod_id": 123, "item_type": "mod"},
    )

    config = converter._generate_config_json()

    assert config["metadata"]["id"] == "gb_mod_123"


def test_generate_config_preserves_gamebanana_wip_identity():
    converter = _make_converter(
        {
            "metadata": {
                "name": "Imported WIP",
                "author": ["Author"],
                "game": "toby.deltarune",
            }
        },
        gamebanana_metadata={"mod_id": 456, "item_type": "wip"},
    )

    config = converter._generate_config_json()

    assert config["metadata"]["id"] == "gb_wip_456"


def test_generate_config_uses_gamebanana_file_name_when_metadata_name_missing():
    """Checks that generateing config uses gamebanana file name when metadata name missing."""
    converter = _make_converter(
        {"metadata": {"author": ["Author"], "game": "toby.deltarune"}},
        gamebanana_metadata={"file_name": "Downloaded Archive Name.zip"},
    )

    config = converter._generate_config_json()

    assert config["metadata"]["name"] == "Downloaded Archive Name"


def test_fallback_mod_name_ignores_gamebanana_file_name_suffixes():
    """Checks that fallback mod name ignores gamebanana file name suffixes."""
    converter = DeltamodConverter("Vase", "mods", gamebanana_metadata={"file_name": "Vase1.1.0.zip"})

    assert converter._fallback_mod_name() == "Vase"


def test_process_files_copies_root_docs(tmp_path):
    """Checks that processing files copies root docs."""
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


def test_process_files_uses_legacy_chapter_layout_for_deltamod_assets(tmp_path):
    """Checks that converted deltamod assets keep chapter folders with plain files."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "patch.xdelta").write_text("patch", encoding="utf-8")
    sprites_dir = source_dir / "sprites"
    sprites_dir.mkdir()
    (sprites_dir / "hero.png").write_text("hero", encoding="utf-8")
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    converter = DeltamodConverter(str(source_dir), str(tmp_path / "mods"))
    converter._target_game = "deltarune"
    converter.modding_xml = ElementTree.fromstring(
        """
        <patches>
            <patch to="./chapter1_windows/data.win" patch="./patch.xdelta" type="xdelta" />
            <patch to="./chapter1_windows/sprites/hero.png" patch="./sprites/hero.png" type="override" />
        </patches>
        """
    )

    converter._process_files(str(target_dir))

    chapter_dir = target_dir / "chapter_1"
    assert (chapter_dir / "patch.xdelta").read_text(encoding="utf-8") == "patch"
    assert (chapter_dir / "sprites" / "hero.png").read_text(encoding="utf-8") == "hero"


def test_convert_uses_metadata_name_for_target_folder(tmp_path):
    """Checks that converted deltamod mods use metadata name instead of temp dir."""
    source_dir = tmp_path / "gb_convert_deadbeef"
    source_dir.mkdir()
    (source_dir / "_deltamodInfo.json").write_text(
        """
        {
            "metadata": {
                "name": "Boss Rush Deluxe",
                "author": ["Author"],
                "game": "toby.deltarune"
            }
        }
        """,
        encoding="utf-8",
    )
    (source_dir / "modding.xml").write_text(
        """
        <patches>
            <patch to="./chapter4_windows/data.win" patch="./chapter4.xdelta" type="xdelta" />
        </patches>
        """,
        encoding="utf-8",
    )
    (source_dir / "chapter4.xdelta").write_text("patch", encoding="utf-8")
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()

    converter = DeltamodConverter(str(source_dir), str(mods_dir))

    result = converter.convert()

    assert result is not None
    assert result.endswith("Boss Rush Deluxe")


def test_convert_supports_revision_four_toml_manifest_and_patch_types(tmp_path):
    source_dir = tmp_path / "revision4"
    source_dir.mkdir()
    (source_dir / "meta.toml").write_text(
        """
deltaruneTargetVersion = "1.05"

[metadata]
name = "Revision Four Mod"
version = "2.0.0"
description = "TOML package"
author = ["First Author", "Second Author"]
game = "toby.deltarune"
packageID = "example.revision.author"
""",
        encoding="utf-8",
    )
    (source_dir / "modding.xml").write_text(
        """
<patches>
    <patch to="./chapter3_windows/data.win" patch="./chapter3.g3mpatch" type="g3mpatch" />
    <patch to="./chapter3_windows/mus/theme.ogg" patch="./theme.ogg" type="copy" />
</patches>
""",
        encoding="utf-8",
    )
    (source_dir / "chapter3.g3mpatch").write_bytes(b"patch")
    (source_dir / "theme.ogg").write_bytes(b"music")
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()

    result = DeltamodConverter(str(source_dir), str(mods_dir)).convert()

    assert result is not None
    result_dir = tmp_path / "mods" / "Revision Four Mod"
    config = json.loads(
        (result_dir / "mod_config.json").read_text(encoding="utf-8")
    )
    metadata = config["metadata"]
    assert metadata["id"] == "example_revision_author"
    assert metadata["author"] == "First Author, Second Author"
    assert metadata["game_version"] == "1.05"
    assert config["files"]["deltarune_3"]["data_file_path"] == "chapter3.g3mpatch"
    assert config["files"]["deltarune_3"]["extra_files"] == ["mus/theme.ogg"]
    assert (result_dir / "chapter_3" / "chapter3.g3mpatch").read_bytes() == b"patch"
    assert (result_dir / "chapter_3" / "mus" / "theme.ogg").read_bytes() == b"music"


def test_revision_four_lts_demo_game_id_maps_to_demo():
    converter = _make_converter(
        {
            "metadata": {
                "name": "Demo Mod",
                "author": "Author",
                "game": "toby.deltarune.demolts",
            }
        }
    )

    config = converter._generate_config_json()

    assert config["metadata"]["game"] == "deltarunedemo"
    assert config["metadata"]["author"] == "Author"
