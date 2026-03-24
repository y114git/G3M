"""Worker thread for downloading files to the Downloads system."""

import contextlib
import logging
import os
import shutil

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


def _cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class DownloadWorker(QThread):
    progress_updated = pyqtSignal(str, int, int, int)
    download_finished = pyqtSignal(str, bool, str, str)

    def __init__(self, record_id: str, url: str, target_path: str, parent=None) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._url = url
        self._target_path = target_path
        self._cancelled = False
        self._active_response = None

    def cancel(self):
        self._cancelled = True
        try:
            if self._active_response:
                self._active_response.close()
        except Exception as e:
            logger.debug(
                f"DownloadWorker.cancel: failed to close active response: {e}",
                exc_info=True,
            )

    def run(self):
        try:
            from config.config import NETWORK_TIMEOUT_HEAD
            from utils.network_utils import download_file, get_session

            session = get_session()
            total_size = 0
            with contextlib.suppress(Exception):
                total_size = int(
                    session.head(
                        self._url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD
                    ).headers.get("content-length", 0)
                )
            downloaded_ref = [0]

            def on_progress(pct):
                if not self._cancelled:
                    self.progress_updated.emit(
                        self._record_id, pct, downloaded_ref[0], total_size
                    )

            def on_response(r):
                self._active_response = r

            os.makedirs(os.path.dirname(self._target_path), exist_ok=True)
            download_file(
                session,
                self._url,
                self._target_path,
                progress_callback=on_progress,
                total_size=total_size,
                downloaded_ref=downloaded_ref,
                cancel_check=lambda: self._cancelled,
                on_response=on_response,
            )
            if self._cancelled:
                _cleanup_file(self._target_path)
                self.download_finished.emit(self._record_id, False, "cancelled", "")
                return
            self.download_finished.emit(self._record_id, True, "", self._target_path)
        except RuntimeError as e:
            _cleanup_file(self._target_path)
            if str(e) == "download_cancelled" or self._cancelled:
                self.download_finished.emit(self._record_id, False, "cancelled", "")
            else:
                logger.error("DownloadWorker: %s", e, exc_info=True)
                self.download_finished.emit(self._record_id, False, str(e), "")
        except Exception as e:
            _cleanup_file(self._target_path)
            logger.error("DownloadWorker: %s", e, exc_info=True)
            self.download_finished.emit(self._record_id, False, str(e), "")


class LocalFileCopyWorker(QThread):
    download_finished = pyqtSignal(str, bool, str, str)
    _CHUNK = 256 * 1024

    def __init__(
        self, record_id: str, source_path: str, target_path: str, parent=None
    ) -> None:
        super().__init__(parent)
        self._record_id = record_id
        self._source_path = source_path
        self._target_path = target_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            os.makedirs(os.path.dirname(self._target_path), exist_ok=True)
            with (
                open(self._source_path, "rb") as src,
                open(self._target_path, "wb") as dst,
            ):
                while True:
                    if self._cancelled:
                        break
                    chunk = src.read(self._CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)
            if self._cancelled:
                _cleanup_file(self._target_path)
                self.download_finished.emit(self._record_id, False, "cancelled", "")
                return
            shutil.copystat(self._source_path, self._target_path)
            self.download_finished.emit(self._record_id, True, "", self._target_path)
        except Exception as e:
            _cleanup_file(self._target_path)
            logger.error("LocalFileCopyWorker: %s", e, exc_info=True)
            self.download_finished.emit(self._record_id, False, str(e), "")
