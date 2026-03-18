"""Base worker class for mod installation."""
import os
import shutil
import logging
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._session = None
        self._active_response = None

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

    def _download_archive_base(self, url: str, target_path: str, status_msg: str) -> bool:
        from utils.file_utils import download_file_with_progress
        try:
            self.status.emit(status_msg, UI_COLORS['status_warning'])
            from utils.network_utils import get_session
            session = get_session()
            self._session = session
            downloaded_ref = [0]
            total_size = self._get_content_length(session, url)

            def progress_callback(progress):
                if not self._cancelled:
                    self.progress.emit(progress)
                    if total_size > 0:
                        downloaded_mb = format_size_mb(downloaded_ref[0])
                        total_mb = format_size_mb(total_size)
                        self.status.emit(f"{status_msg} ({downloaded_mb} / {total_mb})", UI_COLORS['status_warning'])

            def on_response(r):
                self._active_response = r

            success = download_file_with_progress(
                url, target_path,
                progress_callback=progress_callback,
                session=session,
                cancel_check=lambda: self._cancelled,
                on_response=on_response,
                downloaded_ref=downloaded_ref
            )
            if not success:
                raise RuntimeError('download_failed')
            self.progress.emit(100)
            return True
        except RuntimeError as e:
            if str(e) == 'download_cancelled' or self._cancelled:
                return False
            raise
        except Exception as e:
            logger.error(f'{self.__class__.__name__}: Download failed: {e}', exc_info=True)
            return False

    def _create_unique_mod_dir(self, mods_dir: str, mod_name: str) -> str:
        from utils.file_utils import sanitize_filename
        folder_name = sanitize_filename(mod_name)
        target_mod_dir = os.path.join(mods_dir, folder_name)
        counter = 1
        while os.path.exists(target_mod_dir):
            target_mod_dir = os.path.join(mods_dir, f'{folder_name}_{counter}')
            counter += 1
        os.makedirs(target_mod_dir, exist_ok=True)
        return target_mod_dir

    def _copy_directory_contents(self, src_dir: str, dst_dir: str):
        for item in os.listdir(src_dir):
            src_path = os.path.join(src_dir, item)
            dst_path = os.path.join(dst_dir, item)
            if os.path.isdir(src_path):
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

    def _merge_tags(self, config_data: dict, tags: list):
        existing_tags = config_data.get('tags', [])
        if not isinstance(existing_tags, list):
            existing_tags = [existing_tags] if existing_tags else []
        for tag in tags:
            if tag and tag not in existing_tags:
                existing_tags.append(tag)
        config_data['tags'] = existing_tags
