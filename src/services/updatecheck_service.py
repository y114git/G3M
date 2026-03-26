"""Application update checking and installation."""

import contextlib
import hashlib
import logging
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from subprocess import DEVNULL, Popen, run

from PyQt6.QtCore import QObject, pyqtSignal

from config.config import ARCH, LAUNCHER_VERSION, UI_COLORS
from models.app_state import AppState
from models.exceptions import AppError
from services.localization_service import tr
from ui.common.feedback import FeedbackManager
from utils.network_utils import get_session
from utils.path_utils import fix_macos_python_symlink, version_sort_key


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
            update_info = self.get_update_info(system=system, beta_enabled=beta_enabled)
            if update_info is None:
                return
            if system == "Darwin" and "AppTranslocation" in sys.executable:
                logging.warning(
                    "UpdateChecker: App Translocation detected: %s", sys.executable
                )
                self.feedback_service.update_status(
                    tr("errors.app_translocation_detected"), UI_COLORS["status_error"]
                )
                return
            logging.info(
                "UpdateChecker: Update available - version %s",
                update_info["version"],
            )
            self.update_available.emit(update_info)
        except Exception as e:
            import requests

            key = (
                "errors.update_check_network_error"
                if isinstance(e, requests.RequestException)
                else "errors.update_check_general_error"
            )
            self.feedback_service.update_status(
                tr(key, error=str(e)), UI_COLORS["status_error"]
            )

    def get_update_info(
        self, *, system: str | None = None, beta_enabled: bool | None = None
    ) -> dict | None:
        system = system or platform.system()
        if beta_enabled is None:
            beta_enabled = self.app_state.local_config.get("beta_updates_enabled", False)
        launcher_files_key = "launcher_beta_files" if beta_enabled else "launcher_files"
        launcher_files = self.app_state.global_settings.get(launcher_files_key)
        if not isinstance(launcher_files, dict):
            self.feedback_service.update_status(
                tr("status.update_info_not_found"), UI_COLORS["status_warning"]
            )
            return None
        remote_version = str(launcher_files.get("version", "")).strip()
        if not remote_version or version_sort_key(remote_version) <= version_sort_key(
            LAUNCHER_VERSION
        ):
            self.feedback_service.update_status(
                tr("status.launcher_version_up_to_date"), UI_COLORS["status_success"]
            )
            return None
        platform_key = self._get_platform_key(system)
        download_url = (launcher_files.get("urls") or {}).get(platform_key)
        if not download_url:
            self.feedback_service.update_status(
                tr("errors.no_build_for_os", platform=platform_key),
                UI_COLORS["status_warning"],
            )
            return None
        return {
            "version": remote_version,
            "url": download_url,
            "message": launcher_files.get(
                "message", tr("dialogs.new_version_available_simple")
            ),
            "message_ru": launcher_files.get("message_ru"),
            "message_en": launcher_files.get("message_en"),
            "sha256": self._get_platform_value(
                launcher_files.get("sha256"), platform_key
            ),
        }

    def perform_update(self, update_info):
        self.status_changed.emit(
            tr("status.update_available"), UI_COLORS["status_info"]
        )
        threading.Thread(
            target=self._update_worker, args=(update_info,), daemon=True
        ).start()

    def _get_platform_key(self, system: str) -> str | None:
        return {
            "Windows": "windows",
            "Linux": "linux",
            "Darwin": f"macos-{ARCH}",
        }.get(system)

    def _get_platform_value(self, value, platform_key: str | None):
        if isinstance(value, dict):
            return value.get(platform_key or "")
        return value

    def _get_archive_extension(self, url: str) -> str:
        url_path = url.split("?", 1)[0].lower()
        if url_path.endswith(".tar.gz"):
            return ".tar.gz"
        if url_path.endswith(".tar.lzma"):
            return ".tar.lzma"
        return os.path.splitext(url_path)[1]

    def _download_archive(self, update_info: dict, tmp_dir: str) -> str:
        archive_path = os.path.join(
            tmp_dir, f"update{self._get_archive_extension(update_info['url'])}"
        )
        logging.info(
            "[UPDATE] Downloading update from %s to %s",
            update_info["url"],
            archive_path,
        )
        self.status_changed.emit(
            tr("status.downloading_version", version=update_info["version"]),
            UI_COLORS["status_warning"],
        )
        response = get_session(self.app_state).get(
            update_info["url"], stream=True, timeout=60
        )
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        downloaded_size = 0
        with open(archive_path, "wb") as file_obj:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                file_obj.write(chunk)
                downloaded_size += len(chunk)
                if total_size > 0:
                    self.progress_updated.emit(int(downloaded_size / total_size * 100))
        sha256 = str(update_info.get("sha256", "")).strip().lower()
        if sha256:
            self._verify_archive_checksum(archive_path, sha256)
        logging.info(
            "[UPDATE] Successfully downloaded update archive (%s bytes)",
            downloaded_size,
        )
        return archive_path

    def _verify_archive_checksum(self, archive_path: str, expected_sha256: str) -> None:
        digest = hashlib.sha256()
        with open(archive_path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha256 = digest.hexdigest().lower()
        if actual_sha256 != expected_sha256:
            raise AppError(
                "errors.update_failed",
                error=f"Checksum mismatch: expected {expected_sha256}, got {actual_sha256}",
            )

    def _extract_archive(
        self, system: str, archive_path: str, extraction_dir: str
    ) -> None:
        os.makedirs(extraction_dir, exist_ok=True)
        logging.info(
            "[UPDATE] Extracting archive to %s (platform: %s)",
            extraction_dir,
            system,
        )
        if system == "Darwin" and archive_path.lower().endswith(".zip"):
            run(["/usr/bin/ditto", "-x", "-k", archive_path, extraction_dir], check=True)
            return
        from utils.archive_utils import extract_archive

        extract_archive(archive_path, extraction_dir, os.path.basename(archive_path))

    def _find_windows_installer(self, extraction_dir: str) -> str | None:
        return next(
            (
                os.path.join(root, file_name)
                for root, _, files in os.walk(extraction_dir)
                for file_name in files
                if file_name.lower().endswith(".exe")
            ),
            None,
        )

    def _launch_windows_installer(self, extraction_dir: str) -> bool:
        new_exe_path = self._find_windows_installer(extraction_dir)
        if not new_exe_path:
            raise AppError("errors.exe_not_found_in_archive")
        logging.info("[UPDATE] Found installer executable: %s", new_exe_path)
        import ctypes

        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", new_exe_path, None, None, 1
        )
        if result <= 32:
            raise AppError("errors.installer_launch_failed", code=result)
        self.status_changed.emit(
            tr("status.installer_launched_closing"), UI_COLORS["status_success"]
        )
        self.quit_requested.emit()
        timer = threading.Timer(3.0, lambda: os._exit(0))
        timer.daemon = True
        timer.start()
        return True

    def _get_replace_target(self, system: str) -> str:
        current_exe_path = os.path.realpath(sys.executable)
        if system != "Darwin":
            return current_exe_path
        while current_exe_path != "/" and not current_exe_path.endswith(".app"):
            current_exe_path = os.path.dirname(current_exe_path)
        if not current_exe_path.endswith(".app"):
            raise AppError("errors.app_path_not_found")
        return current_exe_path

    def _find_macos_bundle(self, extraction_dir: str) -> str:
        new_content_path = next(
            (
                os.path.join(extraction_dir, entry)
                for entry in os.listdir(extraction_dir)
                if entry.endswith(".app")
            ),
            None,
        )
        if new_content_path is None:
            raise AppError("errors.app_not_found_after_unpack")
        fix_macos_python_symlink(Path(new_content_path))
        return new_content_path

    def _find_linux_executable(self, extraction_dir: str) -> str:
        for root, _, files in os.walk(extraction_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                    return file_path
        largest_file = None
        largest_size = 0
        for root, _, files in os.walk(extraction_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if os.path.isfile(file_path) and (
                    not os.path.splitext(file_name)[1] or file_name.endswith(".AppImage")
                ):
                    size = os.path.getsize(file_path)
                    if size > largest_size:
                        largest_size = size
                        largest_file = file_path
        if largest_file is None or not os.path.exists(largest_file):
            raise AppError("errors.executable_not_found_after_unpack")
        os.chmod(largest_file, 0o700)
        return largest_file

    def _stage_unix_content(self, system: str, extraction_dir: str) -> str:
        new_content_path = (
            self._find_macos_bundle(extraction_dir)
            if system == "Darwin"
            else self._find_linux_executable(extraction_dir)
        )
        persistent_temp_dir = tempfile.mkdtemp(prefix="deltahub-update-persistent-")
        persistent_new_path = os.path.join(
            persistent_temp_dir, os.path.basename(new_content_path)
        )
        if system == "Darwin":
            shutil.copytree(new_content_path, persistent_new_path)
        else:
            shutil.copy2(new_content_path, persistent_new_path)
            os.chmod(persistent_new_path, 0o700)
        return persistent_new_path

    def _build_unix_updater_script(
        self, current_path: str, new_path: str, system: str
    ) -> tuple[str, str]:
        updater_script_path = os.path.join(
            tempfile.gettempdir(), f"deltahub_updater_{int(time.time())}.sh"
        )
        safe_current = current_path.replace("'", "'\\''")
        safe_new = new_path.replace("'", "'\\''")
        launch_cmd = 'open "$OLD_PATH"' if system == "Darwin" else '"$OLD_PATH" &'
        script_content = f"""#!/bin/bash
PID={os.getpid()}
OLD_PATH='{safe_current}'
NEW_PATH='{safe_new}'
BACKUP_PATH="${{OLD_PATH}}.old"
TEMP_DIR='{os.path.dirname(new_path).replace("'", "'\\''")}'
LOG_FILE="/tmp/deltahub_update.log"

while kill -0 "$PID" 2>/dev/null; do sleep 0.5; done
rm -rf "$BACKUP_PATH" 2>> "$LOG_FILE"
if [ -e "$OLD_PATH" ]; then mv "$OLD_PATH" "$BACKUP_PATH" 2>> "$LOG_FILE" || exit 1; fi
if ! mv -f "$NEW_PATH" "$OLD_PATH" 2>> "$LOG_FILE"; then
  if [ -e "$BACKUP_PATH" ]; then mv -f "$BACKUP_PATH" "$OLD_PATH" 2>> "$LOG_FILE"; fi
  exit 1
fi
chmod -R u+rwX,go+rX "$OLD_PATH" 2>> "$LOG_FILE" || true
if [[ "$OSTYPE" == "darwin"* ]]; then
  xattr -r -d com.apple.quarantine "$OLD_PATH" 2>> "$LOG_FILE" || true
fi
if ! ({launch_cmd}) >> "$LOG_FILE" 2>&1; then
  rm -rf "$OLD_PATH" 2>> "$LOG_FILE"
  if [ -e "$BACKUP_PATH" ]; then mv -f "$BACKUP_PATH" "$OLD_PATH" 2>> "$LOG_FILE"; fi
  exit 1
fi
(sleep 10; rm -rf "$BACKUP_PATH" "$TEMP_DIR" "$0") >/dev/null 2>&1 &
"""
        return updater_script_path, script_content

    def _perform_unix_update(self, current_path: str, new_path: str):
        system = platform.system()
        target_dir = os.path.dirname(current_path)
        if not os.access(target_dir, os.W_OK):
            error_msg = tr(
                "errors.update_permission_error_no_write_access", path=target_dir
            )
            logging.error("[UPDATE] %s", error_msg)
            raise PermissionError(error_msg)
        updater_script_path, script_content = self._build_unix_updater_script(
            current_path, new_path, system
        )
        with open(updater_script_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(script_content)
        os.chmod(updater_script_path, 0o700)
        logging.info("[UPDATE] Launching updater script %s", updater_script_path)
        try:
            Popen(
                ["/bin/bash", updater_script_path],
                start_new_session=True,
                stdin=DEVNULL,
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(updater_script_path)
            raise
        self.status_changed.emit(tr("status.restarting"), UI_COLORS["status_success"])
        self.quit_requested.emit()

    def _update_worker(self, update_info):
        installer_launched = False
        try:
            logging.info(
                "[UPDATE] Starting update process for version %s",
                update_info["version"],
            )
            with tempfile.TemporaryDirectory(prefix="deltahub-update-") as tmp_dir:
                archive_path = self._download_archive(update_info, tmp_dir)
                self.status_changed.emit(
                    tr("status.unpacking_and_installing"), UI_COLORS["status_warning"]
                )
                system = platform.system()
                extraction_dir = os.path.join(tmp_dir, "extracted")
                self._extract_archive(system, archive_path, extraction_dir)
                if system == "Windows":
                    installer_launched = self._launch_windows_installer(extraction_dir)
                    return
                replace_target = self._get_replace_target(system)
                staged_content_path = self._stage_unix_content(system, extraction_dir)
                logging.info(
                    "[UPDATE] Unix update: Replacing %s with %s",
                    replace_target,
                    staged_content_path,
                )
                self._perform_unix_update(replace_target, staged_content_path)
        except PermissionError as e:
            logging.error("[UPDATE] Permission error during update: %s", e, exc_info=True)
            self.status_changed.emit(
                tr("errors.update_permission_error"), UI_COLORS["status_error"]
            )
            self.update_error.emit(tr("dialogs.update_permission_error_details"))
        except Exception as e:
            logging.error("[UPDATE] Update failed with error: %s", e, exc_info=True)
            self.status_changed.emit(
                tr("errors.update_failed", error=str(e)), UI_COLORS["status_error"]
            )
            self.update_error.emit(tr("errors.update_could_not_complete", error=str(e)))
        finally:
            if not installer_launched:
                logging.info("[UPDATE] Update process finished")
                self.update_finished.emit()
            else:
                logging.info("[UPDATE] Installer launched, launcher closing")
