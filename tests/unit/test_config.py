

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

    def test_env_config_loading(self):
        from config.config import CLOUD_FUNCTIONS_BASE_URL, DATA_FIREBASE_URL

        assert isinstance(DATA_FIREBASE_URL, str)
        assert isinstance(CLOUD_FUNCTIONS_BASE_URL, str)
        assert DATA_FIREBASE_URL, "DATA_FIREBASE_URL should not be empty"
        assert CLOUD_FUNCTIONS_BASE_URL, "CLOUD_FUNCTIONS_BASE_URL should not be empty"
