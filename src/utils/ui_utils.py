"""UI utility functions.

This module provides utilities for UI operations including debouncing and formatting.
"""
import logging
from PyQt6.QtCore import QTimer, QThread
from typing import Callable, Optional
from utils.format_utils import format_size_mb as _format_size_mb


class DebounceTimer:
    """Timer that delays function execution until after a period of inactivity."""

    def __init__(self, delay_ms: int = 200):
        """Initialize the debounce timer.

        Args:
            delay_ms: Delay in milliseconds before executing callback.
        """
        self.delay_ms = delay_ms
        self._timer: Optional[QTimer] = None
        self._callback: Optional[Callable] = None

    def call(self, callback: Callable) -> None:
        """Schedule a callback to execute after the debounce delay.

        Args:
            callback: Function to execute after delay.
        """
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._callback = callback
        self._timer.timeout.connect(self._execute)
        self._timer.start(self.delay_ms)

    def _execute(self) -> None:
        """Execute the scheduled callback."""
        if self._callback is not None:
            try:
                self._callback()
            except Exception as e:
                import logging
                logging.error(f'DebounceTimer: Error executing callback: {e}', exc_info=True)
        self._timer = None
        self._callback = None

    def cancel(self) -> None:
        """Cancel the pending callback execution."""
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
            self._callback = None


def format_size_mb(size_bytes: int) -> str:
    """Format byte size as megabytes string.

    Args:
        size_bytes: Size in bytes.

    Returns:
        str: Formatted size string.
    """
    return _format_size_mb(size_bytes)


def refresh_ui_after_mod_install(main_window, mod_manager=None):
    """Refresh UI components after mod installation.

    Args:
        main_window: Main application window.
        mod_manager: Mod manager instance (optional).
    """
    from PyQt6.QtCore import QTimer
    from config.constants import UI_COLORS
    from managers.localization_manager import tr
    if hasattr(main_window, 'plugin_manager') and main_window.plugin_manager:
        main_window.plugin_manager.convert_plugin_archives()
        main_window.plugin_manager.load_plugins()
    if hasattr(main_window, '_update_plugin_tabs'):
        main_window._update_plugin_tabs()
    if hasattr(main_window, 'plugin_display'):
        main_window.plugin_display.update_display()
    if mod_manager:
        mod_manager.invalidate_mods_cache()
        QTimer.singleShot(0, lambda: (mod_manager.load_local_mods(_skip_conversion=True), mod_manager.mod_list_updated.emit()))
    if hasattr(main_window, 'library_display'):
        main_window.library_display.update_display()
    if hasattr(main_window, 'search_display'):
        main_window.search_display.update_search_plaques()
        main_window.search_display.update_filtered_mods(preserve_page=True)
    if hasattr(main_window, 'settings_manager'):
        main_window.settings_manager.theme_changed.emit()
    if hasattr(main_window, 'feedback_manager'):
        main_window.feedback_manager.update_status(tr('dialogs.mod_created_successfully'), UI_COLORS['status_success'])
    if hasattr(main_window, '_on_refresh_clicked'):
        QTimer.singleShot(1000, lambda: main_window._on_refresh_clicked(is_initial=False))


def safe_stop_thread(thread, timeout=2000, blocking=True):
    """Safely stop a QThread with timeout and fallback termination.

    Args:
        thread: Thread to stop.
        timeout: Timeout in milliseconds.
        blocking: Whether to wait for thread to finish.
    """
    if not thread:
        return
    if isinstance(thread, QThread):
        try:
            if not thread.isRunning():
                return
            thread.requestInterruption()
            thread.quit()
            if blocking:
                if not thread.wait(timeout):
                    logging.warning(f'safe_stop_thread: thread {type(thread).__name__} did not stop in {timeout}ms. Thread may be blocked. Consider checking isInterruptionRequested() in worker loops.')
                    try:
                        thread.terminate()
                        thread.wait(500)
                    except Exception:
                        pass
        except (RuntimeError, AttributeError):
            pass
        except Exception as e:
            logging.error(f'safe_stop_thread: error stopping thread {type(thread).__name__}: {e}', exc_info=True)
