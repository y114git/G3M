"""Integration tests for test gamebanana."""

import os
from unittest.mock import MagicMock, Mock, patch


class TestGameBananaAPI:
    """Tests for gamebanana."""
    @patch('requests.Session')
    def test_fetch_game_mods(self, mock_session_class):
        """Checks that fetching game mods."""
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_aRecords': [{'_idRow': 12345, '_sModelName': 'Mod', '_sName': 'Test Mod', '_nDownloadCount': 1000}]}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        mods, _needing_metadata = api.get_game_mods(game_id=6755, page=1, per_page=20)

        assert mods is not None
        assert isinstance(mods, list)

    def test_map_mod_data_marks_content_rated_mod_as_nsfw(self):
        """Checks that maping mod data marks content rated mod as nsfw."""
        from adapters.gamebanana_adapter import GameBananaAPI
        api = GameBananaAPI()
        mod = api._map_mod_data({'_idRow': 657995, '_sName': 'Roaring Knight: Berserk', '_nDownloadCount': 34, '_aTags': ['Boss: Roaring Knight'], '_bHasContentRatings': True}, 'deltarune')
        assert mod is not None
        assert mod.is_nsfw is True

    @patch('requests.Session')
    def test_get_mod_profile_page(self, mock_session_class):
        """Checks that getting mod profile page."""
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_idRow': 12345, '_sName': 'Test Mod', '_sDescription': 'A test mod'}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        details = api.get_mod_profile_page(mod_id=12345)
        assert details is None or isinstance(details, dict)

    @patch('requests.Session')
    def test_get_supported_files(self, mock_session_class):
        """Checks that getting supported files."""
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
        assert 'has_g3m_file' in result
        assert 'has_deltamod_file' in result
        assert isinstance(result['supported_files'], list)
        assert isinstance(result['has_supported_files'], bool)
        assert isinstance(result['compatibility_checked'], bool)
        assert isinstance(result['tool_ids'], list)
        assert isinstance(result['has_g3m_file'], bool)
        assert isinstance(result['has_deltamod_file'], bool)

    @patch('requests.Session')
    def test_get_supported_files_with_itemtype(self, mock_session_class):
        """Checks that getting supported files with itemtype."""
        from adapters.gamebanana_adapter import GameBananaAPI
        mock_session = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'_aFiles': [{'_idRow': 1, '_sFile': 'mod.zip', '_nDownloadCount': 500}]}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        api = GameBananaAPI()
        result = api.get_supported_files_for_mod(mod_id=12345, itemtype='Wip')
        assert isinstance(result, dict)
        assert 'supported_files' in result
        assert 'has_supported_files' in result
        assert 'compatibility_checked' in result


class TestGameBananaConverter:
    """Tests for gamebanana."""
    def test_convert_gamebanana_mod(self, temp_mods_dir):
        """Checks that converting gamebanana mod."""
        import tempfile
        import zipfile

        from adapters.gamebanana_converter import GameBananaConverter
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
