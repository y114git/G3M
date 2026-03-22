"""Tests for protocol handler functionality."""
from unittest.mock import Mock, patch

from core.protocol_handler import (
    _enqueue_deltahub_url,
    _parse_deltahub_url,
    handle_one_click_install,
)


class TestProtocolHandler:
    """Test deltahub:// protocol URL parsing and handling."""

    def test_parse_deltahub_url_valid_https(self):
        """Test parsing valid deltahub:// URLs with https."""
        url = "deltahub://https://example.com/mod.zip"
        result = _parse_deltahub_url(url)
        assert result == "https://example.com/mod.zip"

    def test_parse_deltahub_url_valid_http(self):
        """Test parsing valid deltahub:// URLs with http."""
        url = "deltahub://http://example.com/mod.zip"
        result = _parse_deltahub_url(url)
        assert result == "http://example.com/mod.zip"

    def test_parse_deltahub_url_malformed_fixes(self):
        """Test fixing common malformed URLs."""
        # Missing : after https
        url = "deltahub://https//example.com/mod.zip"
        result = _parse_deltahub_url(url)
        assert result == "https://example.com/mod.zip"

        # Missing : after http
        url = "deltahub://http//example.com/mod.zip"
        result = _parse_deltahub_url(url)
        assert result == "http://example.com/mod.zip"

    def test_parse_deltahub_url_with_comma_params(self):
        """Test parsing URLs with comma-separated parameters."""
        url = "deltahub://https://example.com/mod.zip,version=1.0"
        result = _parse_deltahub_url(url)
        assert result == "https://example.com/mod.zip"

    def test_parse_deltahub_url_with_whitespace(self):
        """Test parsing URLs with extra whitespace."""
        url = "deltahub://  https://example.com/mod.zip  "
        result = _parse_deltahub_url(url)
        assert result == "https://example.com/mod.zip"

    def test_parse_deltahub_url_trailing_slash(self):
        """Test parsing URLs with trailing slashes."""
        url = "deltahub://https://example.com/mod.zip/"
        result = _parse_deltahub_url(url)
        assert result == "https://example.com/mod.zip"

    def test_parse_deltahub_url_invalid_no_protocol(self):
        """Test parsing URLs without proper protocol."""
        url = "deltahub://example.com/mod.zip"
        result = _parse_deltahub_url(url)
        assert result == "example.com/mod.zip"  # Should not start with http:// or https://

    @patch('core.protocol_handler.is_game_running')
    @patch('core.protocol_handler.tr')
    def test_handle_one_click_install_game_running(self, mock_tr, mock_game_running):
        """Test handling install when game is running."""
        mock_game_running.return_value = True
        mock_tr.side_effect = lambda key, *args: key

        w = Mock()
        w.feedback_service = Mock()

        url = "deltahub://https://example.com/mod.zip"
        handle_one_click_install(w, url)

        w.feedback_service.show_message.assert_called_once_with('warning', 'ui.warning', 'errors.game_running')
        w.activateWindow.assert_not_called()
        w.raise_.assert_not_called()

    @patch('core.protocol_handler.is_game_running')
    def test_handle_one_click_install_regular_url(self, mock_game_running):
        """Test handling regular HTTP/HTTPS URLs."""
        mock_game_running.return_value = False

        w = Mock()
        w.feedback_service = Mock()
        w.mod_service = Mock()

        url = "https://example.com/mod.zip"
        handle_one_click_install(w, url)

        w.activateWindow.assert_called_once()
        w.raise_.assert_called_once()
        w.mod_service.install_from_url.assert_called_once_with(url)

    @patch('core.protocol_handler.is_game_running')
    @patch('core.protocol_handler._enqueue_deltahub_url')
    def test_handle_one_click_install_deltahub_url(self, mock_enqueue, mock_game_running):
        """Test handling deltahub:// URLs."""
        mock_game_running.return_value = False

        w = Mock()
        w.feedback_service = Mock()

        url = "deltahub://https://example.com/mod.zip"
        handle_one_click_install(w, url)

        w.activateWindow.assert_called_once()
        w.raise_.assert_called_once()
        mock_enqueue.assert_called_once_with(w, url)

    @patch('ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog')
    @patch('core.protocol_handler.tr')
    def test_enqueue_deltahub_url_invalid_url(self, mock_tr, mock_dialog):
        """Test enqueueing invalid deltahub URLs."""
        mock_tr.side_effect = lambda key, *args: key

        w = Mock()
        w.feedback_service = Mock()
        w.app_state = Mock()

        # Test completely invalid URL
        url = "deltahub://invalid-url"
        _enqueue_deltahub_url(w, url)

        w.feedback_service.show_message.assert_called_once_with('error', 'errors.error', 'errors.mod_not_found')
        mock_dialog.assert_not_called()

    @patch('ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog')
    @patch('core.protocol_handler.tr')
    def test_enqueue_deltahub_url_user_cancels(self, mock_tr, mock_dialog):
        """Test enqueueing when user cancels confirmation dialog."""
        mock_tr.side_effect = lambda key, *args: key
        mock_dialog.return_value.exec.return_value = False

        w = Mock()
        w.feedback_service = Mock()
        w.app_state = Mock()
        w.downloads_manager = Mock()

        url = "deltahub://https://example.com/mod.zip"
        _enqueue_deltahub_url(w, url)

        mock_dialog.assert_called_once()
        w.downloads_manager.enqueue_with_feedback.assert_not_called()

    @patch('ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog')
    @patch('core.protocol_handler.tr')
    def test_enqueue_deltahub_url_success(self, mock_tr, mock_dialog):
        """Test successful enqueueing of deltahub URL."""
        mock_tr.side_effect = lambda key, *args: key
        mock_dialog.return_value.exec.return_value = True

        w = Mock()
        w.feedback_service = Mock()
        w.app_state = Mock()
        w.downloads_manager = Mock()

        url = "deltahub://https://example.com/mod.zip"
        _enqueue_deltahub_url(w, url)

        mock_dialog.assert_called_once()
        w.downloads_manager.enqueue_with_feedback.assert_called_once()

        # Check the call arguments
        call_args = w.downloads_manager.enqueue_with_feedback.call_args
        assert call_args[1]['display_name'] == 'mod.zip'
        assert call_args[1]['source_url'] == 'https://example.com/mod.zip'

    @patch('ui.dialogs.confirm_external_download_dialog.ConfirmExternalDownloadDialog')
    @patch('core.protocol_handler.tr')
    def test_enqueue_deltahub_url_no_basename(self, mock_tr, mock_dialog):
        """Test enqueueing URL without clear basename."""
        mock_tr.side_effect = lambda key, *args: key
        mock_dialog.return_value.exec.return_value = True

        w = Mock()
        w.feedback_service = Mock()
        w.app_state = Mock()
        w.downloads_manager = Mock()

        url = "deltahub://https://example.com/"
        _enqueue_deltahub_url(w, url)

        call_args = w.downloads_manager.enqueue_with_feedback.call_args
        assert call_args[1]['display_name'] == 'example.com'
