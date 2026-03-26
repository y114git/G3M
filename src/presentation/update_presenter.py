"""Update and announce presentation helpers."""

import logging

from PyQt6.QtCore import QThread, QTimer, pyqtSignal

from config.config import CLOUD_FUNCTIONS_BASE_URL
from services.localization_service import tr
from utils.network_utils import get_session

UPDATE_PROMPT_RETRY_INTERVAL_MS = 500
UPDATE_PROMPT_MAX_RETRIES = 15


class _GlobalSettingsWorker(QThread):
    """Reloads global settings without blocking the UI."""

    finished = pyqtSignal(bool, dict)

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self._app_state = app_state

    def run(self):
        try:
            response = get_session(self._app_state).get(
                f"{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings", timeout=5
            )
            if response.status_code == 200:
                self.finished.emit(True, response.json() or {})
                return
        except Exception as e:
            logging.warning("reload_global_settings: %s", e)
        self.finished.emit(False, {})


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
    logging.warning(
        "Update dialog fallback: init_completed=%s, is_shown=%s, is_visible=%s",
        init_completed,
        is_shown,
        is_visible,
    )
    app.show_update_prompt.emit(update_info)


def reload_global_settings(app, callback=None):
    if not app.app_state.has_internet:
        if callback:
            callback(False)
        return
    worker = _GlobalSettingsWorker(app.app_state, parent=app)

    def _on_finished(success, data):
        try:
            if success:
                app.app_state.global_settings = data
            if callback:
                callback(success)
        finally:
            worker.deleteLater()

    worker.finished.connect(_on_finished)
    worker.start()


def check_and_show_announce(app, retry_count=0, force_check=False):
    init_completed = app.app_state.initialization_completed
    is_shown = app.app_state.is_shown_to_user
    is_visible = app.isVisible() if hasattr(app, "isVisible") else False
    if not (init_completed and (is_shown or is_visible or force_check)):
        if retry_count < 15:
            QTimer.singleShot(
                500,
                lambda: check_and_show_announce(app, retry_count + 1, force_check),
            )
        return
    announce = (app.app_state.global_settings or {}).get("announce", {})
    announce_version = announce.get("version", 0)
    saved_version = app.app_state.local_config.get("announce_version", 0)
    if not announce_version or saved_version == -1 or announce_version == saved_version:
        return
    announce_message = app._localized_value(announce, "message_ru", "message_en")
    if not announce_message:
        save_announce(app, announce_version)
        return
    if is_visible and not is_shown:
        app.app_state.is_shown_to_user = True
    from ui.dialogs.announce_dialog import AnnounceDialog

    dialog = AnnounceDialog(announce_message, announce.get("link", ""), app)
    dialog.accepted_with_ok.connect(lambda: save_announce(app, announce_version))
    dialog.exec()
    app.app_state.pending_announce_check = False


def save_announce(app, version: int):
    app.app_state.local_config["announce_version"] = version
    app.settings_service.write_local_config()


def prompt_for_update(app, update_info):
    from config.config import LAUNCHER_VERSION, UI_COLORS

    if app.app_state.update_in_progress:
        return
    if app.app_state.game_is_running:
        app.app_state.pending_dialogs.append(("update", update_info))
        return
    app.app_state.update_in_progress = True
    update_message = (
        f"<b>{tr('dialogs.new_version_banner', version=update_info['version']).replace('<br>', '')}</b><br>"
        + tr("dialogs.current_version_banner", current_version=LAUNCHER_VERSION).replace(
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
        "status.update_available", "status.update_available", update_message, True
    ):
        if hasattr(app, "_perform_update_ui_prep"):
            app._perform_update_ui_prep()
        app.update_checker.perform_update(update_info)
        return
    app.app_state.update_in_progress = False
    app.feedback_service.update_status(
        tr("status.update_rejected"), UI_COLORS["status_info"]
    )
    if getattr(app.app_state, "pending_announce_check", False):
        check_and_show_announce(app)
