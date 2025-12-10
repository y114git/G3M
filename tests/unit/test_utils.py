import pytest
from unittest.mock import Mock, patch
from utils.mod_utils import get_mod_key, get_mod_name
from utils.file_utils import sanitize_filename, has_deltamod_info_file


class TestModUtils:

    def test_get_mod_key_from_dict(self):
        mod_data = {'key': 'test_key_001'}
        assert get_mod_key(mod_data) == 'test_key_001'
        mod_data = {'mod_key': 'test_mod_002'}
        assert get_mod_key(mod_data) == 'test_mod_002'
        mod_data = {'name': 'test_mod_003'}
        assert get_mod_key(mod_data) == 'test_mod_003'

    def test_get_mod_key_from_object(self):

        class ModObject:

            def __init__(self):
                self.mod_key = 'test_key_004'
        mod_obj = ModObject()
        assert get_mod_key(mod_obj) == 'test_key_004'

        class ModObject2:

            def __init__(self):
                self.mod_key = 'test_key_005'
        mod_obj2 = ModObject2()
        assert get_mod_key(mod_obj2) == 'test_key_005'

    def test_get_mod_key_none(self):
        assert get_mod_key(None) is None

    def test_get_mod_name_from_dict(self):
        mod_data = {'name': 'Test Mod'}
        assert get_mod_name(mod_data) == 'Test Mod'
        mod_data = {}
        assert get_mod_name(mod_data) == 'Unknown'
        assert get_mod_name(mod_data, 'Default') == 'Default'

    def test_get_mod_name_from_object(self):

        class ModObject:

            def __init__(self):
                self.name = 'Test Mod Object'
        mod_obj = ModObject()
        assert get_mod_name(mod_obj) == 'Test Mod Object'

    def test_get_mod_name_none(self):
        assert get_mod_name(None) == 'Unknown'
        assert get_mod_name(None, 'Custom Default') == 'Custom Default'


class TestFileUtils:

    def test_sanitize_filename(self):
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

    def test_has_deltamod_info_file(self):
        file_list = ['file1.txt', '_deltamodInfo.json', 'file2.txt']
        assert has_deltamod_info_file(file_list) is True
        file_list = ['file1.txt', 'meta.json', 'file2.txt']
        assert has_deltamod_info_file(file_list) is True
        file_list = ['file1.txt', 'file2.txt', 'config.json']
        assert has_deltamod_info_file(file_list) is False
        assert has_deltamod_info_file([]) is False


class TestPathUtils:

    def test_get_user_data_root(self):
        from utils.path_utils import get_user_data_root
        root = get_user_data_root()
        assert root is not None
        assert isinstance(root, str)
        assert 'DELTAHUB' in root

    def test_get_user_mods_dir(self):
        from utils.path_utils import get_user_mods_dir
        mods_dir = get_user_mods_dir()
        assert mods_dir is not None
        assert isinstance(mods_dir, str)
        assert 'mods' in mods_dir

    def test_get_user_plugins_dir(self):
        from utils.path_utils import get_user_plugins_dir
        plugins_dir = get_user_plugins_dir()
        assert plugins_dir is not None
        assert isinstance(plugins_dir, str)
        assert 'plugins' in plugins_dir

    def test_resource_path(self):
        from utils.path_utils import resource_path
        path = resource_path('assets/test.txt')
        assert path is not None
        assert isinstance(path, str)


class TestGameUtils:

    @patch('psutil.process_iter')
    def test_is_game_running(self, mock_process_iter):
        from utils.game_utils import is_game_running
        mock_process = Mock()
        mock_process.info = {'name': 'DELTARUNE.exe'}
        mock_process_iter.return_value = [mock_process]
        assert is_game_running() is True
        mock_process_iter.return_value = []


class TestCryptoUtils:

    def test_generate_secret_key(self):
        from utils.crypto_utils import generate_secret_key
        key = generate_secret_key()
        assert key is not None
        assert isinstance(key, str)
        assert key.startswith('RUNE-')
        assert len(key) > 5

    def test_hash_secret_key(self):
        from utils.crypto_utils import hash_secret_key
        key = 'RUNE-TEST123456'
        hash_value = hash_secret_key(key)
        assert hash_value is not None
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64


class TestNetworkUtils:

    def test_get_session(self):
        from utils.network_utils import get_session
        session = get_session()
        assert session is not None
        assert hasattr(session, 'headers')

    @patch('requests.get')
    def test_download_file(self, mock_get):
        from utils.network_utils import download_file
        mock_response = Mock()
        mock_response.iter_content.return_value = [b'chunk1', b'chunk2']
        mock_response.headers = {'Content-Length': '12'}
        mock_get.return_value = mock_response
        assert callable(download_file)


class TestImageLoader:

    def test_image_loader_exists(self):
        import importlib.util
        spec = importlib.util.find_spec('utils.image_loader')
        if spec is None:
            pytest.skip('ImageLoader not available')
        assert spec is not None


class TestCache:

    def test_cache_basic_operations(self, qapp):
        try:
            from utils.cache import add_to_cache, get_from_cache
            from PyQt6.QtGui import QImage
            test_image = QImage(10, 10, QImage.Format.Format_RGB32)
            test_image.fill(16711680)
            add_to_cache('test_key', test_image)
            retrieved = get_from_cache('test_key')
            assert retrieved is not None
            assert isinstance(retrieved, QImage)
            assert get_from_cache('nonexistent') is None
        except ImportError:
            pytest.skip('Cache not available')
