"""Unit tests for test log viewer service."""

from services.log_viewer_service import LogViewerService


def test_resolve_history_prefers_current_files(tmp_path):
    logs_dir = tmp_path / "logs"
    patching_dir = logs_dir / "patching"
    patching_dir.mkdir(parents=True)

    g3m_log = logs_dir / "g3m.log"
    patching_log = logs_dir / "patching.log"
    conflicts_log = logs_dir / "conflicts.log"
    g3m_log.write_text("g3m current", encoding="utf-8")
    patching_log.write_text("patching current", encoding="utf-8")
    conflicts_log.write_text("conflict current", encoding="utf-8")

    service = LogViewerService(user_data_root=str(tmp_path))
    history = service.resolve_history()

    assert history["g3m"][0].path == str(g3m_log)
    assert history["g3m"][0].is_live is True
    assert history["patching"][0].path == str(patching_log)
    assert history["conflicts"][0].path == str(conflicts_log)


def test_resolve_history_falls_back_to_latest_archives(tmp_path):
    logs_dir = tmp_path / "logs"
    archive_dir = logs_dir / "g3m"
    patching_dir = logs_dir / "patching"
    archive_dir.mkdir(parents=True)
    patching_dir.mkdir(parents=True)

    old_g3m = archive_dir / "g3m_20260101_010101.log"
    new_g3m = archive_dir / "g3m_20260102_020202.log"
    old_patching = patching_dir / "patching_20260101_010101.log"
    new_patching = patching_dir / "patching_20260103_030303.log"
    old_conflict = patching_dir / "conflicts_20260101_010101.log"
    new_conflict = patching_dir / "conflicts_20260104_040404.log"

    for path, text in (
        (old_g3m, "old g3m"),
        (new_g3m, "new g3m"),
        (old_patching, "old patching"),
        (new_patching, "new patching"),
        (old_conflict, "old conflict"),
        (new_conflict, "new conflict"),
    ):
        path.write_text(text, encoding="utf-8")

    service = LogViewerService(user_data_root=str(tmp_path))
    history = service.resolve_history()

    assert history["g3m"][0].path is None
    assert history["g3m"][1].path == str(new_g3m)
    assert history["patching"][1].path == str(new_patching)
    assert history["conflicts"][1].path == str(new_conflict)


def test_read_snapshot_returns_incremental_updates(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    log_path = logs_dir / "g3m.log"
    log_path.write_text("line 1\n", encoding="utf-8")

    service = LogViewerService(user_data_root=str(tmp_path))
    first = service.read_snapshot(str(log_path), previous_state=None)

    assert first.full_text == "line 1\n"

    log_path.write_text("line 1\nline 2\n", encoding="utf-8")
    second = service.read_snapshot(str(log_path), previous_state=first.state)

    assert second.full_text == "line 1\nline 2\n"

    log_path.write_text("reset\n", encoding="utf-8")
    third = service.read_snapshot(str(log_path), previous_state=second.state)

    assert third.full_text == "reset\n"


def test_resolve_history_sorts_archives_by_embedded_timestamp_not_mtime(tmp_path):
    archive_dir = tmp_path / "logs" / "patching"
    archive_dir.mkdir(parents=True)
    newer = archive_dir / "patching_20260103_030303.log"
    older = archive_dir / "patching_20260101_010101.log"
    newer.write_text("newer", encoding="utf-8")
    older.write_text("older", encoding="utf-8")
    newer.touch()
    older.touch()

    service = LogViewerService(user_data_root=str(tmp_path))
    history = service.resolve_history()

    assert history["patching"][1].path == str(newer)


def test_format_archive_label_uses_expected_datetime_shape():
    label = LogViewerService.format_archive_label("patching_20260419_034201.log")

    assert label == "19.04.26 - 03:42:01"
