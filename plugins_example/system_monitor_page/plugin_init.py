import importlib.util
import os
from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

# --- Plugin Metadata ---
PLUGIN_ID = "system_monitor"  # Unique plugin identifier (used for config prefixes)
PLUGIN_NAME = "system_monitor_tab_title"  # Plugin display name (localization key)
VERSION = "1.0.0"
AUTHOR = "DELTAHUB"  # Plugin author (optional, displayed in plugin plaque)
DESCRIPTION = "Displays system monitoring information in a tab"
TAB_HIDE = False

# --- Localization ---
LANG_EN = {
    "system_monitor_tab_title": "System Monitor",
    "system_monitor_error_loading": "Failed to load System Monitor UI."
}

LANG_RU = {
    "system_monitor_tab_title": "Системный монитор",
    "system_monitor_error_loading": "Не удалось загрузить интерфейс системного монитора."
}

# --- Main UI Execution Function ---


def page_init(main_app_instance):
    """
    Called when the plugin's tab is first opened.
    Returns a QWidget instance to be displayed in the tab.
    """
    try:
        plugin_dir = os.path.dirname(__file__)
        ui_path = os.path.join(plugin_dir, "ui.py")

        spec = importlib.util.spec_from_file_location(
            "plugin_ui_system_monitor", ui_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for module at {ui_path}")

        ui_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui_module)

        widget = ui_module.SystemMonitorWidget(main_app_instance)

        # Check if widget is valid
        if widget is None:
            return None

        return widget
    except Exception as e:
        # Get localization function from main app
        tr = main_app_instance.lang_manager.get_text
        error_label = QLabel(
            f"{tr('system_monitor_error_loading')}\n\nError: {e}")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return error_label
