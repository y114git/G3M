"""Persistent bootstrap pointer for the active G3M data directory."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path

LOCATOR_FILENAME = "data-root.json"
LOCATOR_VERSION = 1


class UserDataLocatorError(RuntimeError):
    """Raised when the saved data location cannot be read safely."""


def _normalized_absolute(path: str | os.PathLike[str]) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(os.fspath(path))))


def get_locator_path(default_root: str | os.PathLike[str]) -> Path:
    return Path(_normalized_absolute(default_root)) / LOCATOR_FILENAME


def read_selected_user_data_root(default_root: str | os.PathLike[str]) -> str | None:
    locator_path = get_locator_path(default_root)
    if not locator_path.exists():
        return None
    try:
        payload = json.loads(locator_path.read_text(encoding="utf-8"))
        version = payload.get("version") if isinstance(payload, dict) else None
        selected_path = payload.get("path") if isinstance(payload, dict) else None
        if version != LOCATOR_VERSION or not isinstance(selected_path, str) or not selected_path.strip():
            raise ValueError("unsupported or incomplete locator")
        return _normalized_absolute(selected_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise UserDataLocatorError(
            f"The saved G3M data location is invalid: {locator_path}: {error}"
        ) from error


def clear_selected_user_data_root(default_root: str | os.PathLike[str]) -> None:
    try:
        get_locator_path(default_root).unlink(missing_ok=True)
    except OSError as error:
        raise UserDataLocatorError(
            f"Could not reset the saved G3M data location: {error}"
        ) from error


def write_selected_user_data_root(
    default_root: str | os.PathLike[str], selected_root: str | os.PathLike[str]
) -> None:
    default_path = _normalized_absolute(default_root)
    selected_path = _normalized_absolute(selected_root)
    if os.path.normcase(default_path) == os.path.normcase(selected_path):
        clear_selected_user_data_root(default_path)
        return

    locator_path = get_locator_path(default_path)
    locator_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{locator_path.name}.", suffix=".tmp", dir=locator_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"version": LOCATOR_VERSION, "path": selected_path},
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, locator_path)
    except OSError as error:
        with suppress(OSError):
            os.unlink(temporary_path)
        raise UserDataLocatorError(
            f"Could not save the G3M data location: {error}"
        ) from error
