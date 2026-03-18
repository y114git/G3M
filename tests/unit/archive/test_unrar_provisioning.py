"""Tests for UnRAR provisioning functionality."""
import sys
import unittest
from unittest.mock import MagicMock, patch

from utils.archive_utils import _ensure_unrar_available, _get_unrar_path


class TestUnrarProvisioning(unittest.TestCase):

    def test_ensure_unrar_raises_when_missing(self):
        mock_rarfile = MagicMock()
        mock_rarfile.UNRAR_TOOL = 'unrar'
        with patch.dict(sys.modules, {'rarfile': mock_rarfile}):
            with patch('subprocess.run', side_effect=FileNotFoundError):
                with patch('os.path.exists', return_value=False):
                    with self.assertRaises(FileNotFoundError):
                        _ensure_unrar_available()

    def test_ensure_unrar_uses_bundled_binary(self):
        """Test that _ensure_unrar_available prefers bundled binary."""
        mock_rarfile = MagicMock()
        mock_rarfile.UNRAR_TOOL = 'unrar'
        with patch.dict(sys.modules, {'rarfile': mock_rarfile}):
            with patch('os.path.exists', return_value=True):
                _ensure_unrar_available()
                updated_tool = mock_rarfile.UNRAR_TOOL
                assert any(sub in updated_tool for sub in ('assets', 'bin')), f"Expected path containing 'assets' or 'bin', got: {updated_tool}"


class TestUnrarPathResolution(unittest.TestCase):

    def test_get_unrar_path_returns_string(self):
        """Test that _get_unrar_path returns a string path."""
        result = _get_unrar_path()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_get_unrar_path_contains_unrar(self):
        """Test that the path contains 'unrar' or 'UnRAR'."""
        result = _get_unrar_path()
        self.assertTrue('unrar' in result.lower() or 'UnRAR' in result)

    def test_get_unrar_path_points_to_assets_bin(self):
        """Test that path points to assets/bin directory."""
        result = _get_unrar_path()
        self.assertIn('assets', result)
        self.assertIn('bin', result)


if __name__ == '__main__':
    unittest.main()
