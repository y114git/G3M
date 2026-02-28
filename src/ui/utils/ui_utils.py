"""UI utility functions."""
import logging
from PyQt6.QtCore import QTimer, QThread, QPropertyAnimation, QEasingCurve, QAbstractAnimation
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect
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


class UIAnimator:
    """Helper class for applying UI animations."""

    @staticmethod
    def _animations_enabled(app_state) -> bool:
        if not app_state:
            return True
        return not app_state.local_config.get('disable_animations', False)

    @staticmethod
    def fade_in(widget: QWidget, duration: int = 200, app_state=None) -> QPropertyAnimation:
        """Fade in a widget by animating opacity."""

        should_show = widget.parent() is not None or type(widget).__name__ == "AnimatedToolTip"

        if not UIAnimator._animations_enabled(app_state):
            widget.setWindowOpacity(1.0)
            if hasattr(widget, 'setGraphicsEffect'):
                eff = widget.graphicsEffect()
                if isinstance(eff, QGraphicsOpacityEffect):
                    eff.setOpacity(1.0)
            if should_show:
                widget.show()
            return None

        if should_show:
            widget.show()
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        def cleanup():
            if hasattr(widget, 'setGraphicsEffect'):
                widget.setGraphicsEffect(None)

        anim.finished.connect(cleanup)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

        widget._fade_effect = effect
        widget._fade_anim = anim
        return anim

    @staticmethod
    def fade_out(widget: QWidget, duration: int = 200, app_state=None) -> QPropertyAnimation:
        """Fade out a widget by animating opacity."""
        if not UIAnimator._animations_enabled(app_state):
            widget.hide()
            return None

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        def cleanup():
            widget.hide()
            if hasattr(widget, 'setGraphicsEffect'):
                widget.setGraphicsEffect(None)

        anim.finished.connect(cleanup)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

        widget._fade_effect = effect
        widget._fade_anim = anim
        return anim

    @staticmethod
    def collapse_expand(widget: QWidget, expand: bool, duration: int = 250, app_state=None):
        """Animates max height to simulate expand/collapse."""
        if not UIAnimator._animations_enabled(app_state):
            widget.setVisible(expand)
            widget.setMaximumHeight(16777215)
            return None

        if expand:
            widget.setVisible(True)
            target_height = widget.sizeHint().height()
            start_height = 0
        else:
            start_height = widget.height()
            target_height = 0

        anim = QPropertyAnimation(widget, b"maximumHeight")
        anim.setDuration(duration)
        anim.setStartValue(start_height)
        anim.setEndValue(target_height)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        if not expand:
            anim.finished.connect(lambda: widget.setVisible(False))
        else:
            anim.finished.connect(lambda: widget.setMaximumHeight(16777215))

        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

        widget._collapse_anim = anim
        return anim
