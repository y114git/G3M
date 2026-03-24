"""Full game installation worker.

This module provides a worker thread for downloading and installing the full game.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from config.config import NETWORK_TIMEOUT_MEDIUM, UI_COLORS
from services.localization_service import tr
from ui.utils.ui_utils import format_size_mb
from utils.network_utils import get_session


class FullInstallThread(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, main_window, target_dir: str) -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self.target_dir = target_dir
        self._cancelled = False
        self._session = None
        self._active_response = None

    def cancel(self):
        self._cancelled = True
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception as e:
                    logging.warning(
                        f"FullInstallThread.cancel: session close error: {e}",
                        exc_info=True,
                    )
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logging.warning(
                        f"FullInstallThread.cancel: response close error: {e}",
                        exc_info=True,
                    )
        finally:
            self.status.emit(
                tr("status.operation_cancelled"), UI_COLORS["status_error"]
            )

    def run(self):
        if self.main_window.app_state.game_mode.game_id == "sugaryspire":
            full_install_url = self.main_window.app_state.global_settings.get(
                "full_spire_install_url"
            )
        elif self.main_window.app_state.game_mode.game_id == "undertaleyellow":
            full_install_url = self.main_window.app_state.global_settings.get(
                "full_yellow_install_url"
            )
        else:
            full_install_url = self.main_window.app_state.global_settings.get(
                "full_install_url"
            )
        if not full_install_url:
            self.status.emit(tr("errors.files_not_found"), UI_COLORS["status_error"])
            self.finished.emit(False, self.target_dir)
            return
        self.status.emit(
            tr("status.installing_game_files"), UI_COLORS["status_warning"]
        )
        try:
            session = get_session()
            self._session = session
            resp = session.head(
                full_install_url, allow_redirects=True, timeout=NETWORK_TIMEOUT_MEDIUM
            )
            total_size = int(resp.headers.get("content-length", 0))
            downloaded_ref = [0]
            from utils.file_utils import download_and_extract_archive

            def progress_callback(progress):
                self.progress.emit(progress)
                if total_size > 0:
                    downloaded_mb = format_size_mb(downloaded_ref[0])
                    total_mb = format_size_mb(total_size)
                    self.status.emit(
                        f"{tr('status.installing_game_files')} ({downloaded_mb} / {total_mb})",
                        UI_COLORS["status_warning"],
                    )

            def on_response(r):
                self._active_response = r

            download_and_extract_archive(
                full_install_url,
                self.target_dir,
                progress_callback,
                total_size,
                downloaded_ref,
                session,
                is_game_installation=True,
                cancel_check=lambda: self._cancelled,
                on_response=on_response,
            )
            if self._cancelled:
                self.status.emit(
                    tr("status.operation_cancelled"), UI_COLORS["status_error"]
                )
                self.finished.emit(False, self.target_dir)
                return
            self.status.emit(
                tr("status.demo_installation_complete"), UI_COLORS["status_success"]
            )
            self.finished.emit(True, self.target_dir)
        except Exception as e:
            logging.error(
                f"FullInstallThread.run: installation error: {e}", exc_info=True
            )
            self.status.emit(
                tr("errors.full_installation_error").format(str(e)),
                UI_COLORS["status_error"],
            )
            self.finished.emit(False, self.target_dir)
        finally:
            self._session = None
            self._active_response = None
