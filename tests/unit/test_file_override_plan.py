from pathlib import Path

from utils.patching.file_override_plan import (
    OverrideCandidate,
    apply_override_plan,
    build_override_plan,
    discover_directory_candidates,
)


def test_highest_priority_candidate_wins_without_reading_content(tmp_path):
    low = tmp_path / "low.png"
    high = tmp_path / "high.png"
    low.write_bytes(b"low")
    high.write_bytes(b"high")

    plan = build_override_plan(
        [
            OverrideCandidate(str(low), str(tmp_path / "game" / "A.png"), 0),
            OverrideCandidate(str(high), str(tmp_path / "game" / "a.PNG"), 1),
        ],
        case_sensitive=False,
    )

    assert plan == [OverrideCandidate(str(high), str(tmp_path / "game" / "a.PNG"), 1)]


def test_plan_order_is_deterministic_by_destination(tmp_path):
    candidates = [
        OverrideCandidate("z-source", str(tmp_path / "z.txt"), 0),
        OverrideCandidate("a-source", str(tmp_path / "a.txt"), 0),
    ]
    assert [Path(item.target).name for item in build_override_plan(candidates, case_sensitive=True)] == [
        "a.txt",
        "z.txt",
    ]


def test_discovery_skips_excluded_files(tmp_path):
    source = tmp_path / "mod"
    source.mkdir()
    (source / "image.png").write_bytes(b"image")
    (source / "data.win").write_bytes(b"data")

    candidates = discover_directory_candidates(
        str(source),
        str(tmp_path / "game"),
        priority=3,
        excluded_extensions=(".win",),
    )

    assert [Path(item.source).name for item in candidates] == ["image.png"]


def test_discovery_skips_symlinks(tmp_path):
    import pytest

    source = tmp_path / "mod"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (source / "link.txt").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    assert discover_directory_candidates(
        str(source), str(tmp_path / "game"), priority=3
    ) == []


def test_discovery_follows_explicit_symlink(tmp_path):
    import pytest

    source = tmp_path / "mod"
    source.mkdir()
    outside = tmp_path / "shared" / "icon.png"
    outside.parent.mkdir()
    outside.write_bytes(b"icon")
    try:
        (source / "icon.png").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    candidates = discover_directory_candidates(
        str(source), str(tmp_path / "game"), priority=3, follow_symlinks=True
    )

    assert [Path(item.target).name for item in candidates] == ["icon.png"]
    assert Path(candidates[0].source).read_bytes() == b"icon"


def test_discovery_does_not_follow_directory_link_cycle(tmp_path):
    import pytest

    source = tmp_path / "mod"
    source.mkdir()
    (source / "icon.png").write_bytes(b"icon")
    try:
        (source / "loop").symlink_to(source, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    candidates = discover_directory_candidates(
        str(source), str(tmp_path / "game"), priority=3, follow_symlinks=True
    )

    assert [Path(item.target).name for item in candidates] == ["icon.png"]


def test_apply_uses_random_exclusive_temporary_file(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    target = tmp_path / "game" / "target.txt"
    source.write_text("new", encoding="utf-8")
    calls = []
    original = __import__("tempfile").mkstemp

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result[1])
        return result

    monkeypatch.setattr("utils.patching.file_override_plan.tempfile.mkstemp", capture)

    assert apply_override_plan(
        [OverrideCandidate(str(source), str(target), 1)], backup_or_mark=lambda _path: None
    )
    assert target.read_text(encoding="utf-8") == "new"
    assert calls and calls[0] != str(target.with_name(f".{target.name}.g3m-tmp"))


def test_apply_aborts_when_backup_manifest_cannot_be_saved(tmp_path):
    source = tmp_path / "source.txt"
    target = tmp_path / "game" / "target.txt"
    source.write_text("new", encoding="utf-8")

    assert not apply_override_plan(
        [OverrideCandidate(str(source), str(target), 1)],
        backup_or_mark=lambda _path: False,
    )
    assert not target.exists()
