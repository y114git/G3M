"""Prepares user-data paths needed during bootstrap."""

from __future__ import annotations

import logging
import os
import shutil

from PyQt6.QtWidgets import QMessageBox

from services.localization_service import tr
from utils.path_utils import (
    get_default_user_data_root,
    get_legacy_user_data_root,
    set_user_data_root_override,
)

logger = logging.getLogger(__name__)


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


def resolve_user_data_root_with_migration() -> str:
    g3m_root = get_default_user_data_root()
    legacy_root = get_legacy_user_data_root()

    if os.path.exists(g3m_root):
        return _use_user_data_root(g3m_root)

    if os.path.exists(legacy_root):
        if _ask_user_data_migration_choice(legacy_root, g3m_root):
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
