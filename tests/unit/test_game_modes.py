"""Tests for game_modes: get_tab, get_folder_name with files_key fallback."""

from models.game_modes import DeltaruneGame, GameDefinition, GameTab


class TestGetTab:
    """get_tab should match by tab_id first, then by files_key."""

    def test_match_by_tab_id(self):
        game = DeltaruneGame()
        tab = game.get_tab("deltarune_1")
        assert tab is not None
        assert tab.tab_id == "deltarune_1"
        assert tab.files_key == "1"

    def test_match_by_files_key(self):
        game = DeltaruneGame()
        tab = game.get_tab("1")
        assert tab is not None
        assert tab.tab_id == "deltarune_1"
        assert tab.files_key == "1"

    def test_no_match_returns_none(self):
        game = DeltaruneGame()
        assert game.get_tab("nonexistent") is None

    def test_all_deltarune_chapters_by_files_key(self):
        game = DeltaruneGame()
        for fk in ("0", "1", "2", "3", "4"):
            tab = game.get_tab(fk)
            assert tab is not None, f"files_key={fk} should match"
            assert tab.files_key == fk


class TestGetFolderName:
    """get_folder_name should resolve folder via files_key when tab_id doesn't match."""

    def test_folder_by_tab_id(self):
        game = DeltaruneGame()
        assert game.get_folder_name("deltarune_1") == "chapter_1"

    def test_folder_by_files_key(self):
        game = DeltaruneGame()
        assert game.get_folder_name("1") == "chapter_1"

    def test_folder_unknown_returns_raw(self):
        game = DeltaruneGame()
        assert game.get_folder_name("unknown") == "unknown"

    def test_single_tab_game_folder_by_files_key(self):
        """Single-tab games should also resolve by files_key."""
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
