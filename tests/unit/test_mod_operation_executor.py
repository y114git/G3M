"""Tests for ordered operation mutation and recovery."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import zipfile
from dataclasses import replace

import pytest

from services.mod_operation_executor import (
    ModOperationExecutionError,
    ModOperationExecutor,
    ModOperationJournal,
    ModPatchMismatchError,
    ModRecoveryConflictError,
)
from utils.mod.archive import materialize_archive
from utils.mod.config import MOD_CONFIG_VERSION
from utils.mod.hashing import sha256_path
from utils.mod.operation_plan import ModPathContext, build_mod_operation_plan


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


def _plan(tmp_path, files: list[object]):
    mod_root = tmp_path / "mod"
    game_root = tmp_path / "game"
    mod_root.mkdir()
    game_root.mkdir()
    return mod_root, game_root, build_mod_operation_plan(
        _config(files),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
            runtime="windows",
        ),
    )


def test_executor_preserves_order_and_restores_original_target(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "first.txt").write_text("first", encoding="utf-8")
    (mod_root / "second.txt").write_text("second", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/first.txt",
                    "target": "${game_path}/target.txt",
                    "type": "overwrite",
                },
                {
                    "source": "${mod_path}/second.txt",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)

    assert target.read_text(encoding="utf-8") == "second"
    ModOperationJournal.load(journal.root).restore()
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("tamper_after_planning", [False, True])
def test_extract_source_hash_verifies_the_archive_bytes(tmp_path, tamper_after_planning):
    mod_root, game_root, _ = _plan(tmp_path, [])
    archive_path = mod_root / "payload.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("payload.txt", "original")
    plan = build_mod_operation_plan(
        _config([{
            "source": "${mod_path}/payload.zip",
            "target": "${game_path}/",
            "type": "extract",
            "source_hash": sha256_path(archive_path),
        }]),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root,
            game_data_path=None, user_path=tmp_path / "user",
        ),
    )
    assert not plan.has_errors
    if tamper_after_planning:
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("payload.txt", "tampered")
        with pytest.raises(ModOperationExecutionError, match="source hash does not match"):
            ModOperationExecutor(tmp_path / "session").execute(plan)
        assert not (game_root / "payload.txt").exists()
    else:
        ModOperationExecutor(tmp_path / "session").execute(plan)
        assert (game_root / "payload.txt").read_text(encoding="utf-8") == "original"


def test_extract_from_and_into_archive_roots_preserves_the_archive_file(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    source = mod_root / "source.zip"
    target = game_root / "target.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("payload.txt", "payload")
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("original.txt", "original")
    original_target = target.read_bytes()
    plan = build_mod_operation_plan(
        _config([{
            "source": "${mod_path}/source.zip/",
            "target": "${game_path}/target.zip/", "type": "extract",
        }]),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root,
            game_data_path=None, user_path=tmp_path / "user",
        ),
    )

    assert not plan.has_errors
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)

    assert target.is_file()
    with zipfile.ZipFile(target) as archive:
        assert archive.read("payload.txt") == b"payload"
        assert archive.read("original.txt") == b"original"
    journal.restore()
    assert target.read_bytes() == original_target


@pytest.mark.parametrize("create_parent_with_earlier_operation", [False, True])
def test_forced_recovery_preserves_external_files_under_new_ancestors(tmp_path, create_parent_with_earlier_operation):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "payload.txt").write_text("mod", encoding="utf-8")
    operations = []
    if create_parent_with_earlier_operation:
        operations.append({
            "source": "${mod_path}/payload.txt",
            "target": "${game_path}/new_parent/first.txt", "type": "overwrite",
        })
    operations.append({
        "source": "${mod_path}/payload.txt",
        "target": "${game_path}/new_parent/child/payload.txt", "type": "hard-overwrite",
    })
    plan = build_mod_operation_plan(
        _config(operations),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root,
            game_data_path=None, user_path=tmp_path / "user",
        ),
    )
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    outer_save = game_root / "new_parent" / "save.txt"
    inner_save = game_root / "new_parent" / "child" / "save.txt"
    for save in (outer_save, inner_save):
        save.write_text("game save", encoding="utf-8")

    with pytest.raises(ModRecoveryConflictError, match="changed outside"):
        journal.restore()
    ModOperationJournal.load(journal.root).restore(force=True)

    for save in (outer_save, inner_save):
        assert save.read_text(encoding="utf-8") == "game save"
    assert not (game_root / "new_parent" / "child" / "payload.txt").exists()
    assert not (game_root / "new_parent" / "first.txt").exists()


def test_forced_recovery_keeps_saves_inside_dereferenced_source_directories(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "mod.txt").write_text("mod", encoding="utf-8")
    source = mod_root / "source"
    source.mkdir()
    try:
        (source / "linked").symlink_to(payload, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    plan = build_mod_operation_plan(
        _config([{
            "source": "${mod_path}/source/",
            "target": "${game_path}/deployed/", "type": "hard-extract",
        }]),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root,
            game_data_path=None, user_path=tmp_path / "user",
        ),
    )
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    save = game_root / "deployed" / "linked" / "save.txt"
    save.write_text("game save", encoding="utf-8")

    ModOperationJournal.load(journal.root).restore(force=True)

    assert save.read_text(encoding="utf-8") == "game save"
    assert not (save.parent / "mod.txt").exists()
    assert (payload / "mod.txt").read_text(encoding="utf-8") == "mod"


def test_discarded_journal_keeps_applied_files_without_recovery_data(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [{
                "source": "${mod_path}/replacement.txt",
                "target": "${game_path}/target.txt",
                "type": "overwrite",
            }]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    journal.checkpoint()
    journal.discard()

    assert target.read_text(encoding="utf-8") == "replacement"
    assert not journal.root.exists()


def test_executor_reports_completed_operations_in_visible_order(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    for name in ("one.txt", "two.txt"):
        (mod_root / name).write_text(name, encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/one.txt",
                    "target": "${game_path}/one.txt",
                    "type": "overwrite",
                },
                {
                    "source": "${mod_path}/two.txt",
                    "target": "${game_path}/two.txt",
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
    completed = []

    ModOperationExecutor(tmp_path / "session").execute(
        plan,
        progress=lambda done, total, operation: completed.append(
            (done, total, operation.index)
        ),
    )

    assert completed == [(1, 2, 1), (2, 2, 2)]


def test_executor_merges_simultaneous_data_patches_in_priority_order(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    target = game_root / "data.win"
    target.write_bytes(b"original")
    (mod_root / "first.xdelta").write_bytes(b"first")
    (mod_root / "second.xdelta").write_bytes(b"second")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/first.xdelta",
                    "target": "${game_path}/data.win",
                    "type": "patch",
                },
                {
                    "source": "${mod_path}/second.xdelta",
                    "target": "${game_path}/data.win",
                    "type": "patch",
                },
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
            runtime="windows",
        ),
    )
    first, second = plan.operations
    plan = type(plan)(
        (
            replace(first, merge_group=0, merge_priority=1),
            replace(second, merge_group=0, merge_priority=0),
        ),
        (),
    )
    received = []

    def merge(target_path, patches, output_path):
        received.append((target_path, patches))
        output_path.write_bytes(b"merged")
        return True

    journal = ModOperationExecutor(tmp_path / "session", merger=merge).execute(plan)

    assert [path.name for path in received[0][1]] == ["second.xdelta", "first.xdelta"]
    assert target.read_bytes() == b"merged"
    journal.restore()
    assert target.read_bytes() == b"original"


def test_executor_merges_simultaneous_patches_inside_archive_member(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    archive_path = game_root / "payload.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("data.win", b"original")
    (mod_root / "first.xdelta").write_bytes(b"first")
    (mod_root / "second.xdelta").write_bytes(b"second")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/first.xdelta",
                    "target": "${game_path}/payload.zip/data.win",
                    "type": "patch",
                },
                {
                    "source": "${mod_path}/second.xdelta",
                    "target": "${game_path}/payload.zip/data.win",
                    "type": "patch",
                },
            ]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
            runtime="windows",
        ),
    )
    first, second = plan.operations
    plan = type(plan)(
        (
            replace(first, merge_group=0, merge_priority=1),
            replace(second, merge_group=0, merge_priority=0),
        ),
        (),
    )
    received = []

    def merge(target_path, patches, output_path):
        received.append((target_path, patches))
        output_path.write_bytes(b"merged")
        return True

    journal = ModOperationExecutor(tmp_path / "session", merger=merge).execute(plan)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("data.win") == b"merged"
    assert [path.name for path in received[0][1]] == ["second.xdelta", "first.xdelta"]
    journal.restore()
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("data.win") == b"original"


def test_executor_requires_recovery_before_reusing_a_session_root(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target.txt",
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
    root = tmp_path / "session"
    journal = ModOperationExecutor(root).execute(plan)

    with pytest.raises(ModOperationExecutionError, match="requires recovery"):
        ModOperationExecutor(root)

    journal.restore()
    ModOperationExecutor(root).execute(plan)
    assert target.read_text(encoding="utf-8") == "replacement"


def test_executor_applies_soft_and_hard_directory_operations(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    source = mod_root / "source"
    source.mkdir()
    (source / "same.txt").write_text("mod", encoding="utf-8")
    (source / "new.txt").write_text("new", encoding="utf-8")
    target = game_root / "target"
    target.mkdir()
    (target / "same.txt").write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/source/",
                    "target": "${game_path}/target/",
                    "type": "soft-extract",
                },
                {
                    "source": "${mod_path}/source/new.txt",
                    "target": "${game_path}/target/",
                    "type": "hard-overwrite",
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

    ModOperationExecutor(tmp_path / "session").execute(plan)

    assert sorted(path.name for path in target.iterdir()) == ["new.txt"]


def test_executor_hard_overwrite_file_target_clears_its_parent_and_restores_it(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target_folder = game_root / "target"
    target_folder.mkdir()
    target = target_folder / "target.txt"
    target.write_text("original", encoding="utf-8")
    sibling = target_folder / "other.txt"
    sibling.write_text("other", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target/target.txt",
                    "type": "hard-overwrite",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)

    assert target.read_text(encoding="utf-8") == "replacement"
    assert not sibling.exists()
    journal.restore()
    assert target.read_text(encoding="utf-8") == "original"
    assert sibling.read_text(encoding="utf-8") == "other"


def test_forced_restore_keeps_game_files_beside_hard_overwrite_target(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target_folder = game_root / "target"
    target_folder.mkdir()
    target = target_folder / "target.txt"
    target.write_text("original", encoding="utf-8")
    sibling = target_folder / "other.txt"
    sibling.write_text("other", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target/target.txt",
                    "type": "hard-overwrite",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    journal.checkpoint()
    game_file = target_folder / "save.dat"
    game_file.write_text("progress", encoding="utf-8")

    with pytest.raises(ModRecoveryConflictError):
        journal.restore()

    journal.restore(force=True)

    assert target.read_text(encoding="utf-8") == "original"
    assert sibling.read_text(encoding="utf-8") == "other"
    assert game_file.read_text(encoding="utf-8") == "progress"


def test_forced_restore_keeps_game_files_in_a_new_hard_overwrite_directory(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "new" / "target.txt"
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/new/target.txt",
                    "type": "hard-overwrite",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    journal.checkpoint()
    game_file = target.parent / "save.dat"
    game_file.write_text("progress", encoding="utf-8")

    with pytest.raises(ModRecoveryConflictError):
        journal.restore()

    journal.restore(force=True)

    assert not target.exists()
    assert game_file.read_text(encoding="utf-8") == "progress"


def test_forced_restore_keeps_game_files_in_hard_overwrite_target_directory(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target"
    target.mkdir()
    (target / "original.txt").write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target/",
                    "type": "hard-overwrite",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    journal.checkpoint()
    game_file = target / "save.dat"
    game_file.write_text("progress", encoding="utf-8")

    with pytest.raises(ModRecoveryConflictError):
        journal.restore()

    journal.restore(force=True)

    assert (target / "original.txt").read_text(encoding="utf-8") == "original"
    assert not (target / "replacement.txt").exists()
    assert game_file.read_text(encoding="utf-8") == "progress"


def test_executor_keeps_ordered_hard_overwrite_outputs_in_one_directory(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "first.txt").write_text("first", encoding="utf-8")
    (mod_root / "second.txt").write_text("second", encoding="utf-8")
    target = game_root / "target"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/first.txt",
                    "target": "${game_path}/target/first.txt",
                    "type": "hard-overwrite",
                },
                {
                    "source": "${mod_path}/second.txt",
                    "target": "${game_path}/target/second.txt",
                    "type": "hard-overwrite",
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

    ModOperationExecutor(tmp_path / "session").execute(plan)

    assert (target / "first.txt").read_text(encoding="utf-8") == "first"
    assert (target / "second.txt").read_text(encoding="utf-8") == "second"
    assert not (target / "old.txt").exists()


def test_executor_rebuilds_and_restores_archive_targets(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    archive_path = game_root / "content.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("assets/original.txt", "original")
    original = archive_path.read_bytes()
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/content.zip/assets/replacement.txt",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("assets/replacement.txt") == b"replacement"
    journal.restore()
    assert archive_path.read_bytes() == original


def test_executor_writes_and_restores_an_lzma_target_archive(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    source = mod_root / "payload.bin"
    source.write_bytes(b"payload")
    archive = game_root / "payload.lzma"
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/payload.bin",
                    "target": "${game_path}/payload.lzma",
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

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    materialized = tmp_path / "materialized"
    materialize_archive(archive, materialized)

    assert (materialized / "payload").read_bytes() == b"payload"
    journal.restore()
    assert not archive.exists()


def test_executor_restores_after_failed_patch(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "change.patch").write_text("patch", encoding="utf-8")
    target = game_root / "target.bin"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/change.patch",
                    "target": "${game_path}/target.bin",
                    "type": "patch",
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

    with pytest.raises(ModOperationExecutionError, match="did not produce"):
        ModOperationExecutor(tmp_path / "session", patcher=lambda *_: False).execute(plan)

    assert target.read_text(encoding="utf-8") == "original"


def test_executor_names_the_mod_whose_patch_does_not_fit_and_restores(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "change.patch").write_text("patch", encoding="utf-8")
    target = game_root / "target.bin"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config([{"source": "${mod_path}/change.patch", "target": "${game_path}/target.bin", "type": "patch"}]),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root, game_data_path=None, user_path=tmp_path / "user"
        ),
    )
    plan = replace(plan, operations=tuple(replace(o, mod_id="test_mod") for o in plan.operations))

    def patcher(*_args):
        raise ModOperationExecutionError("patch backend failed: xdelta3: target window checksum mismatch")

    with pytest.raises(ModPatchMismatchError) as caught:
        ModOperationExecutor(tmp_path / "session", patcher=patcher).execute(plan)

    assert (caught.value.mod_id, caught.value.patch) == ("test_mod", "change.patch")
    assert target.read_text(encoding="utf-8") == "original"


def test_executor_passes_a_nonexistent_output_path_to_patchers(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "change.patch").write_text("patch", encoding="utf-8")
    target = game_root / "target.bin"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/change.patch",
                    "target": "${game_path}/target.bin",
                    "type": "patch",
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

    def patcher(_target, _source, output):
        assert not output.exists()
        assert output.suffix == _target.suffix
        output.write_text("patched", encoding="utf-8")
        return True

    ModOperationExecutor(tmp_path / "session", patcher=patcher).execute(plan)

    assert target.read_text(encoding="utf-8") == "patched"


def test_journal_preserves_external_changes_for_explicit_recovery(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target.txt",
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
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    journal.checkpoint()
    target.write_text("external", encoding="utf-8")

    with pytest.raises(ModRecoveryConflictError):
        journal.restore()

    assert target.read_text(encoding="utf-8") == "external"
    journal.retire()
    assert ModOperationJournal.load(tmp_path / "session").state == "retired"
    assert not (tmp_path / "session" / "backups").exists()
    ModOperationExecutor(tmp_path / "session")


def test_plan_warns_about_direct_absolute_operation_paths(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    source = mod_root / "replacement.txt"
    source.write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    direct_source = source.as_posix()
    direct_target = target.as_posix()
    plan = build_mod_operation_plan(
        _config(
            [{"source": direct_source, "target": direct_target, "type": "overwrite"}]
        ),
        ModPathContext.create(
            mod_path=mod_root,
            game_path=game_root,
            game_data_path=None,
            user_path=tmp_path / "user",
        ),
    )

    assert {finding.code for finding in plan.findings} >= {
        "direct_absolute_source",
        "direct_absolute_target",
    }


def test_journal_checkpoint_accepts_completed_g3m_work(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    plan = build_mod_operation_plan(
        _config(
            [
                {
                    "source": "${mod_path}/replacement.txt",
                    "target": "${game_path}/target.txt",
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
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    target.write_text("plugin", encoding="utf-8")

    journal.checkpoint()
    journal.restore()

    assert target.read_text(encoding="utf-8") == "original"


def test_executor_dereferences_source_links_and_restores_target_links(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    payload = mod_root / "payload.txt"
    payload.write_text("linked source", encoding="utf-8")
    target_payload = tmp_path / "target.txt"
    target_payload.write_text("original target", encoding="utf-8")
    target = game_root / "target.txt"
    try:
        (mod_root / "source.txt").symlink_to(payload)
        target.symlink_to(target_payload)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    plan = build_mod_operation_plan(
        _config(
            [{"source": "${mod_path}/source.txt", "target": "${game_path}/target.txt", "type": "overwrite"}]
        ),
        ModPathContext.create(mod_path=mod_root, game_path=game_root, game_data_path=None, user_path=tmp_path / "user"),
    )

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)

    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "linked source"
    journal.restore()
    assert target.is_symlink()
    assert target.read_text(encoding="utf-8") == "original target"


def test_executor_replaces_a_hardlinked_target_without_mutating_its_peer(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "replacement.txt").write_text("replacement", encoding="utf-8")
    target = game_root / "target.txt"
    peer = game_root / "peer.txt"
    target.write_text("original", encoding="utf-8")
    try:
        os.link(target, peer)
    except OSError:
        pytest.skip("hard links are unavailable")
    plan = build_mod_operation_plan(
        _config(
            [{"source": "${mod_path}/replacement.txt", "target": "${game_path}/target.txt", "type": "overwrite"}]
        ),
        ModPathContext.create(mod_path=mod_root, game_path=game_root, game_data_path=None, user_path=tmp_path / "user"),
    )

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)

    assert target.read_text(encoding="utf-8") == "replacement"
    assert peer.read_text(encoding="utf-8") == "original"
    journal.restore()
    assert target.read_text(encoding="utf-8") == "original"
    assert peer.read_text(encoding="utf-8") == "original"


def _extract_into_game_folder(tmp_path, game_folder_name="addons"):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "files" / "Hornet").mkdir(parents=True)
    (mod_root / "files" / "Hornet" / "icon.png").write_text("mod", encoding="utf-8")
    target = game_root / game_folder_name
    target.mkdir()
    (target / "Stock").mkdir()
    (target / "Stock" / "icon.png").write_text("stock", encoding="utf-8")
    subprocess.run(["attrib", "+R", str(target)], check=True)
    plan = build_mod_operation_plan(
        _config([{"source": "${mod_path}/files/", "target": f"${{game_path}}/{game_folder_name}/", "type": "extract"}]),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root, game_data_path=None, user_path=tmp_path / "user"
        ),
    )
    return target, plan


@pytest.mark.skipif(sys.platform != "win32", reason="the read-only folder attribute is a Windows one")
def test_read_only_game_folder_is_restored_after_the_game_closes(tmp_path):
    target, plan = _extract_into_game_folder(tmp_path)
    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    assert (target / "Hornet" / "icon.png").is_file()

    journal.checkpoint()
    journal.restore()

    assert not (target / "Hornet").exists()
    assert (target / "Stock" / "icon.png").read_text(encoding="utf-8") == "stock"


@pytest.mark.skipif(sys.platform != "win32", reason="the read-only folder attribute is a Windows one")
def test_next_launch_starts_after_a_session_with_a_read_only_game_folder(tmp_path):
    target, plan = _extract_into_game_folder(tmp_path)
    session = tmp_path / "session"
    journal = ModOperationExecutor(session).execute(plan)
    journal.checkpoint()
    journal.restore()

    second = ModOperationExecutor(session).execute(plan)
    second.checkpoint()
    second.restore()

    assert not (target / "Hornet").exists()
    assert (target / "Stock" / "icon.png").read_text(encoding="utf-8") == "stock"


@pytest.mark.skipif(sys.platform != "win32", reason="the read-only folder attribute is a Windows one")
def test_stale_backup_of_a_read_only_folder_does_not_block_the_next_launch(tmp_path):
    target, plan = _extract_into_game_folder(tmp_path, "skins")
    session = tmp_path / "session"
    ModOperationExecutor(session).execute(plan)
    # a crash leaves the session unrestored; the user keeps external changes, which retires it
    ModOperationJournal.load(session).retire()

    journal = ModOperationExecutor(session).execute(plan)
    journal.checkpoint()
    journal.restore()

    assert (target / "Stock" / "icon.png").read_text(encoding="utf-8") == "stock"


@pytest.mark.skipif(sys.platform != "win32", reason="the read-only file attribute is a Windows one")
def test_read_only_target_file_is_overwritten_and_restored(tmp_path):
    mod_root, game_root, _ = _plan(tmp_path, [])
    (mod_root / "new.txt").write_text("mod", encoding="utf-8")
    target = game_root / "target.txt"
    target.write_text("original", encoding="utf-8")
    subprocess.run(["attrib", "+R", str(target)], check=True)
    plan = build_mod_operation_plan(
        _config([{"source": "${mod_path}/new.txt", "target": "${game_path}/target.txt", "type": "overwrite"}]),
        ModPathContext.create(
            mod_path=mod_root, game_path=game_root, game_data_path=None, user_path=tmp_path / "user"
        ),
    )

    journal = ModOperationExecutor(tmp_path / "session").execute(plan)
    assert target.read_text(encoding="utf-8") == "mod"
    journal.checkpoint()
    journal.restore()

    assert target.read_text(encoding="utf-8") == "original"


def test_replace_file_replaces_a_read_only_target(tmp_path):
    from services.mod_operation_executor import replace_file

    target = tmp_path / "data.win"
    target.write_text("old", encoding="utf-8")
    os.chmod(target, stat.S_IREAD)
    source = tmp_path / "new.tmp"
    source.write_text("new", encoding="utf-8")

    replace_file(source, target)

    assert target.read_text(encoding="utf-8") == "new"
