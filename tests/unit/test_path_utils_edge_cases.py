"""Additional tests for path utils edge cases and important functions."""
import os
import sys
import time
from unittest.mock import patch

import pytest

from utils.archive_utils import _is_safe_path
from utils.path_utils import (
    _match_steam_path,
    autodetect_path,
    find_chapter_resource_dir,
    get_launcher_dir,
    get_user_data_root,
    get_user_lang_dir,
    get_user_mods_dir,
    get_user_themes_dir,
    resolve_game_executable,
    resource_path,
)


class TestPathUtilsEdgeCases:
    """Tests for path utils edge cases."""
    def test_get_launcher_dir_frozen(self):
        """Checks that getting launcher dir frozen."""
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', '/path/to/app.exe', create=True):
            result = get_launcher_dir()
            assert result == '/path/to'

    def test_get_launcher_dir_development(self):
        """Checks that getting launcher dir development."""
        with patch.object(sys, 'frozen', False, create=True):
            result = get_launcher_dir()
            assert 'utils' in result or 'src' in result

    def test_get_user_data_root_windows(self):
        """Checks that getting user data root windows."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {'LOCALAPPDATA': 'C:\\Users\\Test\\AppData\\Local'}):
            result = get_user_data_root()
            assert os.path.normpath(result) == os.path.normpath('C:\\Users\\Test\\AppData\\Local\\G3M')

    def test_get_user_data_root_windows_fallback(self):
        """Checks that getting user data root windows fallback."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {'APPDATA': 'C:\\Users\\Test\\AppData\\Roaming'}, clear=True):
            result = get_user_data_root()
            assert os.path.normpath(result) == os.path.normpath('C:\\Users\\Test\\AppData\\Roaming\\G3M')

    def test_get_user_data_root_windows_no_env_vars(self):
        """Checks that getting user data root windows no env vars."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {}, clear=True), \
                patch('os.path.expanduser', return_value='C:\\Users\\Test'):
            result = get_user_data_root()
            assert os.path.normpath(result) == os.path.normpath('C:\\Users\\Test\\G3M')

    def test_get_user_data_root_macos(self):
        """Checks that getting user data root macos."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Darwin'), \
                patch('os.path.expanduser', return_value='/Users/Test'):
            result = get_user_data_root()
            assert result == os.path.join('/Users/Test', 'Library', 'Application Support', 'G3M')

    def test_get_user_data_root_linux(self):
        """Checks that getting user data root linux."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Linux'), \
                patch('os.path.expanduser', return_value='/home/test'):
            result = get_user_data_root()
            assert result == os.path.join('/home/test', '.local', 'share', 'G3M')

    def test_get_user_directories_consistency(self):
        """Checks that getting user directories consistency."""
        root = get_user_data_root()
        assert get_user_mods_dir() == os.path.join(root, 'mods')
        assert get_user_lang_dir() == os.path.join(root, 'lang')
        assert get_user_themes_dir() == os.path.join(root, 'themes')

    def test_resource_path_edge_cases(self):
        """Checks that resourceing path edge cases."""
        with patch.object(sys, 'frozen', False, create=True):
            result = resource_path('')
            assert result.endswith('src') or 'src' in result

        result = resource_path('assets/icons/test.ico')
        assert 'assets/icons/test.ico' in result

    def test_resolve_game_executable_edge_cases(self):
        """Checks that resolving game executable edge cases."""
        result = resolve_game_executable(None)
        assert result is None

        result = resolve_game_executable('')
        assert result is None

        result = resolve_game_executable('/non/existent/path')
        assert result is None

    def test_resolve_game_executable_priority_search(self):
        """Checks that resolving game executable priority search."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch('os.path.isdir', return_value=False), \
                patch('os.path.isfile', return_value=False):
            result = resolve_game_executable('/some/game/dir')
            assert result is None

    def test_find_chapter_resource_dir_edge_cases(self):
        """Checks that finding chapter resource dir edge cases."""
        result = find_chapter_resource_dir(None, 'deltarune_1')
        assert result is None

        result = find_chapter_resource_dir('', 'deltarune_1')
        assert result is None

        result = find_chapter_resource_dir('/some/path', None)
        assert result is None

    def test_match_steam_path_edge_cases(self):
        """Checks that matching steam path edge cases."""
        result = _match_steam_path(None, None)
        assert result is False

        with patch('os.path.exists', return_value=False):
            result = _match_steam_path('/some/normalized/path', '/non/existent/steam')
            assert result is False

        with patch('os.path.exists', side_effect=OSError('Permission denied')):
            result = _match_steam_path('/some/path', '/steam/path')
            assert result is False

    def test_autodetect_path_edge_cases(self):
        """Checks that autodetecting path edge cases."""
        result = autodetect_path(None)
        assert result is None

        result = autodetect_path('')
        assert result is None

        long_name = 'A' * 1000
        result = autodetect_path(long_name)
        assert result is None or isinstance(result, str)

    def test_autodetect_path_steam_integration(self):
        """Checks that autodetecting path steam integration."""
        game_name = 'TestGame'

        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {'ProgramFiles': 'C:\\Program Files'}, clear=True), \
                patch('os.path.exists', return_value=True):
            result = autodetect_path(game_name)
            assert isinstance(result, str)

    def test_path_normalization_consistency(self):
        """Checks that pathing normalization consistency."""
        test_paths = [
            'path\\to\\file',
            'path/to/file',
            'path/to\\file',
            'path\\to/file'
        ]

        normalized = [os.path.normpath(p.replace('\\', '/')).replace('\\', '/') for p in test_paths]
        assert len(set(normalized)) == 1

    def test_unicode_path_handling(self):
        """Checks that unicodeing path handling."""
        unicode_paths = [
            'тест/путь',
            'テスト/パス',
            '测试/路径',
            '🎮/game'
        ]

        for path in unicode_paths:
            try:
                normalized = os.path.normpath(path)
                assert isinstance(normalized, str)
            except Exception as e:
                pytest.skip(f"Unicode handling not supported on this platform: {e}")

    def test_path_security_validation(self):
        """Checks that pathing security validation."""
        dangerous_paths = [
            '../../../etc/passwd',
            '/etc/shadow',
            '..\\..\\..\\windows\\system32'
        ]

        windows_absolute_path = 'C:\\Windows\\System32'

        safe_paths = [
            'normal_file.txt',
            'subfolder/file.txt',
            'deep/nested/path.txt',
            windows_absolute_path
        ]

        for path in dangerous_paths:
            assert not _is_safe_path(path), f"Path '{path}' should be detected as unsafe"

        for path in safe_paths:
            assert _is_safe_path(path), f"Path '{path}' should be detected as safe"

    def test_resource_path_pyinstaller_edge_cases(self):
        """Checks that resourceing path pyinstaller edge cases."""
        bundle_root = '/bundle-root/meipass'
        with patch.object(sys, 'frozen', False, create=True), \
                patch.object(sys, '_MEIPASS', bundle_root, create=True):
            result = resource_path('test.txt')
            assert bundle_root not in result

        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, '_MEIPASS', None, create=True):
            result = resource_path('test.txt')
            assert 'test.txt' in result

    def test_get_user_data_root_permission_handling(self):
        """Checks that getting user data root permission handling."""
        with patch('os.path.expanduser', side_effect=PermissionError('Cannot access home')), pytest.raises(PermissionError):
            get_user_data_root()

    def test_resolve_game_executable_permission_handling(self):
        """Checks that resolving game executable permission handling."""
        with patch('os.path.isdir', side_effect=PermissionError('Cannot access')):
            result = resolve_game_executable('/restricted/path')
            assert result is None

    def test_find_chapter_resource_dir_macos_bundle_structure(self):
        """Checks that finding chapter resource dir macos bundle structure."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Darwin'), \
                patch('os.path.exists', return_value=True), \
                patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['chapter1_data', 'other_folder']):

            game_dir = '/Applications/DELTARUNE.app'

            result = find_chapter_resource_dir(game_dir, 'deltarune_1')
            if result:
                assert 'Resources' in result or 'chapter1' in result.lower()

    def test_autodetect_path_common_game_locations(self):
        """Checks that autodetecting path common game locations."""
        game_name = 'TestGame'

        with patch('utils.path_utils.CURRENT_PLATFORM', 'Linux'), \
                patch('os.path.expanduser', return_value='/home/user'), \
                patch('os.path.exists') as mock_exists, \
                patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['SteamLibrary']):

            def exists_side_effect(path):
                return 'steamapps/common/TestGame' in path

            mock_exists.side_effect = exists_side_effect

            result = autodetect_path(game_name)
            assert result is not None
            assert 'TestGame' in result
            assert '/home/user' in result or '/media' in result

        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {}, clear=True), \
                patch('os.path.exists', return_value=False), \
                patch('os.path.isdir', return_value=False):

            result = autodetect_path(game_name)
            assert result is None

        with patch('os.path.exists', return_value=True):
            assert autodetect_path('UNDERTALE YELLOW') is None
            assert autodetect_path('SUGARY SPIRE') is None

    def test_path_utils_performance_considerations(self):
        """Checks that pathing utils performance considerations."""
        start = time.time()
        for _ in range(100):
            get_user_data_root()
        end = time.time()

        assert (end - start) < 1.0

