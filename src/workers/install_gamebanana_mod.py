import os
import tempfile
import shutil
import logging
from typing import Optional, Dict
from PyQt6.QtCore import QThread, pyqtSignal
from config.constants import UI_COLORS, NETWORK_TIMEOUT_HEAD
from managers.localization_manager import tr
from utils.gamebanana_api import GameBananaAPI
from utils.gamebanana_converter import GameBananaConverter
from utils.network_utils import get_session, download_file
import requests
logger = logging.getLogger(__name__)


class InstallGameBananaModThread(QThread):
    status = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    file_selection_required = pyqtSignal(list, str)

    def __init__(self, main_window, mod_info, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.mod_info = mod_info
        self.api = GameBananaAPI()
        self._cancelled = False
        self._session = None
        self._active_response = None
        self._selected_file_index = None
        self._file_selection_event = None

    def cancel(self):
        self._cancelled = True
        try:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
            if self._active_response is not None:
                try:
                    self._active_response.close()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                self.status.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            except Exception:
                pass

    def set_selected_file(self, file_index: int):
        self._selected_file_index = file_index
        if self._file_selection_event:
            self._file_selection_event.set()

    def run(self):
        archive_path = None
        archive_dir = None
        try:
            mod_id = self.mod_info.gamebanana_mod_id
            if not mod_id:
                raise ValueError(tr('errors.invalid_gamebanana_mod_id'))
            if self._cancelled:
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            self.status.emit(tr('status.checking_mod_compatibility'), UI_COLORS['status_info'])
            compatible_file = self.api.find_compatible_file(int(mod_id))
            if not compatible_file:
                mod_url = self.mod_info.external_url or f'https://gamebanana.com/mods/{mod_id}'
                error_msg = f'MOD_NOT_COMPATIBLE:{mod_url}'
                logger.warning(f'Mod {mod_id} does not have a compatible file with _deltamodInfo.json')
                self.status.emit(tr('status.installation_failed'), UI_COLORS['status_error'])
                self.finished.emit(False, error_msg)
                return
            if self._cancelled:
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            download_url = compatible_file.get('_sDownloadUrl')
            if not download_url:
                raise ValueError(tr('errors.no_download_url'))
            self.status.emit(tr('status.downloading_mod'), UI_COLORS['status_warning'])
            file_name = compatible_file.get('_sFile', compatible_file.get('_sName', 'mod.zip'))
            try:
                archive_path = self._download_file(download_url, file_name)
                archive_dir = os.path.dirname(archive_path) if archive_path else None
            except RuntimeError as e:
                if str(e) == 'download_cancelled' or self._cancelled:
                    self._cleanup_temp_files(archive_path, archive_dir)
                    self.finished.emit(False, tr('status.operation_cancelled'))
                    return
                else:
                    raise
            if self._cancelled:
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            try:
                import tempfile
                from utils.file_utils import _extract_archive_raw
                fname_lower = os.path.basename(archive_path).lower()
                with tempfile.TemporaryDirectory(prefix='gb_check_') as temp_dir:
                    try:
                        _extract_archive_raw(archive_path, fname_lower, temp_dir)
                    except Exception as e:
                        error_msg = tr('errors.invalid_archive_format')
                        logger.error(f'Invalid archive format: {archive_path}: {e}')
                        self.status.emit(error_msg, UI_COLORS['status_error'])
                        self.finished.emit(False, error_msg)
                        return
                    has_deltamod_info = False
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file.lower().endswith('_deltamodinfo.json') or file.endswith('_deltamodInfo.json'):
                                has_deltamod_info = True
                                break
                        if has_deltamod_info:
                            break
                    if not has_deltamod_info:
                        mod_url = self.mod_info.external_url or f'https://gamebanana.com/mods/{mod_id}'
                        error_msg = tr('errors.archive_missing_deltamodinfo')
                        logger.error(f'Archive {archive_path} does not contain _deltamodInfo.json despite API check')
                        self.status.emit(error_msg, UI_COLORS['status_error'])
                        self.finished.emit(False, error_msg)
                        return
            except Exception as e:
                error_msg = tr('errors.invalid_archive_format')
                logger.error(f'Error checking archive: {archive_path}: {e}', exc_info=True)
                self.status.emit(error_msg, UI_COLORS['status_error'])
                self.finished.emit(False, error_msg)
                return
            if self._cancelled:
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            self.status.emit(tr('status.converting_mod'), UI_COLORS['status_info'])
            gb_metadata = {'mod_id': mod_id, 'mod_type': self.mod_info.gamebanana_mod_type or 'Mod', 'last_update_timestamp': self.mod_info.gamebanana_last_update_timestamp, 'profile_url': self.mod_info.external_url}
            converter = GameBananaConverter(archive_path, self.main_window.app_state.mods_dir, gb_metadata)
            mod_dir = converter.convert()
            self._cleanup_temp_files(archive_path, archive_dir)
            if not mod_dir:
                raise ValueError(tr('errors.gamebanana_conversion_failed'))
            mod_name = os.path.basename(mod_dir)
            self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
        except RuntimeError as e:
            if str(e) == 'download_cancelled' or self._cancelled:
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, tr('status.operation_cancelled'))
            else:
                logger.error(f'Error installing GameBanana mod (RuntimeError): {e}', exc_info=True)
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, str(e))
        except Exception as e:
            logger.error(f'Error installing GameBanana mod: {e}', exc_info=True)
            self._cleanup_temp_files(archive_path, archive_dir)
            self.finished.emit(False, str(e))

    def _check_file_compatibility(self, download_url: str, file_info: Dict) -> Optional[Dict]:
        try:
            filename = file_info.get('_sFile', 'check.zip')
            if filename.lower().endswith(('.zip', '.7z', '.rar')):
                return {'download_url': download_url, 'filename': filename, 'file_info': file_info}
        except Exception as e:
            logger.debug(f'Error checking file compatibility: {e}')
        return None

    def _cleanup_temp_files(self, archive_path: Optional[str] = None, archive_dir: Optional[str] = None):
        try:
            if archive_path and os.path.exists(archive_path):
                try:
                    os.remove(archive_path)
                except Exception:
                    pass
            if archive_dir and os.path.exists(archive_dir):
                try:
                    shutil.rmtree(archive_dir, ignore_errors=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _download_file(self, url: str, filename: str) -> str:
        temp_dir = tempfile.mkdtemp(prefix='gb_download_')
        archive_path = os.path.join(temp_dir, filename)
        session = get_session()
        self._session = session
        downloaded_ref = [0]
        total_size = 0
        try:
            head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
            total_size = int(head_response.headers.get('content-length', 0))
        except (requests.RequestException, ValueError):
            pass

        def progress_callback(progress):
            if not self._cancelled:
                self.progress.emit(progress)

        def on_response(r):
            self._active_response = r
        try:
            download_file(session, url, archive_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=lambda: self._cancelled, on_response=on_response)
            if not self._cancelled:
                self.progress.emit(100)
            return archive_path
        except RuntimeError as e:
            if str(e) == 'download_cancelled' or self._cancelled:
                self._cleanup_temp_files(archive_path, temp_dir)
                raise
            raise
