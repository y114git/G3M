import importlib.util
import os
from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

# --- Plugin Metadata ---
PLUGIN_NAME = "system_monitor_tab_title"
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
def on_tab_open(main_app_instance):
    """
    Called when the plugin's tab is clicked.
    Returns a QWidget instance to be displayed in the tab.
    """
    try:
        plugin_dir = os.path.dirname(__file__)
        ui_path = os.path.join(plugin_dir, "ui.py")

        spec = importlib.util.spec_from_file_location("plugin_ui_system_monitor", ui_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for module at {ui_path}")

        ui_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui_module)

        return ui_module.SystemMonitorWidget(main_app_instance)
    except Exception as e:
        print(f"Error creating system monitor widget: {e}")
        from localization import tr  # type: ignore
        error_label = QLabel(f"{tr('system_monitor_error_loading')}\n\nError: {e}")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return error_label
