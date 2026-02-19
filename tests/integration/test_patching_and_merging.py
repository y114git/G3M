import os
import json
import shutil
import tempfile
import logging
import zipfile
import pytest
from pathlib import Path
from unittest.mock import Mock
from services.g3mtool_patching_service import (
    G3MToolPatchingService, MOD_TYPE_G3MPATCH, MOD_TYPE_XDELTA,
    MOD_TYPE_DATAFILE, MOD_TYPE_OVERRIDES_ONLY,
)
from adapters.g3mtool_adapter import G3MToolManager
from services.backup_service import BackupManager


class TestG3MToolAdapter:

    def test_adapter_initialization(self):
        g3mtool = G3MToolManager()
        assert g3mtool.platform in ('windows', 'linux', 'macos')

    def test_adapter_availability(self):
        g3mtool = G3MToolManager()
        if g3mtool.g3mtool_path:
            assert os.path.exists(g3mtool.g3mtool_path)
            assert g3mtool.is_available()
        else:
            assert not g3mtool.is_available()

    def test_cancel_active_processes(self):
        g3mtool = G3MToolManager()
        g3mtool.cancel_active_processes()
        assert len(g3mtool._active_processes) == 0


class TestModClassification:

    def test_classify_g3mpatch(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        zip_path = mod_dir / 'patch.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('g3mpatch.json', '{"version": 1}')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH
        assert patch_file.endswith('.zip')

    def test_classify_xdelta(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        (mod_dir / 'data.xdelta').write_bytes(b'fake')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_XDELTA
        assert patch_file.endswith('.xdelta')

    def test_classify_vcdiff(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        (mod_dir / 'data.vcdiff').write_bytes(b'fake')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_XDELTA
        assert patch_file.endswith('.vcdiff')

    def test_classify_datafile(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        (mod_dir / 'data.win').write_bytes(b'FORM' + b'\x00' * 100)
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_DATAFILE
        assert patch_file.endswith('data.win')

    def test_classify_overrides_only(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        (mod_dir / 'sound.ogg').write_bytes(b'fake')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY
        assert patch_file is None

    def test_classify_g3mpatch_priority_over_xdelta(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        zip_path = mod_dir / 'patch.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('g3mpatch.json', '{"version": 1}')
        (mod_dir / 'data.xdelta').write_bytes(b'fake')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH

    def test_classify_zip_without_g3mpatch_json_is_not_g3mpatch(self, tmp_path):
        mod_dir = tmp_path / 'mod'
        mod_dir.mkdir()
        zip_path = mod_dir / 'random.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('readme.txt', 'hello')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY

    def test_classify_empty_dir(self, tmp_path):
        mod_dir = tmp_path / 'empty'
        mod_dir.mkdir()
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY

    def test_classify_nonexistent(self, tmp_path):
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(tmp_path / 'nope'))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY


class TestServiceInitialization:

    def test_service_has_g3mtool(self):
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert hasattr(patcher, 'g3mtool')
        assert isinstance(patcher.g3mtool, G3MToolManager)

    def test_service_has_patching_logger(self):
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert patcher.patching_logger is not None
        assert patcher.patching_logger.name == 'patching'

    def test_cleanup_processes_method_exists(self):
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert hasattr(patcher, 'cleanup_processes_and_temp_files')
        patcher.cleanup_processes_and_temp_files()

    def test_cancel(self):
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher.cancel()
        assert patcher._cancelled is True


class TestBackupFlow:

    def test_backup_and_restore(self, tmp_path):
        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger('test'))
        chapter_id = 'deltarune_1'
        test_file = tmp_path / 'data.win'
        test_file.write_bytes(b'ORIGINAL_CONTENT')
        bm.backup_file(chapter_id, str(test_file))
        assert chapter_id in bm.original_files
        assert str(test_file) in bm.original_files[chapter_id]
        backup_path = bm.original_files[chapter_id][str(test_file)]
        assert os.path.exists(backup_path)
        test_file.write_bytes(b'MODIFIED_CONTENT')
        bm.restore_backups(chapter_id)
        assert test_file.read_bytes() == b'ORIGINAL_CONTENT'

    def test_backup_manifest_tracking(self, tmp_path):
        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger('test'))
        chapter_id = 'deltarune_1'
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test')
        bm.backup_file(chapter_id, str(test_file))
        manifest_path = str(tmp_path / 'manifest.json')
        bm.save_backups_to_manifest(manifest_path)
        with open(manifest_path, 'r') as f:
            manifest_data = json.load(f)
        assert 'modification_order' in manifest_data
        assert chapter_id in manifest_data['modification_order']
        assert str(test_file) in manifest_data['modification_order'][chapter_id]

    def test_multi_chapter_backup_restore(self, tmp_path):
        backup_dir = tmp_path / 'backups'
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger('test'))
        files = {}
        for ch in ['deltarune_1', 'deltarune_2']:
            f = tmp_path / f'{ch}_data.win'
            f.write_bytes(f'ORIGINAL_{ch}'.encode())
            files[ch] = f
            bm.backup_file(ch, str(f))
        for ch, f in files.items():
            f.write_bytes(b'MODIFIED')
        bm.restore_all_backups()
        for ch, f in files.items():
            assert f.read_bytes() == f'ORIGINAL_{ch}'.encode()


class TestReportParsing:

    def test_no_report(self):
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert patcher.get_report_path() is None
        assert patcher.report_has_conflicts() is False
        assert patcher.get_report_stats() == (0, 0)

    def test_report_with_conflicts(self, tmp_path):
        report = tmp_path / 'report.md'
        report.write_text('## Merge Report\n\nTotal conflicts: 3\nAuto-resolved: 1\n')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher._last_report_path = str(report)
        assert patcher.report_has_conflicts() is True
        total, auto = patcher.get_report_stats()
        assert total == 3
        assert auto == 1

    def test_report_without_conflicts(self, tmp_path):
        report = tmp_path / 'report.md'
        report.write_text('## Merge Report\n\nAll patches applied cleanly.\n')
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher._last_report_path = str(report)
        assert patcher.report_has_conflicts() is False


class TestXdeltaPatchApplication:

    def test_xdelta_patch_with_g3mtool(self, game_data_dir, patches_game_dirs, deltarune_chapter_dirs):
        chapter1_dir = deltarune_chapter_dirs['chapter1']
        data_win_path = Path(chapter1_dir) / 'data.win'
        if not data_win_path.exists():
            pytest.skip('Test data.win not found.')
        patch_file = None
        if 'deltarune' in patches_game_dirs:
            chapter1_patches = patches_game_dirs['deltarune'].get('chapter1')
            if chapter1_patches:
                patch_path = Path(chapter1_patches)
                xdelta_patches = list(patch_path.glob('*.xdelta'))
                if xdelta_patches:
                    patch_file = str(xdelta_patches[0])
        if not patch_file:
            pytest.skip('No xdelta patches found.')
        g3mtool = G3MToolManager()
        if not g3mtool.is_available():
            pytest.skip('G3MTool executable not found')
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_data_win = os.path.join(temp_dir, 'data.win')
            shutil.copy2(data_win_path, temp_data_win)
            output_path = os.path.join(temp_dir, 'patched_data.win')
            returncode, stdout, stderr = g3mtool.xpatch_apply(temp_data_win, patch_file, output_path)
            if returncode != 0:
                pytest.fail(f'xpatch apply failed: {stderr[:500]}')
            assert os.path.exists(output_path)
            patched_size = os.path.getsize(output_path)
            assert patched_size > 0
