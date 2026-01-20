import os
import tempfile
import shutil
import logging
from typing import Dict
from PyQt6.QtCore import pyqtSignal
from config.constants import UI_COLORS, NETWORK_TIMEOUT_HEAD
from managers.localization_manager import tr
from utils.file_utils import download_file_with_progress
from utils.archive_utils import extract_archive
from utils.network_utils import get_session
from workers.base_install_worker import BaseInstallWorker
logger = logging.getLogger(__name__)


class PrepareGameBananaManualInstallWorker(BaseInstallWorker):
    finished_with_result = pyqtSignal(bool, object)

    def __init__(self, mod, selected_file: Dict, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.selected_file = selected_file
        self._session = None
        self._active_response = None

    def run(self):
        temp_dir = None
        try:
            mod_key = getattr(self.mod, 'key', None) or getattr(self.mod, 'mod_key', None)
            mod_id_str = mod_key.replace('gb_', '', 1) if mod_key and mod_key.startswith('gb_') else None
            if not mod_id_str:
                raise ValueError(tr('errors.invalid_gamebanana_mod_id'))
            mod_id = int(mod_id_str)
            download_url = self.selected_file.get('download_url') or self.selected_file.get('_sDownloadUrl')
            if not download_url:
                raise ValueError(tr('errors.no_download_url'))
            file_name = self.selected_file.get('name') or self.selected_file.get('_sFile') or self.selected_file.get('_sName') or f'mod_{mod_id}.zip'
            temp_dir = tempfile.mkdtemp(prefix='gb_manual_install_')
            archive_path = os.path.join(temp_dir, file_name)
            self.status.emit(tr('status.downloading_mod'), UI_COLORS['status_warning'])
            session = get_session()
            self._session = session
            downloaded_ref = [0]
            total_size = 0
            try:
                head_response = session.head(download_url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
                total_size = int(head_response.headers.get('content-length', 0))
            except Exception:
                pass

            def progress_callback(progress):
                if not self._cancelled:
                    self.progress.emit(progress)
                    if total_size > 0:
                        from utils.ui_utils import format_size_mb
                        downloaded_mb = format_size_mb(downloaded_ref[0])
                        total_mb = format_size_mb(total_size)
                        self.status.emit(f"{tr('status.downloading_mod')} ({downloaded_mb} / {total_mb})", UI_COLORS['status_warning'])

            def on_response(r):
                self._active_response = r
            success = download_file_with_progress(download_url, archive_path, progress_callback=progress_callback, session=session, cancel_check=lambda: self._cancelled, on_response=on_response, downloaded_ref=downloaded_ref)
            if not success:
                if self._cancelled:
                    raise RuntimeError('download_cancelled')
                raise RuntimeError('download_failed')
            if self._cancelled:
                raise RuntimeError('download_cancelled')
            self.status.emit(tr('status.extracting_mod'), UI_COLORS['status_info'])
            extract_dir = os.path.join(temp_dir, 'extracted')
            os.makedirs(extract_dir, exist_ok=True)
            from utils.archive_utils import extract_with_unrar_retry
            extract_with_unrar_retry(archive_path, extract_dir, extract_func=extract_archive)
            content_path = extract_dir
            contents = os.listdir(extract_dir)
            if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
                content_path = os.path.join(extract_dir, contents[0])
            gb_metadata = {'mod_id': mod_id, 'name': getattr(self.mod, 'name', 'Unknown Mod'), 'icon_url': getattr(self.mod, 'icon_url', None), 'external_url': getattr(self.mod, 'external_url', None), 'tags': getattr(self.mod, 'tags', []) if hasattr(self.mod, 'tags') and self.mod.tags else [], 'category': getattr(self.mod, 'gamebanana_category', None) if hasattr(self.mod, 'gamebanana_category') else None, 'author': getattr(self.mod, 'author', 'Unknown'), 'tagline': getattr(self.mod, 'tagline', ''), 'game': getattr(self.mod, 'game', 'deltarune'), 'version': getattr(self.mod, 'version', '1.0.0')}
            self.finished_with_result.emit(True, (content_path, gb_metadata, temp_dir))
        except RuntimeError as e:
            if str(e) == 'download_cancelled' or self._cancelled:
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass
                self.finished_with_result.emit(False, tr('status.operation_cancelled'))
                return
            else:
                raise
        except Exception as e:
            logger.error(f'PrepareGameBananaManualInstallWorker: Failed to prepare files: {e}', exc_info=True)
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
            self.finished_with_result.emit(False, str(e))

    def cancel(self):
        self._cancelled = True
        self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
        try:
            self._safe_close(self._session, 'session')
            self._safe_close(self._active_response, 'response')
        except Exception as e:
            logger.warning(f'PrepareGameBananaManualInstallWorker.cancel: cleanup failed: {e}', exc_info=True)
