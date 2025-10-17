from PyQt6.QtWidgets import QMessageBox

# --- Plugin Metadata ---
PLUGIN_NAME = "window_opener_tab_title"
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
    so the tab will not be persistently displayed.
    """
    from localization import tr  # type: ignore
    title = tr("window_opener_title")
    message = tr("window_opener_message")
    QMessageBox.information(main_app_instance, title, message)
    return None
