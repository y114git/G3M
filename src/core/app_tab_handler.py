"""Tab change handler extracted from AppWindow."""
import logging
from PyQt6.QtWidgets import QWidget
from services.localization_service import tr


def handle_tab_changed(w, index):
    """Handle main tab widget tab changes. `w` is the AppWindow instance."""
    num_original_tabs = 3
    if getattr(w, '_suppress_tab_handlers', False):
        w.previous_tab_index = index
        return

    if index == 2:
        if hasattr(w, 'plugin_display'):
            w.plugin_display.update_display()
        w.previous_tab_index = index
        return
    if index >= num_original_tabs:
        visible_plugins = [p for p in w.app_state.plugins if not p.get('tab_hide', False)]
        plugin_index = index - num_original_tabs
        if 0 <= plugin_index < len(visible_plugins):
            plugin = w._plugin_tab_map.get(index) or visible_plugins[plugin_index]
            current_widget = w.main_tab_widget.widget(index)
            is_placeholder = type(current_widget) is QWidget and current_widget.layout() is None
            if is_placeholder:
                if w._handling_plugin_tab:
                    return
                w._handling_plugin_tab = True
                plugin = w._resolve_plugin_from_widget(current_widget, visible_plugins, plugin)
                try:
                    new_widget = None
                    handler = plugin.get('page_init') if callable(plugin.get('page_init')) else plugin.get('on_tab_open')
                    if callable(handler):
                        new_widget = w._run_with_plugin_api(plugin, handler)
                    if isinstance(new_widget, QWidget):
                        w.main_tab_widget.removeTab(index)
                        w.main_tab_widget.insertTab(index, new_widget, tr(plugin['name_key']))
                        w._programmatic_tab_change = True
                        w.main_tab_widget.setCurrentIndex(index)
                        w._programmatic_tab_change = False
                        w.previous_tab_index = index
                    else:
                        w._programmatic_tab_change = True
                        w.main_tab_widget.setCurrentIndex(w.previous_tab_index)
                        w._programmatic_tab_change = False
                except Exception as e:
                    logging.error(f"Error running plugin '{plugin['name_key']}': {e}")
                    w.feedback_service.show_message('error', 'errors.error', f"Failed to run plugin '{tr(plugin['name_key'])}':\n{e}")
                    w._programmatic_tab_change = True
                    w.main_tab_widget.setCurrentIndex(w.previous_tab_index)
                    w._programmatic_tab_change = False
                finally:
                    w._handling_plugin_tab = False
                return
            on_tab_open_handler = plugin.get('on_tab_open')
            if callable(on_tab_open_handler):
                try:
                    w._run_with_plugin_api(plugin, on_tab_open_handler)
                except Exception as e:
                    logging.debug(f"Error calling on_tab_open for plugin '{plugin.get('name_key', 'unknown')}': {e}")
        w.previous_tab_index = index
        return
    if index == 1:
        if not getattr(w.app_state, 'library_initialized', False):
            w.app_state.library_initialized = True
            if hasattr(w.app_state, 'all_mods') and w.app_state.all_mods:
                w.library_display.update_display()
    w.previous_tab_index = index
