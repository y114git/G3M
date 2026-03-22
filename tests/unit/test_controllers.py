from types import SimpleNamespace
from unittest.mock import Mock, patch


class TestModOperationsController:

    def test_mod_operations_controller_initialization(self, app_state, feedback_service):
        from controllers.mod_operations_controller import ModOperationsController
        from services.mod_service import ModManager
        mod_service = ModManager(app_state, feedback_service)
        app_window = Mock()
        controller = ModOperationsController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state
        assert controller.mod_service == mod_service


class TestLibraryDisplayController:

    def test_library_display_controller_initialization(self, app_state, feedback_service):
        from controllers.library_display_controller import LibraryDisplayController
        from services.localization_service import localization_service
        from services.mod_service import ModManager
        from services.settings_service import SettingsManager
        from services.used_mods_service import UsedModsManager
        mod_service = ModManager(app_state, feedback_service)
        settings_service = SettingsManager(app_state=app_state, feedback_service=feedback_service, localization_service=localization_service, parent=None)
        used_mods_service = UsedModsManager(app_state, mod_service, feedback_service, settings_service, None)
        app_window = Mock()
        controller = LibraryDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, used_mods_service=used_mods_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state

    def test_library_display_skips_refresh_for_unchanged_valid_cached_view(self, app_state, feedback_service):
        from controllers.library_display_controller import LibraryDisplayController
        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.game_type_combo.currentData.return_value = 'deltarune'
        app_window.library_search_text = ''
        app_window.installed_mods_layout.count.return_value = 2
        app_window.game_launch = Mock()
        mod_service = SimpleNamespace(_installed_mods_cache_valid=True)
        controller = LibraryDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, used_mods_service=Mock(), app_window=app_window)
        controller.refresh_async = Mock()
        controller.update_mod_widgets_active_status = Mock()
        controller._last_render_signature = (controller._current_view_signature(), (('mod_key',),))
        controller.update_display()
        controller.refresh_async.assert_not_called()
        controller.update_mod_widgets_active_status.assert_called_once()

    def test_library_display_refreshes_when_installed_cache_is_invalid(self, app_state, feedback_service):
        from controllers.library_display_controller import LibraryDisplayController
        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.game_type_combo.currentData.return_value = 'deltarune'
        app_window.library_search_text = ''
        app_window.installed_mods_layout.count.return_value = 2
        app_window.game_launch = Mock()
        mod_service = SimpleNamespace(_installed_mods_cache_valid=False)
        controller = LibraryDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, used_mods_service=Mock(), app_window=app_window)
        controller.refresh_async = Mock()
        controller._last_render_signature = (controller._current_view_signature(), (('mod_key',),))
        controller.update_display()
        controller.refresh_async.assert_called_once()

    def test_library_sort_order_name_ascending_and_date_descending(self, app_state, feedback_service):
        """Default ascending=True should sort names A→Z and dates newest→oldest."""
        from controllers.library_display_controller import LibraryDisplayController
        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.game_type_combo.currentData.return_value = 'deltarune'
        app_window.library_search_text = ''
        app_window.game_launch = Mock()
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = [
            {'key': 'b', 'name': 'Beta', 'game': 'deltarune', 'added_date': '2024-01-01 00:00:00'},
            {'key': 'a', 'name': 'Alpha', 'game': 'deltarune', 'added_date': '2025-06-01 00:00:00'},
            {'key': 'c', 'name': 'Charlie', 'game': 'deltarune', 'added_date': '2024-06-01 00:00:00'},
        ]
        controller = LibraryDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, used_mods_service=Mock(), app_window=app_window)
        result = controller._filter_and_sort_installed(mod_service.get_installed_mods_list())
        names = [m['name'] for m in result]
        assert names == ['Alpha', 'Beta', 'Charlie'], f'Name sort ascending should be A→Z, got {names}'
        app_window.library_sort_combo.currentIndex.return_value = 1
        result = controller._filter_and_sort_installed(mod_service.get_installed_mods_list())
        dates = [m['added_date'] for m in result]
        assert dates == ['2025-06-01 00:00:00', '2024-06-01 00:00:00', '2024-01-01 00:00:00'], f'Date sort ascending should be newest first, got {dates}'


class TestSearchDisplayController:

    def test_search_display_controller_initialization(self, app_state, feedback_service):
        from controllers.mod_operations_controller import ModOperationsController
        from controllers.search_display_controller import SearchDisplayController
        from services.mod_service import ModManager
        mod_service = ModManager(app_state, feedback_service)
        mod_ops = ModOperationsController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, app_window=Mock())
        app_window = Mock()
        app_window.mod_list_layout = Mock()
        app_window.mod_list_widget = Mock()
        app_window.modgame_combo = Mock()
        app_window.modgame_combo.currentData = Mock(return_value='deltarune')
        app_window.sort_combo = Mock()
        app_window.sort_combo.currentIndex = Mock(return_value=0)
        app_window.sort_ascending = True
        app_window.page_label = Mock()
        app_window.prev_page_btn = Mock()
        app_window.next_page_btn = Mock()

        controller = SearchDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, mod_ops=mod_ops, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state
        assert hasattr(controller, 'card_widget_cache')
        assert hasattr(controller, '_update_display_debounce')

    def test_refresh_visible_layout_skips_relayout_when_grid_metrics_do_not_change(self, app_state, feedback_service):
        from controllers.search_display_controller import SearchDisplayController
        controller = SearchDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=Mock(), mod_ops=Mock(), app_window=Mock(mod_list_layout=Mock(), mod_list_widget=Mock()))
        controller._sync_mod_grid_metrics = Mock(return_value=False)
        controller._place_layout_widget = Mock()
        controller.update_pagination = Mock()
        controller.ui_widget_updates_enabled = Mock()

        controller.refresh_visible_layout()

        controller._place_layout_widget.assert_not_called()
        controller.update_pagination.assert_not_called()
        controller.ui_widget_updates_enabled.emit.assert_not_called()

    def test_maybe_load_more_for_short_viewport_skips_when_tag_filter_active(self, app_state, feedback_service):
        from controllers.search_display_controller import SearchDisplayController
        scroll = Mock()
        scroll.viewport.return_value.height.return_value = 1000
        app_window = Mock(mods_browser_scroll=scroll, mod_list_widget=Mock(), mod_list_layout=Mock())
        app_window.tag_textedit.isChecked.return_value = True
        app_window.tag_customization.isChecked.return_value = False
        app_window.tag_gameplay.isChecked.return_value = False
        app_window.tag_other.isChecked.return_value = False
        app_window.mod_list_widget.sizeHint.return_value.height.return_value = 100
        controller = SearchDisplayController(app_state=app_state, feedback_service=feedback_service, mod_service=Mock(), mod_ops=Mock(), app_window=app_window)
        controller._load_more_gamebanana_mods_if_needed = Mock()

        controller._maybe_load_more_for_short_viewport()

        controller._load_more_gamebanana_mods_if_needed.assert_not_called()


class TestSettingsUiController:

    def test_settings_ui_controller_initialization(self, app_state, feedback_service, qapp):
        from controllers.settings_controller import SettingsUiController
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager
        settings_service = SettingsManager(app_state=app_state, feedback_service=feedback_service, localization_service=localization_service, parent=qapp)
        from services.customization_service import CustomizationManager
        from services.mod_service import ModManager
        from services.used_mods_service import UsedModsManager
        mod_service = ModManager(app_state, feedback_service)
        used_mods_service = UsedModsManager(app_state, mod_service, feedback_service, settings_service, None)
        customization_service = CustomizationManager(app_state)
        app_window = Mock()
        controller = SettingsUiController(app_state=app_state, feedback_service=feedback_service, settings_service=settings_service, used_mods_service=used_mods_service, customization_service=customization_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state


class TestThemeController:

    def test_theme_controller_initialization(self, app_state, feedback_service, qapp):
        from controllers.theme_controller import ThemeController
        from services.customization_service import CustomizationManager
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager
        settings_service = SettingsManager(app_state=app_state, feedback_service=feedback_service, localization_service=localization_service, parent=qapp)
        customization_service = CustomizationManager(app_state)
        app_window = Mock()
        controller = ThemeController(app_state=app_state, feedback_service=feedback_service, settings_service=settings_service, customization_service=customization_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state

    def test_apply_theme_skips_cache_invalidation_when_params_unchanged(self, app_state, feedback_service):
        from PyQt6.QtWidgets import QApplication as RealQApplication

        from controllers.theme_controller import ThemeController
        app_state.local_config = {'custom_color_text': '#FF0000'}
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith('#'))
        customization_service = Mock()
        app_window = Mock()
        app_window.custom_font_family = None
        app_window.palette.return_value = Mock()
        app_window.status_label = Mock()
        app_window.color_widgets = {'button_hover': Mock(text=lambda: '')}
        app_window.installed_mods_label = None
        app_window.title_bar = None
        app_window.top_panel_widget = Mock()
        app_window.logo_placeholder = Mock()
        app_window.launcher_icon_label = Mock()
        app_window.findChildren.return_value = []
        app_window.plugin_tab_builder = None
        app_window.library_tag_widgets = []
        app_window.search_display = None
        app_window.plugin_display = None
        app_window.library_tab_builder = Mock()
        app_window.library_tab_builder.update_priority_button_style = Mock()
        app_window._apply_window_corner_mask = Mock()
        app_window.update = Mock()
        app_window.size.return_value = Mock()
        with patch('controllers.theme_controller.THEMES', {'default': {'background': 'images/background.png', 'colors': {'text': '#FFFFFF', 'background': '#000000', 'button': '#333333', 'border': '#444444', 'button_hover': '#555555'}, 'font_family': 'Arial', 'font_size_main': 12, 'font_size_small': 10}}), patch('controllers.theme_controller.BgLoader'), patch('controllers.theme_controller.invalidate_stylesheet_cache') as invalidate_stylesheet_cache_mock, patch('ui.common.styling.invalidate_theme_color_cache') as invalidate_theme_color_cache_mock, patch('controllers.theme_controller.build_stylesheet', return_value=''), patch.object(RealQApplication, 'instance', return_value=None), patch('controllers.theme_controller.QApplication', RealQApplication):
            controller = ThemeController(app_state=app_state, feedback_service=feedback_service, settings_service=settings_service, customization_service=customization_service, app_window=app_window)
            controller.apply_theme()
            invalidate_stylesheet_cache_mock.reset_mock()
            invalidate_theme_color_cache_mock.reset_mock()
            controller.apply_theme()
        invalidate_stylesheet_cache_mock.assert_not_called()
        invalidate_theme_color_cache_mock.assert_not_called()

    def test_apply_theme_resets_tooltip_size_cache_key(self, app_state, feedback_service):
        from PyQt6.QtWidgets import QApplication as RealQApplication

        from controllers.theme_controller import ThemeController
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith('#'))
        customization_service = Mock()
        app_window = Mock()
        app_window.custom_font_family = None
        app_window.palette.return_value = Mock()
        app_window.status_label = Mock()
        app_window.color_widgets = {'button_hover': Mock(text=lambda: '')}
        app_window.installed_mods_label = None
        app_window.title_bar = None
        app_window.top_panel_widget = Mock()
        app_window.logo_placeholder = Mock()
        app_window.launcher_icon_label = Mock()
        app_window.findChildren.return_value = []
        app_window.plugin_tab_builder = None
        app_window.library_tag_widgets = []
        app_window.search_display = None
        app_window.plugin_display = None
        app_window.library_tab_builder = Mock()
        app_window.library_tab_builder.update_priority_button_style = Mock()
        app_window._apply_window_corner_mask = Mock()
        app_window.update = Mock()
        app_window.size.return_value = Mock()
        app_window._last_tooltip_size_key = 'tooltip-text'
        with patch('controllers.theme_controller.THEMES', {'default': {'background': 'images/background.png', 'colors': {'text': '#FFFFFF', 'background': '#000000', 'button': '#333333', 'border': '#444444', 'button_hover': '#555555'}, 'font_family': 'Arial', 'font_size_main': 12, 'font_size_small': 10}}), patch('controllers.theme_controller.BgLoader'), patch('controllers.theme_controller.build_stylesheet', return_value=''), patch.object(RealQApplication, 'instance', return_value=None), patch('controllers.theme_controller.QApplication', RealQApplication):
            controller = ThemeController(app_state=app_state, feedback_service=feedback_service, settings_service=settings_service, customization_service=customization_service, app_window=app_window)
            controller.apply_theme(force=True)
        assert app_window._last_tooltip_size_key is None


class TestGameLaunchController:

    def test_game_launch_controller_initialization(self, app_state, feedback_service, qapp):
        from controllers.game_launch_controller import GameLaunchController
        from services.customization_service import CustomizationManager
        from services.launch_service import GameLauncher
        from services.localization_service import localization_service
        from services.mod_service import ModManager
        from services.plugin_service import PluginManager
        from services.settings_service import SettingsManager
        from services.used_mods_service import UsedModsManager
        mod_service = ModManager(app_state, feedback_service)
        settings_service = SettingsManager(app_state=app_state, feedback_service=feedback_service, localization_service=localization_service, parent=qapp)
        used_mods_service = UsedModsManager(app_state, mod_service, feedback_service, settings_service, None)
        game_launcher = GameLauncher(app_state, feedback_service, mod_service)
        customization_service = CustomizationManager(app_state)
        plugin_service = PluginManager(app_state, settings_service)
        app_window = Mock()
        controller = GameLaunchController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, used_mods_service=used_mods_service, settings_service=settings_service, game_launcher=game_launcher, customization_service=customization_service, plugin_service=plugin_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state

    def test_hide_window_with_dont_hide_updates_close_text_and_border_status_color(self):
        from controllers.game_launch_controller import GameLaunchController
        from services.localization_service import tr

        app_state = SimpleNamespace(
            game_mode=SimpleNamespace(supports_full_install=False),
            game_is_running=False,
            is_installing=False,
            operation_cancelled=False,
            is_patching=False,
            initialization_completed=True,
            local_config={'dont_hide_window_on_launch': True, 'custom_color_border': '#123456'},
            action_button_text=None,
            action_button_enabled=False,
            progress_bar_visible=False,
            progress_bar_value=0,
        )
        feedback_service = Mock()
        settings_service = Mock()
        used_mods_service = Mock()
        used_mods_service.check_used_mods_need_updates.return_value = False
        customization_service = Mock()
        plugin_service = Mock()
        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=used_mods_service,
            settings_service=settings_service,
            game_launcher=Mock(),
            customization_service=customization_service,
            plugin_service=plugin_service,
            app_window=Mock(),
        )

        controller.hide_window()

        assert app_state.game_is_running is True
        assert app_state.action_button_text == tr('ui.close_game')
        feedback_service.update_status.assert_called_once_with(tr('status.game_launched_waiting_for_exit'), '#123456')
        settings_service.save_window_geometry.assert_called_once()


class TestAppWindowRestore:

    def test_on_window_restore_requested_uses_show_maximized_for_saved_maximized_state(self):
        from PyQt6.QtCore import Qt

        from core.app_window import AppWindow

        window = Mock()
        window.settings_service.was_window_maximized.return_value = True
        window.settings_service.load_window_geometry.return_value = True
        window.windowState.return_value = Qt.WindowState.WindowMaximized
        window._restoring_window_geometry = False
        window._finish_window_restore = Mock()

        with patch('core.app_window.QTimer.singleShot', side_effect=lambda _ms, callback: callback()):
            AppWindow._on_window_restore_requested(window)

        window.settings_service.was_window_maximized.assert_called_once_with()
        window.settings_service.load_window_geometry.assert_called_once_with(window, apply_maximized_state=False)
        window.setWindowState.assert_called_once()
        window.show.assert_called_once_with()
        window.showMaximized.assert_called_once_with()
        window.showNormal.assert_not_called()
        window._finish_window_restore.assert_called_once_with()
        window.activateWindow.assert_called_once_with()
        window.raise_.assert_called_once_with()
        assert window._restoring_window_geometry is True
