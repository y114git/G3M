from unittest.mock import Mock, patch


class TestAppWindow:
    @patch("app.window.SingleInstanceServer")
    def test_app_window_creation(self, mock_server, qapp, temp_dir):
        from app.window import AppWindow

        mock_server_instance = Mock()
        mock_server_instance.listen.return_value = True
        mock_server.return_value = mock_server_instance
        mock_presence_response = Mock()
        mock_presence_response.status_code = 200
        mock_presence_response.json.return_value = {"online": 0}
        mock_presence_session = Mock()
        mock_presence_session.post.return_value = mock_presence_response
        with (
            patch("utils.path_utils.get_user_data_root", return_value=temp_dir),
            patch("utils.path_utils.get_launcher_dir", return_value=temp_dir),
            patch("utils.path_utils.get_user_mods_dir", return_value=temp_dir),
            patch("utils.path_utils.get_user_plugins_dir", return_value=temp_dir),
            patch(
                "workers.presence_worker.get_session",
                return_value=mock_presence_session,
            ),
        ):
            window = AppWindow()
            try:
                assert window is not None
                assert hasattr(window, "app_state")
                assert hasattr(window, "settings_service")
                assert hasattr(window, "mod_service")
                assert hasattr(window, "game_launch")
                assert window.windowTitle() == "DELTAHUB"
            finally:
                window.close()

    def test_sync_chapter_tab_buttons_hides_extra_buttons_for_single_tab_game(
        self, qapp
    ):
        from PyQt6.QtWidgets import QPushButton, QWidget

        from app.game_ui import sync_chapter_tab_buttons
        from models.game_modes import UndertaleGame

        window = QWidget()
        window.app_state = Mock()
        window.app_state.game_mode = UndertaleGame()
        window.app_state.current_mode = "chapter"
        window.chapter_tabs_widget = QWidget()
        window.chapter_tab_buttons = [QPushButton() for _ in range(5)]
        window._on_chapter_tab_clicked = Mock()
        tabs = sync_chapter_tab_buttons(window)
        assert len(tabs) == 1
        assert window.chapter_tab_buttons[0].isVisible()
        assert (
            getattr(window.chapter_tab_buttons[0], "_chapter_id", None) == "undertale"
        )
        for btn in window.chapter_tab_buttons[1:]:
            assert not btn.isVisible()
            assert getattr(btn, "_chapter_id", None) is None
        assert window.chapter_tabs_widget.isHidden()
        window.chapter_tabs_widget.deleteLater()
        for btn in window.chapter_tab_buttons:
            btn.deleteLater()
        window.deleteLater()


class TestTabBuilders:
    def test_library_tab_builder_creation(self, qapp, app_state, feedback_service):
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        assert builder is not None

    def test_mods_browser_tab_builder_creation(self, qapp, app_state, feedback_service):
        from PyQt6.QtWidgets import QGridLayout

        from ui.builders.search_tab_builder import ModsBrowserTabBuilder

        builder = ModsBrowserTabBuilder(app_state, None)
        assert builder is not None
        widget = builder.build()
        widgets = builder.get_widgets()
        assert widgets["mod_list_columns"] == 1
        assert isinstance(widgets["mod_list_layout"], QGridLayout)
        assert widgets["sort_combo"].currentData() == "relevant"
        assert "show_nsfw_checkbox" in widgets
        assert widgets["show_nsfw_checkbox"].isChecked() is False
        widget.deleteLater()

    def test_mods_browser_show_nsfw_checkbox_scales_with_ui_scale(
        self, qapp, app_state, feedback_service
    ):
        from ui.builders.search_tab_builder import ModsBrowserTabBuilder

        app_state.local_config["ui_scale"] = 1.5
        builder = ModsBrowserTabBuilder(app_state, None)
        widget = builder.build()
        checkbox = builder.get_widgets()["show_nsfw_checkbox"]
        assert "font-size:" in checkbox.styleSheet()
        scaled_style = checkbox.styleSheet()
        app_state.local_config["ui_scale"] = 1.0
        builder.refresh_dynamic_styles()
        base_style = checkbox.styleSheet()
        assert scaled_style != base_style
        widget.deleteLater()

    def test_plugin_tab_builder_creation(self, qapp, app_state, feedback_service):
        from ui.builders.plugin_tab_builder import PluginTabBuilder

        builder = PluginTabBuilder(app_state, None)
        assert builder is not None

    def test_settings_view_builder_creation(self, qapp, app_state, feedback_service):
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        assert builder is not None
        builder.build()
        assert "games_manager_button" in builder.get_widgets()
