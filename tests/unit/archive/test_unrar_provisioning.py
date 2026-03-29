"""Tests for UnRAR provisioning functionality."""
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

from utils.archive_utils import _ensure_unrar_available, _get_unrar_path


class TestUnrarProvisioning(unittest.TestCase):
    """Tests for unrar provisioning."""
    def test_ensure_unrar_raises_when_missing(self):
        """Checks that ensuring unrar raises when missing."""
        mock_rarfile = MagicMock()
        mock_rarfile.UNRAR_TOOL = 'unrar'
        with patch.dict(sys.modules, {'rarfile': mock_rarfile}), patch('subprocess.run', side_effect=FileNotFoundError), patch('os.path.exists', return_value=False), pytest.raises(FileNotFoundError):
            _ensure_unrar_available()

    def test_ensure_unrar_uses_bundled_binary(self):
        """Checks that ensuring unrar uses bundled binary."""
        mock_rarfile = MagicMock()
        mock_rarfile.UNRAR_TOOL = 'unrar'
        with patch.dict(sys.modules, {'rarfile': mock_rarfile}), patch('os.path.exists', return_value=True):
            _ensure_unrar_available()
            updated_tool = mock_rarfile.UNRAR_TOOL
            assert any(sub in updated_tool for sub in ('assets', 'bin')), f"Expected path containing 'assets' or 'bin', got: {updated_tool}"


class TestUnrarPathResolution(unittest.TestCase):
    """Tests for unrar provisioning."""
    def test_get_unrar_path_returns_string(self):
        """Checks that getting unrar path returns string."""
        result = _get_unrar_path()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_unrar_path_contains_unrar(self):
        """Checks that getting unrar path contains unrar."""
        result = _get_unrar_path()
        assert 'unrar' in result.lower() or 'UnRAR' in result

    def test_get_unrar_path_points_to_assets_bin(self):
        """Checks that getting unrar path points to assets bin."""
        result = _get_unrar_path()
        assert 'assets' in result
        assert 'bin' in result


if __name__ == '__main__':
    unittest.main()
