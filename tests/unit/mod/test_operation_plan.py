"""Tests for the shared non-mutating operation planner."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from utils.mod.archive import ArchiveVirtualPath
from utils.mod.config import MOD_CONFIG_VERSION
from utils.mod.hashing import sha256_path
from utils.mod.operation_plan import (
    ModPathContext,
    build_mod_operation_plan,
    build_profile_operation_plan,
)


def _config(files: list[object]) -> dict[str, object]:
    return {
        "config_version": MOD_CONFIG_VERSION,
        "id": "test_mod",
        "name": "Test Mod",
        "version": "1.0.0",
        "authors": [],
        "game": "deltarune",
        "files": files,
    }


def test_planner_preserves_depth_first_order_and_rewrites_deltarune_target(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "first.txt").write_text("first", encoding="utf-8")
    (mod_root / "second.txt").write_text("second", encoding="utf-8")
    target = game_root / "chapter1_mac" / "game.ios"
    target.parent.mkdir()
    target.write_bytes(b"original")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/first.txt",
                    "target": "${game_path}/chapter1_windows/data.win",
                    "type": "overwrite",
                },
                {
                    "Nested": [
                        {
                            "source": "${mod_path}/second.txt",
                            "target": "${game_path}/chapter1_windows/data.win",
                            "type": "patch",
                        }
                    ]
                },
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
            platform="darwin",
        ),
    )

    assert [operation.index for operation in plan.operations] == [1, 2]
    assert plan.operations[1].group_path == ("Nested",)
    assert plan.operations[0].target == target
    assert plan.findings == ()


def test_profile_plan_marks_simultaneous_data_patches_for_priority_merge(tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    (game_root / "data.win").write_bytes(b"original")
    configs = {}
    contexts = {}
    for mod_id in ("first", "second"):
        mod_root = tmp_path / mod_id
        mod_root.mkdir()
        (mod_root / "patch.xdelta").write_bytes(mod_id.encode())
        configs[mod_id] = {
            **_config(
                [
                    {
                        "source": "${mod_path}/patch.xdelta",
                        "target": "${game_path}/data.win",
                        "type": "patch",
                    }
                ]
            ),
            "id": mod_id,
        }
        contexts[mod_id] = ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        )

    plan = build_profile_operation_plan(
        configs, contexts, ("first", "second"), merge_steps=(("first", "second"),)
    )

    assert [operation.merge_group for operation in plan.operations] == [0, 0]
    assert [operation.merge_priority for operation in plan.operations] == [1, 0]


def test_profile_plan_carries_ordered_target_state_between_mod_configs(tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    configs = {}
    contexts = {}
    for mod_id, source_name, operation_type in (
        ("first", "replacement.txt", "overwrite"),
        ("second", "patch.xdelta", "patch"),
    ):
        mod_root = tmp_path / mod_id
        mod_root.mkdir()
        (mod_root / source_name).write_bytes(source_name.encode())
        operation = {
            "source": f"${{mod_path}}/{source_name}",
            "target": "${game_path}/generated.win",
            "type": operation_type,
        }
        if mod_id == "second":
            operation["target_hash"] = sha256_path(mod_root / source_name)
        configs[mod_id] = {
            **_config(
                [operation]
            ),
            "id": mod_id,
        }
        contexts[mod_id] = ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        )

    plan = build_profile_operation_plan(
        configs, contexts, ("first", "second")
    )

    # A file the mod creates in the game folder is expected, so it is not a finding.
    assert plan.findings == ()


def test_profile_plan_reserves_indices_for_unresolved_operations(tmp_path):
    (tmp_path / "payload.txt").write_text("payload", encoding="utf-8")
    context = ModPathContext.create(
        mod_path=tmp_path, game_path=tmp_path / "game",
        game_data_path=None, user_path=tmp_path / "user",
    )
    unresolved = {
        "source": "${mod_path}/payload.txt",
        "target": "${game_data_path}/payload.txt", "type": "overwrite",
    }
    resolved = {
        "source": "${mod_path}/payload.txt",
        "target": "${game_path}/payload.txt", "type": "overwrite",
    }
    configs = {
        "first": {**_config([unresolved, resolved]), "id": "first"},
        "second": {**_config([resolved]), "id": "second"},
    }

    plan = build_profile_operation_plan(
        configs, {"first": context, "second": context}, ("first", "second"),
    )

    assert [(operation.index, operation.mod_id) for operation in plan.operations] == [(2, "first"), (3, "second")]
    assert [(finding.operation_index, finding.code) for finding in plan.findings] == [
        (1, "target_root"),
    ]


@pytest.mark.parametrize("filename", ["data.ios", "game.ios", "game.unx"])
def test_planner_maps_data_targets_from_the_selected_runtime(tmp_path, filename):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    source = mod_root / "replacement.win"
    source.write_text("replacement", encoding="utf-8")
    config = _config(
        [
            {
                "source": "${mod_path}/replacement.win",
                "target": f"${{game_path}}/chapter1_mac/{filename}",
                "type": "overwrite",
            }
        ]
    )

    expected = {
        "windows": game_root / "chapter1_windows" / "data.win",
        "linux": game_root / "chapter1_windows" / "game.unx",
        "macos": game_root / "chapter1_mac" / "game.ios",
    }
    for runtime, target in expected.items():
        target.parent.mkdir(exist_ok=True)
        target.write_text("original", encoding="utf-8")
        plan = build_mod_operation_plan(
            config,
            ModPathContext.create(
                mod_path=mod_root,
                game_path=game_root,
                game_data_path=None,
                user_path=tmp_path / "user",
                runtime=runtime,
            ),
        )

        assert plan.operations[0].target == target
        assert plan.findings == ()


def test_planner_reports_missing_source_and_distinguishes_patch_target(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "copy.txt").write_text("copy", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/missing.xdelta",
                    "target": "${game_path}/missing.win",
                    "type": "patch",
                },
                {
                    "source": "${mod_path}/copy.txt",
                    "target": "${game_path}/new/copy.txt",
                    "type": "overwrite",
                },
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
            platform="win32",
        ),
    )

    assert [(finding.severity, finding.code, finding.operation_index) for finding in plan.findings] == [
        ("error", "source_missing", 1),
        ("error", "target_missing", 1),
    ]


def test_planner_allows_later_patch_of_target_created_earlier(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "replacement.win").write_bytes(b"replacement")
    (mod_root / "patch.xdelta").write_bytes(b"patch")
    plan = build_mod_operation_plan(
        _config(
            [
                {"source": "${mod_path}/replacement.win", "target": "${game_path}/data.win", "type": "overwrite"},
                {"source": "${mod_path}/patch.xdelta", "target": "${game_path}/data.win", "type": "patch"},
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )
    assert not plan.has_errors
    assert not any(
        finding.operation_index == 2 and finding.code == "target_missing"
        for finding in plan.findings
    )


def test_planner_resolves_custom_path_aliases(tmp_path):
    mod_root = tmp_path / "mod"
    data_root = tmp_path / "data"
    mod_root.mkdir()
    data_root.mkdir()
    (mod_root / "settings.json").write_text("{}", encoding="utf-8")
    plan = build_mod_operation_plan(
        {
            **_config(
                [
                    {
                        "source": "${mod_path}/settings.json",
                        "target": "${saves_path}/settings.json",
                        "type": "overwrite",
                    }
                ]
            ),
            "placeholders": {"saves_path": "${user_path}/AppData/Local/Test"},
        },
        ModPathContext.create(
            mod_path=mod_root,
            game_path=None,
            game_data_path=data_root,
            user_path=tmp_path / "user",
        ),
    )

    assert plan.operations[0].target == tmp_path / "user" / "AppData" / "Local" / "Test" / "settings.json"
    assert plan.findings[0].code == "target_created"


@pytest.mark.parametrize(
    ("platform", "source", "target", "code"),
    [
        (
            "linux",
            "C:/Users/Example/mod.bin",
            "${game_path}/mod.bin",
            "source_root",
        ),
        (
            "darwin",
            "${mod_path}/source.bin",
            "C:/Games/Game/mod.bin",
            "target_root",
        ),
        (
            "win32",
            "${mod_path}/source.bin",
            "/home/example/mod.bin",
            "target_root",
        ),
    ],
)
def test_planner_rejects_foreign_literal_absolute_paths(
    tmp_path, platform, source, target, code
):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "source.bin").write_bytes(b"source")

    plan = build_mod_operation_plan(
        _config([{"source": source, "target": target, "type": "overwrite"}]),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
            platform=platform,
        ),
    )

    assert plan.operations == ()
    assert plan.findings[0].code == code


def test_planner_rejects_source_link_outside_placeholder_root(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    try:
        (mod_root / "source.bin").symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable")

    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/source.bin",
                    "target": "${game_path}/target.bin",
                    "type": "overwrite",
                }
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )

    assert plan.operations == ()
    assert plan.findings[0].code == "source_root"


def test_planner_checks_hashes_for_source_links(tmp_path):
    mod = tmp_path / "mod"
    game = tmp_path / "game"
    mod.mkdir()
    game.mkdir()
    (mod / "real.txt").write_text("payload", encoding="utf-8")
    try:
        (mod / "link.txt").symlink_to(mod / "real.txt")
    except OSError:
        pytest.skip("Symbolic links are unavailable")
    plan = build_mod_operation_plan(_config([{
        "source": "${mod_path}/link.txt", "target": "${game_path}/output.txt",
        "type": "overwrite", "source_hash": "sha256:" + "0" * 64,
    }]), ModPathContext.create(
        mod_path=mod, game_path=game, game_data_path=None, user_path=tmp_path / "user",
    ))

    assert {finding.code for finding in plan.findings} >= {"source_link", "source_hash"}


def test_planner_resolves_archive_members(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (game_root / "target.txt").write_text("original", encoding="utf-8")
    with zipfile.ZipFile(mod_root / "payload.zip", "w") as archive:
        archive.writestr("assets/replacement.txt", "replacement")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/payload.zip/assets/replacement.txt",
                    "target": "${game_path}/target.txt",
                    "type": "overwrite",
                },
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )

    assert isinstance(plan.operations[0].source, ArchiveVirtualPath)
    assert plan.findings == ()


def test_planner_checks_declared_source_and_target_hashes(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    source = mod_root / "source.txt"
    target = game_root / "target.txt"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")
    config = _config(
        [
            {
                "source": "${mod_path}/source.txt",
                "target": "${game_path}/target.txt",
                "type": "overwrite",
                "source_hash": sha256_path(source),
                "target_hash": sha256_path(target),
            }
        ]
    )
    context = ModPathContext.create(
        mod_path=mod_root,
        game_path=game_root,
        game_data_path=None,
        user_path=tmp_path / "user",
    )

    assert build_mod_operation_plan(config, context).findings == ()
    target.write_text("changed", encoding="utf-8")
    assert build_mod_operation_plan(config, context).findings[0].code == "target_hash"


def test_planner_accepts_patch_after_ordered_overwrite_to_new_target(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    (mod_root / "patch.xdelta").write_bytes(b"patch")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/generated.win",
                    "type": "overwrite",
                },
                {
                    "source": "${mod_path}/patch.xdelta",
                    "target": "${game_path}/generated.win",
                    "type": "patch",
                },
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )

    assert plan.findings == ()


def test_planner_rejects_source_target_overlap(tmp_path):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    (game_root / "assets").mkdir(parents=True)
    (game_root / "assets" / "input.txt").write_text("input", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${game_path}/assets/",
                    "target": "${game_path}/assets/output/",
                    "type": "extract",
                }
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )

    assert plan.findings[0].code == "source_target_overlap"


def test_profile_planner_flattens_selected_mods_in_profile_order(tmp_path):
    game_root = tmp_path / "game"
    game_root.mkdir()
    configs = {}
    contexts = {}
    for mod_id in ("first", "second"):
        mod_root = tmp_path / mod_id
        mod_root.mkdir()
        (mod_root / f"{mod_id}.txt").write_text(mod_id, encoding="utf-8")
        configs[mod_id] = {
            **_config(
                [
                    {
                        "source": f"${{mod_path}}/{mod_id}.txt",
                        "target": f"${{game_path}}/{mod_id}.txt",
                        "type": "overwrite",
                    }
                ]
            ),
            "id": mod_id,
        }
        contexts[mod_id] = ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        )

    plan = build_profile_operation_plan(configs, contexts, ["second", "first", "second"])

    assert [operation.index for operation in plan.operations] == [1, 2]
    names = []
    for operation in plan.operations:
        assert isinstance(operation.source, Path)
        names.append(operation.source.name)
    assert names == ["second.txt", "first.txt"]
