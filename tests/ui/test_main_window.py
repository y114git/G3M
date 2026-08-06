"""UI tests for test main window."""

import os
from collections.abc import Callable
from typing import cast
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest

from services.localization_service import tr


def _drain_events(qapp, cycles: int = 3, delay_ms: int = 10) -> None:
    wait = cast(Callable[[int], None], QTest.qWait)
    for _ in range(cycles):
        qapp.processEvents()
        wait(delay_ms)


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


def _mod_stub(mod_id: str, name: str, chapter_ids: tuple[str, ...] = ()):
    mod = Mock()
    mod.get_id.return_value = mod_id
    mod.get_name.return_value = name
    mod.name = name
    mod.get_chapter_data.side_effect = lambda chapter_id: (
        {"files": []} if chapter_id in chapter_ids else None
    )
    return mod


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

    def test_settings_game_tab_path_fields_save_on_focus_loss_and_reset(
        self, qapp, temp_dir
    ):
        from app.window import AppWindow
        from utils.path_utils import normalize_user_input_path

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
                _drain_events(qapp)
                window.settings_service.validate_executable_path = lambda path: (
                    path.endswith("G3MTool.exe")
                )

                custom_path = os.path.join(temp_dir, "tools", "G3MTool.exe")
                os.makedirs(os.path.dirname(custom_path), exist_ok=True)
                window.settings_custom_g3mtool_edit.setFocus()
                window.settings_custom_g3mtool_edit.setText(custom_path)
                window.settings_custom_xdelta_edit.setFocus()
                _drain_events(qapp)

                assert window.settings_game_path_label.text().endswith(" Path:")
                assert window.app_state.local_config.get(
                    "custom_g3mtool_path"
                ) == normalize_user_input_path(custom_path)
                assert not window.settings_reset_g3mtool_button.isHidden()

                window.settings_reset_g3mtool_button.click()
                _drain_events(qapp)

                assert (
                    window.app_state.local_config.get("custom_g3mtool_path", "") == ""
                )
                assert window.settings_reset_g3mtool_button.isHidden()
                assert window.focusWidget() is not window.settings_custom_xdelta_edit
            finally:
                _close_app_window(qapp, window)

    def test_settings_custom_executable_manual_entry_rejects_invalid_path(
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
                window.show()
                _drain_events(qapp)
                window.feedback_service.show_message = Mock()
                window.settings_service.validate_executable_path = lambda _path: False

                window.settings_custom_executable_edit.setFocus()
                window.settings_custom_executable_edit.setText("C:/bad/path.exe")
                window.settings_game_path_edit.setFocus()
                _drain_events(qapp)

                assert (
                    window.app_state.local_config.get(
                        window.app_state.game_mode.get_custom_exec_config_key(),
                        "",
                    )
                    == ""
                )
                window.feedback_service.show_message.assert_called_once()
            finally:
                _close_app_window(qapp, window)

    def test_settings_custom_executable_browse_validates_binary_before_save(
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
                window.show()
                _drain_events(qapp)
                window.feedback_service.show_message = Mock()
                window.settings_service.select_executable_path = Mock(return_value=None)

                window.settings_custom_executable_button.click()
                _drain_events(qapp)

                window.settings_service.select_executable_path.assert_called_once()
                assert (
                    window.app_state.local_config.get(
                        window.app_state.game_mode.get_custom_exec_config_key(),
                        "",
                    )
                    == ""
                )
            finally:
                _close_app_window(qapp, window)

    def test_settings_game_path_browse_updates_visible_field_immediately(
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
                window.show()
                _drain_events(qapp)
                new_game_path = os.path.join(temp_dir, "Games", "DELTARUNE")
                os.makedirs(new_game_path, exist_ok=True)
                window.settings_service.prompt_for_game_path = Mock(return_value=True)
                window.app_state.game_mode.set_game_path(
                    window.app_state.local_config, new_game_path
                )

                window.settings_game_path_browse_button.click()
                _drain_events(qapp)

                assert window.settings_game_path_edit.full_text() == new_game_path
                assert window.settings_game_path_edit.toolTip() == new_game_path
                assert not window.settings_game_path_reset_button.isHidden()
            finally:
                _close_app_window(qapp, window)

    def test_settings_game_path_manual_entry_rejects_invalid_folder_without_custom_exe(
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
                window.show()
                _drain_events(qapp)
                window.feedback_service.show_message = Mock()
                window.settings_service.validate_selected_game_path = (
                    lambda _path, *args, **kwargs: False
                )
                previous_path = window.settings_game_path_edit.full_text()

                invalid_path = os.path.join(temp_dir, "BrokenGameFolder")
                os.makedirs(invalid_path, exist_ok=True)
                window.settings_game_path_edit.setFocus()
                window.settings_game_path_edit.setText(invalid_path)
                window.settings_custom_executable_edit.setFocus()
                _drain_events(qapp)

                assert (
                    window.app_state.game_mode.get_game_path(
                        window.app_state.local_config
                    )
                    == previous_path
                )
                assert window.settings_game_path_edit.full_text() == previous_path
                window.feedback_service.show_message.assert_called_once()
            finally:
                _close_app_window(qapp, window)

    def test_settings_path_fields_relocalize_placeholders_without_restart(
        self, qapp, temp_dir
    ):
        from app.localization_utils import relocalize_ui
        from app.window import AppWindow
        from services.localization_service import localization_service, tr

        _, _, _, _, _, patches = _window_test_patches(temp_dir)
        original_language = localization_service.get_current_language()
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
                _drain_events(qapp)

                localization_service.load_language("en")
                window.app_state.local_config["language"] = "en"
                relocalize_ui(window)
                window._update_status(tr("status.launcher_settings"), "status_info")
                _drain_events(qapp)

                assert (
                    window.settings_custom_xdelta_edit.placeholderText()
                    == "Specify path..."
                )
                assert window.settings_custom_wine_label.text() == "Custom Wine:"
                assert (
                    window.settings_custom_portproton_label.text()
                    == "Custom PortProton:"
                )
                assert window.manage_warnings_button.text() == "Manage Warnings"
                assert window.clear_g3mtool_cache_button.text() == "Clear G3MTool Cache"
                assert window.settings_custom_g3mtool_label.text() == "Custom G3MTool:"
                assert (
                    window.change_font_button.text()
                    == window.customization_service.get_font_button_text()
                )
                assert window.status_label.text() == "Launcher settings"

                localization_service.load_language("ru")
                window.app_state.local_config["language"] = "ru"
                relocalize_ui(window)
                _drain_events(qapp)

                assert (
                    window.settings_custom_xdelta_edit.placeholderText()
                    == "Укажите путь..."
                )
                assert window.settings_custom_wine_label.text() == "Кастомный Wine:"
                assert (
                    window.settings_custom_portproton_label.text()
                    == "Кастомный PortProton:"
                )
                assert (
                    window.manage_warnings_button.text()
                    == "Управление предупреждениями"
                )
                assert (
                    window.clear_g3mtool_cache_button.text() == "Очистить кеш G3MTool"
                )
                assert (
                    window.settings_custom_g3mtool_label.text() == "Кастомный G3MTool:"
                )
                assert (
                    window.change_font_button.text()
                    == window.customization_service.get_font_button_text()
                )
                assert window.status_label.text() == "Настройки лаунчера"
            finally:
                localization_service.load_language(original_language)
                _close_app_window(qapp, window)

    def test_clear_g3mtool_cache_button_calls_settings_service(self, qapp, temp_dir):
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
                _drain_events(qapp)
                window.settings_service.clear_g3mtool_cache = Mock(return_value=True)

                window.clear_g3mtool_cache_button.click()
                _drain_events(qapp)

                window.settings_service.clear_g3mtool_cache.assert_called_once()
            finally:
                _close_app_window(qapp, window)

    def test_manage_warnings_button_opens_dialog(self, qapp, temp_dir, monkeypatch):
        from app.window import AppWindow

        opened = {"value": False}

        class FakeWarningDialog:
            def __init__(self, *_args, **_kwargs) -> None:
                opened["value"] = True

            def exec(self):
                return 0

        monkeypatch.setattr(
            "app.settings_setup.WarningPreferencesDialog", FakeWarningDialog
        )

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
                _drain_events(qapp)

                window.manage_warnings_button.click()
                _drain_events(qapp)

                assert opened["value"] is True
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

    def test_save_portproton_override_keeps_legacy_base_path_when_custom_is_cleared(
        self,
    ):
        from app.game_ui import _save_portproton_override

        window = Mock()
        window.app_state.local_config = {
            "custom_portproton_path": "/custom/portproton",
            "portproton_path": "/legacy/portproton",
        }
        window.settings_service.write_local_config = Mock()
        window.settings_service.settings_changed = Mock()

        _save_portproton_override(window, "   ")

        assert window.app_state.local_config["custom_portproton_path"] == ""
        assert window.app_state.local_config["portproton_path"] == "/legacy/portproton"
        window.settings_service.write_local_config.assert_called_once_with()
        window.settings_service.settings_changed.emit.assert_called_once_with()

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
                window.closeEvent(event)

                event.accept.assert_called_once_with()
                assert window.isHidden() is True
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
                window._pending_close_tasks = {"cleanup": False}
                window._force_finish_close_tasks()

                assert window._pending_close_tasks == {"cleanup": True}
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

    def test_title_bar_windows_menu_opens_support_packager(self, qapp, temp_dir):
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
                assert window.title_bar.support_packager_action.text() == tr(
                    "ui.support_packager"
                )
                assert window._support_packager_dialog is None

                window.title_bar.support_packager_action.trigger()
                qapp.processEvents()

                assert window._support_packager_dialog is not None
                assert window._support_packager_dialog.isVisible() is True
            finally:
                if window._support_packager_dialog:
                    window._support_packager_dialog.close()
                _close_app_window(qapp, window)


class TestTabBuilders:
    """Tests for main window."""

    def test_library_tab_builder_creation(self, qapp, app_state, feedback_service):
        """Checks that library tab builder creation."""
        from services.localization_service import tr
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        assert builder is not None
        widget = builder.build()
        widgets = builder.get_widgets()
        assert widgets["add_mod_button"].text() == tr("ui.add_mod")
        assert widgets["diagnostics_button"].text() == tr("diagnostics.button")
        assert widgets["diagnostics_button"].icon().isNull()
        assert (
            widgets["add_mod_button"].minimumHeight()
            == widgets["priority_button"].sizeHint().height()
        )
        assert (
            widgets["diagnostics_button"].minimumHeight()
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
        assert widgets["priority_button"].toolTip() == tr("tooltips.priority_steps")
        assert widgets["priority_button"].text() == "Priority && Steps"
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

    def test_library_header_places_diagnostics_next_to_add_mod(
        self, qapp, app_state, feedback_service
    ):
        from services.localization_service import tr
        from ui.builders.library_tab_builder import LibraryTabBuilder

        builder = LibraryTabBuilder(app_state, None)
        widget = builder.build()
        widgets = builder.get_widgets()
        add_btn = widgets["add_mod_button"]
        diagnostics_btn = widgets["diagnostics_button"]
        header_layout = widgets["library_header_layout"]

        assert header_layout.indexOf(add_btn) < header_layout.indexOf(diagnostics_btn)
        assert diagnostics_btn.toolTip() == tr("diagnostics.tooltip")
        assert diagnostics_btn.icon().isNull()
        widget.deleteLater()

    def test_diagnostics_dialog_lists_current_scope_mods_but_checks_only_enabled(
        self, qapp, app_state, feedback_service
    ):
        from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

        profile_mod = _mod_stub("profile-mod", "Profile Mod", ("deltarune_1",))
        disabled_mod = _mod_stub("disabled-mod", "Disabled Mod", ("deltarune_1",))
        other_game_mod = _mod_stub("other-game", "Other Game", ("undertale_0",))
        app_state.current_mode = "chapter"
        app_state.selected_chapter_id = "deltarune_1"
        used_mods_service = Mock()
        used_mods_service.get_used_mods_list.return_value = [profile_mod]
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = [
            {"id": "profile-mod", "game": "deltarune"},
            {"id": "disabled-mod", "game": "deltarune"},
            {"id": "other-game", "game": "undertale"},
        ]
        by_id = {
            "profile-mod": profile_mod,
            "disabled-mod": disabled_mod,
            "other-game": other_game_mod,
        }
        mod_service.create_mod_object_from_info.side_effect = (
            lambda mod_info, _all_mods=None: by_id[mod_info["id"]]
        )
        mod_service.mod_has_files_for_chapter.side_effect = (
            lambda mod_data, chapter_id: bool(mod_data.get_chapter_data(chapter_id))
        )

        with patch.object(ModDiagnosticsDialog, "_run_analysis", lambda self: None):
            dialog = ModDiagnosticsDialog(app_state, mod_service, used_mods_service)
        try:
            checks = {
                check.text(): check.isChecked() for check in dialog._mod_checks.values()
            }
            assert checks == {"Profile Mod": True, "Disabled Mod": False}
            assert all(check.toolTip() for check in dialog._mod_checks.values())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_diagnostics_dialog_uses_active_selections_for_default_game_scope(
        self, qapp, app_state, feedback_service
    ):
        from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

        enabled_mod = _mod_stub("enabled-mod", "Enabled Mod", ("deltarune_1",))
        disabled_mod = _mod_stub("disabled-mod", "Disabled Mod", ("deltarune_1",))
        app_state.current_mode = "game"
        app_state.selected_chapter_id = None
        used_mods_service = Mock()
        used_mods_service.get_used_mods_list.return_value = []
        used_mods_service.get_active_mod_selections.return_value = {
            "deltarune_1": [enabled_mod]
        }
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = [
            {"id": "enabled-mod", "game": "deltarune"},
            {"id": "disabled-mod", "game": "deltarune"},
        ]
        by_id = {"enabled-mod": enabled_mod, "disabled-mod": disabled_mod}
        mod_service.create_mod_object_from_info.side_effect = (
            lambda mod_info, _all_mods=None: by_id[mod_info["id"]]
        )

        with patch.object(ModDiagnosticsDialog, "_run_analysis", lambda self: None):
            dialog = ModDiagnosticsDialog(app_state, mod_service, used_mods_service)
        try:
            checks = {
                check.text(): check.isChecked() for check in dialog._mod_checks.values()
            }
            assert checks == {"Enabled Mod": True, "Disabled Mod": False}
            assert all(check.toolTip() for check in dialog._mod_checks.values())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_diagnostics_dialog_preserves_empty_explicit_section(
        self, qapp, app_state, feedback_service
    ):
        from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

        app_state.current_mode = "chapter"
        app_state.selected_chapter_id = "deltarune_1"
        used_mods_service = Mock()
        used_mods_service.get_used_mods_list.return_value = []
        used_mods_service.get_active_mod_selections.return_value = {
            "deltarune_2": [_mod_stub("other", "Other", ("deltarune_2",))]
        }
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = []

        with patch.object(ModDiagnosticsDialog, "_run_analysis", lambda self: None):
            dialog = ModDiagnosticsDialog(app_state, mod_service, used_mods_service)
        try:
            used_mods_service.get_active_mod_selections.reset_mock()
            assert dialog._initial_section_mods() == {"deltarune_1": []}
            used_mods_service.get_active_mod_selections.assert_not_called()
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_diagnostics_dialog_clears_preflight_progress(
        self, qapp, app_state, feedback_service
    ):
        from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

        used_mods_service = Mock()
        used_mods_service.get_used_mods_list.return_value = []
        used_mods_service.get_active_mod_selections.return_value = {}
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = []

        with patch.object(ModDiagnosticsDialog, "_run_analysis", lambda self: None):
            dialog = ModDiagnosticsDialog(app_state, mod_service, used_mods_service)
        try:
            dialog._preflight_progress.setValue(73)
            dialog._clear_preflight_result()
            assert dialog._preflight_progress.value() == 0
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_diagnostics_dialog_shows_exact_preflight_issues(
        self, qapp, app_state, feedback_service
    ):
        from services.diagnostics.preflight_service import PreflightReport
        from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

        used_mods_service = Mock()
        used_mods_service.get_used_mods_list.return_value = []
        used_mods_service.get_active_mod_selections.return_value = {}
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = []

        with patch.object(ModDiagnosticsDialog, "_run_analysis", lambda self: None):
            dialog = ModDiagnosticsDialog(app_state, mod_service, used_mods_service)
        try:
            report = PreflightReport(
                False,
                False,
                0.1,
                issues=("xdelta3: XD3_INVALID_INPUT", "PermissionError: access denied"),
                conflict_count=7,
            )
            dialog._on_preflight_ready(report)
            assert "XD3_INVALID_INPUT" in dialog._inspector.toPlainText()
            assert "access denied" in dialog._inspector.toPlainText()
            assert "7" in dialog._summary_labels["conflicts"].text()
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_diagnostics_resource_comparison_does_not_mix_sections(
        self, qapp, app_state, feedback_service
    ):
        from services.mod_diagnostics_service import (
            DataImpact,
            DiagnosticsReport,
            DiagnosticsSummary,
        )
        from ui.dialogs.mod_diagnostics_dialog import ModDiagnosticsDialog

        used_mods_service = Mock()
        used_mods_service.get_used_mods_list.return_value = []
        used_mods_service.get_active_mod_selections.return_value = {}
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = []
        entry = {"type": "code", "name": "shared_name"}

        def impact(section_id, mod_id):
            return DataImpact(
                section_id=section_id,
                mod_id=mod_id,
                mod_name=mod_id,
                patch_path=None,
                patch_type="g3mpatch",
                target_data_path=None,
                deep_analysis_available=True,
                resource_entries=(entry,),
            )

        first = impact("section_a", "first")
        second = impact("section_b", "second")
        with patch.object(ModDiagnosticsDialog, "_run_analysis", lambda self: None):
            dialog = ModDiagnosticsDialog(app_state, mod_service, used_mods_service)
        try:
            dialog._report = DiagnosticsReport(
                DiagnosticsSummary(), (), (first, second), ()
            )
            assert dialog._resource_comparison_text(first, entry) == ""
        finally:
            dialog.close()
            dialog.deleteLater()

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
        """Checks that settings view builder creation."""
        from services.localization_service import tr
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        assert builder is not None
        builder.build()
        assert "games_manager_button" in builder.get_widgets()
        assert "plugins_layout" in builder.get_widgets()
        assert "plugins_widget" in builder.get_widgets()
        assert "pause_background_music_unfocused_checkbox" in builder.get_widgets()
        assert "disable_discord_rich_presence_checkbox" in builder.get_widgets()
        assert builder.get_widgets()["language_combo"].toolTip() == tr(
            "tooltips.language"
        )
        assert builder.get_widgets()["ui_scale_spinbox"].toolTip() == tr(
            "tooltips.ui_scale"
        )

    def test_settings_view_builder_places_discord_presence_toggle_in_appearance_advanced(
        self, qapp, app_state, feedback_service
    ):
        from services.localization_service import tr
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        widget = builder.build()
        try:
            checkbox = builder.get_widgets()["disable_discord_rich_presence_checkbox"]
            assert checkbox.text() == tr("ui.disable_discord_rich_presence")
            assert checkbox.toolTip() == tr("tooltips.disable_discord_rich_presence")
        finally:
            widget.deleteLater()

    def test_settings_view_builder_exposes_custom_binary_controls(
        self, qapp, app_state, feedback_service
    ):
        from services.localization_service import tr
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        widget = builder.build()
        try:
            widgets = builder.get_widgets()
            assert widgets["settings_game_path_label"].text() == "{GAME} Path:"
            assert widgets["settings_custom_g3mtool_edit"].placeholderText() == tr(
                "ui.path_field_placeholder"
            )
            assert widgets["settings_custom_executable_label"].text() == tr(
                "ui.settings_custom_executable_path_label"
            )
            assert widgets["settings_custom_g3mtool_edit"].toolTip() == ""
            assert widgets["settings_custom_g3mtool_button"].toolTip() == tr(
                "tooltips.custom_g3mtool_binary"
            )
            assert widgets["settings_custom_xdelta_button"].text() == "..."
            assert widgets["settings_custom_xdelta_button"].toolTip() == tr(
                "tooltips.custom_xdelta_binary"
            )
            assert widgets["settings_custom_wine_edit"].placeholderText() == tr(
                "ui.path_field_placeholder"
            )
            assert widgets["settings_custom_wine_button"].toolTip() == tr(
                "tooltips.custom_wine_binary"
            )
            assert widgets["settings_custom_portproton_button"].toolTip() == tr(
                "tooltips.custom_portproton_binary"
            )
        finally:
            widget.deleteLater()

    def test_settings_view_builder_exposes_user_data_root_controls(
        self, qapp, app_state, feedback_service
    ):
        from ui.builders.settings_view_builder import SettingsViewBuilder

        builder = SettingsViewBuilder(app_state, None)
        widget = builder.build()
        try:
            widgets = builder.get_widgets()
            assert widgets["settings_user_data_root_label"].text()
            assert widgets["settings_user_data_root_edit"].full_text()
            assert widgets["settings_user_data_root_edit"].isReadOnly()
            assert widgets["settings_user_data_root_button"].text() == "..."
            assert widgets["settings_user_data_root_reset_button"] is not None
        finally:
            widget.deleteLater()

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

    def test_zoom_ui_debounces_scaled_refresh(self, qapp, temp_dir):
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
                refresh_calls = []
                window.settings_service.write_local_config = Mock()
                window._refresh_scaled_card_displays = Mock(
                    side_effect=lambda: refresh_calls.append("refresh")
                )

                window._zoom_ui(1)
                window._zoom_ui(1)

                assert refresh_calls == []
                assert getattr(window, "_ui_scale_refresh_timer", None) is not None
                window._ui_scale_refresh_timer.timeout.emit()
                assert refresh_calls == ["refresh"]
            finally:
                _close_app_window(qapp, window)

    def test_refresh_scaled_card_displays_coalesces_reentrant_requests(
        self, qapp, temp_dir
    ):
        from app.window import AppWindow

        scheduled = []
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
                "app.window.QTimer.singleShot",
                side_effect=lambda _ms, callback: scheduled.append(callback),
            ),
        ):
            window = AppWindow()
            try:
                calls = []

                class _RefreshProbe:
                    def __init__(self) -> None:
                        self.triggered = False

                    def refresh_dynamic_styles(self):
                        calls.append("builder")
                        if not self.triggered:
                            self.triggered = True
                            window._refresh_scaled_card_displays()

                window.search_tab_builder = _RefreshProbe()
                window.search_display = None
                window.library_display = None
                window.settings_builder = None
                window.theme = None

                window._refresh_scaled_card_displays()

                assert calls == ["builder"]
                assert scheduled
                scheduled[-1]()
                assert calls == ["builder", "builder"]
            finally:
                _close_app_window(qapp, window)

    def test_custom_tooltip_uses_target_screen_geometry(self, qapp, temp_dir):
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
                anchor = QPoint(1900, 110)
                screen_geometry = QRect(1600, 0, 320, 220)
                target = Mock()
                target.screen.return_value = Mock(
                    availableGeometry=Mock(return_value=screen_geometry)
                )
                target.rect.return_value.bottomLeft.return_value = QPoint(0, 0)
                target.mapToGlobal.return_value = anchor

                window._last_tooltip_text = "Close"
                window._last_tooltip_target = target
                window._last_tooltip_global_pos = anchor

                with patch("app.window.QApplication.primaryScreen") as primary_screen:
                    primary_screen.return_value = Mock(
                        availableGeometry=Mock(return_value=QRect(0, 0, 300, 120))
                    )
                    window._show_custom_tooltip()

                tooltip = window._tooltip_widget
                assert tooltip is not None
                assert tooltip.isVisible()
                assert tooltip.x() >= screen_geometry.left()
                assert tooltip.x() + tooltip.width() <= screen_geometry.right() + 1
            finally:
                _close_widget(qapp, getattr(window, "_tooltip_widget", None))
                _close_app_window(qapp, window)
