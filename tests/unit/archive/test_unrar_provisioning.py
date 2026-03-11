"""Tests for UnRAR provisioning functionality."""
import sys
import unittest
from unittest.mock import MagicMock, patch

from utils.archive_utils import UnrarMissingError, _ensure_unrar_available, download_and_setup_unrar, _get_unrar_path


class TestUnrarProvisioning(unittest.TestCase):

    def test_ensure_unrar_raises_when_missing(self):
        mock_rarfile = MagicMock()
        # Simulate default rarfile behavior where it sets UNRAR_TOOL to 'unrar'
        mock_rarfile.UNRAR_TOOL = 'unrar'
        with patch.dict(sys.modules, {'rarfile': mock_rarfile}):
            # Mock subprocess to fail (tool not found)
            with patch('subprocess.run', side_effect=FileNotFoundError):
                # Mock local bin check to fail
                with patch('os.path.exists', return_value=False):
                    with self.assertRaises(UnrarMissingError):
                        _ensure_unrar_available()

    def test_download_callback(self):
        """Test that download_and_setup_unrar calls status_callback properly on Windows."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b'fake_data']
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response
        mock_rarfile = MagicMock()

        with patch.dict(sys.modules, {'requests': mock_requests, 'rarfile': mock_rarfile}):
            callback = MagicMock()
            # Mock subprocess.run at the module level since it's imported inside function
            with patch('builtins.open', unittest.mock.mock_open()), \
                    patch('os.makedirs'), \
                    patch('os.path.exists') as mock_exists, \
                    patch('subprocess.run') as mock_subprocess, \
                    patch('os.remove'), \
                    patch('platform.system', return_value='Windows'):
                # First call: target_path doesn't exist, second call: after extraction it does
                mock_exists.side_effect = [False, True]
                mock_subprocess.return_value = MagicMock()  # Successful subprocess run

                success = download_and_setup_unrar(status_callback=callback)

            self.assertTrue(success)
            callback.assert_any_call('Downloading UnRAR utility...')
            callback.assert_any_call('UnRAR installed successfully.')


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


if __name__ == '__main__':
    unittest.main()
