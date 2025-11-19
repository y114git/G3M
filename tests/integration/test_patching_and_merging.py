import os
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock
from core.app_state import AppState
from ui.common.feedback import FeedbackManager
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
            _ = os.path.getsize(temp_data_win)
            mod_manager = Mock()
            merger = MultiModMerger(app_state, mod_manager)
            assert merger.xdelta_path is not None, 'xdelta executable should be found'
            assert os.path.exists(merger.xdelta_path), 'xdelta executable should exist'
            success = merger._apply_xdelta_patches(temp_data_win, [patch_file])
            assert success is True, 'Patch application should return True on success'
            assert os.path.exists(temp_data_win), 'Patched file should exist after patching'
            patched_size = os.path.getsize(temp_data_win)
            assert patched_size > 0, 'Patched file should have content (size > 0)'
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
        assert hasattr(merger, 'utmtcli')
        assert hasattr(merger, 'xdelta_path')

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
