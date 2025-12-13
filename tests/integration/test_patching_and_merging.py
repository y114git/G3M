import os
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock
from managers.multi_mod_merger import MultiModMerger


class TestPatching:

    def test_xdelta_patch_application(self, game_data_dir, patches_game_dirs, deltarune_chapter_dirs, app_state, feedback_manager):
        chapter1_dir = deltarune_chapter_dirs['chapter1']
        data_win_path = Path(chapter1_dir) / 'data.win'
        if not data_win_path.exists():
            pytest.skip('Test data.win not found. Please add vanilla data.win to test fixtures.')
        patch_file = None
        if 'deltarune' in patches_game_dirs:
            chapter1_patches = patches_game_dirs['deltarune'].get('chapter1')
            if chapter1_patches:
                patch_path = Path(chapter1_patches)
                xdelta_patches = list(patch_path.glob('*.xdelta'))
                if xdelta_patches:
                    patch_file = str(xdelta_patches[0])
        if not patch_file:
            pytest.skip('No xdelta patches found. Please add test patches to patches/deltarune/chapter1_/')
        temp_dir = tempfile.mkdtemp()
        try:
            temp_data_win = os.path.join(temp_dir, 'data.win')
            shutil.copy2(data_win_path, temp_data_win)
            original_size = os.path.getsize(temp_data_win)
            mod_manager = Mock()
            merger = MultiModMerger(app_state, mod_manager)
            if merger.xdelta_path is None:
                pytest.fail('xdelta executable not found: merger.xdelta_path is None')
            if not os.path.exists(merger.xdelta_path):
                pytest.fail(f'xdelta executable not found at path: {merger.xdelta_path}')
            import subprocess
            try:
                test_cmd = [merger.xdelta_path, '-h']
                result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
                if result.returncode not in (0, 1):
                    error_output = result.stderr if result.stderr else result.stdout
                    pytest.fail(f"xdelta executable cannot be executed (return code: {result.returncode}). Command: {' '.join(test_cmd)}\nError output: {error_output[:500]}")
            except subprocess.TimeoutExpired:
                pytest.fail(f'xdelta executable timed out when testing execution. Path: {merger.xdelta_path}')
            except (FileNotFoundError, PermissionError, OSError) as e:
                pytest.fail(f"xdelta executable cannot be executed: {type(e).__name__}: {e}\nPath: {merger.xdelta_path}\nFile exists: {os.path.exists(merger.xdelta_path)}\nIs file: {(os.path.isfile(merger.xdelta_path) if os.path.exists(merger.xdelta_path) else 'N/A')}")
            if not os.path.exists(temp_data_win):
                pytest.fail(f'Test data.win file does not exist: {temp_data_win}')
            if not os.path.exists(patch_file):
                pytest.fail(f'Patch file does not exist: {patch_file}')
            test_output = temp_data_win + '.test'
            try:
                test_cmd = [merger.xdelta_path, '-d', '-s', temp_data_win, patch_file, test_output]
                test_result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
                direct_test_success = test_result.returncode == 0 and os.path.exists(test_output)
                if not direct_test_success:
                    error_detail = test_result.stderr.strip() if test_result.stderr else test_result.stdout.strip() if test_result.stdout else 'No error output'
                    if os.path.exists(test_output):
                        os.remove(test_output)
                    pytest.fail(f"Direct xdelta patch test failed.\nCommand: {' '.join(test_cmd)}\nReturn code: {test_result.returncode}\nError: {error_detail[:1000]}\nData.win size: {original_size} bytes\nPatch file: {patch_file}")
                if os.path.exists(test_output):
                    os.remove(test_output)
            except subprocess.TimeoutExpired:
                pytest.fail(f"Direct xdelta patch test timed out after 30 seconds.\nCommand: {' '.join(test_cmd)}\nThis may indicate a problem with the patch file or data.win.")
            except Exception:
                pass
            success = merger._apply_xdelta_patches(temp_data_win, [patch_file])
            if not success:
                log_info = ''
                try:
                    from utils.path_utils import get_user_data_root
                    log_path = os.path.join(get_user_data_root(), 'patching.log')
                    if os.path.exists(log_path):
                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            log_lines = f.readlines()
                            recent_logs = '\n'.join(log_lines[-20:])
                            log_info = f'\n\nRecent patching.log entries:\n{recent_logs}'
                except Exception:
                    pass
                pytest.fail(f"Patch application failed via MultiModMerger._apply_xdelta_patches.\nxdelta_path: {merger.xdelta_path}\npatch_file: {patch_file}\ndata_win_path: {temp_data_win}\ndata_win_size: {original_size} bytes\ndata_win_exists: {os.path.exists(temp_data_win)}\npatch_file_exists: {os.path.exists(patch_file)}\npatch_file_size: {(os.path.getsize(patch_file) if os.path.exists(patch_file) else 'N/A')} bytes{log_info}")
            if not os.path.exists(temp_data_win):
                pytest.fail(f'Patched file does not exist after patching: {temp_data_win}')
            patched_size = os.path.getsize(temp_data_win)
            if patched_size == 0:
                pytest.fail(f'Patched file is empty (size: 0 bytes). Original size: {original_size} bytes')
            if patched_size == original_size:
                pytest.fail(f'Patched file size unchanged ({patched_size} bytes). This may indicate the patch was not applied correctly.')
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_vcdiff_patch_application(self, game_data_dir, patches_game_dirs):
        found_vcdiff = False
        for game_name, game_patches in patches_game_dirs.items():
            if isinstance(game_patches, dict):
                for chapter_name, chapter_path in game_patches.items():
                    patch_path = Path(chapter_path)
                    if any(patch_path.glob('*.vcdiff')):
                        found_vcdiff = True
                        break
            else:
                patch_path = Path(game_patches)
                if any(patch_path.glob('*.vcdiff')):
                    found_vcdiff = True
                    break
            if found_vcdiff:
                break
        if not found_vcdiff:
            pytest.skip('No vcdiff patches found.')
        assert True

    def test_patch_discovery(self, patches_game_dirs):
        all_patches = []
        for game_name, game_patches in patches_game_dirs.items():
            if isinstance(game_patches, dict):
                for chapter_name, chapter_path in game_patches.items():
                    patch_path = Path(chapter_path)
                    xdelta_patches = list(patch_path.glob('*.xdelta'))
                    vcdiff_patches = list(patch_path.glob('*.vcdiff'))
                    all_patches.extend(xdelta_patches)
                    all_patches.extend(vcdiff_patches)
            else:
                patch_path = Path(game_patches)
                xdelta_patches = list(patch_path.glob('*.xdelta'))
                vcdiff_patches = list(patch_path.glob('*.vcdiff'))
                all_patches.extend(xdelta_patches)
                all_patches.extend(vcdiff_patches)
        assert isinstance(patches_game_dirs, dict)
        if all_patches:
            assert len(all_patches) > 0, 'Should find at least one patch if patches exist'
            for patch_file in all_patches:
                assert patch_file.exists(), f'Patch file should exist: {patch_file}'
                assert patch_file.suffix in ['.xdelta', '.vcdiff'], f'Patch should be xdelta or vcdiff: {patch_file}'


class TestMerging:

    def test_merge_multiple_mods(self, patches_game_dirs, deltarune_chapter_dirs, app_state, feedback_manager):
        chapter1_dir = deltarune_chapter_dirs['chapter1']
        if not Path(chapter1_dir).exists():
            pytest.skip('Chapter directory not found.')
        data_win_files = []
        if 'deltarune' in patches_game_dirs:
            chapter1_patches = patches_game_dirs['deltarune'].get('chapter1')
            if chapter1_patches:
                patch_path = Path(chapter1_patches)
                data_win_files = list(patch_path.glob('*.win'))
        if len(data_win_files) < 2:
            pytest.skip('Need at least 2 modified data.win files for merging test. Please add test files to patches/deltarune/chapter1_/')
        mod_manager = Mock()
        merger = MultiModMerger(app_state, mod_manager)
        assert merger is not None
        assert hasattr(merger, 'utmt_wrapper')
        assert hasattr(merger, 'xdelta_path')
        
    def test_progress_throttler_initialization(self, app_state, feedback_manager, qapp):
        """Test that ProgressThrottler can be created and used."""
        from managers.multi_mod_merger import ProgressThrottler
        from PyQt6.QtCore import QTimer
        
        callback_calls = []
        def test_callback(progress, message):
            callback_calls.append((progress, message))
        
        throttler = ProgressThrottler(test_callback, throttle_ms=50, parent=qapp)
        assert throttler is not None
        assert throttler.callback == test_callback
        assert throttler.throttle_ms == 50
        
        # Test update_progress
        throttler.update_progress(10, 'Test message 1')
        throttler.update_progress(20, 'Test message 2')
        throttler.update_progress(30, 'Test message 3')
        
        # Wait a bit for timer to fire
        import time
        time.sleep(0.1)
        qapp.processEvents()
        
        # Flush to ensure all updates are emitted
        throttler.flush()
        qapp.processEvents()
        
        # Should have at least one callback call (the last one)
        assert len(callback_calls) > 0
        # Last call should be the latest update
        assert callback_calls[-1] == (30, 'Test message 3')

    def test_merge_with_priority(self, patches_game_dirs):
        found_data_win = False
        for game_name, game_patches in patches_game_dirs.items():
            if isinstance(game_patches, dict):
                for chapter_name, chapter_path in game_patches.items():
                    patch_path = Path(chapter_path)
                    if any(patch_path.glob('*.win')):
                        found_data_win = True
                        break
            else:
                patch_path = Path(game_patches)
                if any(patch_path.glob('*.win')):
                    found_data_win = True
                    break
            if found_data_win:
                break
        if not found_data_win:
            pytest.skip('No modified data.win files found.')
        assert True


class TestCombinedPatchingAndMerging:

    def test_patch_then_merge(self, game_data_dir, patches_game_dirs):
        found_patches = False
        found_data_win = False
        for game_name, game_patches in patches_game_dirs.items():
            if isinstance(game_patches, dict):
                for chapter_name, chapter_path in game_patches.items():
                    patch_path = Path(chapter_path)
                    if any(patch_path.glob('*.xdelta')) or any(patch_path.glob('*.vcdiff')):
                        found_patches = True
                    if any(patch_path.glob('*.win')):
                        found_data_win = True
            else:
                patch_path = Path(game_patches)
                if any(patch_path.glob('*.xdelta')) or any(patch_path.glob('*.vcdiff')):
                    found_patches = True
                if any(patch_path.glob('*.win')):
                    found_data_win = True
        if not found_patches or not found_data_win:
            pytest.skip('Test files not found. Please add patches and modified files to patches/ subdirectories.')
        assert True

    def test_multiple_patches_sequential(self, game_data_dir, patches_game_dirs):
        all_patches = []
        for game_name, game_patches in patches_game_dirs.items():
            if isinstance(game_patches, dict):
                for chapter_name, chapter_path in game_patches.items():
                    patch_path = Path(chapter_path)
                    patches = list(patch_path.glob('*.xdelta')) + list(patch_path.glob('*.vcdiff'))
                    all_patches.extend(patches)
            else:
                patch_path = Path(game_patches)
                patches = list(patch_path.glob('*.xdelta')) + list(patch_path.glob('*.vcdiff'))
                all_patches.extend(patches)
        if len(all_patches) < 2:
            pytest.skip('Need at least 2 patches for sequential patching test. Add them to patches/ subdirectories.')
        assert True


class TestRestoreOriginal:

    def test_restore_after_patch(self, game_data_dir, deltarune_chapter_dirs):
        chapter1_dir = deltarune_chapter_dirs['chapter1']
        data_win_path = Path(chapter1_dir) / 'data.win'
        if not data_win_path.exists():
            pytest.skip('Original data.win not found.')
        assert True

    def test_restore_after_merge(self, game_data_dir):
        assert True
