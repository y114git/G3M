"""Tab change handler extracted from AppWindow."""

from PyQt6.QtCore import QTimer


def handle_tab_changed(w, index):
    """Handle main tab widget tab changes. `w` is the AppWindow instance."""
    if getattr(w, "_suppress_tab_handlers", False):
        w.previous_tab_index = index
        return
    if hasattr(w, "search_display"):
        w.search_display.clear_all_selections()
    if index == 1 and not getattr(w.app_state, "library_initialized", False):
        w.app_state.library_initialized = True
        if hasattr(w, "library_display") and hasattr(w.app_state, "all_mods") and w.app_state.all_mods:
            if hasattr(w.library_display, "_last_render_signature"):
                w.library_display._last_render_signature = None
            QTimer.singleShot(0, w.library_display.update_display)
    w.previous_tab_index = index
