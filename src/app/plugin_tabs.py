"""Plugin tab management extracted from AppWindow."""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config.config import QSS_EMPTY_PLUGIN_LABEL
from services.localization_service import tr


def create_nobody_came_tab(w):
    """Create and add 'But nobody came.' placeholder tab when no tabs are visible."""
    widget = QWidget()
    widget.setObjectName("nobody_came_tab")
    lay = QVBoxLayout(widget)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl = QLabel(tr("ui.nobody_came"))
    lbl.setStyleSheet(QSS_EMPTY_PLUGIN_LABEL)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    w.main_tab_widget.addTab(widget, "")


def remove_nobody_came_tab(w):
    """Remove 'But nobody came.' tab if it exists as the only tab."""
    if w.main_tab_widget.count() != 1:
        return
    widget = w.main_tab_widget.widget(0)
    if isinstance(widget, QWidget) and widget.objectName() == "nobody_came_tab":
        w.main_tab_widget.removeTab(0)


def init_plugin_placeholder_tab(w, tab_index):
    """Initialize a plugin placeholder tab at the given index if needed."""
    current_widget = w.main_tab_widget.widget(tab_index)
    is_placeholder = type(current_widget) is QWidget and current_widget.layout() is None
    if not is_placeholder or tab_index not in w._plugin_tab_map:
        return
    plugin = w._plugin_tab_map[tab_index]
    try:
        handler = (
            plugin.get("page_init")
            if callable(plugin.get("page_init"))
            else plugin.get("on_tab_open")
        )
        if callable(handler):
            new_widget = run_with_plugin_api(w, plugin, handler)
            if isinstance(new_widget, QWidget):
                try:
                    new_widget.setProperty("plugin_name_key", plugin.get("name_key"))
                    new_widget._plugin_info = plugin
                except Exception as e:
                    logging.debug(
                        f"Failed to bind plugin metadata for '{plugin.get('name_key', 'unknown')}': {e}",
                        exc_info=True,
                    )
                w.main_tab_widget.removeTab(tab_index)
                w.main_tab_widget.insertTab(
                    tab_index, new_widget, tr(plugin["name_key"])
                )
                w.main_tab_widget.setCurrentIndex(tab_index)
    except Exception as e:
        logging.exception(
            f"Error initializing plugin '{plugin.get('name_key', 'unknown')}: {e}'"
        )


def update_nobody_came_state(w, num_main_tabs, plugin_count):
    """Show or remove 'But nobody came.' based on tab/plugin counts."""
    if num_main_tabs == 0 and plugin_count == 0:
        if w.main_tab_widget.count() == 0:
            create_nobody_came_tab(w)
    elif num_main_tabs == 0 and plugin_count > 0:
        remove_nobody_came_tab(w)
        if w.main_tab_widget.count() > 0:
            idx = max(w.main_tab_widget.currentIndex(), 0)
            init_plugin_placeholder_tab(w, idx)


def update_plugin_tabs(w):
    """Reload plugins and sync plugin tabs in the main tab widget."""
    if not hasattr(w, "plugin_service") or not hasattr(w, "main_tab_widget"):
        return
    if w._handling_plugin_tab:
        return
    w._handling_plugin_tab = True
    w.plugin_service.load_plugins()
    num_main_tabs = getattr(w, "_num_main_tabs_visible", 3)
    w._plugin_tab_map = w.plugin_service.update_plugin_tabs(
        w.main_tab_widget, num_original_tabs=num_main_tabs
    )
    update_nobody_came_state(w, num_main_tabs, len(w._plugin_tab_map))
    if hasattr(w, "plugin_display"):
        w.plugin_display.update_display()
    w._handling_plugin_tab = False


def restore_last_active_tab(w):
    """Restore the last active tab from config."""
    last_tab = w.app_state.local_config.get("last_active_tab", 0)
    if last_tab == 0:
        return
    max_tabs = w.main_tab_widget.count() - 1
    if last_tab > max_tabs:
        return
    w.main_tab_widget.setCurrentIndex(last_tab)


def run_with_plugin_api(w, plugin, handler):
    """Run a plugin handler with temporary plugin API binding."""
    plugin_api = plugin.get("api")
    if plugin_api:
        w.plugin_api = plugin_api
    try:
        return handler(w)
    finally:
        if hasattr(w, "plugin_api"):
            del w.plugin_api


def resolve_plugin_from_widget(current_widget, visible_plugins, plugin):
    """Resolve the plugin dict from a tab widget via metadata or property."""
    try:
        bound = getattr(current_widget, "_plugin_info", None)
        if isinstance(bound, dict):
            return bound
    except Exception as e:
        logging.debug(
            f"Failed to resolve plugin info from widget binding: {e}", exc_info=True
        )
    try:
        if current_widget is not None and hasattr(current_widget, "property"):
            name_key = current_widget.property("plugin_name_key")
            if name_key:
                for p in visible_plugins:
                    if p.get("name_key") == name_key:
                        return p
    except Exception as e:
        logging.debug(
            f"Failed to resolve plugin info from widget property: {e}",
            exc_info=True,
        )
    return plugin
