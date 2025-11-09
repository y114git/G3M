import os
import sys
import platform
import tempfile
import shutil
import threading
import subprocess
import requests
import logging
from utils.network_utils import get_session
from PyQt6.QtCore import QObject, pyqtSignal
from managers.localization_manager import tr
from config.constants import LAUNCHER_VERSION, UI_COLORS, ARCH
from core.app_state import AppState
from ui.common.feedback import FeedbackManager


class UpdateChecker(QObject):
    update_available = pyqtSignal(dict)
    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    update_finished = pyqtSignal()
    update_error = pyqtSignal(str)
    quit_requested = pyqtSignal()

    def __init__(self, app_state: AppState, feedback_manager: FeedbackManager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager

    def check_for_updates(self):
        beta_enabled = self.app_state.local_config.get('beta_updates_enabled', False)
        if beta_enabled:
            self.feedback_manager.update_status(tr('status.beta_updates_enabled'), UI_COLORS['status_warning'])
        try:
            launcher_files_key = 'launcher_beta_files' if beta_enabled else 'launcher_files'
            launcher_files = self.app_state.global_settings.get(launcher_files_key)
            if not isinstance(launcher_files, dict):
                self.feedback_manager.update_status(tr('status.update_info_not_found'), UI_COLORS['status_warning'])
                return
            remote_version = launcher_files.get('version')
            from utils.file_utils import version_sort_key as _vkey
            if not remote_version or _vkey(remote_version) <= _vkey(LAUNCHER_VERSION):
                self.feedback_manager.update_status(tr('status.launcher_version_up_to_date'), UI_COLORS['status_success'])
                return
            platform_key_map = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': f'macos-{ARCH}'}
            current_platform_key = platform_key_map.get(platform.system())
            download_url = launcher_files.get('urls', {}).get(current_platform_key)
            update_message = launcher_files.get('message', tr('dialogs.new_version_available_simple'))
            update_message_ru = launcher_files.get('message_ru')
            update_message_en = launcher_files.get('message_en')
            if not download_url:
                self.feedback_manager.update_status(tr('errors.no_build_for_os', platform=current_platform_key), UI_COLORS['status_warning'])
                return
            update_info = {'version': remote_version, 'url': download_url, 'message': update_message, 'message_ru': update_message_ru, 'message_en': update_message_en}
            logging.info(f'UpdateChecker: Update available - version {remote_version}, emitting update_available signal')
            self.update_available.emit(update_info)
        except requests.RequestException as e:
            self.feedback_manager.update_status(tr('errors.update_check_network_error', error=str(e)), UI_COLORS['status_error'])
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.update_check_general_error', error=str(e)), UI_COLORS['status_error'])

    def perform_update(self, update_info):
        self.status_changed.emit(tr('status.update_available'), UI_COLORS['status_info'])
        threading.Thread(target=self._update_worker, args=(update_info,), daemon=True).start()

    def _update_worker(self, update_info):
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub-update-') as tmp_dir:
                archive_path = os.path.join(tmp_dir, 'update' + os.path.splitext(update_info['url'].split('?')[0])[1])
                self.feedback_manager.update_status(tr('status.downloading_version', version=update_info['version']), UI_COLORS['status_warning'])
                session = get_session()
                response = session.get(update_info['url'], stream=True, timeout=60)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                with open(archive_path, 'wb') as f:
                    downloaded_size = 0
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        downloaded_size += len(data)
                        if total_size > 0:
                            self.progress_updated.emit(int(downloaded_size / total_size * 100))
                self.feedback_manager.update_status(tr('status.unpacking_and_installing'), UI_COLORS['status_warning'])
                system = platform.system()
                extraction_dir = os.path.join(tmp_dir, 'extracted')
                os.makedirs(extraction_dir, exist_ok=True)
                if system != 'Darwin':
                    from utils.file_utils import extract_archive
                    extract_archive(archive_path, extraction_dir, os.path.basename(archive_path))
                if system == 'Windows':
                    new_exe_path = next((os.path.join(root, f) for root, _, files in os.walk(extraction_dir) for f in files if f.lower().endswith('.exe')), None)
                    if not new_exe_path:
                        raise RuntimeError(tr('errors.exe_not_found_in_archive'))
                    import ctypes
                    ctypes.windll.shell32.ShellExecuteW(None, 'runas', new_exe_path, None, None, 1)
                    self.feedback_manager.update_status(tr('status.installer_launched_closing'), UI_COLORS['status_success'])
                    self.quit_requested.emit()
                    return
                current_exe_path = os.path.realpath(sys.executable)
                replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), '..', '..')) if system == 'Darwin' else current_exe_path
                backup_path = f'{replace_target}.old'
                if system == 'Darwin':
                    if archive_path.lower().endswith('.zip'):
                        subprocess.run(['/usr/bin/ditto', '-x', '-k', archive_path, extraction_dir], check=True)
                    new_content_path = next((os.path.join(extraction_dir, d) for d in os.listdir(extraction_dir) if d.endswith('.app')), None)
                    if new_content_path is None:
                        raise RuntimeError(tr('errors.app_not_found_after_unpack'))
                    from pathlib import Path
                    from utils.file_utils import fix_macos_python_symlink
                    fix_macos_python_symlink(Path(new_content_path))
                else:
                    new_content_path = next((os.path.join(root, file) for root, _, files in os.walk(extraction_dir) for file in files if os.path.isfile(os.path.join(root, file)) and os.access(os.path.join(root, file), os.X_OK)), None)
                    if new_content_path is None or not os.path.exists(new_content_path):
                        raise RuntimeError(tr('errors.executable_not_found_after_unpack'))
                    os.chmod(new_content_path, 493)
                if os.path.exists(backup_path):
                    shutil.rmtree(backup_path, ignore_errors=True)
                os.rename(replace_target, backup_path)
                if system == 'Darwin':
                    shutil.copytree(new_content_path, replace_target)
                else:
                    shutil.move(new_content_path, replace_target)
                self.feedback_manager.update_status(tr('status.restarting'), UI_COLORS['status_success'])
                os.execv(current_exe_path, sys.argv)
        except PermissionError:
            self.feedback_manager.update_status(tr('errors.update_permission_error'), UI_COLORS['status_error'])
            self.update_error.emit(tr('dialogs.update_permission_error_details'))
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.update_failed', error=str(e)), UI_COLORS['status_error'])
            self.update_error.emit(tr('errors.update_could_not_complete', error=str(e)))
        finally:
            self.update_finished.emit()
