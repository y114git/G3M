import os
import sys
import platform
import tempfile
import shutil
import threading
import subprocess
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
        except Exception as e:
            import requests
            if isinstance(e, requests.RequestException):
                self.feedback_manager.update_status(tr('errors.update_check_network_error', error=str(e)), UI_COLORS['status_error'])
            else:
                self.feedback_manager.update_status(tr('errors.update_check_general_error', error=str(e)), UI_COLORS['status_error'])

    def perform_update(self, update_info):
        self.status_changed.emit(tr('status.update_available'), UI_COLORS['status_info'])
        threading.Thread(target=self._update_worker, args=(update_info,), daemon=True).start()

    def _update_worker(self, update_info):
        installer_launched = False
        try:
            logging.info(f"[UPDATE] Starting update process for version {update_info['version']}")
            with tempfile.TemporaryDirectory(prefix='deltahub-update-') as tmp_dir:
                archive_path = os.path.join(tmp_dir, 'update' + os.path.splitext(update_info['url'].split('?')[0])[1])
                logging.info(f"[UPDATE] Downloading update from {update_info['url']} to {archive_path}")
                self.feedback_manager.update_status(tr('status.downloading_version', version=update_info['version']), UI_COLORS['status_warning'])
                session = get_session()
                response = session.get(update_info['url'], stream=True, timeout=60)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                logging.info(f'[UPDATE] Update archive size: {total_size} bytes')
                with open(archive_path, 'wb') as f:
                    downloaded_size = 0
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        downloaded_size += len(data)
                        if total_size > 0:
                            self.progress_updated.emit(int(downloaded_size / total_size * 100))
                logging.info(f'[UPDATE] Successfully downloaded update archive ({downloaded_size} bytes)')
                self.feedback_manager.update_status(tr('status.unpacking_and_installing'), UI_COLORS['status_warning'])
                system = platform.system()
                extraction_dir = os.path.join(tmp_dir, 'extracted')
                os.makedirs(extraction_dir, exist_ok=True)
                logging.info(f'[UPDATE] Extracting archive to {extraction_dir} (platform: {system})')
                if system != 'Darwin':
                    from utils.file_utils import extract_archive
                    extract_archive(archive_path, extraction_dir, os.path.basename(archive_path))
                if system == 'Windows':
                    new_exe_path = next((os.path.join(root, f) for root, _, files in os.walk(extraction_dir) for f in files if f.lower().endswith('.exe')), None)
                    if not new_exe_path:
                        logging.error('[UPDATE] Executable not found in extracted archive')
                        raise RuntimeError(tr('errors.exe_not_found_in_archive'))
                    logging.info(f'[UPDATE] Found installer executable: {new_exe_path}')
                    logging.info('[UPDATE] Launching installer with elevated privileges (runas)')
                    import ctypes
                    import time
                    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', new_exe_path, None, None, 1)
                    if result > 32:
                        time.sleep(0.5)
                        installer_name = os.path.basename(new_exe_path)
                        try:
                            import psutil
                            processes = [p for p in psutil.process_iter(['pid', 'name']) if p.info['name'].lower() == installer_name.lower()]
                            if processes:
                                logging.info(f"[UPDATE] Installer process confirmed running (PID: {processes[0].info['pid']})")
                            else:
                                logging.warning('[UPDATE] Installer process not found immediately, but launch was successful')
                        except ImportError:
                            logging.info('[UPDATE] psutil not available, skipping process verification')
                        except Exception as e:
                            logging.warning(f'[UPDATE] Could not verify installer process: {e}')
                        logging.info(f'[UPDATE] Installer launched successfully (result code: {result}), closing launcher')
                        self.feedback_manager.update_status(tr('status.installer_launched_closing'), UI_COLORS['status_success'])
                        installer_launched = True
                        self.quit_requested.emit()
                        return
                    else:
                        logging.error(f'[UPDATE] Failed to launch installer (result code: {result})')
                        raise RuntimeError(tr('errors.installer_launch_failed', code=result))
                current_exe_path = os.path.realpath(sys.executable)
                replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), '..', '..')) if system == 'Darwin' else current_exe_path
                backup_path = f'{replace_target}.old'
                logging.info(f'[UPDATE] Current executable: {current_exe_path}')
                logging.info(f'[UPDATE] Replace target: {replace_target}')
                logging.info(f'[UPDATE] Backup path: {backup_path}')
                if system == 'Darwin':
                    logging.info('[UPDATE] Processing macOS update')
                    if archive_path.lower().endswith('.zip'):
                        logging.info('[UPDATE] Extracting ZIP archive using ditto')
                        subprocess.run(['/usr/bin/ditto', '-x', '-k', archive_path, extraction_dir], check=True)
                    new_content_path = next((os.path.join(extraction_dir, d) for d in os.listdir(extraction_dir) if d.endswith('.app')), None)
                    if new_content_path is None:
                        logging.error('[UPDATE] .app bundle not found in extracted archive')
                        raise RuntimeError(tr('errors.app_not_found_after_unpack'))
                    logging.info(f'[UPDATE] Found .app bundle: {new_content_path}')
                    from pathlib import Path
                    from utils.file_utils import fix_macos_python_symlink
                    fix_macos_python_symlink(Path(new_content_path))
                    logging.info('[UPDATE] Fixed Python symlink in .app bundle')
                else:
                    logging.info('[UPDATE] Processing Linux update')
                    new_content_path = next((os.path.join(root, file) for root, _, files in os.walk(extraction_dir) for file in files if os.path.isfile(os.path.join(root, file)) and os.access(os.path.join(root, file), os.X_OK)), None)
                    if new_content_path is None or not os.path.exists(new_content_path):
                        logging.error('[UPDATE] Executable not found in extracted archive')
                        raise RuntimeError(tr('errors.executable_not_found_after_unpack'))
                    logging.info(f'[UPDATE] Found executable: {new_content_path}')
                    os.chmod(new_content_path, 493)
                    logging.info('[UPDATE] Set executable permissions on new launcher')
                if os.path.exists(backup_path):
                    logging.info(f'[UPDATE] Removing old backup: {backup_path}')
                    shutil.rmtree(backup_path, ignore_errors=True)
                logging.info(f'[UPDATE] Creating backup: {replace_target} -> {backup_path}')
                os.rename(replace_target, backup_path)
                logging.info(f'[UPDATE] Replacing launcher: {new_content_path} -> {replace_target}')
                if system == 'Darwin':
                    shutil.copytree(new_content_path, replace_target)
                else:
                    shutil.move(new_content_path, replace_target)
                if not os.path.exists(replace_target):
                    logging.error(f'[UPDATE] Replacement failed: {replace_target} does not exist after replacement')
                    if os.path.exists(backup_path):
                        logging.info('[UPDATE] Attempting to restore backup')
                        if system == 'Darwin':
                            shutil.rmtree(replace_target, ignore_errors=True)
                            shutil.copytree(backup_path, replace_target)
                        else:
                            shutil.move(backup_path, replace_target)
                    raise RuntimeError(tr('errors.update_replacement_failed'))
                logging.info('[UPDATE] Replacement successful, restarting launcher')
                self.feedback_manager.update_status(tr('status.restarting'), UI_COLORS['status_success'])
                os.execv(current_exe_path, sys.argv)
        except PermissionError as e:
            logging.error(f'[UPDATE] Permission error during update: {e}', exc_info=True)
            self.feedback_manager.update_status(tr('errors.update_permission_error'), UI_COLORS['status_error'])
            self.update_error.emit(tr('dialogs.update_permission_error_details'))
        except Exception as e:
            logging.error(f'[UPDATE] Update failed with error: {e}', exc_info=True)
            self.feedback_manager.update_status(tr('errors.update_failed', error=str(e)), UI_COLORS['status_error'])
            self.update_error.emit(tr('errors.update_could_not_complete', error=str(e)))
        finally:
            if not installer_launched:
                logging.info('[UPDATE] Update process finished')
                self.update_finished.emit()
            else:
                logging.info('[UPDATE] Installer launched, launcher closing')
