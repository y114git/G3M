"""Unit tests for the asynchronous operation journal worker."""

import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from services.mod_operation_executor import ModRecoveryConflictError


def test_restore_load_failure_is_not_reported_as_success(qapp, tmp_path):
    from workers.mod.journal_worker import ModOperationJournalThread

    worker = ModOperationJournalThread("restore", journal_root=tmp_path)
    with patch(
        "workers.mod.journal_worker.ModOperationJournal.load",
        side_effect=OSError("broken manifest"),
    ):
        worker.run()

    assert worker.result == (False, ["broken manifest"])
    assert isinstance(worker.error, OSError)


def test_restore_without_a_journal_completes_successfully(qapp):
    from workers.mod.journal_worker import ModOperationJournalThread

    worker = ModOperationJournalThread("restore")
    worker.run()

    assert worker.result == (True, [])


def test_conflicted_restore_keeps_temporary_launch_files_until_resolved(qapp, tmp_path):
    from workers.mod.journal_worker import ModOperationJournalThread

    journal = Mock()
    journal.restore.side_effect = ModRecoveryConflictError("external change")
    target_exe = tmp_path / "DELTARUNE.exe"
    music_folder = tmp_path / "mus"
    target_exe.write_bytes(b"temporary")
    music_folder.mkdir()

    worker = ModOperationJournalThread(
        "restore",
        journal=journal,
        cleanup_info={"target_exe": target_exe, "mus_folders": [music_folder]},
    )
    worker.run()

    assert worker.result == (False, ["external change"])
    assert target_exe.exists()
    assert music_folder.exists()


def test_retiring_journal_removes_temporary_launch_files(qapp, tmp_path):
    from workers.mod.journal_worker import ModOperationJournalThread

    journal = Mock()
    target_exe = tmp_path / "DELTARUNE.exe"
    music_folder = tmp_path / "mus"
    target_exe.write_bytes(b"temporary")
    music_folder.mkdir()

    worker = ModOperationJournalThread(
        "retire",
        journal=journal,
        cleanup_info={"target_exe": target_exe, "mus_folders": [music_folder]},
    )
    worker.run()

    journal.retire.assert_called_once_with()
    assert worker.result == (True, [])
    assert not target_exe.exists()
    assert not music_folder.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the read-only attribute is a Windows one")
def test_read_only_temporary_launch_files_are_removed(qapp, tmp_path):
    from workers.mod.journal_worker import ModOperationJournalThread

    target_exe = tmp_path / "DELTARUNE.exe"
    music_folder = tmp_path / "mus"
    target_exe.write_bytes(b"temporary")
    music_folder.mkdir()
    (music_folder / "song.ogg").write_bytes(b"audio")
    for path in (target_exe, music_folder / "song.ogg", music_folder):
        subprocess.run(["attrib", "+R", str(path)], check=True)

    worker = ModOperationJournalThread(
        "retire",
        journal=Mock(),
        cleanup_info={"target_exe": target_exe, "mus_folders": [music_folder]},
    )
    worker.run()

    assert worker.result == (True, [])
    assert not target_exe.exists()
    assert not music_folder.exists()
