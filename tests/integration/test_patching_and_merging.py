import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from adapters.g3mtool_adapter import G3MToolManager
from services.backup_service import BackupManager
from services.g3mtool_patching_service import (
    MOD_TYPE_DATAFILE,
    MOD_TYPE_G3MPATCH,
    MOD_TYPE_OVERRIDES_ONLY,
    MOD_TYPE_XDELTA,
    G3MToolPatchingService,
)


class TestG3MToolAdapter:
    """Tests for patching and merging."""
    def test_adapter_initialization(self):
        """Checks that adaptering initialization."""
        g3mtool = G3MToolManager()
        assert g3mtool.platform in ("windows", "linux", "macos")

    def test_adapter_availability(self):
        """Checks that adaptering availability."""
        g3mtool = G3MToolManager()
        if g3mtool.g3mtool_path:
            assert os.path.exists(g3mtool.g3mtool_path)
            assert g3mtool.is_available()
        else:
            assert not g3mtool.is_available()

    def test_cancel_active_processes(self):
        """Checks that canceling active processes."""
        g3mtool = G3MToolManager()
        g3mtool.cancel_active_processes()
        assert len(g3mtool._active_processes) == 0

    def test_parse_progress(self):
        """Checks that parsing progress."""
        assert G3MToolManager._parse_progress("Applying patch: 67%") == (
            67,
            "Applying patch",
        )
        assert G3MToolManager._parse_progress("not progress") is None


class TestModClassification:
    """Tests for patching and merging."""
    def test_classify_g3mpatch(self, tmp_path):
        """Checks that classifying g3mpatch."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "patch.g3mpatch").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH
        assert patch_file.endswith(".g3mpatch")

    def test_classify_xdelta(self, tmp_path):
        """Checks that classifying xdelta."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "data.xdelta").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_XDELTA
        assert patch_file.endswith(".xdelta")

    def test_classify_vcdiff(self, tmp_path):
        """Checks that classifying vcdiff."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "data.vcdiff").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_XDELTA
        assert patch_file.endswith(".vcdiff")

    def test_classify_datafile(self, tmp_path):
        """Checks that classifying datafile."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "data.win").write_bytes(b"FORM" + b"\x00" * 100)
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_DATAFILE
        assert patch_file.endswith("data.win")

    def test_classify_overrides_only(self, tmp_path):
        """Checks that classifying overrides only."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "sound.ogg").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY
        assert patch_file is None

    def test_classify_g3mpatch_priority_over_xdelta(self, tmp_path):
        """Checks that classifying g3mpatch priority over xdelta."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "patch.g3mpatch").write_bytes(b"fake")
        (mod_dir / "data.xdelta").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_G3MPATCH

    def test_classify_plain_zip_is_not_g3mpatch(self, tmp_path):
        """Checks that classifying plain zip is not g3mpatch."""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir()
        (mod_dir / "random.zip").write_bytes(b"fake")
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY

    def test_classify_empty_dir(self, tmp_path):
        """Checks that classifying empty dir."""
        mod_dir = tmp_path / "empty"
        mod_dir.mkdir()
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(mod_dir))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY

    def test_classify_nonexistent(self, tmp_path):
        """Checks that classifying nonexistent."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        _patch_file, mod_type = patcher._classify_mod(str(tmp_path / "nope"))
        assert mod_type == MOD_TYPE_OVERRIDES_ONLY


class TestServiceInitialization:
    """Tests for patching and merging."""
    def test_service_has_g3mtool(self):
        """Checks that serviceing has g3mtool."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert hasattr(patcher, "g3mtool")
        assert isinstance(patcher.g3mtool, G3MToolManager)

    def test_service_has_patching_logger(self):
        """Checks that serviceing has patching logger."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert patcher.patching_logger is not None
        assert patcher.patching_logger.name == "patching"

    def test_cleanup_processes_method_exists(self):
        """Checks that cleanuping processes method exists."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert hasattr(patcher, "cleanup_processes_and_temp_files")
        patcher.cleanup_processes_and_temp_files()

    def test_cancel(self):
        """Checks that canceling works."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher.cancel()
        assert patcher._cancelled is True

    def test_warning_handler_can_abort(self):
        """Checks that warninging handler can abort."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.warning_handler = Mock(return_value=False)

        assert patcher._request_warning("warning text") is False
        patcher.warning_handler.assert_called_once()

    def test_skip_patching_warnings_bypasses_handler(self):
        """Checks that skipping patching warnings bypasses handler."""
        app_state = Mock()
        app_state.local_config = {"skip_patching_warnings": True}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher.warning_handler = Mock(return_value=False)

        assert patcher._request_warning("warning text") is True
        patcher.warning_handler.assert_not_called()


class TestBackupFlow:
    """Tests for patching and merging."""
    def test_backup_and_restore(self, tmp_path):
        """Checks that backuping and restore."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger("test"))
        chapter_id = "deltarune_1"
        test_file = tmp_path / "data.win"
        test_file.write_bytes(b"ORIGINAL_CONTENT")
        bm.backup_file(chapter_id, str(test_file))
        assert chapter_id in bm.original_files
        assert str(test_file) in bm.original_files[chapter_id]
        backup_path = bm.original_files[chapter_id][str(test_file)]
        assert os.path.exists(backup_path)
        test_file.write_bytes(b"MODIFIED_CONTENT")
        bm.restore_backups(chapter_id)
        assert test_file.read_bytes() == b"ORIGINAL_CONTENT"

    def test_backup_manifest_tracking(self, tmp_path):
        """Checks that backuping manifest tracking."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger("test"))
        chapter_id = "deltarune_1"
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        bm.backup_file(chapter_id, str(test_file))
        manifest_path = str(tmp_path / "manifest.json")
        bm.save_backups_to_manifest(manifest_path)
        with open(manifest_path) as f:
            manifest_data = json.load(f)
        assert "modification_order" in manifest_data
        assert chapter_id in manifest_data["modification_order"]
        assert str(test_file) in manifest_data["modification_order"][chapter_id]

    def test_multi_chapter_backup_restore(self, tmp_path):
        """Checks that multiing chapter backup restore."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bm = BackupManager(str(backup_dir), patching_logger=logging.getLogger("test"))
        files = {}
        for ch in ["deltarune_1", "deltarune_2"]:
            f = tmp_path / f"{ch}_data.win"
            f.write_bytes(f"ORIGINAL_{ch}".encode())
            files[ch] = f
            bm.backup_file(ch, str(f))
        for _ch, f in files.items():
            f.write_bytes(b"MODIFIED")
        bm.restore_all_backups()
        for ch, f in files.items():
            assert f.read_bytes() == f"ORIGINAL_{ch}".encode()


class TestReportParsing:
    """Tests for patching and merging."""
    def test_no_report(self):
        """Checks that noing report."""
        patcher = G3MToolPatchingService(Mock(), Mock())
        assert patcher.get_report_path() is None
        assert patcher.report_has_conflicts() is False
        assert patcher.get_report_stats() == (0, 0)

    def test_report_with_conflicts(self, tmp_path):
        """Checks that reporting  with conflicts."""
        report = tmp_path / "report.md"
        report.write_text("## Merge Report\n\nTotal conflicts: 3\nAuto-resolved: 1\n")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher._last_report_path = str(report)
        assert patcher.report_has_conflicts() is True
        total, auto = patcher.get_report_stats()
        assert total == 3
        assert auto == 1

    def test_report_without_conflicts(self, tmp_path):
        """Checks that reporting  without conflicts."""
        report = tmp_path / "report.md"
        report.write_text("## Merge Report\n\nAll patches applied cleanly.\n")
        patcher = G3MToolPatchingService(Mock(), Mock())
        patcher._last_report_path = str(report)
        assert patcher.report_has_conflicts() is False


class TestXdeltaPatchApplication:
    """Tests for patching and merging."""
    def test_xdelta_patch_with_g3mtool(
        self, game_data_dir, patches_game_dirs, deltarune_chapter_dirs
    ):
        """Checks that xdeltaing patch with g3mtool."""
        chapter1_dir = deltarune_chapter_dirs["chapter1"]
        data_win_path = Path(chapter1_dir) / "data.win"
        if not data_win_path.exists():
            pytest.skip("Test data.win not found.")
        patch_file = None
        if "deltarune" in patches_game_dirs:
            chapter1_patches = patches_game_dirs["deltarune"].get("chapter1")
            if chapter1_patches:
                patch_path = Path(chapter1_patches)
                xdelta_patches = list(patch_path.glob("*.xdelta"))
                if xdelta_patches:
                    patch_file = str(xdelta_patches[0])
        if not patch_file:
            pytest.skip("No xdelta patches found.")
        g3mtool = G3MToolManager()
        if not g3mtool.is_available():
            pytest.skip("G3MTool executable not found")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_data_win = os.path.join(temp_dir, "data.win")
            shutil.copy2(data_win_path, temp_data_win)
            output_path = os.path.join(temp_dir, "patched_data.win")
            returncode, _stdout, stderr = g3mtool.xpatch_apply(
                temp_data_win, patch_file, output_path
            )
            if returncode != 0:
                pytest.fail(f"xpatch apply failed: {stderr[:500]}")
            assert os.path.exists(output_path)
            patched_size = os.path.getsize(output_path)
            assert patched_size > 0

    def test_xdelta_missing_output_uses_warning_fallback(self, tmp_path):
        """Checks that xdeltaing missing output uses warning fallback."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        data_win_path = tmp_path / "data.win"
        patch_file = tmp_path / "chapter4.xdelta"
        output_path = tmp_path / "patched_data.win"
        data_win_path.write_bytes(b"ORIGINAL")
        patch_file.write_bytes(b"PATCH")
        patcher.g3mtool.xpatch_apply = Mock(return_value=(0, "", ""))
        patcher.warning_handler = Mock(return_value=True)

        result = patcher._apply_single_mod(
            str(data_win_path),
            (str(patch_file), MOD_TYPE_XDELTA, str(tmp_path)),
            str(output_path),
            str(tmp_path / "g3mtool.log"),
            0,
            100,
            "Chapter 4",
        )

        assert result is True
        assert output_path.read_bytes() == b"ORIGINAL"
        patcher.warning_handler.assert_called_once()


class TestFileOverrideProgress:
    """Tests for patching and merging."""
    def test_apply_file_overrides_reports_incremental_progress(self, tmp_path):
        """Checks that applying file overrides reports incremental progress."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        mod_dir.mkdir()
        target_dir.mkdir()
        (mod_dir / "readme.txt").write_text("hello", encoding="utf-8")
        (mod_dir / "notes.md").write_text("world", encoding="utf-8")
        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._backup_or_mark_file = Mock()
        patcher._request_warning = Mock(return_value=True)
        patcher.patching_logger = Mock()
        progress_updates = []

        result = apply_file_overrides(
            patcher,
            str(mod_dir),
            str(target_dir),
            set(),
            False,
            progress_callback=lambda fraction, message: progress_updates.append(
                (fraction, message)
            ),
            mod_name="Test Mod",
        )

        assert result is True
        assert len(progress_updates) >= 2
        assert progress_updates[-1][0] == 1

    def test_xdelta_without_matching_target_does_not_warn(self, tmp_path):
        """Checks that xdeltaing  without matching target does not warn."""
        from utils.patching.file_override_utils import apply_file_overrides

        mod_dir = tmp_path / "mod"
        target_dir = tmp_path / "target"
        mod_dir.mkdir()
        target_dir.mkdir()
        (mod_dir / "chapter1.xdelta").write_bytes(b"fake")
        patcher = Mock()
        patcher.xdelta_modpack = False
        patcher._request_warning = Mock(return_value=False)
        patcher.patching_logger = Mock()

        result = apply_file_overrides(
            patcher, str(mod_dir), str(target_dir), set(), False
        )

        assert result is True
        patcher._request_warning.assert_not_called()


class TestG3MPatchProgressText:
    """Tests for patching and merging."""
    def test_multi_patch_progress_uses_generic_patching_text(
        self, monkeypatch, tmp_path
    ):
        """Checks that multiing patch progress uses generic patching text."""
        app_state = Mock()
        app_state.local_config = {}
        patcher = G3MToolPatchingService(app_state, Mock())
        patcher._temp_dir = str(tmp_path)
        patcher._continue_without_data_patch = Mock(return_value=False)
        patcher.report_has_conflicts = Mock(return_value=False)
        progress_messages = []

        monkeypatch.setattr(
            "services.g3mtool_patching_service.tr",
            lambda key, **kwargs: f"{key}|{kwargs}",
        )
        patcher._emit_chapter_progress = Mock(
            side_effect=lambda start, end, fraction, message: progress_messages.append(
                message
            )
        )
        patcher.g3mtool.merge_patches = Mock(
            side_effect=lambda *args, **kwargs: (
                kwargs["progress_callback"](50, "merge"),
                tmp_path.joinpath("out.win").write_text("patched", encoding="utf-8"),
                (0, "", ""),
            )[-1]
        )

        assert patcher._apply_multi_mod(
            str(tmp_path / "data.win"),
            [
                ("a.g3mpatch", MOD_TYPE_G3MPATCH, "a"),
                ("b.g3mpatch", MOD_TYPE_G3MPATCH, "b"),
            ],
            str(tmp_path / "out.win"),
            str(tmp_path / "g3mtool.log"),
            "chapter1",
            0,
            100,
            "Chapter 1",
        )
        assert any(
            "status.patching_chapter" in message for message in progress_messages
        )
        assert all(
            "status.merging_patches" not in message for message in progress_messages
        )
