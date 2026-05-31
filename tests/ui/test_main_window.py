import os
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from services.localization_service import tr


def _drain_events(qapp, cycles: int = 3, delay_ms: int = 10) -> None:
    for _ in range(cycles):
        qapp.processEvents()
        QTest.qWait(delay_ms)


def _close_app_window(qapp, window) -> None:
    window.close()
    _drain_events(qapp, cycles=12, delay_ms=20)
    window.deleteLater()
    _drain_events(qapp, cycles=6, delay_ms=10)


def _close_widget(qapp, widget) -> None:
    if widget is None:
        return
    widget.close()
    _drain_events(qapp, cycles=6, delay_ms=10)
    widget.deleteLater()
    _drain_events(qapp, cycles=6, delay_ms=10)


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
            patch(
                "app_context.application_context.get_launcher_dir",
                return_value=temp_dir,
            ),
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
                assert window.windowTitle() == "G3M"
            finally:
                _close_app_window(qapp, window)

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
            patch(
                "bootstrap.bootstrap_coordinator.BootstrapCoordinator.post_show_initialization"
            ) as post_init,
        ):
            window = AppWindow()
            try:
                window._post_show_initialization()
                window._post_show_initialization()
                assert post_init.call_count == 1
            finally:
                _close_app_window(qapp, window)

    def test_mods_browser_updates_cards_without_tab_switch_when_tag_changes(
        self, qapp, temp_dir
    ):
        """Checks that modsing browser updates cards without tab switch when tag changes."""
        from app.window import AppWindow
        from models.mod_models import BrowserModInfo

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
        ):
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
                _drain_events(qapp, cycles=12, delay_ms=50)
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
                _drain_events(qapp, cycles=12, delay_ms=50)

                assert [mod.name for mod in window.app_state.filtered_mods] == ["P"]
                assert window.mod_list_layout.count() == 1

                window.tag_textedit.setChecked(True)
                _drain_events(qapp, cycles=12, delay_ms=50)

                assert window.app_state.filtered_mods == []
                assert window.mod_list_layout.count() == 0
            finally:
                _close_app_window(qapp, window)

    def test_mods_browser_layout_refresh_restores_all_visible_cards(
        self, qapp, temp_dir
    ):
        from app.window import AppWindow
        from models.mod_models import BrowserModInfo

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
        ):
            window = AppWindow()
            try:
                window.search_display._load_more_gamebanana_mods_if_needed = (
                    lambda *args, **kwargs: None
                )
                window.app_state.mods_loaded = True
                window.app_state.gamebanana_loading = False
                window.show()
                _drain_events(qapp, cycles=12, delay_ms=40)
                window.app_state.all_mods = [
                    BrowserModInfo(
                        id=f"gb_mod_{idx}",
                        name=f"Mod {idx}",
                        version="1",
                        author="x",
                        description="x",
                        game="deltarune",
                    )
                    for idx in range(3)
                ]
                window.search_display.update_filtered_mods()
                _drain_events(qapp, cycles=12, delay_ms=40)

                cards = list(window.search_display._iter_layout_cards())
                assert len(cards) == 3
                for card in cards[1:]:
                    card.setUpdatesEnabled(False)

                window.search_display.refresh_visible_layout()
                _drain_events(qapp, cycles=6, delay_ms=20)

                cards = list(window.search_display._iter_layout_cards())
                assert len(cards) == 3
                assert all(card.isVisible() for card in cards)
                assert all(card.updatesEnabled() for card in cards)
            finally:
                _close_app_window(qapp, window)

    def test_mods_browser_scroll_area_never_shows_horizontal_scrollbar(
        self, qapp, temp_dir
    ):
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
        ):
            window = AppWindow()
            try:
                assert (
                    window.mods_browser_scroll.horizontalScrollBarPolicy()
                    == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                )
            finally:
                _close_app_window(qapp, window)

    def test_window_maximized_state_is_saved_on_state_change(self, qapp, temp_dir):
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
        ):
            window = AppWindow()
            try:
                window.show()
                _drain_events(qapp, cycles=4, delay_ms=20)

                window.showMaximized()
                _drain_events(qapp, cycles=6, delay_ms=20)

                saved = window.app_state.local_config.get("window_geometry_state")
                assert saved["maximized"] is True
            finally:
                _close_app_window(qapp, window)

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
        from PyQt6.QtWidgets import QDialog, QFileDialog

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
        ):
            window = AppWindow()
            dialog = QDialog(window)
            file_dialog = QFileDialog(window)
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
                file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
                file_dialog.show()
                file_dialog.raise_()
                file_dialog.activateWindow()
                qapp.processEvents()
                assert window._should_pause_background_audio() is False
                file_dialog.close()
                window.showMinimized()
                qapp.processEvents()
                assert window._should_pause_background_audio() is True
            finally:
                _close_widget(qapp, file_dialog)
                _close_widget(qapp, dialog)
                _close_app_window(qapp, window)

    def test_close_event_hides_window_and_defers_cleanup(self, qapp, temp_dir):
        from app.window import AppWindow

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        scheduled = []
        app_mock = Mock()

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
            patch("app.window.QApplication.instance", return_value=app_mock),
            patch(
                "app.window.QTimer.singleShot",
                side_effect=lambda _ms, cb: scheduled.append(cb),
            ),
        ):
            window = AppWindow()
            try:
                event = Mock()
                with patch.object(
                    window.analytics_service,
                    "shutdown_async",
                    side_effect=lambda cb: (cb(), False)[1],
                ) as shutdown_async:
                    window.closeEvent(event)

                event.accept.assert_called_once_with()
                assert window.isHidden() is True
                shutdown_async.assert_called_once()
                assert scheduled, "expected deferred cleanup to be scheduled"
            finally:
                for callback in scheduled:
                    callback()
                window.deleteLater()
                _drain_events(qapp, cycles=6, delay_ms=10)

    def test_force_finish_close_tasks_quits_when_cleanup_flags_stall(
        self, qapp, temp_dir
    ):
        from app.window import AppWindow

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        app_mock = Mock()

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
            patch("app.window.QApplication.instance", return_value=app_mock),
        ):
            window = AppWindow()
            try:
                window._pending_close_tasks = {"analytics": False, "cleanup": True}
                window._force_finish_close_tasks()

                assert window._pending_close_tasks == {
                    "analytics": True,
                    "cleanup": True,
                }
                app_mock.quit.assert_called_once_with()
            finally:
                _close_app_window(qapp, window)

    def test_title_bar_windows_menu_opens_log_viewer(self, qapp, temp_dir):
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
        ):
            window = AppWindow()
            try:
                assert window.title_bar.windows_button.text() == tr("ui.windows_menu")
                assert window.title_bar.log_viewer_action.text() == tr("ui.log_viewer")
                assert window._log_viewer_dialog is None

                window.title_bar.log_viewer_action.trigger()
                qapp.processEvents()

                assert window._log_viewer_dialog is not None
                assert window._log_viewer_dialog.isVisible() is True

                first_dialog = window._log_viewer_dialog
                window.title_bar.log_viewer_action.trigger()
                qapp.processEvents()

                assert window._log_viewer_dialog is first_dialog
                assert window._log_viewer_dialog.isVisible() is True
            finally:
                if window._log_viewer_dialog:
                    window._log_viewer_dialog.close()
                _close_app_window(qapp, window)


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
        assert widgets["full_install_checkbox"].toolTip() == tr(
            "tooltips.full_install_toggle"
        )
        assert widgets["priority_button"].toolTip() == tr("tooltips.mod_priority")
        assert (
            "QScrollBar::handle:horizontal"
            in widgets["filters_scroll"].horizontalScrollBar().styleSheet()
        )
        assert (
            "border: 1px solid"
            in widgets["filters_scroll"].horizontalScrollBar().styleSheet()
        )
        widget.deleteLater()

    def test_library_actions_keep_expected_order_in_filters(
        self, qapp, app_state, feedback_service
    ):
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        widget = builder.build()
        widget.show()
        actions_widget = builder._library_actions_widget
        actions_layout = actions_widget.layout()
        modding_btn = builder.widgets["library_modding_tools_button"]
        downloads_btn = builder.widgets["library_downloads_button"]
        search_btn = builder.widgets["library_search_button"]

        assert builder._library_filters_layout.indexOf(actions_widget) >= 0
        assert actions_layout.indexOf(modding_btn) < actions_layout.indexOf(
            downloads_btn
        )
        assert actions_layout.indexOf(downloads_btn) < actions_layout.indexOf(
            search_btn
        )
        assert search_btn.isVisible()
        widget.close()
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
        assert (
            "QScrollBar::handle:horizontal"
            in widgets["filters_scroll"].horizontalScrollBar().styleSheet()
        )
        assert (
            "border: 1px solid"
            in widgets["filters_scroll"].horizontalScrollBar().styleSheet()
        )
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
        assert builder.get_widgets()["language_combo"].toolTip() == tr(
            "tooltips.language"
        )
        assert builder.get_widgets()["ui_scale_spinbox"].toolTip() == tr(
            "tooltips.ui_scale"
        )

    def test_settings_view_builder_icon_buttons_scale_with_ui_scale(
        self, qapp, app_state, feedback_service
    ):
        from ui.builders.settings_view_builder import SettingsViewBuilder

        app_state.local_config["ui_scale"] = 1.0
        builder = SettingsViewBuilder(app_state, None)
        widget = builder.build()
        games_manager_button = builder.get_widgets()["games_manager_button"]
        base_icon_size = games_manager_button.iconSize().width()
        base_button_width = games_manager_button.width()

        app_state.local_config["ui_scale"] = 1.5
        builder.refresh_dynamic_styles()

        assert games_manager_button.iconSize().width() > base_icon_size
        assert games_manager_button.width() > base_button_width
        widget.deleteLater()
