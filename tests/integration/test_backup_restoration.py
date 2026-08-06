"""Integration tests for test backup restoration."""

import logging
import os
from unittest.mock import patch

from services.backup_service import BackupManager
from services.g3mtool_patching_service import G3MToolPatchingService


class TestBackupRestoration:
    """Tests for backup restoration."""

    def test_complete_backup_restoration_flow(
        self, temp_dir, app_state, feedback_service
    ):
        """Checks that complete backup restoration flow."""
        from services.mod.service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        patcher = G3MToolPatchingService(app_state, mod_service)
        backup_dir = os.path.join(temp_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        patcher.backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = "deltarune_1"
        game_dir = os.path.join(temp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        data_win = os.path.join(game_dir, "data.win")
        sound_dir = os.path.join(game_dir, "sound", "Desktop")
        os.makedirs(sound_dir, exist_ok=True)
        bank_file = os.path.join(sound_dir, "test.bank")
        with open(data_win, "wb") as f:
            f.write(b"ORIGINAL_DATA_WIN")
        with open(bank_file, "wb") as f:
            f.write(b"ORIGINAL_BANK_FILE")
        patcher.backup_service.backup_file(chapter_id, data_win)
        patcher.backup_service.backup_file(chapter_id, bank_file)
        with open(data_win, "wb") as f:
            f.write(b"MODIFIED_DATA_WIN")
        with open(bank_file, "wb") as f:
            f.write(b"MODIFIED_BANK_FILE")
        patcher.backup_service.restore_all_backups()
        with open(data_win, "rb") as f:
            assert f.read() == b"ORIGINAL_DATA_WIN"
        with open(bank_file, "rb") as f:
            assert f.read() == b"ORIGINAL_BANK_FILE"

    def test_file_integrity_after_restoration(self, temp_dir):
        """Checks that file integrity after restoration."""
        backup_dir = os.path.join(temp_dir, "backups")
        backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = "deltarune_1"
        test_file = os.path.join(temp_dir, "test.txt")
        original_content = "A" * 1000
        with open(test_file, "w") as f:
            f.write(original_content)
        original_size = os.path.getsize(test_file)
        backup_service.backup_file(chapter_id, test_file)
        with open(test_file, "w") as f:
            f.write("B" * 500)
        backup_service.restore_backups(chapter_id)
        assert os.path.exists(test_file)
        restored_size = os.path.getsize(test_file)
        assert restored_size == original_size
        with open(test_file) as f:
            restored_content = f.read()
            assert restored_content == original_content

    def test_restoration_order(self, temp_dir):
        """Checks that restoration order."""
        backup_dir = os.path.join(temp_dir, "backups")
        backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = "deltarune_1"
        test_dir = os.path.join(temp_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        files = []
        for i in range(5):
            file_path = os.path.join(test_dir, f"file{i}.txt")
            with open(file_path, "w") as f:
                f.write(f"original{i}")
            files.append(file_path)
            backup_service.backup_file(chapter_id, file_path)
        for file_path in files:
            with open(file_path, "w") as f:
                f.write("modified")
        backup_service.restore_backups(chapter_id)
        for i, file_path in enumerate(files):
            with open(file_path) as f:
                content = f.read()
                assert content == f"original{i}", (
                    f"File {file_path} not restored correctly"
                )

    def test_sound_file_restoration(self, temp_dir):
        """Checks that sound file restoration."""
        backup_dir = os.path.join(temp_dir, "backups")
        backup_service = BackupManager(
            backup_dir, patching_logger=logging.getLogger("test")
        )
        chapter_id = "deltarune_1"
        sound_dir = os.path.join(temp_dir, "game", "sound", "Desktop")
        os.makedirs(sound_dir, exist_ok=True)
        bank_files = []
        for i in range(3):
            bank_file = os.path.join(sound_dir, f"sound{i}.bank")
            original_content = f"BANK_FILE_{i}".encode()
            with open(bank_file, "wb") as f:
                f.write(original_content)
            bank_files.append((bank_file, original_content))
            backup_service.backup_file(chapter_id, bank_file)
        for bank_file, _ in bank_files:
            with open(bank_file, "wb") as f:
                f.write(b"MODIFIED")
        backup_service.restore_backups(chapter_id)
        for bank_file, original_content in bank_files:
            assert os.path.exists(bank_file)
            with open(bank_file, "rb") as f:
                restored_content = f.read()
                assert restored_content == original_content, (
                    f"Bank file {bank_file} not restored correctly"
                )

    def test_failed_restore_keeps_backup_and_manifest(
        self, temp_dir, app_state, feedback_service
    ):
        from services.mod.service import ModManager

        patcher = G3MToolPatchingService(
            app_state, ModManager(app_state, feedback_service)
        )
        backup_dir = os.path.join(temp_dir, "backups")
        target = os.path.join(temp_dir, "data.win")
        manifest = os.path.join(temp_dir, "session.lock")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        patcher.backup_service = BackupManager(backup_dir)
        assert patcher.backup_service.backup_file("undertale", target)
        patcher.backup_service.save_backups_to_manifest(manifest)
        with open(target, "wb") as file:
            file.write(b"MODDED")

        with patch(
            "services.backup_service.shutil.copyfile",
            side_effect=PermissionError("locked"),
        ):
            restored = patcher.restore_all_backups()

        assert restored is False
        assert os.path.isdir(backup_dir)
        assert os.path.isfile(manifest)
        with open(target, "rb") as file:
            assert file.read() == b"MODDED"

    def test_restore_is_atomic_when_copy_fails(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        target = os.path.join(temp_dir, "data.win")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        assert manager.backup_file("undertale", target)
        with open(target, "wb") as file:
            file.write(b"MODDED")

        with patch(
            "services.backup_service.shutil.copyfile",
            side_effect=OSError("interrupted copy"),
        ):
            assert manager.restore_all_backups() is False

        with open(target, "rb") as file:
            assert file.read() == b"MODDED"
        assert not any(name.endswith(".g3m-restore") for name in os.listdir(temp_dir))

    def test_transient_restore_failure_can_be_retried(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        target = os.path.join(temp_dir, "data.win")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        assert manager.backup_file("undertale", target)
        with open(target, "wb") as file:
            file.write(b"MODDED")

        with patch(
            "services.backup_service.shutil.copyfile",
            side_effect=PermissionError("locked"),
        ):
            assert manager.restore_all_backups() is False

        assert manager.restore_all_backups() is True
        with open(target, "rb") as file:
            assert file.read() == b"ORIGINAL"

    def test_restore_attempts_every_chapter_after_one_failure(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        manager.original_files = {"chapter_1": {}, "chapter_2": {}}
        results = {"chapter_1": False, "chapter_2": True}

        with patch.object(
            manager, "restore_backups", side_effect=lambda chapter: results[chapter]
        ) as restore:
            assert manager.restore_all_backups() is False

        assert {call.args[0] for call in restore.call_args_list} == set(results)

    def test_missing_backup_is_reported_as_failure(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        target = os.path.join(temp_dir, "data.win")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        assert manager.backup_file("undertale", target)
        backup = manager.original_files["undertale"][target]
        os.remove(backup)

        assert manager.restore_all_backups() is False
        assert target in manager.original_files["undertale"]

    def test_manifest_write_is_atomic(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        manifest = os.path.join(temp_dir, "session.lock")
        with open(manifest, "w", encoding="utf-8") as file:
            file.write("previous-valid-manifest")

        with patch(
            "services.backup_service.os.replace",
            side_effect=PermissionError("locked"),
        ):
            assert manager.save_backups_to_manifest(manifest) is False

        with open(manifest, encoding="utf-8") as file:
            assert file.read() == "previous-valid-manifest"
        assert not any(name.endswith(".tmp") for name in os.listdir(temp_dir))

    def test_finalized_session_restores_when_deployed_hash_matches(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        target = os.path.join(temp_dir, "data.win")
        manifest = os.path.join(temp_dir, "session.lock")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        assert manager.backup_file("undertale", target)
        with open(target, "wb") as file:
            file.write(b"DEPLOYED_MOD")
        assert manager.save_backups_to_manifest(manifest)
        assert manager.capture_deployed_state()

        recovered = BackupManager.load_from_manifest(manifest)
        assert recovered.restore_all_backups() is True
        with open(target, "rb") as file:
            assert file.read() == b"ORIGINAL"

    def test_finalized_session_does_not_overwrite_external_change(self, temp_dir):
        manager = BackupManager(os.path.join(temp_dir, "backups"))
        target = os.path.join(temp_dir, "data.win")
        manifest = os.path.join(temp_dir, "session.lock")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        assert manager.backup_file("undertale", target)
        with open(target, "wb") as file:
            file.write(b"DEPLOYED_MOD")
        assert manager.save_backups_to_manifest(manifest)
        assert manager.capture_deployed_state()
        with open(target, "wb") as file:
            file.write(b"USER_CHANGE")

        recovered = BackupManager.load_from_manifest(manifest)
        assert recovered.restore_all_backups() is False
        assert recovered.external_changes == [target]
        with open(target, "rb") as file:
            assert file.read() == b"USER_CHANGE"
        assert os.path.isfile(manifest)

    def test_patcher_archives_conflict_and_clears_active_session(
        self, temp_dir, app_state, feedback_service
    ):
        from services.mod.service import ModManager

        patcher = G3MToolPatchingService(
            app_state, ModManager(app_state, feedback_service)
        )
        backup_dir = os.path.join(temp_dir, "patching_backups")
        manifest = os.path.join(temp_dir, "session.lock")
        target = os.path.join(temp_dir, "data.win")
        with open(target, "wb") as file:
            file.write(b"ORIGINAL")
        patcher.backup_service = BackupManager(backup_dir)
        assert patcher.backup_service.backup_file("undertale", target)
        with open(target, "wb") as file:
            file.write(b"DEPLOYED_MOD")
        assert patcher.backup_service.save_backups_to_manifest(manifest)
        assert patcher.finalize_session_state()
        with open(target, "wb") as file:
            file.write(b"USER_CHANGE")

        assert patcher.restore_all_backups() is True

        with open(target, "rb") as file:
            assert file.read() == b"USER_CHANGE"
        assert patcher.last_restore_external_changes == [target]
        assert os.path.isdir(patcher.last_restore_conflict_archive)
        assert os.path.isfile(
            os.path.join(patcher.last_restore_conflict_archive, "session.json")
        )
        assert not os.path.exists(manifest)
        assert not os.path.exists(backup_dir)
