"""Shared safe dialog helpers."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)


def safe_question(
    parent,
    title: str,
    message: str,
    buttons,
    default_button,
    *,
    log_message: str = "Confirmation dialog failed",
):
    try:
        return QMessageBox.question(parent, title, message, buttons, default_button)
    except Exception:
        logger.warning(log_message, exc_info=True)
        return default_button
