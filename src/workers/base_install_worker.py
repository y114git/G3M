"""Base worker class for mod installation."""
import os
import shutil
import logging
import threading
from typing import Optional, Callable, List
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS, NETWORK_TIMEOUT_HEAD
from services.localization_service import tr
from ui.utils.ui_utils import format_size_mb
logger = logging.getLogger(__name__)


class BaseInstallWorker(QThread):
    """Base class for mod installation worker threads."""
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)
    unrar_needed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._session = None
        self._active_response = None
        self._unrar_event = threading.Event()
        self._unrar_installed = False

    def signal_unrar_installed(self, success: bool):
        self._unrar_installed = success
        self._unrar_event.set()

    def wait_for_unrar_install(self, timeout: float = 120.0) -> bool:
        self._unrar_event.clear()
        self._unrar_installed = False
        self.unrar_needed.emit()
        self._unrar_event.wait(timeout=timeout)
        return self._unrar_installed

    def _safe_close(self, resource, label: str) -> None:
        if resource is None:
            return
        try:
            resource.close()
        except Exception as e:
            logger.debug(f'{self.__class__.__name__}.cancel: Error closing {label}: {e}')

    def cancel(self):
        self._cancelled = True
        try:
            self._safe_close(self._session, 'session')
            self._safe_close(self._active_response, 'response')
        except Exception as e:
            logger.debug(f'{self.__class__.__name__}.cancel: Error during cleanup: {e}')
        finally:
            try:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            except Exception as e:
                logger.debug(f'{self.__class__.__name__}.cancel: Error emitting status: {e}')

    def _cleanup_temp_files(self, archive_path: Optional[str] = None, archive_dir: Optional[str] = None):
        try:
            if archive_path and os.path.exists(archive_path):
                try:
                    os.remove(archive_path)
                except Exception as e:
                    logger.debug(f'{self.__class__.__name__}: Error removing archive file {archive_path}: {e}')
            if archive_dir and os.path.exists(archive_dir):
                try:
                    shutil.rmtree(archive_dir, ignore_errors=True)
                except Exception as e:
                    logger.debug(f'{self.__class__.__name__}: Error removing archive directory {archive_dir}: {e}')
        except Exception as e:
            logger.debug(f'{self.__class__.__name__}: Error during cleanup: {e}')

    def _get_content_length(self, session, url: str) -> int:
        try:
            head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
            return int(head_response.headers.get('content-length', 0))
        except Exception:
            return 0

    def _make_download_progress_callback(self, status_text: str, total_size: int, downloaded_ref: List[int], status_color: str = None) -> Callable[[int], None]:
        if status_color is None:
            status_color = UI_COLORS['status_warning']

        def progress_callback(progress: int):
            if not self._cancelled:
                self.progress.emit(progress)
                if total_size > 0:
                    downloaded_mb = format_size_mb(downloaded_ref[0])
                    total_mb = format_size_mb(total_size)
                    self.status.emit(f'{status_text} ({downloaded_mb} / {total_mb})', status_color)
        return progress_callback
