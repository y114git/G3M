import sys
import types

from dotenv import load_dotenv as real_load_dotenv


class TestConstants:
    """Tests for config."""
    def test_constants_import(self):
        """Checks that constantsing import."""
        from config.config import (
            APP_VERSION,
            GAMEBANANA_API_BASE,
            SOCIAL_LINKS,
            UI_COLORS,
        )

        assert APP_VERSION is not None
        assert isinstance(UI_COLORS, dict)
        assert isinstance(SOCIAL_LINKS, dict)
        assert GAMEBANANA_API_BASE is not None

    def test_ui_colors_structure(self):
        """Checks that uiing colors structure."""
        from config.config import UI_COLORS

        assert "status_error" in UI_COLORS
        assert "status_success" in UI_COLORS
        assert "status_warning" in UI_COLORS
        assert "status_info" in UI_COLORS

    def test_gamebanana_constants(self):
        """Checks that gamebananaing constants."""
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

    @staticmethod
    def _reload_config_module() -> types.ModuleType:
        sys.modules.pop("config.config", None)
        import config.config as config_module

        return config_module

    def test_env_config_loading_without_env(self, monkeypatch):
        """Checks that enving config loading without env."""
        monkeypatch.delenv("CLOUD_FUNCTIONS_BASE_URL", raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)

        config_module = self._reload_config_module()

        assert isinstance(config_module.CLOUD_FUNCTIONS_BASE_URL, str)
        assert config_module.CLOUD_FUNCTIONS_BASE_URL == ""

    def test_env_config_loading_with_dotenv_file(self, monkeypatch, tmp_path):
        """Checks that enving config loading with dotenv file."""
        configured_value = "https://example.com/functions"
        monkeypatch.delenv("CLOUD_FUNCTIONS_BASE_URL", raising=False)
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text(
            f"CLOUD_FUNCTIONS_BASE_URL={configured_value}\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "dotenv.load_dotenv",
            lambda *args, **kwargs: real_load_dotenv(dotenv_path=dotenv_path, override=True),
        )

        config_module = self._reload_config_module()

        assert isinstance(config_module.CLOUD_FUNCTIONS_BASE_URL, str)
        assert configured_value == config_module.CLOUD_FUNCTIONS_BASE_URL

    def test_presence_timing_constants(self):
        """Checks that presenceing timing constants."""
        from config.config import ONLINE_UPDATE_INTERVAL

        expected = 10 * 60 * 1000
        assert expected == ONLINE_UPDATE_INTERVAL
