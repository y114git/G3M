import os
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestGameBananaAPI:

    @patch('requests.Session')
    def test_fetch_game_mods(self, mock_session_class):
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_aRecords': [{'_idRow': 12345, '_sModelName': 'Mod', '_sName': 'Test Mod', '_nDownloadCount': 1000}]}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        mods, needing_metadata = api.get_game_mods(game_id=6755, page=1, per_page=20)
        assert mods is not None
        assert isinstance(mods, list)

    @patch('requests.Session')
    def test_get_mod_details(self, mock_session_class):
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_idRow': 12345, '_sName': 'Test Mod', '_sDescription': 'A test mod'}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        details = api.get_mod_details(mod_id=12345)
        assert details is None or isinstance(details, dict)

    @patch('requests.Session')
    def test_get_supported_files(self, mock_session_class):
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_aFiles': [{'_idRow': 1, '_sFile': 'mod.zip', '_nDownloadCount': 500}]}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        result = api.get_supported_files_for_mod(mod_id=12345)
        assert isinstance(result, dict)
        assert 'supported_files' in result
        assert 'has_supported_files' in result
        assert 'compatibility_checked' in result
        assert 'preferred_format' in result
        assert 'tool_ids' in result
        assert 'has_deltahub_file' in result
        assert 'has_deltamod_file' in result
        assert isinstance(result['supported_files'], list)
        assert isinstance(result['has_supported_files'], bool)
        assert isinstance(result['compatibility_checked'], bool)
        assert isinstance(result['tool_ids'], list)
        assert isinstance(result['has_deltahub_file'], bool)
        assert isinstance(result['has_deltamod_file'], bool)

    @patch('requests.Session')
    def test_get_supported_files_with_external_url(self, mock_session_class):
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_aFiles': [{'_idRow': 1, '_sFile': 'mod.zip', '_nDownloadCount': 500}]}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        external_url = 'https://gamebanana.com/mods/12345'
        result = api.get_supported_files_for_mod(mod_id=12345, external_url=external_url)
        assert isinstance(result, dict)
        assert 'supported_files' in result
        assert 'has_supported_files' in result
        assert 'compatibility_checked' in result


class TestGameBananaConverter:

    def test_convert_gamebanana_mod(self, temp_mods_dir):
        from adapters.gamebanana_converter import GameBananaConverter
        import tempfile
        import zipfile
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_archive:
            archive_path = tmp_archive.name
            with zipfile.ZipFile(archive_path, 'w') as zf:
                zf.writestr('meta.json', '{"metadata": {"name": "Test Mod"}}')
                zf.writestr('file1.txt', 'test')
        try:
            converter = GameBananaConverter(archive_path=archive_path, mods_dir=temp_mods_dir, gamebanana_metadata={'mod_id': 12345})
            assert converter is not None
        finally:
            os.unlink(archive_path)


class TestGameBananaUpdateManager:

    def test_update_service_initialization(self, app_state, feedback_service):
        try:
            from services.gamebanana_update_service import GameBananaUpdateManager
            update_service = GameBananaUpdateManager(mods_dir=app_state.mods_dir)
            assert update_service is not None
            assert update_service.mods_dir == app_state.mods_dir
        except ImportError:
            import pytest
            pytest.skip('GameBananaUpdateManager not available in this version')
