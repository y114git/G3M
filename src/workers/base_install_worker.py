import os
import shutil
import tempfile
import logging
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS
from managers.localization_manager import tr
from utils.network_utils import get_session, download_file
from utils.format_utils import format_size_mb
logger = logging.getLogger(__name__)


class BaseInstallWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
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
                    logger.debug(f'{self.__class__.__name__}.cancel: Error closing session: {e}')
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception as e:
                    logger.debug(f'{self.__class__.__name__}.cancel: Error closing response: {e}')
        except Exception as e:
            logger.debug(f'{self.__class__.__name__}.cancel: Error during cleanup: {e}')
        finally:
            try:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            except Exception as e:
                logger.debug(f'{self.__class__.__name__}.cancel: Error emitting status: {e}')

    def _download_file(self, url: str, filename: str, temp_dir_prefix: str = 'download_') -> Optional[str]:
        temp_dir = tempfile.mkdtemp(prefix=temp_dir_prefix)
        archive_path = os.path.join(temp_dir, filename)
        download_success = False
        try:
            from utils.file_utils import download_file_with_progress
            session = get_session()
            self._session = session
            downloaded_ref = [0]
            total_size_for_status = 0
            try:
                head_response = session.head(url, allow_redirects=True, timeout=10)
                total_size_for_status = int(head_response.headers.get('content-length', 0))
            except Exception:
                pass

            def progress_callback(progress):
                if not self._cancelled:
                    self.progress.emit(progress)
                    if total_size_for_status > 0 and hasattr(self, 'status'):
                        downloaded_mb = format_size_mb(downloaded_ref[0])
                        total_mb = format_size_mb(total_size_for_status)
                        current_status = getattr(self, '_current_status', tr('status.downloading_mod'))
                        self.status.emit(f'{current_status} ({downloaded_mb} / {total_mb})', UI_COLORS['status_warning'])

            def on_response(r):
                self._active_response = r
            try:
                success = download_file_with_progress(url, archive_path, progress_callback=progress_callback, session=session, cancel_check=lambda: self._cancelled, on_response=on_response, downloaded_ref=downloaded_ref)
                if not success:
                    raise RuntimeError('download_failed')
                download_success = True
                return archive_path
            except RuntimeError as e:
                if str(e) == 'download_cancelled' or self._cancelled:
                    self._cleanup_temp_files(archive_path, temp_dir)
                    raise RuntimeError('download_cancelled')
                raise
        except Exception:
            if not download_success:
                try:
                    self._cleanup_temp_files(archive_path, temp_dir)
                except Exception as e:
                    logger.debug(f'{self.__class__.__name__}: Error during cleanup after download failure: {e}')
            raise

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
