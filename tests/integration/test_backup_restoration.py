import os
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock
from services.backup_service import BackupManager
from services.mod_merge_service import MultiModMerger
from services.patching_log_service import get_patching_logger


class TestBackupRestoration:

    def test_complete_backup_restoration_flow(self, temp_dir, app_state, feedback_service):
        from services.mod_service import ModManager
        mod_service = ModManager(app_state, feedback_service)
        merger = MultiModMerger(app_state, mod_service)
        backup_dir = os.path.join(temp_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        merger.backup_service = BackupManager(backup_dir, patching_logger=merger.patching_logger)
        chapter_id = 1
        game_dir = os.path.join(temp_dir, 'game')
        os.makedirs(game_dir, exist_ok=True)
        data_win = os.path.join(game_dir, 'data.win')
        sound_dir = os.path.join(game_dir, 'sound', 'Desktop')
        os.makedirs(sound_dir, exist_ok=True)
        bank_file = os.path.join(sound_dir, 'test.bank')
        with open(data_win, 'wb') as f:
            f.write(b'ORIGINAL_DATA_WIN')
        with open(bank_file, 'wb') as f:
            f.write(b'ORIGINAL_BANK_FILE')
        merger.backup_service.backup_file(chapter_id, data_win)
        merger.backup_service.backup_file(chapter_id, bank_file)
        with open(data_win, 'wb') as f:
            f.write(b'MODIFIED_DATA_WIN')
        with open(bank_file, 'wb') as f:
            f.write(b'MODIFIED_BANK_FILE')
        merger.backup_service.restore_all_backups()
        with open(data_win, 'rb') as f:
            assert f.read() == b'ORIGINAL_DATA_WIN'
        with open(bank_file, 'rb') as f:
            assert f.read() == b'ORIGINAL_BANK_FILE'

    def test_file_integrity_after_restoration(self, temp_dir):
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_service = BackupManager(backup_dir, patching_logger=get_patching_logger())
        chapter_id = 1
        test_file = os.path.join(temp_dir, 'test.txt')
        original_content = 'A' * 1000
        with open(test_file, 'w') as f:
            f.write(original_content)
        original_size = os.path.getsize(test_file)
        backup_service.backup_file(chapter_id, test_file)
        with open(test_file, 'w') as f:
            f.write('B' * 500)
        backup_service.restore_backups(chapter_id)
        assert os.path.exists(test_file)
        restored_size = os.path.getsize(test_file)
        assert restored_size == original_size
        with open(test_file, 'r') as f:
            restored_content = f.read()
            assert restored_content == original_content

    def test_restoration_order(self, temp_dir):
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_service = BackupManager(backup_dir, patching_logger=get_patching_logger())
        chapter_id = 1
        test_dir = os.path.join(temp_dir, 'test')
        os.makedirs(test_dir, exist_ok=True)
        files = []
        for i in range(5):
            file_path = os.path.join(test_dir, f'file{i}.txt')
            with open(file_path, 'w') as f:
                f.write(f'original{i}')
            files.append(file_path)
            backup_service.backup_file(chapter_id, file_path)
        for file_path in files:
            with open(file_path, 'w') as f:
                f.write('modified')
        backup_service.restore_backups(chapter_id)
        for i, file_path in enumerate(files):
            with open(file_path, 'r') as f:
                content = f.read()
                assert content == f'original{i}', f'File {file_path} not restored correctly'

    def test_sound_file_restoration(self, temp_dir):
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_service = BackupManager(backup_dir, patching_logger=get_patching_logger())
        chapter_id = 1
        sound_dir = os.path.join(temp_dir, 'game', 'sound', 'Desktop')
        os.makedirs(sound_dir, exist_ok=True)
        bank_files = []
        for i in range(3):
            bank_file = os.path.join(sound_dir, f'sound{i}.bank')
            original_content = f'BANK_FILE_{i}'.encode()
            with open(bank_file, 'wb') as f:
                f.write(original_content)
            bank_files.append((bank_file, original_content))
            backup_service.backup_file(chapter_id, bank_file)
        for bank_file, _ in bank_files:
            with open(bank_file, 'wb') as f:
                f.write(b'MODIFIED')
        backup_service.restore_backups(chapter_id)
        for bank_file, original_content in bank_files:
            assert os.path.exists(bank_file)
            with open(bank_file, 'rb') as f:
                restored_content = f.read()
                assert restored_content == original_content, f'Bank file {bank_file} not restored correctly'
