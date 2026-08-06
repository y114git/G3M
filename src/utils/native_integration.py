"""Native OS integrations for opening resources and file system dialogs."""

import ctypes
import logging
import os
import subprocess
import sys

from PyQt6.QtWidgets import QFileDialog

from services.background_operations import background_operations

logger = logging.getLogger(__name__)


def get_open_file_name(
    parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[str, str]:
    selected, chosen_filter = QFileDialog.getOpenFileName(
        parent,
        caption or "",
        directory or "",
        file_filter or "All Files (*)",
    )
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
        directory or "",
        file_filter or "All Files (*)",
    )
    return (
        [str(path) for path in selected if str(path).strip()],
        str(chosen_filter or ""),
    )


def get_save_file_name(
    parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[str, str]:
    selected, chosen_filter = QFileDialog.getSaveFileName(
        parent,
        caption or "",
        directory or "",
        file_filter or "All Files (*)",
    )
    return (str(selected or ""), str(chosen_filter or ""))


def get_existing_directory(parent, caption: str, directory: str = "") -> str:
    selected = QFileDialog.getExistingDirectory(
        parent,
        caption or "",
        directory or "",
    )
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
