"""Update and announce presentation helpers."""

import logging
import time

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from config.config import CLOUD_FUNCTIONS_BASE_URL
from services.localization_service import tr
from utils.network_utils import cloud_function_request, get_session

logger = logging.getLogger(__name__)

UPDATE_PROMPT_RETRY_INTERVAL_MS = 500
UPDATE_PROMPT_MAX_RETRIES = 15
GLOBAL_SETTINGS_CACHE_TTL_SECONDS = 300


class _GlobalSettingsWorker(QThread):
    """Reloads global settings without blocking the UI."""

    finished = pyqtSignal(bool, dict)

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent if isinstance(parent, QObject) else None)
        self._app_state = app_state

    def run(self):
        try:
            response = cloud_function_request(
                "get",
                f"{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings",
                session=get_session(self._app_state),
                timeout=5,
            )
            if response and response.status_code == 200:
                self.finished.emit(True, response.json() or {})
                return
        except Exception as e:
            logger.warning("reload_global_settings: %s", e)
        self.finished.emit(False, {})


def _run_global_settings_callback(callback, success: bool) -> None:
    if not callback:
        return
    try:
        callback(success)
    except Exception:
        logger.exception("reload_global_settings: callback failed")


def _safe_update_status(app, message: str, color: str) -> None:
    feedback_service = getattr(app, "feedback_service", None)
    update_status = getattr(feedback_service, "update_status", None)
    if not callable(update_status):
        return
    try:
        update_status(message, color)
    except Exception:
        logger.exception("Update presenter: status feedback failed")


def _safe_warning(parent, title: str, message: str) -> None:
    try:
        QMessageBox.warning(parent, title, message)
    except Exception:
        logger.exception("Update presenter: warning dialog failed")


def handle_update_info(app, update_info, retry_count=0):
    """Show the update prompt once the UI is ready, retrying every 500ms for up to 7.5 seconds."""
    init_completed = app.app_state.initialization_completed
    is_shown = app.app_state.is_shown_to_user
    is_visible = app.isVisible() if hasattr(app, "isVisible") else False
    if init_completed and (is_shown or is_visible):
        if is_visible and not is_shown:
            app.app_state.is_shown_to_user = True
        app.show_update_prompt.emit(update_info)
        return
    if retry_count < UPDATE_PROMPT_MAX_RETRIES:
        QTimer.singleShot(
            UPDATE_PROMPT_RETRY_INTERVAL_MS,
            lambda: handle_update_info(app, update_info, retry_count + 1),
        )
        return
    logger.warning(
        "Update dialog fallback: init_completed=%s, is_shown=%s, is_visible=%s",
        init_completed,
        is_shown,
        is_visible,
    )
    app.show_update_prompt.emit(update_info)


def reload_global_settings(app, callback=None, *, force_refresh: bool = False):
    if not force_refresh and app.app_state.global_settings and (
        time.time() - float(getattr(app.app_state, "global_settings_loaded_at", 0.0))
        < GLOBAL_SETTINGS_CACHE_TTL_SECONDS
    ):
        _run_global_settings_callback(callback, True)
        return
    if not app.app_state.has_internet:
        _run_global_settings_callback(callback, False)
        return
    if getattr(app.app_state, "global_settings_load_in_progress", False):
        _run_global_settings_callback(callback, True)
        return
    app.app_state.global_settings_load_in_progress = True
    if not isinstance(app, QObject):
        try:
            response = cloud_function_request(
                "get",
                f"{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings",
                session=get_session(app.app_state),
                timeout=5,
            )
            success = bool(response and response.status_code == 200)
            if success:
                app.app_state.global_settings = response.json() or {}
                app.app_state.global_settings_loaded_at = time.time()
        except Exception as e:
            logger.warning("reload_global_settings: %s", e)
            success = False
        finally:
            _run_global_settings_callback(callback, success)
            app.app_state.global_settings_load_in_progress = False
        return
    worker = _GlobalSettingsWorker(app.app_state, parent=app)

    def _on_finished(success, data):
        try:
            if success:
                app.app_state.global_settings = data
                app.app_state.global_settings_loaded_at = time.time()
            _run_global_settings_callback(callback, success)
        finally:
            app.app_state.global_settings_load_in_progress = False
            worker.deleteLater()

    worker.finished.connect(_on_finished)
    worker.start()


def check_and_show_announce(app, retry_count=0, force_check=False):
    init_completed = app.app_state.initialization_completed
    is_shown = app.app_state.is_shown_to_user
    is_visible = app.isVisible() if hasattr(app, "isVisible") else False
    if not (init_completed and (is_shown or is_visible or force_check)):
        if retry_count < UPDATE_PROMPT_MAX_RETRIES:
            QTimer.singleShot(
                UPDATE_PROMPT_RETRY_INTERVAL_MS,
                lambda: check_and_show_announce(app, retry_count + 1, force_check),
            )
        return
    if not app.app_state.global_settings and not force_check:
        return
    announce = (app.app_state.global_settings or {}).get("announce", {})
    announce_messages = announce.get("messages", {})
    if not isinstance(announce_messages, dict):
        return
    announce_version = announce.get("version", 0)
    saved_version = app.app_state.local_config.get("announce_version", 0)
    if not announce_version or saved_version == -1 or announce_version == saved_version:
        return
    announce_message = app._localized_value(
        announce_messages, "message_ru", "message_en"
    )
    if not announce_message:
        save_announce(app, announce_version)
        return
    if is_visible and not is_shown:
        app.app_state.is_shown_to_user = True
    from ui.dialogs.announce_dialog import AnnounceDialog

    if getattr(app.app_state, "active_announce_dialog", None) is not None:
        return

    localized_announce = dict(announce)
    localized_announce["messages"] = announce_messages
    localized_announce["message"] = announce_message

    def _submit_poll(selected_options: list[str]) -> bool:
        success, error_message = app.announce_service.submit_poll_vote(
            localized_announce, selected_options
        )
        if success:
            return True
        _safe_warning(
            app,
            tr("dialogs.warning"),
            error_message or tr("dialogs.failed_submit_poll"),
        )
        return False

    dialog = AnnounceDialog(
        localized_announce,
        app,
        on_submit_poll=_submit_poll,
    )
    dialog.accepted_with_ok.connect(lambda: save_announce(app, announce_version))
    app.app_state.active_announce_dialog = dialog
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.finished.connect(
        lambda _result: setattr(app.app_state, "active_announce_dialog", None)
    )
    dialog.show()
    app.app_state.pending_announce_check = False


def save_announce(app, version: int):
    app.app_state.local_config["announce_version"] = version
    app.settings_service.write_local_config()


def prompt_for_update(app, update_info):
    from config.config import APP_VERSION, UI_COLORS

    if app.app_state.update_in_progress:
        return
    if app.app_state.game_is_running:
        app.app_state.pending_dialogs.append(("update", update_info))
        return
    app.app_state.update_in_progress = True
    update_message = (
        f"<b>{tr('dialogs.new_version_banner', version=update_info['version']).replace('<br>', '')}</b><br>"
        + tr("dialogs.current_version_banner", current_version=APP_VERSION).replace(
            "<br><br>", ""
        )
        + "<br><br>"
    )
    message_text = app._localized_value(
        update_info, "message_ru", "message_en", "message"
    )
    update_message += f"<b>{tr('dialogs.whats_new')}</b><br>{message_text}<br><br>"
    update_message += tr("dialogs.want_download_install_now") + tr(
        "dialogs.app_will_restart"
    )
    if app.feedback_service.ask_question(
        "status.update_available",
        "status.update_available",
        update_message,
        True,
        details_is_html=True,
    ):
        if hasattr(app, "_perform_update_ui_prep"):
            app._perform_update_ui_prep()
        app.update_checker.perform_update(update_info)
        return
    app.app_state.update_in_progress = False
    _safe_update_status(app, tr("status.update_rejected"), UI_COLORS["status_info"])
    if getattr(app.app_state, "pending_announce_check", False):
        check_and_show_announce(app)
