"""UI utility functions."""
import logging
from PyQt6.QtCore import QTimer, QThread
from typing import Callable, Optional


class DebounceTimer:
    """Timer that delays function execution until after a period of inactivity."""

    def __init__(self, delay_ms: int = 200):
        self.delay_ms = delay_ms
        self._timer: Optional[QTimer] = None
        self._callback: Optional[Callable] = None

    def call(self, callback: Callable) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._callback = callback
        self._timer.timeout.connect(self._execute)
        self._timer.start(self.delay_ms)

    def _execute(self) -> None:
        if self._callback is not None:
            try:
                self._callback()
            except Exception as e:
                import logging
                logging.error(f'DebounceTimer: Error executing callback: {e}', exc_info=True)
        self._timer = None
        self._callback = None

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
            self._callback = None


def format_size_mb(size_bytes: int) -> str:
    if size_bytes <= 0:
        return '0 MB'
    return f'{size_bytes / (1024 * 1024):.1f} MB'


def refresh_ui_after_mod_install(main_window, mod_service=None):
    from config.constants import UI_COLORS
    from services.localization_service import tr
    if hasattr(main_window, 'plugin_service') and main_window.plugin_service:
        main_window.plugin_service.convert_plugin_archives()
        main_window.plugin_service.load_plugins()
    if hasattr(main_window, '_update_plugin_tabs'):
        main_window._update_plugin_tabs()
    if hasattr(main_window, 'plugin_display'):
        main_window.plugin_display.update_display()
    if mod_service:
        mod_service.invalidate_mods_cache()
        mod_service.load_local_mods(_skip_conversion=True)
        mod_service.mod_list_updated.emit()
    if hasattr(main_window, 'library_display'):
        main_window.library_display.update_display()
    if hasattr(main_window, 'search_display'):
        main_window.search_display.update_search_cards()
        main_window.search_display.update_filtered_mods(preserve_page=True)
    if hasattr(main_window, 'settings_service'):
        main_window.settings_service.theme_changed.emit()
    if hasattr(main_window, 'feedback_service'):
        main_window.feedback_service.update_status(tr('dialogs.mod_created_successfully'), UI_COLORS['status_success'])
    if hasattr(main_window, '_on_refresh_clicked'):
        main_window._on_refresh_clicked(is_initial=False)


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
