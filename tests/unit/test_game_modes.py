"""Tests for game_modes: get_tab, get_folder_name with files_key fallback."""

from models.game_modes import (
    CustomGameRecord,
    CustomSingleTabGame,
    DeltaruneGame,
    GameDefinition,
    GameTab,
)


class TestGetTab:
    """Tests for game modes."""
    def test_match_by_tab_id(self):
        """Checks that matching  by tab id."""
        game = DeltaruneGame()
        tab = game.get_tab("deltarune_1")
        assert tab is not None
        assert tab.tab_id == "deltarune_1"
        assert tab.files_key == "1"

    def test_match_by_files_key(self):
        """Checks that matching  by files key."""
        game = DeltaruneGame()
        tab = game.get_tab("1")
        assert tab is not None
        assert tab.tab_id == "deltarune_1"
        assert tab.files_key == "1"

    def test_no_match_returns_none(self):
        """Checks that noing match returns none."""
        game = DeltaruneGame()
        assert game.get_tab("nonexistent") is None

    def test_all_deltarune_chapters_by_files_key(self):
        """Checks that alling deltarune chapters by files key."""
        game = DeltaruneGame()
        for fk in ("0", "1", "2", "3", "4"):
            tab = game.get_tab(fk)
            assert tab is not None, f"files_key={fk} should match"
            assert tab.files_key == fk


class TestGetFolderName:
    """Tests for game modes."""
    def test_folder_by_tab_id(self):
        """Checks that foldering  by tab id."""
        game = DeltaruneGame()
        assert game.get_folder_name("deltarune_1") == "chapter_1"

    def test_folder_by_files_key(self):
        """Checks that foldering  by files key."""
        game = DeltaruneGame()
        assert game.get_folder_name("1") == "chapter_1"

    def test_folder_unknown_returns_raw(self):
        """Checks that foldering unknown returns raw."""
        game = DeltaruneGame()
        assert game.get_folder_name("unknown") == "unknown"

    def test_single_tab_game_folder_by_files_key(self):
        """Checks that singleing tab game folder by files key."""
        game = GameDefinition()
        game.game_id = "testgame"
        game.tabs = [
            GameTab(
                tab_id="testgame_main",
                files_key="main",
                name_key="tabs.main",
                folder_name="main_data",
            )
        ]
        assert game.get_folder_name("main") == "main_data"
        assert game.get_folder_name("testgame_main") == "main_data"


class TestCustomSingleTabGame:
    """Tests for game modes."""
    def test_custom_game_uses_generated_runtime_keys(self):
        """Checks that customing game uses generated runtime keys."""
        record = CustomGameRecord(
            id="custom_test",
            display_name="Test Game",
            primary_executable="test.exe",
            data_file_name="game.ios",
            steam_app_id="123",
            gamebanana_id=456,
        )
        game = CustomSingleTabGame(record)
        assert game.game_id == "custom_test"
        assert game.path_config_key == "custom_game_path_custom_test"
        assert game.custom_exec_config_key == "custom_game_exec_custom_test"
        assert game.used_mods_config_key == "used_mods_custom_test"
        assert game.data_file_name == "game.ios"
        assert game.tabs[0].tab_id == "custom_test"
        assert game.tabs[0].files_key == "custom_test"
        assert game.get_folder_name("custom_test") == "custom_test"
        assert not game.direct_launch_allowed
