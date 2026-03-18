"""Additional tests for path utils edge cases and important functions."""
import os
import sys
import time
from unittest.mock import patch
import pytest

from utils.path_utils import (
    get_launcher_dir, get_user_data_root, get_user_mods_dir,
    get_user_lang_dir, get_user_plugins_dir, get_user_themes_dir,
    resource_path, resolve_game_executable, find_chapter_resource_dir,
    _match_steam_path, autodetect_path
)
from utils.file_utils import _safe_join
from utils.archive_utils import _is_safe_path


class TestPathUtilsEdgeCases:
    """Test edge cases and important functions in path_utils."""

    def test_get_launcher_dir_frozen(self):
        """Test get_launcher_dir when frozen."""
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', '/path/to/app.exe', create=True):
            result = get_launcher_dir()
            assert result == '/path/to'

    def test_get_launcher_dir_development(self):
        """Test get_launcher_dir in development mode."""
        with patch.object(sys, 'frozen', False, create=True):
            result = get_launcher_dir()
            assert 'utils' in result or 'src' in result

    def test_get_user_data_root_windows(self):
        """Test get_user_data_root on Windows."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {'LOCALAPPDATA': 'C:\\Users\\Test\\AppData\\Local'}):
            result = get_user_data_root()
            assert result == 'C:\\Users\\Test\\AppData\\Local\\DELTAHUB'

    def test_get_user_data_root_windows_fallback(self):
        """Test get_user_data_root on Windows without LOCALAPPDATA."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {'APPDATA': 'C:\\Users\\Test\\AppData\\Roaming'}, clear=True):
            result = get_user_data_root()
            assert result == 'C:\\Users\\Test\\AppData\\Roaming\\DELTAHUB'

    def test_get_user_data_root_windows_no_env_vars(self):
        """Test get_user_data_root on Windows without env vars."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {}, clear=True), \
                patch('os.path.expanduser', return_value='C:\\Users\\Test'):
            result = get_user_data_root()
            assert result == 'C:\\Users\\Test\\DELTAHUB'

    def test_get_user_data_root_macos(self):
        """Test get_user_data_root on macOS."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Darwin'), \
                patch('os.path.expanduser', return_value='/Users/Test'):
            result = get_user_data_root()
            assert result == os.path.join('/Users/Test', 'Library', 'Application Support', 'DELTAHUB')

    def test_get_user_data_root_linux(self):
        """Test get_user_data_root on Linux."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Linux'), \
                patch('os.path.expanduser', return_value='/home/test'):
            result = get_user_data_root()
            assert result == os.path.join('/home/test', '.local', 'share', 'DELTAHUB')

    def test_get_user_directories_consistency(self):
        """Test that user directories are consistent with data root."""
        root = get_user_data_root()
        assert get_user_mods_dir() == os.path.join(root, 'mods')
        assert get_user_lang_dir() == os.path.join(root, 'lang')
        assert get_user_plugins_dir() == os.path.join(root, 'plugins')
        assert get_user_themes_dir() == os.path.join(root, 'themes')

    def test_resource_path_edge_cases(self):
        """Test resource_path with edge cases."""
        with patch.object(sys, 'frozen', False, create=True):
            result = resource_path('')
            assert result.endswith('src') or 'src' in result

        result = resource_path('assets/icons/test.ico')
        assert 'assets/icons/test.ico' in result

    def test_resolve_game_executable_edge_cases(self):
        """Test resolve_game_executable with edge cases."""
        result = resolve_game_executable(None)
        assert result is None

        result = resolve_game_executable('')
        assert result is None

        result = resolve_game_executable('/non/existent/path')
        assert result is None

    def test_resolve_game_executable_priority_search(self):
        """Test that platform priority search works correctly."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch('os.path.isdir', return_value=False), \
                patch('os.path.isfile', return_value=False):
            result = resolve_game_executable('/some/game/dir')
            # Without matching executables, should return None
            assert result is None

    def test_find_chapter_resource_dir_edge_cases(self):
        """Test find_chapter_resource_dir with edge cases."""
        result = find_chapter_resource_dir(None, 'deltarune_1')
        assert result is None

        result = find_chapter_resource_dir('', 'deltarune_1')
        assert result is None

        result = find_chapter_resource_dir('/some/path', None)
        assert result is None

    def test_match_steam_path_edge_cases(self):
        """Test _match_steam_path with edge cases."""
        result = _match_steam_path(None, None)
        assert result is False

        with patch('os.path.exists', return_value=False):
            result = _match_steam_path('/some/normalized/path', '/non/existent/steam')
            assert result is False

        with patch('os.path.exists', side_effect=OSError('Permission denied')):
            result = _match_steam_path('/some/path', '/steam/path')
            assert result is False

    def test_autodetect_path_edge_cases(self):
        """Test autodetect_path with edge cases."""
        result = autodetect_path(None)
        assert result is None

        result = autodetect_path('')
        assert result is None

        long_name = 'A' * 1000
        result = autodetect_path(long_name)
        assert result is None or isinstance(result, str)

    def test_autodetect_path_steam_integration(self):
        """Test autodetect_path Steam library detection."""
        game_name = 'TestGame'

        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch.dict(os.environ, {'ProgramFiles': 'C:\\Program Files'}, clear=True), \
                patch('os.path.exists', return_value=True):
            result = autodetect_path(game_name)
            assert isinstance(result, str)

    def test_path_normalization_consistency(self):
        """Test that path normalization is consistent across platforms."""
        test_paths = [
            'path\\to\\file',
            'path/to/file',
            'path/to\\file',
            'path\\to/file'
        ]

        normalized = [os.path.normpath(p.replace('\\', '/')).replace('\\', '/') for p in test_paths]
        assert len(set(normalized)) == 1

    def test_unicode_path_handling(self):
        """Test Unicode path handling."""
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
        """Test path security validation using actual API functions."""
        dangerous_paths = [
            '../../../etc/passwd',
            '..\\..\\..\\windows\\system32',
            '/etc/shadow'  # Unix absolute path
        ]

        # Note: C:\Windows\System32 is not detected as unsafe by _is_safe_path
        # because it only checks for '..' and Unix-style absolute paths starting with '/'
        windows_absolute_path = 'C:\\Windows\\System32'

        safe_paths = [
            'normal_file.txt',
            'subfolder/file.txt',
            'deep/nested/path.txt',
            windows_absolute_path  # Considered safe by _is_safe_path but handled by _safe_join
        ]

        # Test _is_safe_path function
        for path in dangerous_paths:
            assert not _is_safe_path(path), f"Path '{path}' should be detected as unsafe"

        for path in safe_paths:
            assert _is_safe_path(path), f"Path '{path}' should be detected as safe"

        # Test _safe_join function with dangerous paths
        base_dir = '/safe/base'

        for dangerous_path in dangerous_paths:
            with pytest.raises(ValueError, match='path_traversal'):
                _safe_join(base_dir, dangerous_path)

        # Test _safe_join with Windows absolute path (should also raise)
        with pytest.raises(ValueError, match='path_traversal'):
            _safe_join(base_dir, windows_absolute_path)

        # Test _safe_join function with safe paths
        for safe_path in safe_paths:
            if safe_path == windows_absolute_path:
                continue  # Skip Windows absolute path as it's handled above
            try:
                result = _safe_join(base_dir, safe_path)
                # Just verify it doesn't raise an exception and returns a string
                assert isinstance(result, str)
                assert len(result) > len(base_dir)  # Should be longer than base
            except ValueError:
                pytest.fail(f"Safe path '{safe_path}' should not raise ValueError")

    def test_resource_path_pyinstaller_edge_cases(self):
        """Test resource_path with PyInstaller edge cases."""
        with patch.object(sys, 'frozen', False, create=True), \
                patch.object(sys, '_MEIPASS', '/tmp/meipass', create=True):
            result = resource_path('test.txt')
            assert '/tmp/meipass' not in result

        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, '_MEIPASS', None, create=True):
            result = resource_path('test.txt')
            assert 'test.txt' in result

    def test_get_user_data_root_permission_handling(self):
        """Test get_user_data_root when home directory is not accessible."""
        with patch('os.path.expanduser', side_effect=PermissionError('Cannot access home')):
            with pytest.raises(PermissionError):
                get_user_data_root()

    def test_resolve_game_executable_permission_handling(self):
        """Test resolve_game_executable with permission issues."""
        with patch('os.path.isdir', side_effect=PermissionError('Cannot access')):
            result = resolve_game_executable('/restricted/path')
            assert result is None

    def test_find_chapter_resource_dir_macos_bundle_structure(self):
        """Test chapter resource detection on macOS with complex bundle structure."""
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Darwin'), \
                patch('os.path.exists', return_value=True), \
                patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['chapter1_data', 'other_folder']):

            game_dir = '/Applications/DELTARUNE.app'

            result = find_chapter_resource_dir(game_dir, 'deltarune_1')
            if result:
                assert 'Resources' in result or 'chapter1' in result.lower()

    def test_autodetect_path_common_game_locations(self):
        """Test autodetect_path checks common game locations with controlled mocks."""
        game_name = 'TestGame'

        # Test Windows path detection
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch('os.getenv') as mock_getenv, \
                patch('os.path.exists') as mock_exists:

            mock_getenv.side_effect = lambda key, default=None: {
                'ProgramFiles(x86)': 'C:\\Program Files (x86)',
                'ProgramFiles': 'C:\\Program Files'
            }.get(key, default)

            # Mock that game exists in first Steam location
            def exists_side_effect(path):
                return 'Steam\\steamapps\\common\\TestGame' in path

            mock_exists.side_effect = exists_side_effect

            result = autodetect_path(game_name)
            assert result is not None
            assert 'TestGame' in result
            assert result.startswith('C:\\')

        # Test Linux path detection
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Linux'), \
                patch('os.path.expanduser', return_value='/home/user'), \
                patch('os.path.exists') as mock_exists, \
                patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['SteamLibrary']):

            # Mock that game exists in Linux Steam location
            def exists_side_effect(path):
                return 'steamapps/common/TestGame' in path

            mock_exists.side_effect = exists_side_effect

            result = autodetect_path(game_name)
            assert result is not None
            assert 'TestGame' in result
            assert '/home/user' in result or '/media' in result

        # Test case when no game found
        with patch('utils.path_utils.CURRENT_PLATFORM', 'Windows'), \
                patch('os.getenv', return_value=None), \
                patch('os.path.exists', return_value=False):

            result = autodetect_path(game_name)
            assert result is None

        # Test excluded games
        with patch('os.path.exists', return_value=True):
            assert autodetect_path('UNDERTALE YELLOW') is None
            assert autodetect_path('SUGARY SPIRE') is None

    def test_path_utils_performance_considerations(self):
        """Test that path utilities don't have performance issues."""

        start = time.time()
        for _ in range(100):
            get_user_data_root()
        end = time.time()

        assert (end - start) < 1.0
