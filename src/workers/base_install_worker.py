import os
import shutil
import tempfile
import logging
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS
from managers.localization_manager import tr
from utils.network_utils import get_session, download_file
from utils.ui_utils import format_size_mb
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
