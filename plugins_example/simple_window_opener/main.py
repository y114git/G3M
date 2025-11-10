from PyQt6.QtWidgets import QMessageBox

# --- Plugin Metadata ---
PLUGIN_ID = "simple_window_opener"  # Unique plugin identifier (used for config prefixes)
PLUGIN_NAME = "window_opener_tab_title"  # Plugin display name (localization key)
VERSION = "1.0.0"
AUTHOR = "DELTAHUB"  # Plugin author (optional, displayed in plugin plaque)
DESCRIPTION = "Opens a message box when the plugin tab is clicked"
TAB_HIDE = False

# --- Localization ---
LANG_EN = {
    "window_opener_tab_title": "Open Window",
    "window_opener_title": "Plugin Window",
    "window_opener_message": "This is a new window opened by a plugin."
}

LANG_RU = {
    "window_opener_tab_title": "Открыть окно",
    "window_opener_title": "Окно плагина",
    "window_opener_message": "Это новое окно, открытое плагином."
}


# --- Main UI Execution Function ---
def on_tab_open(main_app_instance):
    """
    Called when the plugin's tab is clicked.
    This function opens a new window and returns None,
    so the user will be returned to the previous tab.
    """
    # Get localization function from main app
    tr = main_app_instance.lang_manager.get_text
    title = tr("window_opener_title")
    message = tr("window_opener_message")
    QMessageBox.information(main_app_instance, title, message)
    return None
