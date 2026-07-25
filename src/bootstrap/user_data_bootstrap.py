"""Prepares user-data paths needed during bootstrap."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from bootstrap.user_data_locator import (
    UserDataLocatorError,
    clear_selected_user_data_root,
    read_selected_user_data_root,
    write_selected_user_data_root,
)
from services.localization_service import tr
from utils.path_utils import (
    get_default_user_data_root,
    get_legacy_user_data_root,
    set_user_data_root_override,
)

logger = logging.getLogger(__name__)


class UserDataRootUnavailableError(RuntimeError):
    """Raised when the configured data directory cannot be used."""


def _ask_unavailable_root_action(error: Exception) -> tuple[str, str]:
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("data_root.unavailable_title"))
    box.setText(tr("data_root.unavailable_message", error=str(error)))
    retry_button = box.addButton(
        tr("data_root.retry"), QMessageBox.ButtonRole.AcceptRole
    )
    choose_button = box.addButton(
        tr("data_root.choose_another"), QMessageBox.ButtonRole.ActionRole
    )
    default_button = box.addButton(
        tr("data_root.use_default"), QMessageBox.ButtonRole.DestructiveRole
    )
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is retry_button:
        return "retry", ""
    if clicked is choose_button:
        selected = QFileDialog.getExistingDirectory(
            None, tr("data_root.select_directory")
        )
        return ("choose", selected) if selected else ("cancel", "")
    if clicked is default_button:
        return "default", ""
    return "cancel", ""


def _ask_user_data_migration_choice(legacy_root: str, target_root: str) -> bool:
    message_box = QMessageBox()
    message_box.setIcon(QMessageBox.Icon.Question)
    message_box.setWindowTitle(tr("startup.user_data_migration_title"))
    message_box.setText(
        tr(
            "startup.user_data_migration_message",
            legacy_root=legacy_root,
            target_root=target_root,
        )
    )
    message_box.setInformativeText(tr("startup.user_data_migration_details"))
    migrate_button = message_box.addButton(
        tr("startup.user_data_migration_move"), QMessageBox.ButtonRole.YesRole
    )
    message_box.addButton(tr("startup.user_data_migration_fresh"), QMessageBox.ButtonRole.NoRole)
    message_box.setDefaultButton(migrate_button)
    message_box.exec()
    return message_box.clickedButton() is migrate_button


def _use_user_data_root(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    set_user_data_root_override(path)
    return path


def _copy_missing_entries(source_root: str, target_root: str) -> None:
    for entry in os.listdir(source_root):
        source_path = os.path.join(source_root, entry)
        target_path = os.path.join(target_root, entry)
        if os.path.exists(target_path):
            continue
        if os.path.islink(source_path):
            os.symlink(os.readlink(source_path), target_path)
        elif os.path.isdir(source_path):
            shutil.copytree(source_path, target_path)
        else:
            shutil.copy2(source_path, target_path)


def _safe_warning(title: str, message: str) -> None:
    try:
        QMessageBox.warning(None, title, message)
    except Exception:
        logger.exception("Failed to show user data bootstrap warning")


def _validate_selected_root(path: str) -> str:
    if not os.path.isdir(path):
        raise UserDataRootUnavailableError(
            f"The configured G3M data location is not available: {path}"
        )
    probe_path = ""
    try:
        descriptor, probe_path = tempfile.mkstemp(prefix=".g3m-write-test-", dir=path)
        os.close(descriptor)
        os.unlink(probe_path)
        probe_path = ""
    except OSError as error:
        raise UserDataRootUnavailableError(
            f"The configured G3M data location is not writable: {path}"
        ) from error
    finally:
        if probe_path:
            with contextlib.suppress(OSError):
                os.unlink(probe_path)
    set_user_data_root_override(path)
    return path


def resolve_user_data_root_with_migration(*, interactive: bool = True) -> str:
    g3m_root = get_default_user_data_root()
    legacy_root = get_legacy_user_data_root()

    while True:
        try:
            selected_root = read_selected_user_data_root(g3m_root)
            if selected_root is not None:
                return _validate_selected_root(selected_root)
            break
        except (UserDataLocatorError, UserDataRootUnavailableError) as error:
            if not interactive:
                raise
            action, selected_path = _ask_unavailable_root_action(error)
            if action == "retry":
                continue
            if action == "choose" and selected_path:
                _validate_selected_root(selected_path)
                write_selected_user_data_root(g3m_root, selected_path)
                continue
            if action == "default":
                clear_selected_user_data_root(g3m_root)
                break
            raise UserDataRootUnavailableError(
                f"G3M cannot start without an available data location: {error}"
            ) from error

    if os.path.exists(g3m_root):
        return _use_user_data_root(g3m_root)

    if os.path.exists(legacy_root):
        if interactive and _ask_user_data_migration_choice(legacy_root, g3m_root):
            try:
                os.makedirs(g3m_root, exist_ok=True)
                _copy_missing_entries(legacy_root, g3m_root)
            except OSError as error:
                logger.error(
                    "Failed to copy legacy data into %s: %s",
                    g3m_root,
                    error,
                    exc_info=True,
                )
                _safe_warning(
                    tr("startup.user_data_migration_failed_title"),
                    tr(
                        "startup.user_data_migration_failed_message",
                        error=str(error),
                    ),
                )
        return _use_user_data_root(g3m_root)

    return _use_user_data_root(g3m_root)
