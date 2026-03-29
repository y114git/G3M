import json
import os
from pathlib import Path
from types import SimpleNamespace

from services.backup_service import BackupManager
from services.pizza_tower_afom_service import PizzaTowerAFOMService
from utils.pizzatower_afom_utils import apply_afom_towers_from_mod_source


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_afom_service_detects_single_root_archive_layout(tmp_path):
    service = PizzaTowerAFOMService()
    extract_dir = tmp_path / "extract"
    root = extract_dir / "Crumbling_Tower_Supreme"
    _write_text(
        root / "Crumbling_Tower_Supreme.tower.ini",
        '[properties]\nmainlevel="tower"\nname="The Crumbling Tower of Pizza Supreme"\n',
    )
    _write_text(root / "levels" / "Supreme" / "level.ini", "[properties]\n")

    inspection = service.inspect_extracted_archive(str(extract_dir))

    assert inspection.eligible is True
    assert inspection.root_dirs == [str(root)]


def test_afom_service_rejects_root_with_loose_files(tmp_path):
    service = PizzaTowerAFOMService()
    extract_dir = tmp_path / "extract"
    root = extract_dir / "TowerOne"
    _write_text(
        root / "tower.ini",
        '[properties]\nmainlevel="tower"\nname="Tower One"\n',
    )
    _write_text(extract_dir / "readme.txt", "loose")

    inspection = service.inspect_extracted_archive(str(extract_dir))

    assert inspection.eligible is False


def test_afom_service_converts_multi_root_archive_to_towers_mod(tmp_path):
    service = PizzaTowerAFOMService()
    extract_dir = tmp_path / "extract"
    first_root = extract_dir / "TowerOne"
    second_root = extract_dir / "TowerTwo"
    for root, name in ((first_root, "Tower One"), (second_root, "Tower Two")):
        _write_text(
            root / f"{root.name}.tower.ini",
            f'[properties]\nmainlevel="tower"\nname="{name}"\n',
        )
        _write_text(root / "levels" / root.name / "level.ini", "[properties]\n")

    mods_dir = tmp_path / "mods"
    result = service.convert_extracted_archive(
        str(extract_dir),
        str(mods_dir),
        source_file_path="multi_afom.zip",
        gamebanana_metadata={"name": "Converted AFOM", "mod_id": 42, "game": "pizzatower"},
    )

    result_path = Path(result)
    config = json.loads((result_path / "mod_config.json").read_text("utf-8"))
    assert config["metadata"]["name"] == "Converted AFOM"
    assert config["metadata"]["id"] == "gb_mod_42"
    assert config["metadata"]["tags"] == ["CYOP/AFOM"]
    assert config["files"]["pizzatower"]["extra_files"] == ["towers/"]
    assert (result_path / "towers" / "TowerOne" / "TowerOne.tower.ini").exists()
    assert (result_path / "towers" / "TowerTwo" / "TowerTwo.tower.ini").exists()


def test_apply_afom_towers_copies_into_towers_and_restores(tmp_path, monkeypatch):
    mod_source_dir = tmp_path / "mod"
    _write_text(mod_source_dir / "towers" / "TowerOne" / "tower.ini", "new tower")
    _write_text(mod_source_dir / "towers" / "TowerTwo" / "tower.ini", "second tower")

    appdata_dir = tmp_path / "appdata"
    towers_dir = appdata_dir / "PizzaTower_GM2" / "towers"
    existing_file = towers_dir / "TowerOne" / "tower.ini"
    _write_text(existing_file, "original tower")

    backup_mgr = BackupManager(str(tmp_path / "backups"))
    monkeypatch.setenv("APPDATA", str(appdata_dir))

    ok = apply_afom_towers_from_mod_source(
        str(mod_source_dir),
        backup_or_mark=lambda target_file: (
            backup_mgr.backup_file("pizzatower", target_file)
            if os.path.exists(target_file)
            else backup_mgr.mark_file_added("pizzatower", target_file)
        ),
        logger=SimpleNamespace(debug=lambda *args, **kwargs: None),
        extract_archive=lambda archive_path, target_dir: None,
    )

    assert ok is True
    assert existing_file.read_text("utf-8") == "new tower"
    assert (towers_dir / "TowerTwo" / "tower.ini").read_text("utf-8") == "second tower"

    backup_mgr.restore_all_backups()

    assert existing_file.read_text("utf-8") == "original tower"
    assert not (towers_dir / "TowerTwo" / "tower.ini").exists()
