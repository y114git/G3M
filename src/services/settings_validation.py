"""Executable and path validation helpers for settings workflows."""

from __future__ import annotations

import contextlib
import os
import platform
import subprocess

from services.localization_service import tr
from utils.process_utils import format_external_process_error


def has_unix_executable_signature(filepath: str) -> bool:
    try:
        with open(filepath, "rb") as handle:
            header = handle.read(4)
    except OSError:
        return False
    if header.startswith(b"#!"):
        return True
    if header == b"\x7fELF":
        return True
    return header in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }


def validate_windows_executable_path(
    filepath: str, *, subprocess_module=subprocess
) -> str | None:
    native_filepath = os.path.normpath(filepath)
    command = [native_filepath]
    creationflags = getattr(subprocess_module, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess_module, "CREATE_SUSPENDED", 0
    )
    popen_kwargs = {
        "stdout": subprocess_module.DEVNULL,
        "stderr": subprocess_module.DEVNULL,
        "creationflags": creationflags,
    }
    process = None
    try:
        process = subprocess_module.Popen(command, **popen_kwargs)
    except (
        OSError,
        ValueError,
        subprocess_module.SubprocessError,
    ) as error:
        return format_external_process_error(
            error, command=command, target_path=native_filepath
        )
    finally:
        if process is not None:
            with contextlib.suppress(OSError, ValueError, subprocess_module.SubprocessError):
                process.kill()
            with contextlib.suppress(OSError, ValueError, subprocess_module.SubprocessError):
                process.wait(timeout=0.2)
    return None


def get_executable_path_error(filepath: str) -> str | None:
    if not os.path.isfile(filepath):
        return tr("errors.launch_command_missing_path", path=filepath)
    if platform.system() == "Windows":
        return validate_windows_executable_path(filepath)
    if not os.access(filepath, os.X_OK):
        return tr("errors.launch_permission_denied", path=filepath)
    if not has_unix_executable_signature(filepath):
        return tr("errors.invalid_executable_file", file=os.path.basename(filepath))
    return None
