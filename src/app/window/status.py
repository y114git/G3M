"""Status and update UI helpers for AppWindow."""

import logging

from config.config import UI_COLORS
from services.localization_service import localization_service, tr

logger = logging.getLogger(__name__)


def get_update_widgets(window):
    return [
        window.action_button,
        window.community_button,
        window.change_background_button,
    ]


def set_update_ui_enabled(window, enabled: bool) -> None:
    for widget in get_update_widgets(window):
        if widget:
            widget.setEnabled(enabled)
    if getattr(window, "top_refresh_button", None):
        window.top_refresh_button.setEnabled(enabled)
    window.settings_button.setEnabled(enabled)


def perform_update_ui_prep(window) -> None:
    set_update_ui_enabled(window, False)
    if not window.app_state.is_settings_view:
        window.tab_widget.setEnabled(False)
    window.progress_bar.setVisible(True)
    window.progress_bar.setValue(0)


def on_update_cleanup(window) -> None:
    try:
        window.progress_bar.setVisible(False)
    except Exception as e:
        logger.debug(f"Update cleanup - progress bar: {e}")
    window.app_state.update_in_progress = False
    try:
        if not window.app_state.is_settings_view:
            window.tab_widget.setEnabled(True)
        set_update_ui_enabled(window, True)
        window.game_launch.update_button_state()
    except Exception as e:
        logger.debug(f"Update cleanup - UI restore: {e}")


def on_progress_update(window, value: int) -> None:
    window.progress_bar.setValue(value)
    if value > 0 and (not window.progress_bar.isVisible()):
        window.progress_bar.setVisible(True)


def update_status(window, message: str, color: str = "white") -> None:
    window._last_status_translation = match_status_translation(message)
    set_status_text(window, message, color)


def update_localized_status(window, tr_key: str, color: str = "white", **kwargs) -> None:
    window._last_status_translation = (tr_key, dict(kwargs))
    set_status_text(window, tr(tr_key, **kwargs), color)


def match_status_translation(message: str) -> tuple[str, dict] | None:
    status_strings = getattr(localization_service, "strings", {}).get("status", {})
    if not isinstance(status_strings, dict):
        return None
    for key, value in status_strings.items():
        if not isinstance(value, str):
            continue
        tr_key = f"status.{key.removeprefix('_')}"
        if tr(tr_key) == message:
            return tr_key, {}
    return None


def refresh_localized_status(window) -> None:
    status_translation = getattr(window, "_last_status_translation", None)
    if not status_translation:
        return
    tr_key, kwargs = status_translation
    set_status_text(
        window,
        tr(tr_key, **kwargs),
        getattr(window, "_last_status_color", "white"),
    )


def set_status_text(window, message: str, color: str = "white") -> None:
    window._last_status_color = color
    actual_color = UI_COLORS.get(color, color)
    if not window.status_label.wordWrap():
        window.status_label.setWordWrap(True)
    window.status_label.setText(message)
    window.status_label.setStyleSheet(f"color: {actual_color};")
