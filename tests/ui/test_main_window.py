import os
import time
from unittest.mock import Mock, patch


def _window_test_patches(temp_dir):
    user_root = os.path.join(temp_dir, "user")
    profiles_dir = os.path.join(temp_dir, "profiles")
    themes_dir = os.path.join(temp_dir, "themes")
    for path in (user_root, profiles_dir, themes_dir):
        os.makedirs(path, exist_ok=True)
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"online": 0}
    mock_response.text = ""
    mock_response.content = b""
    mock_response.raise_for_status = Mock()
    mock_session = Mock()
    mock_session.get.return_value = mock_response
    mock_session.post.return_value = mock_response
    return (
        user_root,
        profiles_dir,
        themes_dir,
        mock_response,
        mock_session,
        (
            patch(
                "app_context.application_context.get_user_data_root",
                return_value=user_root,
            ),
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
            patch(
                "services.profile_service.get_user_profiles_dir",
                return_value=profiles_dir,
            ),
            patch("requests.get", return_value=mock_response),
            patch("requests.post", return_value=mock_response),
            patch("requests.Session", return_value=mock_session),
            patch("ui.widgets.mod.base_mod_widget.load_mod_icon_universal"),
        ),
    )


class TestAppWindow:
    """Tests for main window."""
    def test_app_window_creation(self, qapp, temp_dir):
        """Checks that apping window creation."""
        from app.window import AppWindow

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
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
                assert window.windowTitle() == "G3M"
            finally:
                window.close()

    def test_post_show_initialization_runs_once(self, qapp, temp_dir):
        """Checks that posting show initialization runs once."""
        from app.window import AppWindow

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
            patch("bootstrap.bootstrap_coordinator.BootstrapCoordinator.post_show_initialization") as post_init,
        ):
            window = AppWindow()
            try:
                window._post_show_initialization()
                window._post_show_initialization()
                assert post_init.call_count == 1
            finally:
                window.close()

    def test_mods_browser_updates_cards_without_tab_switch_when_tag_changes(
        self, qapp, temp_dir
    ):
        """Checks that modsing browser updates cards without tab switch when tag changes."""
        from app.window import AppWindow
        from models.mod_models import BrowserModInfo

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            window = AppWindow()
            try:
                window.search_display._load_more_gamebanana_mods_if_needed = (
                    lambda *args, **kwargs: None
                )
                window.app_state.mods_loaded = True
                window.app_state.gamebanana_loading = False
                window.app_state.search_text = ""
                pizzatower_index = window.modgame_combo.findData("pizzatower")
                window.modgame_combo.setCurrentIndex(pizzatower_index)
                window.show()
                for _ in range(12):
                    qapp.processEvents()
                    time.sleep(0.05)
                window.app_state.all_mods = [
                    BrowserModInfo(
                        id="gb_mod_3",
                        name="P",
                        version="1",
                        author="x",
                        description="x",
                        game="pizzatower",
                        tags=["CYOP/AFOM"],
                        gamebanana_category="CYOP/AFOM",
                    )
                ]
                window.search_display.update_filtered_mods()
                for _ in range(12):
                    qapp.processEvents()
                    time.sleep(0.05)

                assert [mod.name for mod in window.app_state.filtered_mods] == ["P"]
                assert window.mod_list_layout.count() == 1

                window.tag_textedit.setChecked(True)
                for _ in range(12):
                    qapp.processEvents()
                    time.sleep(0.05)

                assert window.app_state.filtered_mods == []
                assert window.mod_list_layout.count() == 0
            finally:
                window.close()

    def test_sync_chapter_tab_buttons_hides_extra_buttons_for_single_tab_game(
        self, qapp
    ):
        """Checks that syncing chapter tab buttons hides extra buttons for single tab game."""
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

    def test_background_audio_pause_detection_accepts_child_windows(
        self, qapp, temp_dir
    ):
        from PyQt6.QtWidgets import QDialog

        from app.window import AppWindow

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            window = AppWindow()
            dialog = QDialog(window)
            try:
                window.app_state.local_config["pause_background_music_unfocused"] = True
                qapp.processEvents()
                window.show()
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
                qapp.processEvents()
                assert window._should_pause_background_audio() is False
                dialog.close()
                window.showMinimized()
                qapp.processEvents()
                assert window._should_pause_background_audio() is True
            finally:
                dialog.close()
                window.close()


class TestTabBuilders:
    """Tests for main window."""
    def test_library_tab_builder_creation(self, qapp, app_state, feedback_service):
        """Checks that librarying tab builder creation."""
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
        """Checks that modsing browser tab builder creation."""
        from PyQt6.QtWidgets import QGridLayout

        from services.localization_service import tr
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
        """Checks that modsing browser show nsfw checkbox scales with ui scale."""
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
        """Checks that settingsing view builder creation."""
        from services.localization_service import tr
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        assert builder is not None
        builder.build()
        assert "games_manager_button" in builder.get_widgets()
        assert "plugins_layout" in builder.get_widgets()
        assert "plugins_widget" in builder.get_widgets()
        assert "pause_background_music_unfocused_checkbox" in builder.get_widgets()
        assert builder.get_widgets()["language_combo"].toolTip() == tr("tooltips.language")
        assert builder.get_widgets()["ui_scale_spinbox"].toolTip() == tr("tooltips.ui_scale")
