"""Unit tests for ModManager manual-install handoff."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QObject

from services.mod.service import ModManager


class _Parent(QObject):
    pass


def test_manual_install_handoff_clears_finished_url_install_task(temp_dir, qapp):
    current_task = Mock()
    app_state = SimpleNamespace(
        is_installing=True,
        current_task=current_task,
        clear_current_task=Mock(side_effect=lambda: setattr(app_state, "current_task", None)),
    )
    parent = _Parent()
    manager = ModManager(app_state, Mock(), parent=parent)
    statuses = []
    manager.status_changed.connect(lambda message, color: statuses.append((message, color)))

    manager._on_manual_install_required(
        prepared_path=temp_dir,
        archive_path="archive.zip",
        temp_dir=temp_dir,
    )

    assert app_state.is_installing is False
    app_state.clear_current_task.assert_called_once()
    assert app_state.current_task is None
    assert statuses


def test_manual_install_error_cleans_temp_dir_if_feedback_fails(tmp_path, qapp):
    temp_dir = tmp_path / "manual"
    temp_dir.mkdir()
    app_state = SimpleNamespace(
        is_installing=True,
        current_task=Mock(),
        clear_current_task=Mock(),
    )
    parent = _Parent()
    parent.pizza_oven_conversion_presenter = Mock()
    parent.pizza_oven_conversion_presenter.prompt_with_manual_options.side_effect = (
        RuntimeError("presenter failed")
    )
    parent.feedback_service = Mock()
    parent.feedback_service.show_message.side_effect = RuntimeError("feedback failed")
    manager = ModManager(app_state, Mock(), parent=parent)

    manager._on_manual_install_required(
        prepared_path=str(temp_dir),
        archive_path="archive.zip",
        temp_dir=str(temp_dir),
    )

    assert not temp_dir.exists()
