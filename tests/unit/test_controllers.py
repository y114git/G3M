from unittest.mock import Mock


class TestModOperationsController:

    def test_mod_operations_controller_initialization(self, app_state, feedback_manager):
        from managers.mod_manager import ModManager
        from controllers.mod_operations_controller import ModOperationsController
        mod_manager = ModManager(app_state, feedback_manager)
        app_window = Mock()
        controller = ModOperationsController(app_state=app_state, feedback_manager=feedback_manager, mod_manager=mod_manager, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state
        assert controller.mod_manager == mod_manager


class TestLibraryDisplayController:

    def test_library_display_controller_initialization(self, app_state, feedback_manager):
        from controllers.library_display_controller import LibraryDisplayController
        from managers.mod_manager import ModManager
        from managers.used_mods_manager import UsedModsManager
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        mod_manager = ModManager(app_state, feedback_manager)
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=None)
        slot_manager = UsedModsManager(app_state, mod_manager, feedback_manager, settings_manager, None)
        app_window = Mock()
        controller = LibraryDisplayController(app_state=app_state, feedback_manager=feedback_manager, mod_manager=mod_manager, slot_manager=slot_manager, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state


class TestSearchDisplayController:

    def test_search_display_controller_initialization(self, app_state, feedback_manager):
        from controllers.search_display_controller import SearchDisplayController
        from managers.mod_manager import ModManager
        from controllers.mod_operations_controller import ModOperationsController
        mod_manager = ModManager(app_state, feedback_manager)
        mod_ops = ModOperationsController(app_state=app_state, feedback_manager=feedback_manager, mod_manager=mod_manager, app_window=Mock())
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

        controller = SearchDisplayController(app_state=app_state, feedback_manager=feedback_manager, mod_manager=mod_manager, mod_ops=mod_ops, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state
        assert hasattr(controller, 'plaque_widget_cache')
        assert hasattr(controller, '_update_display_debounce')


class TestSettingsUiController:

    def test_settings_ui_controller_initialization(self, app_state, feedback_manager, qapp):
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        from controllers.settings_ui_controller import SettingsUiController
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=qapp)
        from managers.used_mods_manager import UsedModsManager
        from managers.customization_manager import CustomizationManager
        from managers.mod_manager import ModManager
        mod_manager = ModManager(app_state, feedback_manager)
        slot_manager = UsedModsManager(app_state, mod_manager, feedback_manager, settings_manager, None)
        customization_manager = CustomizationManager(app_state)
        app_window = Mock()
        controller = SettingsUiController(app_state=app_state, feedback_manager=feedback_manager, settings_manager=settings_manager, slot_manager=slot_manager, customization_manager=customization_manager, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state


class TestThemeController:

    def test_theme_controller_initialization(self, app_state, feedback_manager, qapp):
        from controllers.theme_controller import ThemeController
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        from managers.customization_manager import CustomizationManager
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=qapp)
        customization_manager = CustomizationManager(app_state)
        app_window = Mock()
        controller = ThemeController(app_state=app_state, feedback_manager=feedback_manager, settings_manager=settings_manager, customization_manager=customization_manager, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state


class TestGameLaunchController:

    def test_game_launch_controller_initialization(self, app_state, feedback_manager, qapp):
        from controllers.game_launch_controller import GameLaunchController
        from managers.mod_manager import ModManager
        from managers.used_mods_manager import UsedModsManager
        from managers.settings_manager import SettingsManager
        from managers.localization_manager import localization_manager
        from managers.launch_manager import GameLauncher
        from managers.customization_manager import CustomizationManager
        from managers.plugin_manager import PluginManager
        mod_manager = ModManager(app_state, feedback_manager)
        settings_manager = SettingsManager(app_state=app_state, feedback_manager=feedback_manager, localization_manager=localization_manager, parent=qapp)
        slot_manager = UsedModsManager(app_state, mod_manager, feedback_manager, settings_manager, None)
        game_launcher = GameLauncher(app_state, feedback_manager, mod_manager)
        customization_manager = CustomizationManager(app_state)
        plugin_manager = PluginManager(app_state, settings_manager)
        app_window = Mock()
        controller = GameLaunchController(app_state=app_state, feedback_manager=feedback_manager, mod_manager=mod_manager, slot_manager=slot_manager, settings_manager=settings_manager, game_launcher=game_launcher, customization_manager=customization_manager, plugin_manager=plugin_manager, app_window=app_window)
        assert controller is not None
        assert controller.app_state == app_state
