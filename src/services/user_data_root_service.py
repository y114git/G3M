"""Validation and preparation for changing the active G3M data directory."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field

from bootstrap.user_data_locator import LOCATOR_FILENAME

logger = logging.getLogger(__name__)


class DataRootValidationError(ValueError):
    """Raised when a proposed data directory is unsafe or unusable."""

    def __init__(self, error_key: str) -> None:
        self.error_key = error_key
        super().__init__(error_key)


@dataclass(frozen=True, slots=True)
class DataRootChangeResult:
    status: str
    selected_path: str
    error: str = ""
    error_key: str = ""
    error_args: dict[str, str] = field(default_factory=dict)


def _normalize(path: str) -> str:
    if not str(path or "").strip():
        raise DataRootValidationError("select_directory")
    return os.path.normpath(os.path.abspath(os.path.expanduser(path)))


def _is_within(path: str, parent: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath((path, parent))) == os.path.normcase(parent)
    except ValueError:
        return False


def _verify_writable(directory: str) -> None:
    descriptor, probe = tempfile.mkstemp(prefix=".g3m-write-test-", dir=directory)
    os.close(descriptor)
    os.unlink(probe)


def validate_data_root_change(source: str, destination: str) -> str:
    source_path = _normalize(source)
    destination_path = _normalize(destination)
    resolved_source = os.path.normcase(os.path.realpath(source_path))
    resolved_destination = os.path.normcase(os.path.realpath(destination_path))
    if resolved_source == resolved_destination:
        raise DataRootValidationError("already_active")
    if _is_within(resolved_destination, resolved_source) or _is_within(
        resolved_source, resolved_destination
    ):
        raise DataRootValidationError("directories_overlap")
    if os.path.exists(destination_path) and not os.path.isdir(destination_path):
        raise DataRootValidationError("not_directory")
    return destination_path


def _copy_root(
    source: str,
    destination: str,
    cancelled: Callable[[], bool],
) -> DataRootChangeResult:
    entries = [entry for entry in os.scandir(source) if entry.name != LOCATOR_FILENAME]
    conflicts = [entry.name for entry in entries if os.path.lexists(os.path.join(destination, entry.name))]
    if conflicts:
        return DataRootChangeResult(
            "conflict",
            destination,
            error_key="destination_conflict",
            error_args={"entries": ", ".join(sorted(conflicts))},
        )
    for entry in entries:
        if cancelled():
            return DataRootChangeResult("cancelled", destination)
        target = os.path.join(destination, entry.name)
        if entry.is_symlink():
            os.symlink(os.readlink(entry.path), target, target_is_directory=entry.is_dir(follow_symlinks=False))
        elif entry.is_dir(follow_symlinks=False):
            shutil.copytree(entry.path, target, symlinks=True)
        else:
            shutil.copy2(entry.path, target, follow_symlinks=False)
    return DataRootChangeResult("ready", destination)


def prepare_data_root_change(
    source: str,
    destination: str,
    *,
    copy_data: bool,
    cancelled: Callable[[], bool] | None = None,
) -> DataRootChangeResult:
    try:
        destination_path = validate_data_root_change(source, destination)
        is_cancelled = cancelled or (lambda: False)
        if is_cancelled():
            return DataRootChangeResult("cancelled", destination_path)
        if not copy_data:
            os.makedirs(destination_path, exist_ok=True)
            _verify_writable(destination_path)
            return DataRootChangeResult("ready", destination_path)

        parent = os.path.dirname(destination_path)
        os.makedirs(parent, exist_ok=True)
        if os.path.exists(destination_path) and not os.path.isdir(destination_path):
            raise DataRootValidationError("not_directory")
        source_path = _normalize(source)
        source_entries = [
            entry.name for entry in os.scandir(source_path) if entry.name != LOCATOR_FILENAME
        ]
        conflicts = [
            name for name in source_entries if os.path.lexists(os.path.join(destination_path, name))
        ]
        if conflicts:
            return DataRootChangeResult(
                "conflict",
                destination_path,
                error_key="destination_conflict",
                error_args={"entries": ", ".join(sorted(conflicts))},
            )

        staging_path = tempfile.mkdtemp(prefix=".g3m-data-stage-", dir=parent)
        backup_path = ""
        try:
            if os.path.isdir(destination_path):
                shutil.copytree(
                    destination_path, staging_path, dirs_exist_ok=True, symlinks=True
                )
            result = _copy_root(source_path, staging_path, is_cancelled)
            if result.status != "ready":
                return DataRootChangeResult(
                    result.status,
                    destination_path,
                    result.error,
                    result.error_key,
                    result.error_args,
                )
            if os.path.isdir(destination_path):
                backup_path = tempfile.mkdtemp(prefix=".g3m-data-old-", dir=parent)
                os.rmdir(backup_path)
                os.replace(destination_path, backup_path)
            try:
                os.replace(staging_path, destination_path)
                staging_path = ""
            except OSError:
                if backup_path and not os.path.exists(destination_path):
                    os.replace(backup_path, destination_path)
                    backup_path = ""
                raise
            if backup_path:
                try:
                    shutil.rmtree(backup_path)
                except OSError as error:
                    logger.warning(
                        "Committed data-root migration but could not remove backup %s: %s",
                        backup_path,
                        error,
                    )
                backup_path = ""
            return DataRootChangeResult("ready", destination_path)
        finally:
            if staging_path:
                shutil.rmtree(staging_path, ignore_errors=True)
            if backup_path and not os.path.exists(destination_path):
                with contextlib.suppress(OSError):
                    os.replace(backup_path, destination_path)
    except DataRootValidationError as error:
        return DataRootChangeResult(
            "invalid",
            os.path.normpath(str(destination)),
            error=error.error_key,
            error_key=error.error_key,
        )
    except OSError as error:
        return DataRootChangeResult(
            "io_error",
            os.path.normpath(str(destination)),
            error=str(error),
            error_key="io_error",
            error_args={"error": str(error)},
        )
