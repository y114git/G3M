"""Worker thread for scanning mod directories."""

import json
import logging
import os

from PyQt6.QtCore import QThread, pyqtSignal

from config.constants import MOD_CONFIG_FILENAME


class ModScanThread(QThread):
    """Background thread for scanning mod directory."""

    scan_completed = pyqtSignal(dict)

    def __init__(self, mods_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.mods_dir = mods_dir
        self._cancel_flag = False

    def cancel(self):
        self._cancel_flag = True

    def run(self):
        try:
            if self.parent() and hasattr(self.parent(), "app_state"):
                app_state = self.parent().app_state
                if hasattr(app_state, "_scan_blocked") and app_state._scan_blocked:
                    logging.debug("ModScanThread: Scan blocked during installation")
                    self.scan_completed.emit({})
                    return
        except Exception as e:
            logging.debug(f"ModScanThread: Could not check scan block status: {e}")
        result = {}
        if not os.path.exists(self.mods_dir):
            self.scan_completed.emit(result)
            return
        try:
            with os.scandir(self.mods_dir) as entries:
                for entry in entries:
                    if self._cancel_flag:
                        break
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    folder_name = entry.name
                    folder_path = entry.path
                    try:
                        from utils.file_utils import migrate_mod_config

                        migrate_mod_config(folder_path)
                    except Exception:
                        logging.warning(
                            f"ModScanThread: failed to migrate mod config in {folder_path}"
                        )
                    config_path = os.path.join(folder_path, MOD_CONFIG_FILENAME)
                    if not os.path.exists(config_path):
                        continue
                    try:
                        config_size = os.path.getsize(config_path)
                        if config_size == 0:
                            logging.warning(
                                f"ModScanThread: Corrupted config detected (0 bytes) in {config_path}, skipping mod"
                            )
                            continue
                        config_mtime = os.path.getmtime(config_path)
                        with open(config_path, encoding="utf-8") as f:
                            config_data = json.load(f)
                        key = config_data.get("key") or config_data.get("mod_key")
                        if not key:
                            continue
                        if key in result:
                            existing_info = result[key]
                            if config_mtime <= existing_info.get("config_mtime", 0):
                                continue
                        result[key] = {
                            "key": key,
                            "folder_path": folder_path,
                            "folder_name": folder_name,
                            "config_data": config_data,
                            "config_mtime": config_mtime,
                        }
                    except (OSError, PermissionError, ValueError):
                        logging.warning(
                            f"ModScanThread: Corrupted config detected (failed to access) in {config_path}"
                        )
                        continue
                    except KeyError:
                        logging.debug(f"ModScanThread: missing key in {config_path}")
                        continue
                    except Exception:
                        logging.error(
                            f"ModScanThread: Corrupted config detected (unexpected error) in {folder_path}"
                        )
                        continue
        except OSError:
            logging.error(f"ModScanThread: failed to list directory {self.mods_dir}")
        except Exception as e:
            logging.debug(f"ModScanThread: Unexpected error during scan: {e}")
        try:
            self.scan_completed.emit(result)
        except Exception as e:
            logging.error(
                f"ModScanThread: Failed to emit scan_completed signal: {e}",
                exc_info=True,
            )
