"""Window-local runtime state initialization."""

import platform

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPixmap


def initialize_window_runtime(window) -> None:
    """Populate window-local runtime fields that are not application services."""
    window._tooltip_widget = None
    window._tooltip_timer = QTimer(window)
    window._tooltip_timer.setSingleShot(True)
    window._tooltip_timer.timeout.connect(window._show_custom_tooltip)
    window._last_tooltip_text = ""
    window._last_tooltip_target = None
    window._last_tooltip_size_key = None
    window.resize(875, 750)
    window._initial_size = window.size()
    window.background_movie = None
    window.background_pixmap: QPixmap | None = None
    window.custom_font_family = None
    window._bg_music_running = False
    window._bg_music_thread = None
    window._suppress_tab_handlers = False
    window._last_online_count = 0
    window._install_op_id = 0
    window.pending_updates = []
    window._mods_display_ready_emitted = False
    window._post_show_initialized = False
    window._resize_margin = 6
    window._restoring_window_geometry = False
    window._window_layout_refresh_timer = QTimer(window)
    window._window_layout_refresh_timer.setSingleShot(True)
    window._window_layout_refresh_timer.timeout.connect(
        window._refresh_after_window_layout_change
    )
    window._last_resize_cursor_shape = None
    window._downloads_dialog = None
    window._game_versions_dialog = None
    window._modding_tools_dialog = None
    window._supports_volume = platform.system() == "Windows"
