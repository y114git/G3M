import os
from unittest.mock import Mock, patch


class TestAppWindow:
    def test_app_window_creation(self, qapp, temp_dir):
        from app.window import AppWindow

        user_root = os.path.join(temp_dir, "user")
        mods_dir = os.path.join(temp_dir, "mods")
        profiles_dir = os.path.join(temp_dir, "profiles")
        themes_dir = os.path.join(temp_dir, "themes")
        for path in (user_root, mods_dir, profiles_dir, themes_dir):
            os.makedirs(path, exist_ok=True)
        mock_presence_response = Mock()
        mock_presence_response.status_code = 200
        mock_presence_response.json.return_value = {"online": 0}
        mock_presence_session = Mock()
        mock_presence_session.post.return_value = mock_presence_response
        with (
            patch("app_context.application_context.get_user_data_root", return_value=user_root),
            patch("app_context.application_context.get_launcher_dir", return_value=temp_dir),
            patch(
                "services.g3mtool_patching_service.get_user_data_root",
                return_value=user_root,
            ),
            patch(
                "services.blocklist_service.get_user_data_root",
                return_value=user_root,
            ),
            patch("utils.path_utils.get_user_themes_dir", return_value=themes_dir),
            patch("services.profile_service.get_user_mods_dir", return_value=mods_dir),
            patch(
                "services.profile_service.get_user_profiles_dir",
                return_value=profiles_dir,
            ),
            patch(
                "workers.presence_worker.get_session",
                return_value=mock_presence_session,
            ),
        ):
            window = AppWindow()
            try:
                assert window is not None
                assert hasattr(window, "context")
                assert hasattr(window, "app_state")
                assert hasattr(window, "settings_service")
                assert hasattr(window, "mod_service")
                assert hasattr(window, "game_launch")
                assert hasattr(window, "session_manager")
                assert hasattr(window, "plugins_widget")
                assert hasattr(window, "plugins_container")
                assert window.windowTitle() == "DELTAHUB"
            finally:
                window.close()

    def test_post_show_initialization_runs_once(self, qapp, temp_dir):
        from app.window import AppWindow

        user_root = os.path.join(temp_dir, "user")
        mods_dir = os.path.join(temp_dir, "mods")
        profiles_dir = os.path.join(temp_dir, "profiles")
        themes_dir = os.path.join(temp_dir, "themes")
        for path in (user_root, mods_dir, profiles_dir, themes_dir):
            os.makedirs(path, exist_ok=True)
        mock_presence_response = Mock()
        mock_presence_response.status_code = 200
        mock_presence_response.json.return_value = {"online": 0}
        mock_presence_session = Mock()
        mock_presence_session.post.return_value = mock_presence_response
        with (
            patch("app_context.application_context.get_user_data_root", return_value=user_root),
            patch("app_context.application_context.get_launcher_dir", return_value=temp_dir),
            patch(
                "services.g3mtool_patching_service.get_user_data_root",
                return_value=user_root,
            ),
            patch(
                "services.blocklist_service.get_user_data_root",
                return_value=user_root,
            ),
            patch("utils.path_utils.get_user_themes_dir", return_value=themes_dir),
            patch("services.profile_service.get_user_mods_dir", return_value=mods_dir),
            patch(
                "services.profile_service.get_user_profiles_dir",
                return_value=profiles_dir,
            ),
            patch(
                "workers.presence_worker.get_session",
                return_value=mock_presence_session,
            ),
            patch("bootstrap.bootstrap_coordinator.BootstrapCoordinator.post_show_initialization") as post_init,
        ):
            window = AppWindow()
            try:
                window._post_show_initialization()
                window._post_show_initialization()
                assert post_init.call_count == 1
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
        from services.localization_service import tr
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        assert builder is not None
        widget = builder.build()
        widgets = builder.get_widgets()
        assert widgets["add_mod_button"].text() == tr("ui.add_mod")
        assert (
            widgets["add_mod_button"].minimumHeight()
            == widgets["priority_button"].sizeHint().height()
        )
        assert widgets["library_profile_label"].text() == tr("ui.profile_label")
        assert widgets["library_game_label"].text() == tr("ui.game_label")
        assert widgets["installed_mods_label"].text() == tr("ui.installed_mods_label")
        assert widgets["profile_combo"].toolTip() == tr("tooltips.profile_combo")
        assert widgets["chapter_mode_checkbox"].toolTip() == tr("tooltips.chapter_mode")
        assert widgets["full_install_checkbox"].toolTip() == tr("tooltips.full_install_toggle")
        assert widgets["priority_button"].toolTip() == tr("tooltips.mod_priority")
        widget.deleteLater()

    def test_mods_browser_tab_builder_creation(self, qapp, app_state, feedback_service):
        from services.localization_service import tr
        from PyQt6.QtWidgets import QGridLayout

        from ui.builders.search_tab_builder import ModsBrowserTabBuilder

        builder = ModsBrowserTabBuilder(app_state, None)
        assert builder is not None
        widget = builder.build()
        widgets = builder.get_widgets()
        assert widgets["mod_list_columns"] == 1
        assert isinstance(widgets["mod_list_layout"], QGridLayout)
        assert widgets["sort_combo"].currentData() == "relevant"
        assert widgets["sort_combo"].toolTip() == tr("tooltips.sort_mode")
        assert widgets["modgame_combo"].toolTip() == tr("tooltips.select_game")
        assert "show_nsfw_checkbox" in widgets
        assert widgets["show_nsfw_checkbox"].isChecked() is False
        assert widgets["show_nsfw_checkbox"].toolTip() == tr("tooltips.show_nsfw")
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

    def test_settings_view_builder_creation(self, qapp, app_state, feedback_service):
        from services.localization_service import tr
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        assert builder is not None
        builder.build()
        assert "games_manager_button" in builder.get_widgets()
        assert "plugins_layout" in builder.get_widgets()
        assert "plugins_widget" in builder.get_widgets()
        assert builder.get_widgets()["language_combo"].toolTip() == tr("tooltips.language")
        assert builder.get_widgets()["ui_scale_spinbox"].toolTip() == tr("tooltips.ui_scale")
