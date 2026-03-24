"""Application update checking and installation."""

import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from config.config import ARCH, LAUNCHER_VERSION, UI_COLORS
from models.app_state import AppState
from models.exceptions import AppError
from services.localization_service import tr
from ui.common.feedback import FeedbackManager
from utils.network_utils import get_session


class UpdateChecker(QObject):
    """Manages launcher update checking and installation."""

    update_available = pyqtSignal(dict)
    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    update_finished = pyqtSignal()
    update_error = pyqtSignal(str)
    quit_requested = pyqtSignal()

    def __init__(
        self, app_state: AppState, feedback_service: FeedbackManager, parent=None
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_service = feedback_service

    def check_for_updates(self):
        beta_enabled = self.app_state.local_config.get("beta_updates_enabled", False)
        system = platform.system()
        if beta_enabled:
            self.feedback_service.update_status(
                tr("status.beta_updates_enabled"), UI_COLORS["status_warning"]
            )
        try:
            launcher_files_key = (
                "launcher_beta_files" if beta_enabled else "launcher_files"
            )
            launcher_files = self.app_state.global_settings.get(launcher_files_key)
            if not isinstance(launcher_files, dict):
                self.feedback_service.update_status(
                    tr("status.update_info_not_found"), UI_COLORS["status_warning"]
                )
                return
            remote_version = launcher_files.get("version")
            from utils.path_utils import version_sort_key as _vkey

            if not remote_version or _vkey(remote_version) <= _vkey(LAUNCHER_VERSION):
                self.feedback_service.update_status(
                    tr("status.launcher_version_up_to_date"),
                    UI_COLORS["status_success"],
                )
                return
            platform_key_map = {
                "Windows": "windows",
                "Linux": "linux",
                "Darwin": f"macos-{ARCH}",
            }
            current_platform_key = platform_key_map.get(system)
            download_url = launcher_files.get("urls", {}).get(current_platform_key)
            update_message = launcher_files.get(
                "message", tr("dialogs.new_version_available_simple")
            )
            update_message_ru = launcher_files.get("message_ru")
            update_message_en = launcher_files.get("message_en")
            if not download_url:
                self.feedback_service.update_status(
                    tr("errors.no_build_for_os", platform=current_platform_key),
                    UI_COLORS["status_warning"],
                )
                return
            update_info = {
                "version": remote_version,
                "url": download_url,
                "message": update_message,
                "message_ru": update_message_ru,
                "message_en": update_message_en,
            }
            if system == "Darwin" and "AppTranslocation" in sys.executable:
                logging.warning(
                    f"UpdateChecker: App Translocation detected: {sys.executable}"
                )
                self.feedback_service.update_status(
                    tr("errors.app_translocation_detected"), UI_COLORS["status_error"]
                )
                return
            logging.info(
                f"UpdateChecker: Update available - version {remote_version}, emitting update_available signal"
            )
            self.update_available.emit(update_info)
        except Exception as e:
            import requests

            if isinstance(e, requests.RequestException):
                self.feedback_service.update_status(
                    tr("errors.update_check_network_error", error=str(e)),
                    UI_COLORS["status_error"],
                )
            else:
                self.feedback_service.update_status(
                    tr("errors.update_check_general_error", error=str(e)),
                    UI_COLORS["status_error"],
                )

    def perform_update(self, update_info):
        self.status_changed.emit(
            tr("status.update_available"), UI_COLORS["status_info"]
        )
        threading.Thread(
            target=self._update_worker, args=(update_info,), daemon=True
        ).start()

    def _perform_unix_update(self, current_exe_path, new_content_path):
        system = platform.system()
        target_dir = os.path.dirname(current_exe_path)
        if not os.access(target_dir, os.W_OK):
            error_msg = tr(
                "errors.update_permission_error_no_write_access", path=target_dir
            )
            logging.error(f"[UPDATE] {error_msg}")
            raise PermissionError(error_msg)
        updater_script_path = os.path.join(
            tempfile.gettempdir(), f"deltahub_updater_{int(time.time())}.sh"
        )
        current_pid = os.getpid()
        safe_old = current_exe_path.replace("'", "'\\''")
        safe_new = new_content_path.replace("'", "'\\''")
        if system == "Darwin":
            launch_cmd = 'open "$OLD_PATH"'
        else:
            launch_cmd = '"$OLD_PATH" &'
        new_content_parent = os.path.dirname(new_content_path).replace("'", "'\\''")
        script_content = f"""#!/bin/bash\n# DELTAHUB Updater Script\n# Generated at {time.strftime("%Y-%m-%d %H:%M:%S")}\n\nPID={current_pid}\nOLD_PATH='{safe_old}'\nNEW_PATH='{safe_new}'\nTEMP_DIR='{new_content_parent}'\nLOG_FILE="/tmp/deltahub_update.log"\n\n# 1. Wait for main process to finish\necho "Waiting for PID $PID to close..." > "$LOG_FILE"\nwhile kill -0 "$PID" 2>/dev/null; do\n   sleep 0.5\ndone\n\necho "Process closed. Updating..." >> "$LOG_FILE"\n\n# 2. Remove old version (or move to backup)\n# On macOS this removes .app folder, on Linux file\nrm -rf "$OLD_PATH" 2>> "$LOG_FILE"\n\n# 3. Move new version to old location\nmv -f "$NEW_PATH" "$OLD_PATH" 2>> "$LOG_FILE"\n\n# 4. Restore execute permissions (critical for Linux/Mac)\nchmod -R 755 "$OLD_PATH" 2>> "$LOG_FILE"\n\n# 5. (macOS only) Remove quarantine if needed\nif [[ "$OSTYPE" == "darwin"* ]]; then\n   xattr -r -d com.apple.quarantine "$OLD_PATH" 2>> "$LOG_FILE" || true\nfi\n\n# 6. Launch new version\necho "Launching new version..." >> "$LOG_FILE"\n{launch_cmd} >> "$LOG_FILE" 2>&1\n\n# 7. Clean temp directory (if empty)\nrm -rf "$TEMP_DIR" 2>/dev/null || true\n\n# 8. Self-cleanup script (optional but clean)\nrm -f "$0" 2>/dev/null || true\n"""
        with open(updater_script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(updater_script_path, 0o700)
        logging.info(f"[UPDATE] Created updater script: {updater_script_path}")
        logging.info(f"[UPDATE] Launching updater script for PID {current_pid}")
        try:
            subprocess.Popen(
                ["/bin/bash", updater_script_path],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("[UPDATE] Updater script launched successfully")
        except Exception as e:
            logging.error(f"[UPDATE] Failed to launch updater script: {e}")
            try:
                os.remove(updater_script_path)
            except Exception as cleanup_err:
                logging.warning(
                    f"[UPDATE] Failed to remove updater script {updater_script_path}: {cleanup_err}"
                )
            raise
        self.feedback_service.update_status(
            tr("status.restarting"), UI_COLORS["status_success"]
        )
        self.quit_requested.emit()

    def _update_worker(self, update_info):
        installer_launched = False
        try:
            logging.info(
                f"[UPDATE] Starting update process for version {update_info['version']}"
            )
            with tempfile.TemporaryDirectory(prefix="deltahub-update-") as tmp_dir:
                url_path = update_info["url"].split("?")[0]
                url_lower = url_path.lower()
                if url_lower.endswith(".tar.gz"):
                    ext = ".tar.gz"
                elif url_lower.endswith(".tar.lzma"):
                    ext = ".tar.lzma"
                else:
                    ext = os.path.splitext(url_path)[1]
                archive_path = os.path.join(tmp_dir, "update" + ext)
                logging.info(
                    f"[UPDATE] Downloading update from {update_info['url']} to {archive_path}"
                )
                self.feedback_service.update_status(
                    tr("status.downloading_version", version=update_info["version"]),
                    UI_COLORS["status_warning"],
                )
                session = get_session()
                response = session.get(update_info["url"], stream=True, timeout=60)
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                logging.info(f"[UPDATE] Update archive size: {total_size} bytes")
                with open(archive_path, "wb") as f:
                    downloaded_size = 0
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        downloaded_size += len(data)
                        if total_size > 0:
                            self.progress_updated.emit(
                                int(downloaded_size / total_size * 100)
                            )
                logging.info(
                    f"[UPDATE] Successfully downloaded update archive ({downloaded_size} bytes)"
                )
                self.feedback_service.update_status(
                    tr("status.unpacking_and_installing"), UI_COLORS["status_warning"]
                )
                system = platform.system()
                extraction_dir = os.path.join(tmp_dir, "extracted")
                os.makedirs(extraction_dir, exist_ok=True)
                logging.info(
                    f"[UPDATE] Extracting archive to {extraction_dir} (platform: {system})"
                )
                if system != "Darwin":
                    from utils.archive_utils import extract_archive

                    extract_archive(
                        archive_path, extraction_dir, os.path.basename(archive_path)
                    )
                if system == "Windows":
                    new_exe_path = next(
                        (
                            os.path.join(root, f)
                            for root, _, files in os.walk(extraction_dir)
                            for f in files
                            if f.lower().endswith(".exe")
                        ),
                        None,
                    )
                    if not new_exe_path:
                        logging.error(
                            "[UPDATE] Executable not found in extracted archive"
                        )
                        raise AppError("errors.exe_not_found_in_archive")
                    logging.info(f"[UPDATE] Found installer executable: {new_exe_path}")
                    logging.info(
                        "[UPDATE] Launching installer with elevated privileges (runas)"
                    )
                    import ctypes

                    result = ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", new_exe_path, None, None, 1
                    )
                    if result > 32:
                        time.sleep(1.0)
                        installer_name = os.path.basename(new_exe_path)
                        try:
                            import psutil

                            processes = [
                                p
                                for p in psutil.process_iter(["pid", "name"])
                                if p.info["name"].lower() == installer_name.lower()
                            ]
                            if processes:
                                logging.info(
                                    f"[UPDATE] Installer process confirmed running (PID: {processes[0].info['pid']})"
                                )
                            else:
                                logging.warning(
                                    "[UPDATE] Installer process not found immediately, but launch was successful"
                                )
                        except ImportError:
                            logging.info(
                                "[UPDATE] psutil not available, skipping process verification"
                            )
                        except Exception as e:
                            logging.warning(
                                f"[UPDATE] Could not verify installer process: {e}"
                            )
                        logging.info(
                            f"[UPDATE] Installer launched successfully (result code: {result}), force terminating launcher"
                        )
                        self.feedback_service.update_status(
                            tr("status.installer_launched_closing"),
                            UI_COLORS["status_success"],
                        )
                        installer_launched = True
                        logging.info(
                            "[UPDATE] Force terminating launcher process to allow installer to replace files"
                        )
                        try:
                            import gc

                            gc.collect()
                        except Exception as e:
                            logging.debug(
                                f"[UPDATE] Failed to trigger GC before exit: {e}",
                                exc_info=True,
                            )
                        os._exit(0)
                    else:
                        logging.error(
                            f"[UPDATE] Failed to launch installer (result code: {result})"
                        )
                        raise AppError("errors.installer_launch_failed", code=result)
                current_exe_path = os.path.realpath(sys.executable)
                if system == "Darwin":
                    while current_exe_path != "/" and (
                        not current_exe_path.endswith(".app")
                    ):
                        current_exe_path = os.path.dirname(current_exe_path)
                    if not current_exe_path.endswith(".app"):
                        logging.error(
                            "[UPDATE] Could not find .app bundle in executable path"
                        )
                        raise AppError("errors.app_path_not_found")
                    replace_target = current_exe_path
                else:
                    replace_target = current_exe_path
                logging.info(f"[UPDATE] Current executable: {sys.executable}")
                logging.info(f"[UPDATE] Replace target: {replace_target}")
                if system == "Darwin":
                    logging.info("[UPDATE] Processing macOS update")
                    if archive_path.lower().endswith(".zip"):
                        logging.info("[UPDATE] Extracting ZIP archive using ditto")
                        subprocess.run(
                            [
                                "/usr/bin/ditto",
                                "-x",
                                "-k",
                                archive_path,
                                extraction_dir,
                            ],
                            check=True,
                        )
                    new_content_path = next(
                        (
                            os.path.join(extraction_dir, d)
                            for d in os.listdir(extraction_dir)
                            if d.endswith(".app")
                        ),
                        None,
                    )
                    if new_content_path is None:
                        logging.error(
                            "[UPDATE] .app bundle not found in extracted archive"
                        )
                        raise AppError("errors.app_not_found_after_unpack")
                    logging.info(f"[UPDATE] Found .app bundle: {new_content_path}")
                    from pathlib import Path

                    from utils.path_utils import fix_macos_python_symlink

                    fix_macos_python_symlink(Path(new_content_path))
                    logging.info("[UPDATE] Fixed Python symlink in .app bundle")
                else:
                    logging.info("[UPDATE] Processing Linux update")
                    new_content_path = None
                    for root, _, files in os.walk(extraction_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            if os.path.isfile(file_path) and os.access(
                                file_path, os.X_OK
                            ):
                                new_content_path = file_path
                                break
                        if new_content_path:
                            break
                    if new_content_path is None:
                        largest_file = None
                        largest_size = 0
                        for root, _, files in os.walk(extraction_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                if os.path.isfile(file_path) and (
                                    not os.path.splitext(file)[1]
                                    or file.endswith(".AppImage")
                                ):
                                    size = os.path.getsize(file_path)
                                    if size > largest_size:
                                        largest_size = size
                                        largest_file = file_path
                        new_content_path = largest_file
                    if new_content_path is None or not os.path.exists(new_content_path):
                        logging.error(
                            "[UPDATE] Executable not found in extracted archive"
                        )
                        raise AppError("errors.executable_not_found_after_unpack")
                    logging.info(f"[UPDATE] Found executable: {new_content_path}")
                    os.chmod(new_content_path, 0o700)
                    logging.info("[UPDATE] Set executable permissions on new launcher")
                persistent_temp_dir = tempfile.mkdtemp(
                    prefix="deltahub-update-persistent-"
                )
                persistent_new_path = os.path.join(
                    persistent_temp_dir, os.path.basename(new_content_path)
                )
                if system == "Darwin":
                    logging.info(
                        f"[UPDATE] Copying .app bundle to persistent temp: {persistent_new_path}"
                    )
                    shutil.copytree(new_content_path, persistent_new_path)
                else:
                    logging.info(
                        f"[UPDATE] Copying executable to persistent temp: {persistent_new_path}"
                    )
                    shutil.copy2(new_content_path, persistent_new_path)
                    os.chmod(persistent_new_path, 0o700)
                logging.info(
                    f"[UPDATE] Unix update: Replacing {replace_target} with {persistent_new_path}"
                )
                self._perform_unix_update(replace_target, persistent_new_path)
        except PermissionError as e:
            logging.error(
                f"[UPDATE] Permission error during update: {e}", exc_info=True
            )
            self.feedback_service.update_status(
                tr("errors.update_permission_error"), UI_COLORS["status_error"]
            )
            self.update_error.emit(tr("dialogs.update_permission_error_details"))
        except Exception as e:
            logging.error(f"[UPDATE] Update failed with error: {e}", exc_info=True)
            self.feedback_service.update_status(
                tr("errors.update_failed", error=str(e)), UI_COLORS["status_error"]
            )
            self.update_error.emit(tr("errors.update_could_not_complete", error=str(e)))
        finally:
            if not installer_launched:
                logging.info("[UPDATE] Update process finished")
                self.update_finished.emit()
            else:
                logging.info("[UPDATE] Installer launched, launcher closing")
