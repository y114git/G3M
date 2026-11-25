"""Native OS integrations for opening resources and file system dialogs."""

import ctypes
import logging
import os
import subprocess
import sys

from PyQt6.QtWidgets import QFileDialog

from services.background_operations import background_operations
from utils.path_utils import get_user_data_root

logger = logging.getLogger(__name__)

LAST_DIALOG_DIR_FILE = "last_dialog_dir.txt"


def _last_dir_path() -> str:
    return os.path.join(get_user_data_root(), LAST_DIALOG_DIR_FILE)


def _remembered_dir() -> str:
    """The folder the last file dialog ended in, or "" when none was kept or it is gone."""
    try:
        with open(_last_dir_path(), encoding="utf-8") as handle:
            folder = handle.read().strip()
    except OSError:
        return ""
    return folder if folder and os.path.isdir(folder) else ""


def _remember_dir(chosen: str) -> None:
    folder = chosen if os.path.isdir(chosen) else os.path.dirname(chosen)
    if not folder or not os.path.isdir(folder) or folder == _remembered_dir():
        return
    target = _last_dir_path()
    temporary = target + ".tmp"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(folder)
        os.replace(temporary, target)
    except OSError as error:
        logger.debug("Could not keep the last dialog folder: %s", error)


def _start_location(directory: str) -> str:
    """A folder the caller chose wins. No hint, the home folder or a bare file name start in the folder of the last dialog."""
    given = directory or ""
    folder = given if os.path.isdir(given) else os.path.dirname(given)
    home = os.path.expanduser("~")
    if (
        folder
        and os.path.isdir(folder)
        and os.path.normcase(os.path.abspath(folder)) != os.path.normcase(home)
    ):
        return given
    last = _remembered_dir()
    if not last:
        return given
    if given and not os.path.isdir(given):
        return os.path.join(last, os.path.basename(given))
    return last


def get_open_file_name(
    parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[str, str]:
    selected, chosen_filter = QFileDialog.getOpenFileName(
        parent,
        caption or "",
        _start_location(directory),
        file_filter or "All Files (*)",
    )
    _remember_dir(str(selected or ""))
    return (str(selected or ""), str(chosen_filter or ""))


def get_open_file_names(
    parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[list[str], str]:
    selected, chosen_filter = QFileDialog.getOpenFileNames(
        parent,
        caption or "",
        _start_location(directory),
        file_filter or "All Files (*)",
    )
    paths = [str(path) for path in selected if str(path).strip()]
    if paths:
        _remember_dir(paths[0])
    return (paths, str(chosen_filter or ""))


def get_save_file_name(
    parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[str, str]:
    selected, chosen_filter = QFileDialog.getSaveFileName(
        parent,
        caption or "",
        _start_location(directory),
        file_filter or "All Files (*)",
    )
    _remember_dir(str(selected or ""))
    return (str(selected or ""), str(chosen_filter or ""))


def get_existing_directory(parent, caption: str, directory: str = "") -> str:
    selected = QFileDialog.getExistingDirectory(
        parent,
        caption or "",
        _start_location(directory),
    )
    _remember_dir(str(selected or ""))
    return str(selected or "")


def open_url_native(url: str) -> bool:
    if not url:
        return False
    try:
        if os.name == "nt":
            return (
                ctypes.windll.shell32.ShellExecuteW(None, "open", url, None, None, 1)
                > 32
            )
        command = ["open" if sys_platform_is_macos() else "xdg-open", url]
        background_operations.track_process(
            subprocess.Popen(command), cancel=lambda: None
        )
        return True
    except Exception as error:
        logger.error("Failed to open URL %s: %s", url, error, exc_info=True)
        return False


def open_path_native(path: str) -> bool:
    if not path:
        return False
    try:
        if os.name == "nt":
            return (
                ctypes.windll.shell32.ShellExecuteW(None, "open", path, None, None, 1)
                > 32
            )
        command = ["open" if sys_platform_is_macos() else "xdg-open", path]
        background_operations.track_process(
            subprocess.Popen(command), cancel=lambda: None
        )
        return True
    except Exception as error:
        logger.error("Failed to open path %s: %s", path, error, exc_info=True)
        return False


def sys_platform_is_macos() -> bool:
    return sys.platform == "darwin"
