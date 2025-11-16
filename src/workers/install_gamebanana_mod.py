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
from utils.file_utils import check_filename_is_deltamod_info
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
                logger.warning(f'Mod {mod_id} does not have a compatible file with mod_config.json or deltamod info file')
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
            file_format = compatible_file.get('file_format', 'deltamod')
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
                    has_mod_config = False
                    has_deltamod_info = False
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file == 'mod_config.json':
                                has_mod_config = True
                            elif check_filename_is_deltamod_info(file):
                                has_deltamod_info = True
                        if has_mod_config or has_deltamod_info:
                            break
                    if not has_mod_config and (not has_deltamod_info):
                        mod_url = self.mod_info.external_url or f'https://gamebanana.com/mods/{mod_id}'
                        error_msg = tr('errors.archive_missing_modinfo')
                        logger.error(f'Archive {archive_path} does not contain mod_config.json or deltamod info file despite API check')
                        self.status.emit(error_msg, UI_COLORS['status_error'])
                        self.finished.emit(False, error_msg)
                        return
                    if has_mod_config:
                        file_format = 'deltahub'
                    elif has_deltamod_info:
                        file_format = 'deltamod'
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
            if file_format == 'deltahub':
                self.status.emit(tr('status.installing_mod'), UI_COLORS['status_info'])
                try:
                    mod_dir = self._install_deltahub_mod(archive_path, mod_id)
                    self._cleanup_temp_files(archive_path, archive_dir)
                    if not mod_dir:
                        raise ValueError(tr('errors.gamebanana_installation_failed'))
                    mod_name = os.path.basename(mod_dir)
                    self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                except Exception as e:
                    self._cleanup_temp_files(archive_path, archive_dir)
                    logger.error(f'Error installing DELTAHUB mod from GameBanana: {e}', exc_info=True)
                    raise ValueError(tr('errors.gamebanana_installation_failed'))
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

    def _install_deltahub_mod(self, archive_path: str, mod_id: int) -> Optional[str]:
        import tempfile
        import json
        from utils.file_utils import _extract_archive_raw, remove_archive_extension, sanitize_filename
        from managers.settings_manager import SettingsManager
        fname_lower = os.path.basename(archive_path).lower()
        with tempfile.TemporaryDirectory(prefix='gb_install_dh_') as temp_dir:
            try:
                _extract_archive_raw(archive_path, fname_lower, temp_dir)
            except Exception as e:
                logger.error(f'Error extracting DELTAHUB mod archive: {e}')
                raise
            mod_config_path = None
            content_root = temp_dir
            for root, dirs, files in os.walk(temp_dir):
                if 'mod_config.json' in files:
                    mod_config_path = os.path.join(root, 'mod_config.json')
                    if root != temp_dir:
                        content_root = root
                    break
            if not mod_config_path:
                logger.error('mod_config.json not found in DELTAHUB mod archive')
                raise ValueError('mod_config.json not found in archive')
            try:
                with open(mod_config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                logger.error(f'Error reading mod_config.json: {e}')
                raise
            is_redirect = False
            files_in_archive = []
            for root, dirs, files in os.walk(content_root):
                for file in files:
                    if file != 'mod_config.json':
                        files_in_archive.append(file)
            if len(files_in_archive) == 0:
                external_url = config_data.get('external_url') or config_data.get('download_url')
                if external_url:
                    logger.info(f'DELTAHUB mod {mod_id} appears to be a redirect to {external_url}')
                    is_redirect = True
                    self.status.emit(tr('status.downloading_from_external'), UI_COLORS['status_info'])
                    try:
                        redirect_archive_path = self._download_file(external_url, 'redirect_mod.zip')
                        return self._install_deltahub_mod(redirect_archive_path, mod_id)
                    except Exception as e:
                        logger.error(f'Error downloading redirect mod: {e}')
                        raise ValueError(f'Failed to download redirect mod: {e}')
            mod_key = config_data.get('mod_key')
            if not mod_key:
                mod_key = f'gb_{mod_id}'
                config_data['mod_key'] = mod_key
            mod_name = config_data.get('name', f'mod_{mod_id}')
            folder_name = sanitize_filename(mod_name)
            target_mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name)
            counter = 1
            while os.path.exists(target_mod_dir):
                folder_name_with_counter = f'{folder_name}_{counter}'
                target_mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name_with_counter)
                counter += 1
            os.makedirs(target_mod_dir, exist_ok=True)
            for item in os.listdir(content_root):
                src_path = os.path.join(content_root, item)
                dst_path = os.path.join(target_mod_dir, item)
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)
            config_data['is_gamebanana_mod'] = True
            config_data['is_local_mod'] = False
            config_data['gamebanana_mod_id'] = str(mod_id)
            if self.mod_info.gamebanana_mod_type:
                config_data['gamebanana_mod_type'] = self.mod_info.gamebanana_mod_type
            if self.mod_info.gamebanana_last_update_timestamp:
                config_data['gamebanana_last_update_timestamp'] = self.mod_info.gamebanana_last_update_timestamp
            if not config_data.get('external_url') and self.mod_info.external_url:
                config_data['external_url'] = self.mod_info.external_url
            expected_mod_key = f'gb_{mod_id}'
            config_data['mod_key'] = expected_mod_key
            target_config_path = os.path.join(target_mod_dir, 'mod_config.json')
            try:
                with open(target_config_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=4, ensure_ascii=False)
                logger.info(f'Installed DELTAHUB mod: {target_mod_dir}, mod_key={expected_mod_key}')
            except Exception as e:
                logger.error(f'Error writing mod_config.json: {e}')
                raise
            return target_mod_dir

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
        download_success = False
        try:
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
                download_success = True
                return archive_path
            except RuntimeError as e:
                if str(e) == 'download_cancelled' or self._cancelled:
                    self._cleanup_temp_files(archive_path, temp_dir)
                    raise
                raise
        except Exception as e:
            if not download_success:
                try:
                    self._cleanup_temp_files(archive_path, temp_dir)
                except Exception:
                    pass
            raise
