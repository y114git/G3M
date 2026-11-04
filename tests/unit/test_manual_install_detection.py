from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zipfile
import zlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ui.dialogs.manual_install.detection import (
    detect_operations,
    pack_patch,
    scan_files,
    scan_import_files,
    verify_operations,
)
from utils.mod.operation_plan import ModPathContext, portable_operation_path


def _context(tmp_path):
    game, source = tmp_path / "game", tmp_path / "mod"
    game.mkdir()
    source.mkdir()
    return ModPathContext.create(
        mod_path=source,
        game_path=game,
        game_data_path=game / "saves",
        user_path=tmp_path,
    )


def _integer(value):
    result = [value & 127]
    while value := value >> 7:
        result.append((value & 127) | 128)
    return bytes(reversed(result))


def _xdelta(path, result, *, checksum=True, source=True):
    # A valid VCDIFF ADD window. Probing verifies its output independently of the backend.
    instruction = b"\x01" + _integer(len(result))
    delta = (
        _integer(len(result))
        + b"\0"
        + _integer(len(result))
        + _integer(len(instruction))
        + b"\0"
    )
    if checksum:
        delta += struct.pack(">I", zlib.adler32(result))
    delta += result + instruction
    path.write_bytes(
        b"\xd6\xc3\xc4\0\0"
        + bytes([(4 if checksum else 0) | (1 if source else 0)])
        + (b"\x01\x00" if source else b"")
        + _integer(len(delta))
        + delta
    )


def _g3mpatch(path, original, modified=b"patched", *, md5=True):
    manifest = {
        "original": {"size": len(original)},
        "modified": {"md5": hashlib.md5(modified, usedforsecurity=False).hexdigest()},
    }
    if md5:
        manifest["original"]["md5"] = hashlib.md5(
            original, usedforsecurity=False
        ).hexdigest()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("g3mpatch.json", json.dumps(manifest))


def test_portable_paths_choose_specific_roots_and_match_whole_components(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    assert (
        portable_operation_path(context.game_data_path / "slot.sav", context)
        == "${game_data_path}/slot.sav"
    )
    assert (
        portable_operation_path(context.game_path / "data.win", context)
        == "${game_path}/data.win"
    )
    assert (
        portable_operation_path(tmp_path / "game_other" / "data.win", context)
        == "${user_path}/game_other/data.win"
    )
    assert (
        portable_operation_path(context.mod_path / "patch.g3mpatch", context)
        == "${mod_path}/patch.g3mpatch"
    )


@pytest.mark.parametrize("count", [1, 2])
def test_xdelta_stops_at_first_checksum_verified_output(tmp_path, count):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    for index in range(count):
        (context.game_path / f"base{index}.bin").write_bytes(b"original")
    patch = context.mod_path / "mod.xdelta"
    _xdelta(patch, b"patched")

    attempts = []

    def apply(_kind, base, _patch, output):
        attempts.append(base.read_bytes())
        assert base.parent != context.game_path
        output.write_bytes(b"patched")
        return True

    result = detect_operations(scan_import_files(context.mod_path), context, apply)
    assert result["mod.xdelta"]["target"] == "${game_path}/base0.bin"
    assert result["mod.xdelta"]["target_hash"].startswith("sha256:")
    assert attempts == [b"original"]


@pytest.mark.parametrize(("checked", "output"), [(False, b"patched"), (True, b"wrong")])
def test_xdelta_without_proof_is_unassigned(tmp_path, checked, output):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "data.bin").write_bytes(b"original")
    _xdelta(context.mod_path / "patch.xdelta", b"patched", checksum=checked)

    def apply(_kind, _base, _patch, destination):
        destination.write_bytes(output)
        return True

    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}


def test_g3mpatch_uses_manifest_and_checks_modified_output(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "right.bin").write_bytes(b"original")
    (context.game_path / "wrong.bin").write_bytes(b"other---")
    _g3mpatch(context.mod_path / "patch.g3mpatch", b"original")
    attempted = []

    def apply(kind, base, _patch, output):
        attempted.append((kind, base.read_bytes()))
        output.write_bytes(b"patched")
        return True

    result = detect_operations(scan_import_files(context.mod_path), context, apply)
    assert result["patch.g3mpatch"]["target"] == "${game_path}/right.bin"
    assert attempted == [("g3mpatch", b"original")]

    def wrong_output(_kind, _base, _patch, output):
        output.write_bytes(b"incomplete")
        return True

    assert (
        detect_operations(scan_import_files(context.mod_path), context, wrong_output)
        == {}
    )


def test_manifest_without_hash_does_not_guess(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "data.bin").write_bytes(b"original")
    _g3mpatch(context.mod_path / "patch.g3mpatch", b"original", md5=False)
    apply = Mock(return_value=True)
    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}
    apply.assert_not_called()


@pytest.mark.parametrize("kind", ["xdelta", "g3mpatch"])
def test_detection_prefers_game_folder_and_stops_before_later_files(tmp_path, monkeypatch, kind):
    from ui.dialogs.manual_install import detection

    context = replace(_context(tmp_path), game_data_path=tmp_path / "game_data")
    assert context.game_path is not None
    assert context.game_data_path is not None
    assert context.mod_path is not None
    assert context.game_data_path is not None
    context.game_data_path.mkdir()
    primary = context.game_path / "a" / "deep" / "renamed.bin"
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b"original")
    assert context.game_path is not None
    (context.game_path / "z").mkdir()
    (context.game_path / "z" / "duplicate.bin").write_bytes(b"original")
    assert context.game_data_path is not None
    (context.game_data_path / "duplicate.bin").write_bytes(b"original")
    patch = context.mod_path / f"patch.{kind}"
    (_g3mpatch if kind == "g3mpatch" else _xdelta)(patch, b"original" if kind == "g3mpatch" else b"patched")
    visited = []
    walk = detection.os.walk

    def observed_walk(*args, **kwargs):
        for entry in walk(*args, **kwargs):
            if Path(args[0]) in (context.game_path, context.game_data_path):
                visited.append(Path(entry[0]))
            yield entry

    monkeypatch.setattr(detection.os, "walk", observed_walk)
    attempts = []

    def apply(_kind, base, _patch, output):
        attempts.append(base.read_bytes())
        output.write_bytes(b"patched")
        return True

    result = detect_operations([(str(patch), patch.name)], context, apply)
    assert result[patch.name]["target"] == "${game_path}/a/deep/renamed.bin"
    assert attempts == [b"original"]
    assert visited == [context.game_path, primary.parent.parent, primary.parent]


def test_g3mpatch_hash_search_reaches_deep_target_after_many_files(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    for index in range(100):
        (context.game_path / f"wrong{index}.bin").write_bytes(b"wrong---")
    target = context.game_path / "nested" / "deeper" / "anything.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    patch = context.mod_path / "patch.g3mpatch"
    _g3mpatch(patch, b"original")
    attempts = []

    def apply(_kind, base, _patch, output):
        attempts.append(base.read_bytes())
        output.write_bytes(b"patched")
        return True

    result = detect_operations([(str(patch), patch.name)], context, apply)
    assert result[patch.name]["target"] == "${game_path}/nested/deeper/anything.bin"
    assert attempts == [b"original"]


def test_unreadable_candidate_does_not_block_game_data_fallback(tmp_path, monkeypatch):
    from ui.dialogs.manual_install import detection

    context = replace(_context(tmp_path), game_data_path=tmp_path / "game_data")
    assert context.game_path is not None
    assert context.game_data_path is not None
    assert context.mod_path is not None
    assert context.game_data_path is not None
    context.game_data_path.mkdir()
    assert context.game_path is not None
    unreadable = context.game_path / "blocked.bin"
    unreadable.write_bytes(b"original")
    assert context.game_data_path is not None
    (context.game_data_path / "base.bin").write_bytes(b"original")
    patch = context.mod_path / "patch.g3mpatch"
    _g3mpatch(patch, b"original")
    md5 = detection._md5

    def read_hash(path, cancelled):
        if path == unreadable:
            raise PermissionError
        return md5(path, cancelled)

    monkeypatch.setattr(detection, "_md5", read_hash)

    def apply(_kind, _base, _patch, output):
        output.write_bytes(b"patched")
        return True

    result = detect_operations([(str(patch), patch.name)], context, apply)
    assert result[patch.name]["target"] == "${game_data_path}/base.bin"


def test_cancellation_during_folder_walk_never_opens_secondary_root(tmp_path, monkeypatch):
    from ui.dialogs.manual_install import detection

    context = replace(_context(tmp_path), game_data_path=tmp_path / "game_data")
    assert context.game_path is not None
    assert context.game_data_path is not None
    assert context.mod_path is not None
    assert context.game_data_path is not None
    context.game_data_path.mkdir()
    assert context.game_path is not None
    (context.game_path / "nested").mkdir()
    (context.game_path / "nested" / "base.bin").write_bytes(b"original")
    patch = context.mod_path / "patch.g3mpatch"
    _g3mpatch(patch, b"original")
    cancelled = [False]
    visited = []
    walk = detection.os.walk

    def cancelling_walk(*args, **kwargs):
        for entry in walk(*args, **kwargs):
            if Path(args[0]) in (context.game_path, context.game_data_path):
                visited.append(Path(entry[0]))
                cancelled[0] = True
            yield entry

    monkeypatch.setattr(detection.os, "walk", cancelling_walk)
    apply = Mock()
    assert detect_operations([(str(patch), patch.name)], context, apply, cancelled=lambda: cancelled[0]) == {}
    assert visited == [context.game_path]
    apply.assert_not_called()


def test_overwrite_detection_uses_data_folder_with_game_folder_priority(tmp_path):
    context = replace(_context(tmp_path), game_data_path=tmp_path / "game_data")
    assert context.game_path is not None
    assert context.game_data_path is not None
    assert context.mod_path is not None
    primary = context.game_path / "nested" / "asset.bin"
    secondary = context.game_data_path / "nested" / "asset.bin"
    for path in (primary, secondary):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"old")
    source = context.mod_path / "nested" / "asset.bin"
    source.parent.mkdir()
    source.write_bytes(b"new")
    files = scan_import_files(context.mod_path)
    apply = Mock()
    assert detect_operations(files, context, apply)["nested/asset.bin"]["target"] == "${game_path}/nested/asset.bin"
    primary.unlink()
    assert detect_operations(files, context, apply)["nested/asset.bin"]["target"] == "${game_data_path}/nested/asset.bin"
    apply.assert_not_called()


def test_known_relative_file_destinations_do_not_walk_game_directories(tmp_path, monkeypatch):
    from ui.dialogs.manual_install import detection

    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    for root in (context.game_path, context.mod_path):
        (root / "assets").mkdir()
        for index in range(100):
            (root / "assets" / f"file{index}.bin").write_bytes(b"content")
    files = scan_import_files(context.mod_path)
    walk = detection.os.walk

    def no_game_walk(root, *args, **kwargs):
        assert Path(root) not in (context.game_path, context.game_data_path)
        return walk(root, *args, **kwargs)

    monkeypatch.setattr(detection.os, "walk", no_game_walk)
    result = detect_operations(files, context, Mock())
    assert len(result) == 100
    assert all(entry["target"].startswith("${game_path}/assets/") for entry in result.values())


@pytest.mark.parametrize("stage", ["copy", "md5", "sha256", "checksum"])
def test_large_file_reads_and_copy_honor_cancellation(tmp_path, stage):
    from ui.dialogs.manual_install import detection

    source = tmp_path / "large.bin"
    source.write_bytes(b"a" * (3 * 1024 * 1024))
    calls = []

    def cancelled():
        calls.append(True)
        return len(calls) >= 3

    with pytest.raises(InterruptedError):
        if stage == "copy":
            detection.copy_file(source, tmp_path / "copy.bin", cancelled)
        elif stage == "md5":
            detection._md5(source, cancelled)
        elif stage == "sha256":
            detection.sha256_path(source, cancelled=cancelled)
        else:
            detection._output_matches(source, [(source.stat().st_size, 0)], cancelled)
    assert len(calls) == 3


def test_recursive_scan_excludes_symlinks_and_junctions(tmp_path, monkeypatch):
    root = tmp_path / "game"
    root.mkdir()
    for name in ("linked", "junction", "normal"):
        (root / name).mkdir()
        (root / name / "base.bin").write_bytes(b"original")
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "linked")
    monkeypatch.setattr(Path, "is_junction", lambda path: path.name == "junction")
    assert [relative for _, relative in scan_files(root)] == ["normal/base.bin"]


def test_timed_out_probe_is_not_assigned(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "one.bin").write_bytes(b"one")
    (context.game_path / "two.bin").write_bytes(b"two")
    _xdelta(context.mod_path / "patch.xdelta", b"patched")

    def apply(_kind, base, _patch, output):
        return None

    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}


def test_game_files_are_private_probe_inputs(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    original = context.game_path / "data.bin"
    original.write_bytes(b"original")
    _xdelta(context.mod_path / "patch.xdelta", b"patched")

    def apply(_kind, base, _patch, _output):
        base.write_bytes(b"backend changed its input")
        return False

    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}
    assert original.read_bytes() == b"original"


def test_unpacked_g3mpatch_is_one_portable_source(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    folder = context.mod_path / "patch"
    (folder / "CodeEntries").mkdir(parents=True)
    (folder / "g3mpatch.json").write_text('{"original": {}}', encoding="utf-8")
    (folder / "CodeEntries" / "code.gml").write_text("return 1;", encoding="utf-8")
    files = scan_import_files(context.mod_path)
    assert files == [(str(folder), "patch.g3mpatch")]
    output = tmp_path / "packed.g3mpatch"
    pack_patch(folder, output)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"g3mpatch.json", "CodeEntries/code.gml"}
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
        assert all(info.create_system == 3 and info.external_attr == 0o600 << 16 and info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
    repeated = tmp_path / "repeated.g3mpatch"
    (folder / "g3mpatch.json").touch()
    pack_patch(folder, repeated)
    assert output.read_bytes() == repeated.read_bytes()
    nested_output = folder / "packed.g3mpatch"
    pack_patch(folder, nested_output)
    assert output.read_bytes() == nested_output.read_bytes()
    nested_output.unlink()
    alternative = context.mod_path / "PATCH.g3mpatch"
    alternative.write_bytes(b"packed alternative")
    files = scan_import_files(context.mod_path)
    assert len({relative.casefold() for _source, relative in files}) == len(files)
    from ui.dialogs.manual_install.workers import write_import

    config = {
        "config_version": "2.0.0",
        "id": "collision_test",
        "name": "Collision test",
        "version": "1.0.0",
        "authors": [],
        "game": "undertale",
        "files": [],
    }
    saved = write_import(
        files, config, tmp_path / "library", import_root=context.mod_path
    )
    assert (saved / "files/PATCH.g3mpatch").read_bytes() == b"packed alternative"
    with zipfile.ZipFile(saved / "files/patch_patch.g3mpatch") as archive:
        assert archive.read("CodeEntries/code.gml") == b"return 1;"


def test_exact_paths_are_assigned_but_alternatives_and_executables_are_not(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "music").mkdir()
    (context.game_path / "music" / "battle.ogg").write_bytes(b"old")
    (context.game_path / "Game.exe").write_bytes(b"exe")
    for wrapper in ("one", "two"):
        folder = context.mod_path / wrapper / "music"
        folder.mkdir(parents=True)
        (folder / "battle.ogg").write_bytes(b"new")
    (context.mod_path / "Game.exe").write_bytes(b"replacement")
    apply = Mock()
    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}
    files = scan_import_files(context.mod_path / "one")
    assert (
        detect_operations(files, context, apply)["music/battle.ogg"]["target"]
        == "${game_path}/music/battle.ogg"
    )


def test_cancellation_does_not_assign_a_partially_checked_patch(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "data.bin").write_bytes(b"original")
    _xdelta(context.mod_path / "patch.xdelta", b"patched")
    cancelled = [False]

    def apply(_kind, _base, _patch, output):
        output.write_bytes(b"patched")
        cancelled[0] = True
        return True

    assert (
        detect_operations(
            scan_import_files(context.mod_path),
            context,
            apply,
            cancelled=lambda: cancelled[0],
        )
        == {}
    )


def test_xdelta_source_segments_exclude_impossible_bases(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "too-small.bin").write_bytes(b"small")
    (context.game_path / "large.bin").write_bytes(b"b" * 120)
    patch = context.mod_path / "patch.xdelta"
    _xdelta(patch, b"patched", source=False)
    raw = patch.read_bytes()
    patch.write_bytes(raw[:5] + b"\x05" + _integer(100) + _integer(20) + raw[6:])
    attempted = []

    def apply(_kind, base, _source, output):
        attempted.append(base.stat().st_size)
        output.write_bytes(b"patched")
        return True

    result = detect_operations(scan_import_files(context.mod_path), context, apply)
    assert result["patch.xdelta"]["target"] == "${game_path}/large.bin"
    assert attempted == [120]


def test_xdelta_that_does_not_use_a_base_cannot_identify_its_destination(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "only-file.bin").write_bytes(b"original")
    _xdelta(context.mod_path / "patch.xdelta", b"patched", source=False)
    apply = Mock()
    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}
    apply.assert_not_called()


def test_probe_limit_stops_unsuccessful_xdelta_trials(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("ui.dialogs.manual_install.detection._AUTO_PROBE_LIMIT", 2)
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    for index in range(3):
        (context.game_path / f"base{index}.bin").write_bytes(bytes([index]))
    _xdelta(context.mod_path / "patch.xdelta", b"patched")
    attempts = []

    def apply(_kind, _base, _patch, output):
        attempts.append(1)
        output.write_bytes(b"patched")
        return len(attempts) == 3

    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}
    assert len(attempts) == 2


def test_xdelta_limit_still_allows_fallback_into_nested_game_data_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.dialogs.manual_install.detection._AUTO_PROBE_LIMIT", 2)
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    for index in range(2):
        (context.game_path / f"wrong{index}.bin").write_bytes(b"wrong")
    context.game_data_path.mkdir()
    (context.game_data_path / "base.bin").write_bytes(b"original")
    patch = context.mod_path / "patch.xdelta"
    _xdelta(patch, b"patched")
    attempts = []

    def apply(_kind, base, _patch, output):
        content = base.read_bytes()
        attempts.append(content)
        if content != b"original":
            return False
        output.write_bytes(b"patched")
        return True

    result = detect_operations([(str(patch), patch.name)], context, apply)
    assert result[patch.name]["target"] == "${game_data_path}/base.bin"
    assert attempts == [b"wrong", b"wrong", b"original"]


def test_patch_changed_during_detection_is_not_assigned(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "base.bin").write_bytes(b"original")
    patch = context.mod_path / "patch.xdelta"
    _xdelta(patch, b"patched")

    def apply(_kind, _base, source, output):
        output.write_bytes(b"patched")
        source.write_bytes(b"changed during probing")
        return True

    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}


def test_probe_deadline_never_confirms_an_unfinished_search(tmp_path, monkeypatch):
    from ui.dialogs.manual_install import detection

    clock = [0]
    monkeypatch.setattr(detection, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "one.bin").write_bytes(b"one")
    (context.game_path / "two.bin").write_bytes(b"two")
    _xdelta(context.mod_path / "patch.xdelta", b"patched")
    attempts = []

    def apply(_kind, _base, _patch, output):
        attempts.append(1)
        output.write_bytes(b"patched")
        clock[0] = detection._AUTO_PROBE_SECONDS + 1
        return True

    assert detect_operations(scan_import_files(context.mod_path), context, apply) == {}
    assert len(attempts) == 1


def test_patch_chain_resolves_different_placeholders_to_the_same_file(tmp_path):
    from utils.mod.hashing import sha256_path

    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    context.game_data_path.mkdir()
    target = context.game_data_path / "data.bin"
    target.write_bytes(b"original")
    first, second = context.mod_path / "a.xdelta", context.mod_path / "b.xdelta"
    _xdelta(first, b"first")
    _xdelta(second, b"second")
    assignments = {
        "a.xdelta": {
            "type": "patch",
            "target": "${game_path}/saves/data.bin",
            "target_hash": sha256_path(target),
            "source_hash": sha256_path(first),
        },
        "b.xdelta": {"type": "patch", "target": "${game_data_path}/data.bin"},
    }
    bases = []

    def apply(_kind, base, patch, output):
        bases.append(base.read_bytes())
        output.write_bytes(b"first" if patch == first else b"second")
        return True

    verified = verify_operations(
        scan_import_files(context.mod_path), context, assignments, apply
    )
    assert set(verified) == {"a.xdelta", "b.xdelta"}
    assert bases == [b"original", b"first"]
    assert target.read_bytes() == b"original"


def test_patch_verification_follows_overwrites_and_checks_every_output(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    target = context.game_path / "data.bin"
    target.write_bytes(b"original")
    replacement = context.mod_path / "a.bin"
    replacement.write_bytes(b"replacement")
    patch = context.mod_path / "b.xdelta"
    _xdelta(patch, b"patched")
    files = scan_import_files(context.mod_path)
    assignments = {
        "a.bin": {"type": "overwrite", "target": "${game_path}/data.bin"},
        "b.xdelta": {"type": "patch", "target": "${game_path}/data.bin"},
    }

    def apply(_kind, base, _patch, output):
        assert base.read_bytes() == b"replacement"
        output.write_bytes(b"patched")
        return True

    verified = verify_operations(files, context, assignments, apply)
    assert (
        verified["a.bin"]["source_hash"]
        == "sha256:" + hashlib.sha256(b"replacement").hexdigest()
    )
    assert (
        verified["b.xdelta"]["target_hash"]
        == "sha256:" + hashlib.sha256(b"replacement").hexdigest()
    )
    assert target.read_bytes() == b"original"

    with pytest.raises(ValueError, match="cannot be applied"):
        verify_operations(files, context, assignments, lambda *_args: False)


def test_patch_verification_rejects_changed_source_and_bad_g3mpatch_output(tmp_path):
    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    (context.game_path / "data.bin").write_bytes(b"original")
    patch = context.mod_path / "patch.g3mpatch"
    _g3mpatch(patch, b"original")
    assignment = {
        "patch.g3mpatch": {"type": "patch", "target": "${game_path}/data.bin"}
    }

    def apply(_kind, _base, _patch, output):
        output.write_bytes(b"wrong")
        return True

    with pytest.raises(ValueError, match="expected file"):
        verify_operations(
            scan_import_files(context.mod_path), context, assignment, apply
        )

    def changed(_kind, _base, source, output):
        source.write_bytes(b"changed")
        output.write_bytes(b"patched")
        return True

    with pytest.raises(ValueError, match="changed during validation"):
        verify_operations(
            scan_import_files(context.mod_path), context, assignment, changed
        )


@pytest.mark.parametrize("kind", ["xdelta", "g3mpatch"])
@pytest.mark.parametrize("location", ["game", "data", "data_only"])
def test_native_patch_detection_save_execution_and_restore(tmp_path, kind, location):
    from adapters.g3mtool_adapter import G3MToolManager
    from services.mod_operation_executor import ModOperationExecutor
    from services.mod_operation_support import create_g3mtool_patcher
    from ui.dialogs.manual_install.workers import write_import
    from utils.mod.config import load_mod_config
    from utils.mod.hashing import sha256_path
    from utils.mod.operation_plan import build_mod_operation_plan

    context = _context(tmp_path)
    assert context.mod_path is not None
    assert context.game_path is not None
    assert context.game_data_path is not None
    context = replace(context, game_data_path=tmp_path / "game_data")
    assert context.game_data_path is not None
    context.game_data_path.mkdir()
    if location == "data_only":
        context = replace(context, game_path=None)
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    target_root = context.game_path if location == "game" else context.game_data_path
    assert target_root is not None
    base = target_root / "nested" / "deeper" / "renamed.bin"
    base.parent.mkdir(parents=True)
    shutil.copyfile(fixtures / "game_data/undertale/data.win", base)
    assert target_root is not None
    (target_root / "wrong.bin").write_bytes(b"wrong base")
    modified = fixtures / "patches/undertale/data_patched.win"
    app_state = SimpleNamespace(local_config={})
    tool = G3MToolManager(app_state)
    assert tool.is_available(), tool.get_unavailable_reason()
    patch = context.mod_path / f"mod.{kind}"
    create = tool.xpatch_create if kind == "xdelta" else tool.patch_create
    code, stdout, stderr = create(str(base), str(modified), str(patch))
    assert code == 0, stderr or stdout
    if kind == "g3mpatch":
        folder = context.mod_path / "unpacked"
        with zipfile.ZipFile(patch) as archive:
            archive.extractall(folder)
        patch.unlink()
    else:
        # Some downloads call xdelta files .patch. Saved sources must work at launch too.
        patch.rename(context.mod_path / "mod.patch")

    def apply(format_name, private_base, source, output):
        method = tool.xpatch_apply if format_name == "xdelta" else tool.apply_patch
        return method(str(private_base), str(source), str(output))[0] == 0

    files = scan_import_files(context.mod_path)
    assignments = detect_operations(files, context, apply)
    relative = files[0][1]
    placeholder = "game_path" if location == "game" else "game_data_path"
    assert assignments[relative]["target"] == f"${{{placeholder}}}/nested/deeper/renamed.bin"
    verified = verify_operations(files, context, assignments, apply)
    config = {
        "config_version": "2.0.0",
        "id": "native_test",
        "name": "Native test",
        "version": "1.0.0",
        "authors": [],
        "game": "undertale",
        "files": [dict(verified[relative], source=f"${{mod_path}}/files/{relative}")],
    }
    saved = write_import(
        files, config, tmp_path / "library", import_root=context.mod_path
    )
    stored = load_mod_config(saved / "mod_config.json")
    assert sha256_path(saved / "files" / relative) == verified[relative]["source_hash"]
    launch_context = ModPathContext.create(
        mod_path=saved,
        game_path=context.game_path,
        game_data_path=context.game_data_path,
        user_path=tmp_path,
    )
    plan = build_mod_operation_plan(stored, launch_context)
    assert not plan.has_errors, plan.findings
    original = base.read_bytes()
    journal = ModOperationExecutor(
        tmp_path / "session", patcher=create_g3mtool_patcher(app_state)
    ).execute(plan)
    assert base.read_bytes() == modified.read_bytes()
    journal.restore()
    assert base.read_bytes() == original


@pytest.mark.parametrize(("docs_as_info", "expected"), [(True, {"type": "info"}), (False, None)])
def test_documents_are_marked_as_info_only_when_the_setting_is_on(tmp_path, docs_as_info, expected):
    context = _context(tmp_path)
    assert context.mod_path is not None
    (context.mod_path / "README.md").write_text("Guide", encoding="utf-8")
    (context.mod_path / "notes.txt").write_text("Notes", encoding="utf-8")

    result = detect_operations(
        scan_import_files(context.mod_path), context, lambda *_args: True, docs_as_info=docs_as_info
    )

    assert result.get("README.md") == expected
    assert result.get("notes.txt") == expected
