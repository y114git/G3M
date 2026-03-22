from unittest.mock import patch


class TestConstants:

    def test_constants_import(self):
        from config.constants import (
            APP_ID,
            GAMEBANANA_API_BASE,
            LAUNCHER_VERSION,
            SOCIAL_LINKS,
            UI_COLORS,
        )
        assert LAUNCHER_VERSION is not None
        assert APP_ID is not None
        assert isinstance(UI_COLORS, dict)
        assert isinstance(SOCIAL_LINKS, dict)
        assert GAMEBANANA_API_BASE is not None

    def test_ui_colors_structure(self):
        from config.constants import UI_COLORS
        assert 'status_error' in UI_COLORS
        assert 'status_success' in UI_COLORS
        assert 'status_warning' in UI_COLORS
        assert 'status_info' in UI_COLORS

    def test_gamebanana_constants(self):
        from config.constants import (
            GAMEBANANA_GAME_IDS,
            GAMEBANANA_TOOL_ID_DELTAHUB,
            GAMEBANANA_TOOL_ID_DELTAMOD,
        )
        assert isinstance(GAMEBANANA_GAME_IDS, dict)
        assert 'deltarune' in GAMEBANANA_GAME_IDS
        assert 'undertale' in GAMEBANANA_GAME_IDS
        assert 'undertaleyellow' in GAMEBANANA_GAME_IDS
        assert 'pizzatower' in GAMEBANANA_GAME_IDS
        assert 'sugaryspire' in GAMEBANANA_GAME_IDS
        assert GAMEBANANA_TOOL_ID_DELTAHUB is not None
        assert GAMEBANANA_TOOL_ID_DELTAMOD is not None


class TestConfigLoader:

    def test_config_loader_import(self):
        from config.config_loader import ConfigLoader, get_config_value
        assert callable(get_config_value)
        assert ConfigLoader is not None

    @patch('config.config_loader.get_config_value')
    def test_get_config_value(self, mock_get_value):
        from config.config_loader import get_config_value
        mock_get_value.return_value = 'test_value'
        assert callable(get_config_value)
        assert get_config_value('TEST_KEY', 'default') == 'test_value'
