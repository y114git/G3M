import contextlib
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from config.config import UI_COLORS
from services.game_detection_service import is_game_running
from services.localization_service import localization_service, tr
from ui.utils.ui_utils import safe_stop_thread
from workers.fetch_mods_worker import FetchModsThread


class _PostFetchWorker(QThread):
    """Background worker for heavy post-fetch operations (scan + cache restore)."""

    done = pyqtSignal(bool)

    def __init__(self, mod_service, app_state, parent=None) -> None:
        super().__init__(parent)
        self._mod_service = mod_service
        self._app_state = app_state

    def run(self):
        try:
            self._mod_service.invalidate_mods_cache()
            self._mod_service.load_local_mods()
            self.done.emit(True)
        except Exception as e:
            logging.error(f"_PostFetchWorker: Error: {e}", exc_info=True)
            self.done.emit(False)


class RefreshController:
    def __init__(
        self,
        app_state,
        feedback_service,
        mod_service,
        used_mods_service,
        game_launch_controller,
        update_checker,
        settings_service=None,
        app_window=None,
    ) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.used_mods_service = used_mods_service
        self.game_launch_controller = game_launch_controller
        self.update_checker = update_checker
        self.settings_service = settings_service
        self.app_window = app_window
        self.fetch_thread = None
        self.details_thread = None

    def cleanup(self):
        self._stop_fetch_thread()

    def _cleanup_thread_later(self, thread) -> None:
        try:
            if thread.isFinished():
                thread.deleteLater()
            else:
                thread.finished.connect(lambda: thread.deleteLater())
        except (RuntimeError, TypeError, AttributeError):
            pass

    def _stop_worker_thread(
        self,
        thread,
        *,
        disconnect_signals=None,
        check_running=False,
        error_label="thread",
    ) -> None:
        try:
            if disconnect_signals:
                for signal in disconnect_signals:
                    if signal is None:
                        continue
                    with contextlib.suppress(TypeError, RuntimeError, AttributeError):
                        signal.disconnect()
            try:
                if hasattr(thread, "cancel"):
                    thread.cancel()
            except (RuntimeError, AttributeError):
                logging.debug("Failed to cancel thread")
            try:
                if not check_running or thread.isRunning():
                    safe_stop_thread(thread, timeout=200, blocking=False)
            except (RuntimeError, AttributeError):
                logging.debug("Failed to cancel thread")
            self._cleanup_thread_later(thread)
        except Exception as e:
            logging.debug(
                f"RefreshController: Error stopping {error_label} (thread may be deleted): {e}"
            )

    def refresh_mods_list(
        self,
        is_initial=False,
        language_combo=None,
        localization_callback=None,
        on_fetch_finished_kwargs=None,
    ):
        try:
            if (
                hasattr(self.app_state, "_scan_blocked")
                and self.app_state._scan_blocked
            ):
                return
            if language_combo is not None:
                current_lang_code = localization_service.get_current_language()
                localization_service.rescan_languages()
                language_combo.blockSignals(True)
                try:
                    language_combo.clear()
                    for (
                        code,
                        name,
                    ) in localization_service.get_available_languages().items():
                        language_combo.addItem(name, code)
                    index = language_combo.findData(current_lang_code)
                    if index != -1:
                        language_combo.setCurrentIndex(index)
                finally:
                    language_combo.blockSignals(False)
            if not is_initial and localization_callback:
                localization_callback()
            if is_game_running():
                self.feedback_service.update_status(
                    tr("status.cant_update_while_running"), UI_COLORS["status_warning"]
                )
                return
            self._stop_fetch_thread()
            try:
                if self.fetch_thread:
                    try:
                        if self.fetch_thread.isRunning():
                            logging.warning(
                                "RefreshController: Previous fetch thread still running, ignoring new fetch"
                            )
                            return
                    except (RuntimeError, AttributeError):
                        self.fetch_thread = None
            except Exception as e:
                logging.debug(f"RefreshController: Error checking fetch thread: {e}")
                self.fetch_thread = None
            self.update_checker.check_for_updates()

            class FetchContext:
                def __init__(self, app_state, mod_service, settings_service) -> None:
                    self.app_state = app_state
                    self.mod_service = mod_service
                    self.settings_service = settings_service

            fetch_context = FetchContext(
                self.app_state, self.mod_service, self.settings_service
            )
            self.fetch_thread = FetchModsThread(
                fetch_context, force_update=True, parent=None
            )
            self.fetch_thread.status.connect(self.feedback_service.update_status)
            finished_kwargs = on_fetch_finished_kwargs or {}
            self.fetch_thread.result.connect(
                lambda success: self._on_fetch_finished(
                    success,
                    localization_callback=localization_callback,
                    **finished_kwargs,
                )
            )
            self.fetch_thread.start()
        except Exception as e:
            error_msg = f"Failed to refresh mods list: {e}"
            logging.error(
                f"RefreshController.refresh_mods_list: {error_msg}", exc_info=True
            )
            self.feedback_service.update_status(
                f"{tr('errors.update_list_failed')}: {e!s}", UI_COLORS["status_error"]
            )

    def _stop_fetch_thread(self):
        if self.fetch_thread:
            fetch_thread = self.fetch_thread
            self.fetch_thread = None
            self._stop_worker_thread(fetch_thread, error_label="fetch thread")
        if self.details_thread:
            details_thread = self.details_thread
            self.details_thread = None
            self._stop_worker_thread(
                details_thread,
                disconnect_signals=[
                    getattr(details_thread, "mod_updated", None),
                    getattr(details_thread, "finished", None),
                    getattr(details_thread, "progress", None),
                ],
                check_running=True,
                error_label="details thread",
            )

    def _on_fetch_finished(
        self,
        success: bool,
        localization_callback=None,
        update_filtered_mods_callback=None,
        update_installed_mods_callback=None,
        update_action_button_callback=None,
        mods_loaded_signal=None,
        fetch_thread=None,
    ):
        if not hasattr(self, "_fetch_finished_in_progress"):
            self._fetch_finished_in_progress = False
        if self._fetch_finished_in_progress:
            logging.debug(
                "RefreshController: _on_fetch_finished already in progress, skipping"
            )
            return
        self._fetch_finished_in_progress = True

        self._post_fetch_worker = _PostFetchWorker(
            self.mod_service, self.app_state, parent=self.app_window
        )

        def _on_post_fetch_done(worker_success):
            try:
                if not self.app_state.mods_loaded:
                    self.app_state.mods_loaded = True
                    if mods_loaded_signal:
                        mods_loaded_signal.emit()
                if update_filtered_mods_callback:
                    try:
                        update_filtered_mods_callback()
                    except Exception as e:
                        logging.error(
                            f"RefreshController: Error in update_filtered_mods_callback: {e}",
                            exc_info=True,
                        )
                if update_installed_mods_callback:
                    update_installed_mods_callback()
                self.game_launch_controller.refresh_mods_in_use()
                if update_action_button_callback:
                    update_action_button_callback()
                if success:
                    self.feedback_service.update_status(
                        tr("status.mod_list_updated"), UI_COLORS["status_success"]
                    )
                else:
                    fallback_msg = (
                        tr("ui.network_fallback_message")
                        if self.app_state.all_mods
                        else tr("ui.network_update_failed")
                    )
                    self.feedback_service.update_status(
                        fallback_msg, UI_COLORS["status_error"]
                    )
                self.used_mods_service.load_used_mods_state()
            except Exception as e:
                error_msg = f"Error processing mod list: {e}"
                logging.error(
                    f"RefreshController._on_fetch_finished: {error_msg}", exc_info=True
                )
                self.feedback_service.update_status(
                    tr("errors.mod_list_processing_error", error=str(e)),
                    UI_COLORS["status_error"],
                )
            finally:
                self._fetch_finished_in_progress = False
                fetch_thread_to_cleanup = (
                    fetch_thread if fetch_thread else self.fetch_thread
                )
                if fetch_thread_to_cleanup:
                    self._cleanup_thread_later(fetch_thread_to_cleanup)
                self._cleanup_thread_later(self._post_fetch_worker)
                self._post_fetch_worker = None

        self._post_fetch_worker.done.connect(_on_post_fetch_done)
        self._post_fetch_worker.start()
