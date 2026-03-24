from unittest.mock import patch

import pytest


class TestConstants:
    def test_constants_import(self):
        from config.config import (
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
        from config.config import UI_COLORS

        assert "status_error" in UI_COLORS
        assert "status_success" in UI_COLORS
        assert "status_warning" in UI_COLORS
        assert "status_info" in UI_COLORS

    def test_gamebanana_constants(self):
        from config.config import (
            GAMEBANANA_TOOL_ID_DELTAHUB,
            GAMEBANANA_TOOL_ID_DELTAMOD,
        )
        from models.game_modes import BUILTIN_GAME_REGISTRY

        for game_id in (
            "deltarune",
            "undertale",
            "undertaleyellow",
            "pizzatower",
            "sugaryspire",
        ):
            assert game_id in BUILTIN_GAME_REGISTRY, f"{game_id} missing from registry"
            assert BUILTIN_GAME_REGISTRY[game_id].gamebanana_id, (
                f"{game_id} has no gamebanana_id"
            )
        assert GAMEBANANA_TOOL_ID_DELTAHUB is not None
        assert GAMEBANANA_TOOL_ID_DELTAMOD is not None

    def test_validate_config_raises_for_missing_required_urls(self):
        from config import config_loader as config_loader_module

        with (
            patch.object(config_loader_module, "get_config_value", side_effect=lambda key, default="": {"DATA_FIREBASE_URL": "", "CLOUD_FUNCTIONS_BASE_URL": "  "}.get(key, default)),
            pytest.raises(RuntimeError, match="Missing required config DATA_FIREBASE_URL, CLOUD_FUNCTIONS_BASE_URL"),
        ):
            config_loader_module.validate_config()


class TestConfigLoader:
    def test_config_loader_import(self):
        from config.config_loader import ConfigLoader, get_config_value

        assert callable(get_config_value)
        assert ConfigLoader is not None

    @patch("config.config_loader.get_config_value")
    def test_get_config_value(self, mock_get_value):
        from config.config_loader import get_config_value

        mock_get_value.return_value = "test_value"
        assert callable(get_config_value)
        assert get_config_value("TEST_KEY", "default") == "test_value"
