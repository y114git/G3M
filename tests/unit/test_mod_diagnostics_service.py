"""Unit tests for current operation diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

from services.mod_diagnostics_service import ModDiagnosticsService
from utils.mod.operation_plan import ModPathContext


def _config(mod_id: str, files: list[dict[str, str]]) -> dict[str, object]:
    return {
        "config_version": "2.0.0",
        "id": mod_id,
        "name": mod_id.title(),
        "version": "1.0.0",
        "authors": ["Author"],
        "game": "deltarune",
        "files": files,
    }


def _context(root, game, user, runtime: str | None = None) -> ModPathContext:
    return ModPathContext.create(
        mod_path=root,
        game_path=game,
        game_data_path=None,
        user_path=user,
        runtime=runtime,
    )


def test_operation_diagnostics_reuses_shared_plan_and_relation_results(tmp_path):
    mod_root = tmp_path / "main"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "copy.txt").write_text("copy", encoding="utf-8")
    config = _config(
        "main",
        [{"source": "${mod_path}/copy.txt", "target": "${game_path}/new/copy.txt", "type": "overwrite"}],
    )
    config["dependencies"] = ["missing:before"]

    report = ModDiagnosticsService(SimpleNamespace(), SimpleNamespace()).build_operation_report(
        {"main": config}, [["main"]], {"main": _context(mod_root, game_root, tmp_path / "user")}
    )

    assert report.summary.selected_mods == 1
    assert report.summary.new_files == 1
    assert {(issue.severity, issue.code) for issue in report.issues} == {
        ("warning", "dependency_missing"),
    }


def test_operation_diagnostics_keeps_invalid_field_and_correction(tmp_path):
    mod_root = tmp_path / "main"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    config = _config("main", [])
    del config["name"]

    report = ModDiagnosticsService(SimpleNamespace(), SimpleNamespace()).build_operation_report(
        {"main": config}, [["main"]], {"main": _context(mod_root, game_root, tmp_path / "user")}
    )

    issue = next(issue for issue in report.issues if issue.code == "missing_field")
    assert issue.field_path == "name"
    assert issue.severity == "error"
    assert issue.recommendation


def test_operation_diagnostics_exposes_one_safe_dependency_arrangement(tmp_path):
    game_root = tmp_path / "game"
    main_root = tmp_path / "main"
    base_root = tmp_path / "base"
    game_root.mkdir()
    main_root.mkdir()
    base_root.mkdir()
    main = _config("main", [])
    main["dependencies"] = ["base:before"]
    base = _config("base", [])

    report = ModDiagnosticsService(SimpleNamespace(), SimpleNamespace()).build_operation_report(
        {"main": main, "base": base},
        [["main", "base"]],
        {
            "main": _context(main_root, game_root, tmp_path / "user"),
            "base": _context(base_root, game_root, tmp_path / "user"),
        },
    )

    assert report.recommended_steps == (("base", "main"),)
    assert any(issue.code == "dependency_arrangement_recommended" for issue in report.issues)


def test_operation_diagnostics_marks_conflicting_targets(tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "shared.txt").write_text("base", encoding="utf-8")
    roots = {mod_id: tmp_path / mod_id for mod_id in ("first", "second")}
    for mod_id, root in roots.items():
        root.mkdir()
        (root / "payload.txt").write_text(mod_id, encoding="utf-8")
    configs = {
        mod_id: _config(mod_id, [{"source": "${mod_path}/payload.txt", "target": "${game_path}/shared.txt", "type": "overwrite"}])
        for mod_id in roots
    }

    report = ModDiagnosticsService(SimpleNamespace(), SimpleNamespace()).build_operation_report(
        configs,
        [["first", "second"]],
        {mod_id: _context(root, game_root, tmp_path / "user") for mod_id, root in roots.items()},
    )

    assert [impact.operation for impact in report.file_impacts] == ["conflict", "conflict"]
    assert report.summary.conflicts == 1
    assert report.issues[-1].code == "file_conflict"


def test_operation_diagnostics_describes_data_patch(tmp_path):
    game_root = tmp_path / "game"
    mod_root = tmp_path / "patch"
    game_root.mkdir()
    mod_root.mkdir()
    (game_root / "data.win").write_bytes(b"base")
    (mod_root / "payload.xdelta").write_bytes(b"patch")
    config = _config("patch", [{"source": "${mod_path}/payload.xdelta", "target": "${game_path}/data.win", "type": "patch"}])

    report = ModDiagnosticsService(SimpleNamespace(), SimpleNamespace()).build_operation_report(
        {"patch": config}, [["patch"]], {"patch": _context(mod_root, game_root, tmp_path / "user", runtime="windows")}
    )

    assert report.summary.data_files == 1
    assert report.data_impacts[0].patch_type == "patch"
    assert report.data_impacts[0].target_data_path is not None
    assert report.data_impacts[0].target_data_path.endswith("data.win")


def test_unavailable_report_is_explicit():
    report = ModDiagnosticsService(SimpleNamespace(), SimpleNamespace()).unavailable_report("migration failed")

    assert report.summary.issues == 1
    assert report.issues[0].explanation == "migration failed"
