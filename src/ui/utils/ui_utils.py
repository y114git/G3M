"""UI utility functions."""

import contextlib
import logging
from collections.abc import Callable

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QThread,
    QTimer,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget


class DebounceTimer:
    """Timer that delays function execution until after a period of inactivity."""

    def __init__(self, delay_ms: int = 200) -> None:
        self.delay_ms = delay_ms
        self._timer: QTimer | None = None
        self._callback: Callable | None = None

    def _ensure_timer(self) -> QTimer:
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._execute)
        return self._timer

    def call(self, callback: Callable) -> None:
        timer = self._ensure_timer()
        if timer.isActive():
            timer.stop()
        self._callback = callback
        timer.start(self.delay_ms)

    def _execute(self) -> None:
        if self._callback is not None:
            try:
                self._callback()
            except Exception as e:
                logging.error(
                    f"DebounceTimer: Error executing callback: {e}", exc_info=True
                )
        self._callback = None

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._callback = None


def format_size_mb(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 MB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def refresh_ui_after_mod_install(main_window, mod_service=None):
    from config.constants import UI_COLORS
    from services.localization_service import tr

    if hasattr(main_window, "plugin_service") and main_window.plugin_service:
        main_window.plugin_service.convert_plugin_archives()
        main_window.plugin_service.load_plugins()
    if hasattr(main_window, "_update_plugin_tabs"):
        main_window._update_plugin_tabs()
    if hasattr(main_window, "plugin_display"):
        main_window.plugin_display.update_display()
    if mod_service:
        mod_service.invalidate_mods_cache()
        mod_service.load_local_mods(_skip_conversion=True)
        mod_service.mod_list_updated.emit()
    if hasattr(main_window, "library_display"):
        main_window.library_display.update_display()
    if hasattr(main_window, "search_display"):
        main_window.search_display.update_search_cards()
        main_window.search_display.update_filtered_mods(preserve_page=True)
    if hasattr(main_window, "settings_service"):
        main_window.settings_service.theme_changed.emit()
    if hasattr(main_window, "feedback_service"):
        main_window.feedback_service.update_status(
            tr("dialogs.mod_created_successfully"), UI_COLORS["status_success"]
        )
    if hasattr(main_window, "_on_refresh_clicked"):
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
            if blocking and not thread.wait(timeout):
                logging.warning(
                    f"safe_stop_thread: thread {type(thread).__name__} did not stop in {timeout}ms. Thread may be blocked. Consider checking isInterruptionRequested() in worker loops."
                )
                try:
                    thread.terminate()
                    thread.wait(500)
                except Exception as e:
                    logging.debug(
                        f"safe_stop_thread: failed to terminate thread {type(thread).__name__}: {e}",
                        exc_info=True,
                    )
        except RuntimeError, AttributeError:
            pass
        except Exception as e:
            logging.error(
                f"safe_stop_thread: error stopping thread {type(thread).__name__}: {e}",
                exc_info=True,
            )


class UIAnimator:
    """Helper class for applying UI animations."""

    @staticmethod
    def _animations_enabled(app_state) -> bool:
        if not app_state:
            return True
        return not app_state.local_config.get("disable_animations", False)

    @staticmethod
    def _preserve_fade_effect(widget: QWidget) -> bool:
        return bool(getattr(widget, "_preserve_fade_effect", False))

    @staticmethod
    def _stop_existing_fade(widget: QWidget) -> None:
        anim = getattr(widget, "_fade_anim", None)
        if not anim:
            return
        with contextlib.suppress(RuntimeError, AttributeError):
            anim.stop()
        if getattr(widget, "_fade_anim", None) is anim:
            widget._fade_anim = None
        with contextlib.suppress(RuntimeError, AttributeError):
            anim.deleteLater()

    @staticmethod
    def get_opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
        return UIAnimator._get_opacity_effect(widget)

    @staticmethod
    def _get_opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
        effect = getattr(widget, "_fade_effect", None)
        if isinstance(effect, QGraphicsOpacityEffect):
            current_effect = (
                widget.graphicsEffect() if hasattr(widget, "graphicsEffect") else None
            )
            if current_effect is not effect:
                widget.setGraphicsEffect(effect)
            return effect
        current_effect = (
            widget.graphicsEffect() if hasattr(widget, "graphicsEffect") else None
        )
        if isinstance(current_effect, QGraphicsOpacityEffect):
            effect = current_effect
        else:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        widget._fade_effect = effect
        return effect

    @staticmethod
    def fade_in(
        widget: QWidget, duration: int = 200, app_state=None
    ) -> QPropertyAnimation:
        """Fade in a widget by animating opacity."""

        should_show = (
            widget.parent() is not None or type(widget).__name__ == "AnimatedToolTip"
        )
        preserve_effect = UIAnimator._preserve_fade_effect(widget)

        if not UIAnimator._animations_enabled(app_state):
            widget.setWindowOpacity(1.0)
            if hasattr(widget, "setGraphicsEffect"):
                eff = widget.graphicsEffect()
                if isinstance(eff, QGraphicsOpacityEffect):
                    eff.setOpacity(1.0)
            if should_show:
                widget.show()
            return None

        UIAnimator._stop_existing_fade(widget)
        if should_show:
            widget.show()
        effect = UIAnimator._get_opacity_effect(widget)
        effect.setOpacity(0.0)

        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        def cleanup():
            if preserve_effect:
                effect.setOpacity(1.0)
            else:
                if hasattr(widget, "setGraphicsEffect"):
                    widget.setGraphicsEffect(None)
                widget._fade_effect = None
            widget._fade_anim = None

        anim.finished.connect(cleanup)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

        widget._fade_effect = effect
        widget._fade_anim = anim
        return anim

    @staticmethod
    def fade_out(
        widget: QWidget, duration: int = 200, app_state=None
    ) -> QPropertyAnimation:
        """Fade out a widget by animating opacity."""
        preserve_effect = UIAnimator._preserve_fade_effect(widget)
        if not UIAnimator._animations_enabled(app_state):
            widget.hide()
            return None

        UIAnimator._stop_existing_fade(widget)
        effect = UIAnimator._get_opacity_effect(widget)
        effect.setOpacity(1.0)

        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)

        def cleanup():
            widget.hide()
            if preserve_effect:
                effect.setOpacity(0.0)
            else:
                if hasattr(widget, "setGraphicsEffect"):
                    widget.setGraphicsEffect(None)
                widget._fade_effect = None
            widget._fade_anim = None

        anim.finished.connect(cleanup)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

        widget._fade_effect = effect
        widget._fade_anim = anim
        return anim

    @staticmethod
    def collapse_expand(
        widget: QWidget, expand: bool, duration: int = 250, app_state=None
    ) -> QPropertyAnimation | None:
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
