from unittest.mock import Mock
from types import SimpleNamespace


class TestModOperationsController:

    def test_mod_operations_controller_initialization(self, app_state, feedback_service):
        from services.mod_service import ModManager
        from controllers.mod_operations_controller import ModOperationsController
        mod_service = ModManager(app_state, feedback_service)
        app_window = Mock()
        controller = ModOperationsController(app_state=app_state, feedback_service=feedback_service, mod_service=mod_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state
        assert controller.mod_service == mod_service


class TestLibraryDisplayController:

    def test_library_display_controller_initialization(self, app_state, feedback_service):
        from controllers.library_display_controller import LibraryDisplayController
        from services.mod_service import ModManager
        from services.used_mods_service import UsedModsManager
        from services.settings_service import SettingsManager
        from services.localization_service import localization_service
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
        app_window.library_sort_ascending = False
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
        app_window.library_sort_ascending = False
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


class TestSearchDisplayController:

    def test_search_display_controller_initialization(self, app_state, feedback_service):
        from controllers.search_display_controller import SearchDisplayController
        from services.mod_service import ModManager
        from controllers.mod_operations_controller import ModOperationsController
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


class TestSettingsUiController:

    def test_settings_ui_controller_initialization(self, app_state, feedback_service, qapp):
        from services.settings_service import SettingsManager
        from services.localization_service import localization_service
        from controllers.settings_controller import SettingsUiController
        settings_service = SettingsManager(app_state=app_state, feedback_service=feedback_service, localization_service=localization_service, parent=qapp)
        from services.used_mods_service import UsedModsManager
        from services.customization_service import CustomizationManager
        from services.mod_service import ModManager
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
        from services.settings_service import SettingsManager
        from services.localization_service import localization_service
        from services.customization_service import CustomizationManager
        settings_service = SettingsManager(app_state=app_state, feedback_service=feedback_service, localization_service=localization_service, parent=qapp)
        customization_service = CustomizationManager(app_state)
        app_window = Mock()
        controller = ThemeController(app_state=app_state, feedback_service=feedback_service, settings_service=settings_service, customization_service=customization_service, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state


class TestGameLaunchController:

    def test_game_launch_controller_initialization(self, app_state, feedback_service, qapp):
        from controllers.game_launch_controller import GameLaunchController
        from services.mod_service import ModManager
        from services.used_mods_service import UsedModsManager
        from services.settings_service import SettingsManager
        from services.localization_service import localization_service
        from services.launch_service import GameLauncher
        from services.customization_service import CustomizationManager
        from services.plugin_service import PluginManager
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
