"""Unit tests for read-only mod diagnostics planning."""

from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

from models.mod_models import LocalModInfo
from services.mod_diagnostics_service import ModDiagnosticsService


class _ModService:
    def __init__(self, folders: dict[str, str]) -> None:
        self._folders = folders

    def get_mod_folder_path(self, mod_id: str) -> str | None:
        return self._folders.get(mod_id)


def _write_config(root, config: dict) -> None:
    (root / "mod_config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )


def _make_mod(root, mod_id: str, name: str, files: dict) -> LocalModInfo:
    config = {
        "id": mod_id,
        "name": name,
        "version": "1.0",
        "author": "Tester",
        "description": "",
        "game": "deltarune",
        "files": files,
    }
    _write_config(root, config)
    return LocalModInfo.from_dict(config)


def test_diagnostics_detects_new_modified_and_conflicting_extra_files(tmp_path):
    """Plans file impacts without writing to the target game directory."""
    game_dir = tmp_path / "game" / "chapter1_"
    game_dir.mkdir(parents=True)
    (game_dir / "data.win").write_bytes(b"data")
    (game_dir / "lang_en.json").write_text("old", encoding="utf-8")

    mod_a_root = tmp_path / "mods" / "a"
    mod_b_root = tmp_path / "mods" / "b"
    (mod_a_root / "chapter_1").mkdir(parents=True)
    (mod_b_root / "chapter_1").mkdir(parents=True)
    (mod_a_root / "chapter_1" / "lang_en.json").write_text("a", encoding="utf-8")
    (mod_a_root / "chapter_1" / "new_asset.txt").write_text("new", encoding="utf-8")
    (mod_b_root / "chapter_1" / "lang_en.json").write_text("b", encoding="utf-8")

    mod_a = _make_mod(
        mod_a_root,
        "mod-a",
        "Mod A",
        {
            "deltarune_1": {
                "extra_files": ["chapter_1/lang_en.json", "chapter_1/new_asset.txt"]
            }
        },
    )
    mod_b = _make_mod(
        mod_b_root,
        "mod-b",
        "Mod B",
        {"deltarune_1": {"extra_files": ["chapter_1/lang_en.json"]}},
    )
    app_state = SimpleNamespace(
        game_mode=SimpleNamespace(game_id="deltarune"),
        local_config={},
    )
    service = ModDiagnosticsService(
        app_state,
        _ModService({"mod-a": str(mod_a_root), "mod-b": str(mod_b_root)}),
        target_dir_resolver=lambda _chapter_id, *_args, **_kwargs: str(game_dir),
    )

    report = service.build_report({"deltarune_1": [mod_a, mod_b]})

    by_name = {impact.target_relative_path.replace("\\", "/"): impact for impact in report.file_impacts}
    assert by_name["new_asset.txt"].operation == "add"
    assert by_name["lang_en.json"].operation == "conflict"
    assert by_name["lang_en.json"].existing is True
    assert report.summary.new_files == 1
    assert report.summary.conflicts == 1
    assert any(issue.severity == "error" for issue in report.issues)
    assert (game_dir / "new_asset.txt").exists() is False


def test_diagnostics_marks_g3mpatch_data_entries_as_deep_analyzable(tmp_path):
    """Reports deep diagnostics availability per data file entry."""
    game_dir = tmp_path / "game" / "chapter1_"
    game_dir.mkdir(parents=True)
    (game_dir / "data.win").write_bytes(b"data")
    mod_root = tmp_path / "mods" / "patchy"
    (mod_root / "chapter_1").mkdir(parents=True)
    patch_path = mod_root / "chapter_1" / "patch.g3mpatch"
    with zipfile.ZipFile(patch_path, "w") as archive:
        archive.writestr(
            "g3mpatch.json",
            json.dumps(
                {
                    "statistics": {"totalChanged": 2, "totalNew": 1, "totalDeleted": 0},
                    "resources": {"Sprites": {"changed": ["spr_a"], "new": ["spr_b"]}},
                }
            ),
        )
    mod_data = _make_mod(
        mod_root,
        "patchy",
        "Patchy",
        {"deltarune_1": {"data_file_path": "chapter_1/patch.g3mpatch"}},
    )
    app_state = SimpleNamespace(
        game_mode=SimpleNamespace(game_id="deltarune"),
        local_config={},
    )
    service = ModDiagnosticsService(
        app_state,
        _ModService({"patchy": str(mod_root)}),
        target_dir_resolver=lambda _chapter_id, *_args, **_kwargs: str(game_dir),
    )

    report = service.build_report({"deltarune_1": [mod_data]})

    assert len(report.data_impacts) == 1
    impact = report.data_impacts[0]
    assert impact.patch_type == "g3mpatch"
    assert impact.deep_analysis_available is True
    assert impact.resource_summary["Sprites"]["new"] == 1
    assert {
        (entry["type"], entry["operation"], entry["name"])
        for entry in impact.resource_entries
    } == {("Sprites", "new", "spr_b"), ("Sprites", "changed", "spr_a")}
    assert report.summary.new_files == 1
    assert report.summary.modified_files == 1
    assert report.summary.deep_analyzable_data_files == 1


def test_diagnostics_uses_g3mpatch_manifest_archive_paths(tmp_path):
    game_dir = tmp_path / "game" / "chapter1_"
    game_dir.mkdir(parents=True)
    (game_dir / "data.win").write_bytes(b"data")
    mod_root = tmp_path / "mods" / "patchy"
    (mod_root / "chapter_1").mkdir(parents=True)
    patch_path = mod_root / "chapter_1" / "patch.g3mpatch"
    with zipfile.ZipFile(patch_path, "w") as archive:
        archive.writestr(
            "g3mpatch.json",
            json.dumps(
                {
                    "resources": {
                        "CodeEntries": {
                            "changed": [
                                {
                                    "name": "gml_Object_obj_test_Create_0",
                                    "files": {
                                        "code.gml": "CodeEntries/gml_Object_obj_test_Create_0/code.gml"
                                    },
                                }
                            ]
                        }
                    }
                }
            ),
        )
    mod_data = _make_mod(
        mod_root,
        "patchy",
        "Patchy",
        {"deltarune_1": {"data_file_path": "chapter_1/patch.g3mpatch"}},
    )
    app_state = SimpleNamespace(
        game_mode=SimpleNamespace(game_id="deltarune"),
        local_config={},
    )
    service = ModDiagnosticsService(
        app_state,
        _ModService({"patchy": str(mod_root)}),
        target_dir_resolver=lambda _chapter_id, *_args, **_kwargs: str(game_dir),
    )

    report = service.build_report({"deltarune_1": [mod_data]})

    assert report.data_impacts[0].resource_entries[0]["files"] == (
        "CodeEntries/gml_Object_obj_test_Create_0/code.gml",
    )


def test_diagnostics_keeps_extra_file_targets_inside_game_root(tmp_path):
    game_dir = tmp_path / "common" / "DELTARUNE"
    game_dir.mkdir(parents=True)
    mod_root = tmp_path / "mods" / "menu"
    (mod_root / "chapter_0" / "mus").mkdir(parents=True)
    (mod_root / "chapter_0" / "mus" / "joker.ogg").write_bytes(b"ogg")
    mod_data = _make_mod(
        mod_root,
        "menu-mod",
        "Menu Mod",
        {"deltarune_0": {"extra_files": ["chapter_0/mus/joker.ogg"]}},
    )
    app_state = SimpleNamespace(
        game_mode=SimpleNamespace(game_id="deltarune"),
        local_config={},
    )
    service = ModDiagnosticsService(
        app_state,
        _ModService({"menu-mod": str(mod_root)}),
        target_dir_resolver=lambda _chapter_id, *_args, **_kwargs: str(game_dir),
    )

    report = service.build_report({"deltarune_0": [mod_data]})

    assert len(report.file_impacts) == 1
    impact = report.file_impacts[0]
    assert impact.target_root == str(game_dir)
    assert impact.target_relative_path.replace("\\", "/") == "mus/joker.ogg"


def test_diagnostics_falls_back_when_extra_target_root_is_unrelated(tmp_path):
    game_dir = tmp_path / "game"
    other_dir = tmp_path / "other"
    game_dir.mkdir()
    other_dir.mkdir()

    assert (
        ModDiagnosticsService._safe_target_root(str(other_dir), str(game_dir))
        == str(game_dir)
    )
