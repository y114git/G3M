"""Main window controller composition."""

from PyQt6.QtWidgets import QApplication

from app.dialogs import on_downloads_record_updated, on_downloads_use_completed
from app.game_ui import on_games_registry_changed, on_used_mods_updated
from app.localization_utils import relocalize_ui
from controllers.game_launch_controller import GameLaunchController
from controllers.library_display_controller import LibraryDisplayController
from controllers.mod_operations_controller import ModOperationsController
from controllers.plugins_controller import PluginsController
from controllers.refresh_controller import RefreshController
from controllers.search_display_controller import SearchDisplayController
from controllers.settings_controller import SettingsUiController
from controllers.theme_controller import ThemeController
from presentation.pizza_oven_conversion_presenter import (
    PizzaOvenConversionPresenter,
)
from presentation.update_presenter import handle_update_info
from ui.utils.ui_utils import DebounceTimer


class WindowComposition:
    """Creates presentation controllers and wires them to the application context."""

    def __init__(self, window) -> None:
        self.window = window

    def compose(self) -> None:
        window = self.window
        window.feedback_service.status_updated.connect(window.update_status_signal.emit)
        window.settings_service.language_changed.connect(lambda _: relocalize_ui(window))
        if window.plugin_runtime_service is not None:
            window.settings_service.language_changed.connect(
                lambda _: window.plugin_runtime_service.execute_hook("language_changed")
            )
        window.settings_service.restart_required.connect(
            lambda msg: window.feedback_service.show_message(
                "info",
                "dialogs.restart_required",
                msg,
            )
        )
        window.settings_service.status_changed.connect(window.update_status_signal.emit)
        if window.plugin_runtime_service is not None:
            window.settings_service.theme_changed.connect(
                lambda: window.plugin_runtime_service.execute_hook("theme_changed")
            )
        window.mod_service.progress_updated.connect(window.set_progress_signal.emit)
        window.mod_service.status_changed.connect(window.update_status_signal.emit)
        window.mod_service.url_prompt_required.connect(window._handle_url_install_prompt)
        window.game_launcher.status_changed.connect(window.update_status_signal.emit)
        window.game_launcher.progress_updated.connect(window.set_progress_signal.emit)
        window.game_launcher.game_launch_started.connect(
            window.hide_window_signal.emit
        )
        window.game_launcher.game_launch_finished.connect(
            window.restore_window_signal.emit
        )
        window.update_checker.update_available.connect(
            lambda info: handle_update_info(window, info)
        )
        window.update_checker.status_changed.connect(window.update_status_signal.emit)
        window.update_checker.progress_updated.connect(window.set_progress_signal.emit)
        window.update_checker.update_finished.connect(window._on_update_cleanup)
        window.update_checker.update_error.connect(
            lambda msg: window.feedback_service.show_message(
                "error",
                "errors.error",
                msg,
            )
        )
        window.update_checker.quit_requested.connect(QApplication.quit)
        window.used_mods_service.used_mods_updated.connect(
            lambda: on_used_mods_updated(window)
        )
        if window.plugin_runtime_service:
            window.profile_service.profile_switched.connect(
                lambda _name: window.plugin_runtime_service.execute_hook("profile_changed")
            )
        window.session_manager.online_count_changed.connect(window._update_online_label)
        window._load_used_mods_debounce = DebounceTimer(delay_ms=200)
        window.mod_ops = ModOperationsController(
            window.app_state,
            window.feedback_service,
            window.mod_service,
            window,
        )
        window.library_display = LibraryDisplayController(
            window.app_state,
            window.feedback_service,
            window.mod_service,
            window.used_mods_service,
            window,
        )
        window.search_display = SearchDisplayController(
            window.app_state,
            window.feedback_service,
            window.mod_service,
            window.mod_ops,
            window,
        )
        for signal_name, method_name in (
            ("ui_button_text_update", "setText"),
            ("ui_button_tooltip_update", "setToolTip"),
            ("ui_button_icon_update", "setIcon"),
            ("ui_button_enabled_update", "setEnabled"),
            ("ui_widget_updates_enabled", "setUpdatesEnabled"),
        ):
            getattr(window.search_display, signal_name).connect(
                lambda widget_name, value, method=method_name: window._set_widget_attr(
                    widget_name,
                    method,
                    value,
                )
            )
        window.settings_ui = SettingsUiController(
            window.app_state,
            window.feedback_service,
            window.settings_service,
            window.used_mods_service,
            window.customization_service,
            window,
        )
        window.theme = ThemeController(
            window.app_state,
            window.feedback_service,
            window.settings_service,
            window.customization_service,
            window,
        )
        window.game_launch = GameLaunchController(
            window.app_state,
            window.feedback_service,
            window.mod_service,
            window.used_mods_service,
            window.settings_service,
            window.game_launcher,
            window.customization_service,
            window,
        )
        window.pizza_oven_conversion_presenter = PizzaOvenConversionPresenter(
            window.app_state,
            window.feedback_service,
            window.settings_service,
            window.mod_service,
            window.pizza_oven_conversion_service,
            window,
        )
        window.refresh_controller = RefreshController(
            window.app_state,
            window.feedback_service,
            window.mod_service,
            window.used_mods_service,
            window.game_launch,
            window.update_checker,
            window.settings_service,
            app_window=window,
        )
        if (
            window.plugin_catalog_service is not None
            and window.plugin_state_service is not None
            and window.plugin_runtime_service is not None
            and window.plugin_install_service is not None
        ):
            window.plugins_ui = PluginsController(
                window.app_state,
                window.feedback_service,
                window.downloads_manager,
                window.plugin_catalog_service,
                window.plugin_state_service,
                window.plugin_runtime_service,
                window.plugin_install_service,
                window,
            )
            window.initialization_finished.connect(
                lambda: window.plugin_runtime_service.execute_hook("app_ready")
            )
        else:
            window.plugins_ui = None
        if window.plugins_ui is not None:
            window.settings_service.theme_changed.connect(
                lambda: window.plugins_ui.handle_theme_refresh()
            )
        self._connect_cross_service_signals()

    def _connect_cross_service_signals(self) -> None:
        window = self.window
        window.mod_service.mod_list_updated.connect(window.library_display.update_display)
        window.mod_service.mod_list_updated.connect(window.search_display.update_search_cards)
        window.mod_service.mod_list_updated.connect(
            lambda: window._load_used_mods_debounce.call(
                window.used_mods_service.load_used_mods_state
            )
        )
        window.used_mods_service.used_mod_changed.connect(
            lambda _chapter_id: window.game_launch.update_button_state()
        )
        window.used_mods_service.used_mod_changed.connect(
            lambda chapter_id: (
                window.library_display._update_priority_button_visibility(chapter_id)
                if hasattr(window.library_display, "_update_priority_button_visibility")
                else None
            )
        )
        window.used_mods_service.action_button_update_needed.connect(
            window.game_launch.update_button_state
        )
        window.used_mods_service.mod_widgets_update_needed.connect(
            window.library_display.update_mod_widgets_active_status
        )
        window.game_launch.window_hide_requested.connect(window.hide)
        window.game_launch.window_restore_requested.connect(
            window._on_window_restore_requested
        )
        window.game_launch.library_display_update_requested.connect(
            window.library_display.update_display
        )
        window.game_launch.search_display_update_requested.connect(
            window.search_display.update_display
        )
        window.game_launch.update_geometry_requested.connect(window.updateGeometry)
        window.game_launch.show_pending_dialogs_requested.connect(
            window._show_pending_dialogs
        )
        window.game_launch.pending_updates_changed.connect(
            lambda updates: setattr(window, "pending_updates", updates)
        )
        window.settings_service.theme_changed.connect(
            window.theme.on_theme_changed_by_service
        )
        window.settings_service.settings_changed.connect(
            window.search_display.update_filtered_mods
        )
        window.downloads_manager.use_completed.connect(
            lambda: on_downloads_use_completed(window)
        )
        window.downloads_manager.record_updated.connect(
            lambda record: on_downloads_record_updated(window, record)
        )
        window.game_registry_service.games_changed.connect(
            lambda: on_games_registry_changed(window)
        )
