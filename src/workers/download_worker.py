"""Worker thread for downloading files to the Downloads system."""

import contextlib
import hashlib
import logging
import os
import re
import shutil

from PyQt6.QtCore import pyqtSignal

from ui.utils.thread_lifetime import ManagedQThread
from ui.utils.thread_lifetime import safe_emit as _safe_emit
from utils.mod.archive import archive_format, archive_suffix_from_content
from utils.process_utils import format_filesystem_error, format_network_error

logger = logging.getLogger(__name__)

CHECKSUM_WARNING = (
    "The file does not match the checksum published on GameBanana. "
    "It may have been replaced since the listing was loaded, or damaged during download."
)


def _cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as error:
        logger.debug("Best-effort operation failed: %s", error, exc_info=True)


class DownloadWorker(ManagedQThread):
    progress_updated = pyqtSignal(str, int, int, int)
    download_finished = pyqtSignal(str, bool, str, str)

    def __init__(
        self,
        record_id: str,
        url: str,
        target_path: str,
        *,
        expected_md5: str | None = None,
        allowed_hosts: frozenset[str] | None = None,
        md5_refresh=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._md5_refresh = md5_refresh
        self._record_id = record_id
        self._url = url
        self._target_path = target_path
        self._expected_md5 = expected_md5
        self._allowed_hosts = allowed_hosts
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

    def _name_archive_by_content(self) -> None:
        """A 1-click link such as gamebanana.com/mmdl/123 has no file extension; without one the archive is never opened."""
        if archive_format(self._target_path) is not None:
            return
        from utils.file_utils import safe_move

        if suffix := archive_suffix_from_content(self._target_path):
            renamed = self._target_path + suffix
            if safe_move(self._target_path, renamed):
                self._target_path = renamed
            else:
                logger.warning("DownloadWorker: could not add %s to %s", suffix, self._target_path)

    def _checksum_warning(self) -> str:
        """Describe a verified checksum mismatch, or return an empty string."""
        expected = str(self._expected_md5 or "").strip().casefold()
        if not re.fullmatch(r"[0-9a-f]{32}", expected):
            return ""
        actual = _file_md5(self._target_path, cancel_check=lambda: self._cancelled)
        if actual == expected:
            return ""
        if self._md5_refresh and actual == self._md5_refresh():
            return ""
        return CHECKSUM_WARNING

    def run(self):
        try:
            from utils.network_utils import download_file, get_session

            session = get_session()
            total_size = 0
            downloaded_ref = [0]

            def on_progress(pct):
                if not self._cancelled:
                    _safe_emit(
                        "DownloadWorker",
                        self.progress_updated,
                        self._record_id,
                        pct,
                        downloaded_ref[0],
                        total_size,
                    )

            def on_response(r):
                nonlocal total_size
                self._active_response = r
                if not total_size:
                    with contextlib.suppress(TypeError, ValueError):
                        total_size = int(r.headers.get("content-length", 0))

            os.makedirs(os.path.dirname(self._target_path), exist_ok=True)
            _cleanup_file(self._target_path)
            download_file(
                session,
                self._url,
                self._target_path,
                progress_callback=on_progress,
                total_size=total_size,
                downloaded_ref=downloaded_ref,
                cancel_check=lambda: self._cancelled,
                on_response=on_response,
                allowed_hosts=self._allowed_hosts,
            )
            if self._cancelled:
                _cleanup_file(self._target_path)
                _safe_emit(
                    "DownloadWorker",
                    self.download_finished,
                    self._record_id,
                    False,
                    "cancelled",
                    "",
                )
                return
            self._name_archive_by_content()
            warning = self._checksum_warning()
            if self._cancelled:
                raise RuntimeError("download_cancelled")
            _safe_emit(
                "DownloadWorker",
                self.download_finished,
                self._record_id,
                True,
                warning,
                self._target_path,
            )
        except RuntimeError as e:
            _cleanup_file(self._target_path)
            if str(e) == "download_cancelled" or self._cancelled:
                _safe_emit(
                    "DownloadWorker",
                    self.download_finished,
                    self._record_id,
                    False,
                    "cancelled",
                    "",
                )
            else:
                logger.error("DownloadWorker: %s", e, exc_info=True)
                _safe_emit(
                    "DownloadWorker",
                    self.download_finished,
                    self._record_id,
                    False,
                    format_network_error(e, url=self._url),
                    "",
                )
        except Exception as e:
            _cleanup_file(self._target_path)
            logger.error("DownloadWorker: %s", e, exc_info=True)
            _safe_emit(
                "DownloadWorker",
                self.download_finished,
                self._record_id,
                False,
                format_network_error(e, url=self._url),
                "",
            )


def _file_md5(path: str, *, cancel_check=None) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            if cancel_check and cancel_check():
                raise RuntimeError("download_cancelled")
            digest.update(chunk)
    return digest.hexdigest()


class LocalFileCopyWorker(ManagedQThread):
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
                _safe_emit(
                    "LocalFileCopyWorker",
                    self.download_finished,
                    self._record_id,
                    False,
                    "cancelled",
                    "",
                )
                return
            shutil.copystat(self._source_path, self._target_path)
            _safe_emit(
                "LocalFileCopyWorker",
                self.download_finished,
                self._record_id,
                True,
                "",
                self._target_path,
            )
        except Exception as e:
            _cleanup_file(self._target_path)
            logger.error("LocalFileCopyWorker: %s", e, exc_info=True)
            _safe_emit(
                "LocalFileCopyWorker",
                self.download_finished,
                self._record_id,
                False,
                format_filesystem_error(e, path=self._source_path),
                "",
            )
