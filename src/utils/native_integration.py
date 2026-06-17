"""Native OS integrations for opening resources and file system dialogs."""

import contextlib
import ctypes
import logging
import os
import subprocess
import sys
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _split_qt_filter_entry(filter_entry: str) -> tuple[str, list[str]]:
    filter_entry = filter_entry.strip()
    if not filter_entry:
        return ("All Files", ["*"])
    if "(" not in filter_entry or ")" not in filter_entry:
        return (filter_entry, ["*"])
    label, _, remainder = filter_entry.partition("(")
    patterns = remainder.rsplit(")", 1)[0]
    globs = [pattern.strip() for pattern in patterns.split() if pattern.strip()]
    return (label.strip() or "Files", globs or ["*"])


def _qt_filter_to_tk_filetypes(file_filter: str) -> list[tuple[str, str | tuple[str, ...]]]:
    entries = [entry for entry in (file_filter or "").split(";;") if entry.strip()]
    if not entries:
        return [("All Files", "*")]
    filetypes: list[tuple[str, str | tuple[str, ...]]] = []
    for entry in entries:
        label, globs = _split_qt_filter_entry(entry)
        normalized_globs = tuple("*" if glob == "*" else glob for glob in globs)
        filetypes.append(
            (label, normalized_globs[0] if len(normalized_globs) == 1 else normalized_globs)
        )
    return filetypes or [("All Files", "*")]


def _default_extension_from_filter(file_filter: str) -> str:
    entries = [entry for entry in (file_filter or "").split(";;") if entry.strip()]
    for entry in entries:
        _label, globs = _split_qt_filter_entry(entry)
        for glob in globs:
            if glob.startswith("*.") and len(glob) > 2 and "*" not in glob[2:]:
                return glob[1:]
    return ""


def _run_tk_dialog(dialog_runner: Callable[[], object], default):
    root = None
    try:
        from tkinter import TclError, Tk

        root = Tk()
        root.withdraw()
        with contextlib.suppress(TclError):
            root.attributes("-topmost", True)
        return dialog_runner()
    except Exception as error:
        logger.error("Native dialog failed: %s", error, exc_info=True)
        return default
    finally:
        if root is not None:
            from tkinter import TclError

            with contextlib.suppress(TclError):
                root.update_idletasks()
            with contextlib.suppress(TclError):
                root.destroy()


def get_open_file_name(
    _parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[str, str]:
    from tkinter import filedialog

    filetypes = _qt_filter_to_tk_filetypes(file_filter)
    selected = _run_tk_dialog(
        lambda: filedialog.askopenfilename(
            title=caption or "",
            initialdir=directory or "",
            filetypes=filetypes,
        ),
        "",
    )
    return (str(selected or ""), file_filter if selected else "")


def get_open_file_names(
    _parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[list[str], str]:
    from tkinter import filedialog

    filetypes = _qt_filter_to_tk_filetypes(file_filter)
    selected = _run_tk_dialog(
        lambda: filedialog.askopenfilenames(
            title=caption or "",
            initialdir=directory or "",
            filetypes=filetypes,
        ),
        (),
    )
    paths = [str(path) for path in selected if str(path).strip()]
    return (paths, file_filter if paths else "")


def get_save_file_name(
    _parent,
    caption: str,
    directory: str = "",
    file_filter: str = "All Files (*)",
) -> tuple[str, str]:
    from tkinter import filedialog

    filetypes = _qt_filter_to_tk_filetypes(file_filter)
    initialdir = ""
    initialfile = ""
    if directory:
        if os.path.isdir(directory):
            initialdir = directory
        else:
            initialdir = os.path.dirname(directory)
            initialfile = os.path.basename(directory)
    selected = _run_tk_dialog(
        lambda: filedialog.asksaveasfilename(
            title=caption or "",
            initialdir=initialdir,
            initialfile=initialfile,
            filetypes=filetypes,
            defaultextension=_default_extension_from_filter(file_filter),
        ),
        "",
    )
    return (str(selected or ""), file_filter if selected else "")


def get_existing_directory(_parent, caption: str, directory: str = "") -> str:
    from tkinter import filedialog

    selected = _run_tk_dialog(
        lambda: filedialog.askdirectory(
            title=caption or "",
            initialdir=directory or "",
            mustexist=False,
        ),
        "",
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
        subprocess.Popen(command)
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
        subprocess.Popen(command)
        return True
    except Exception as error:
        logger.error("Failed to open path %s: %s", path, error, exc_info=True)
        return False


def sys_platform_is_macos() -> bool:
    return sys.platform == "darwin"
