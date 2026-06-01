import os
from unittest.mock import Mock, patch

import pytest

from utils.file_utils import has_deltamod_info_file, sanitize_filename
from utils.mod_utils import get_mod_id, get_mod_name


class TestUiUtils:
    """Tests for utils."""
    def test_stop_existing_fade_clears_animation_reference_and_deletes_anim(self, qapp):
        """Checks that stopping existing fade clears animation reference and deletes anim."""
        from PyQt6.QtWidgets import QWidget

        from ui.utils.ui_utils import UIAnimator
        widget = QWidget()
        anim = Mock()
        widget._fade_anim = anim
        UIAnimator._stop_existing_fade(widget)
        anim.stop.assert_called_once_with()
        anim.deleteLater.assert_called_once_with()
        assert widget._fade_anim is None
        widget.deleteLater()


class TestModUtils:
    """Tests for utils."""
    def test_get_mod_id_from_dict(self):
        """Checks that getting mod id from dict."""
        mod_data = {'id': 'test_key_001'}
        assert get_mod_id(mod_data) == 'test_key_001'
        mod_data = {'id': 'test_mod_002'}
        assert get_mod_id(mod_data) == 'test_mod_002'
        mod_data = {'name': 'test_mod_003'}
        assert get_mod_id(mod_data) == 'test_mod_003'

    def test_get_mod_id_from_object(self):
        """Checks that getting mod id from object."""
        class ModObject:

            def __init__(self) -> None:
                self.id = 'test_key_004'
        mod_obj = ModObject()
        assert get_mod_id(mod_obj) == 'test_key_004'

        class ModObject2:

            def __init__(self) -> None:
                self.id = 'test_key_005'
        mod_obj2 = ModObject2()
        assert get_mod_id(mod_obj2) == 'test_key_005'

    def test_get_mod_id_none(self):
        """Checks that getting mod id none."""
        assert get_mod_id(None) is None

    def test_get_mod_name_from_dict(self):
        """Checks that getting mod name from dict."""
        mod_data = {'name': 'Test Mod'}
        assert get_mod_name(mod_data) == 'Test Mod'
        mod_data = {}
        assert get_mod_name(mod_data) == 'Unknown'
        assert get_mod_name(mod_data, 'Default') == 'Default'

    def test_get_mod_name_from_object(self):
        """Checks that getting mod name from object."""
        class ModObject:

            def __init__(self) -> None:
                self.name = 'Test Mod Object'
        mod_obj = ModObject()
        assert get_mod_name(mod_obj) == 'Test Mod Object'

    def test_get_mod_name_none(self):
        """Checks that getting mod name none."""
        assert get_mod_name(None) == 'Unknown'
        assert get_mod_name(None, 'Custom Default') == 'Custom Default'


class TestFileUtils:
    """Tests for utils."""
    def test_sanitize_filename(self):
        """Checks that sanitizing filename."""
        assert sanitize_filename('test_file.txt') == 'test_file.txt'
        assert sanitize_filename('test/file.txt') == 'testfile.txt'
        assert sanitize_filename('test\\file.txt') == 'testfile.txt'
        assert sanitize_filename('test:file.txt') == 'testfile.txt'
        assert sanitize_filename('test*file.txt') == 'testfile.txt'
        assert sanitize_filename('test?file.txt') == 'testfile.txt'
        assert sanitize_filename('test<file.txt') == 'testfile.txt'
        assert sanitize_filename('test>file.txt') == 'testfile.txt'
        assert sanitize_filename('test|file.txt') == 'testfile.txt'
        assert sanitize_filename('CON.txt') == 'CON.txt'
        assert sanitize_filename('PRN.txt') == 'PRN.txt'
        assert sanitize_filename('AUX.txt') == 'AUX.txt'

    def test_safe_rmtree_default_params(self, temp_dir, qapp):
        """Checks that sanitizing rmtree default params."""
        from utils.file_utils import safe_rmtree

        test_dir = os.path.join(temp_dir, 'test_rmtree')
        os.makedirs(test_dir, exist_ok=True)
        test_file = os.path.join(test_dir, 'test.txt')
        with open(test_file, 'w') as f:
            f.write('test')

        result = safe_rmtree(test_dir)
        assert result is True
        assert not os.path.exists(test_dir)

        test_dir2 = os.path.join(temp_dir, 'test_rmtree2')
        os.makedirs(test_dir2, exist_ok=True)
        result2 = safe_rmtree(test_dir2, max_retries=2, delay=0.1)
        assert result2 is True
        assert not os.path.exists(test_dir2)

    def test_safe_rmtree_fails_when_directory_still_exists(self, temp_dir, monkeypatch):
        """Checks that sanitizing rmtree fails when removal silently leaves directory behind."""
        from utils.file_utils import safe_rmtree

        test_dir = os.path.join(temp_dir, "test_rmtree_stuck")
        os.makedirs(test_dir, exist_ok=True)
        monkeypatch.setattr("utils.file_utils.shutil.rmtree", lambda *_args, **_kwargs: None)

        assert safe_rmtree(test_dir, max_retries=1, delay=0) is False
        assert os.path.exists(test_dir)

    def test_has_deltamod_info_file(self):
        """Checks that detecting deltamod info file."""
        file_list = ['file1.txt', '_deltamodInfo.json', 'file2.txt']
        assert has_deltamod_info_file(file_list) is True
        file_list = ['file1.txt', 'meta.json', 'file2.txt']
        assert has_deltamod_info_file(file_list) is True
        file_list = ['file1.txt', 'file2.txt', 'mod_config.json']
        assert has_deltamod_info_file(file_list) is False
        assert has_deltamod_info_file([]) is False


class TestGameUtils:
    """Tests for utils."""
    @patch('psutil.process_iter')
    def test_is_game_running(self, mock_process_iter):
        """Checks that detects game running."""
        from services.game_detection_service import is_game_running
        mock_process = Mock()
        mock_process.info = {'name': 'DELTARUNE.exe'}
        mock_process_iter.return_value = [mock_process]
        assert is_game_running() is True
        mock_process_iter.return_value = []
        assert is_game_running() is False

    @patch('services.game_detection_service.psutil.pid_exists', side_effect=TypeError)
    def test_is_game_running_invalid_pid_returns_false(self, mock_pid_exists):
        """Checks that invalid pid input returns false."""
        from services.game_detection_service import is_game_running

        assert is_game_running("bad") is False
        mock_pid_exists.assert_called_once_with("bad")

    @patch('services.game_detection_service.psutil.pid_exists', side_effect=OverflowError)
    def test_is_game_running_overflow_pid_returns_false(self, mock_pid_exists):
        """Checks that overflow pid input returns false."""
        from services.game_detection_service import is_game_running
        large_pid = 10**100

        assert is_game_running(large_pid) is False
        mock_pid_exists.assert_called_once_with(large_pid)


class TestNetworkUtils:
    """Tests for utils."""


class TestCache:
    """Tests for utils."""
    def test_cache_basic_operations(self, qapp):
        """Checks that cache basic operations."""
        try:
            from PyQt6.QtGui import QImage

            from utils.cache_utils import add_to_cache, get_from_cache
            test_image = QImage(10, 10, QImage.Format.Format_RGB32)
            test_image.fill(16711680)
            add_to_cache('test_key', test_image)
            retrieved = get_from_cache('test_key')
            assert retrieved is not None
            assert isinstance(retrieved, QImage)
            assert get_from_cache('nonexistent') is None
        except ImportError:
            pytest.skip('Cache not available')
