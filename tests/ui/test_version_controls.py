from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QScrollArea

from models.game_version_models import GameVersionRecord
from ui.dialogs.game.create_version_dialog import CreateVersionDialog
from ui.dialogs.game.versions_dialog import _VersionRecordWidget
from ui.dialogs.mod.versions_dialog import _VersionItemWidget


def test_create_version_requires_name_and_preserves_profile(qtbot, app_state):
    dialog = CreateVersionDialog("DELTARUNE", app_state, ["Music"])
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog._ok_button.isEnabled()
    assert dialog._name_label.buddy() is dialog._name_input
    assert not dialog._name_label.text().startswith("[")
    dialog._name_input.setText("   ")
    assert not dialog._ok_button.isEnabled()
    qtbot.keyClick(dialog._name_input, Qt.Key.Key_Return)
    assert dialog.isVisible()
    dialog._name_input.setText("Chapter One")
    assert dialog._ok_button.isEnabled()
    dialog._profile_combo.setCurrentIndex(1)
    assert dialog._profile_label.buddy() is dialog._profile_combo
    qtbot.keyClick(dialog._name_input, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.version_name == "Chapter One"
    assert dialog.selected_profile == "Music"


@pytest.mark.parametrize("kind", ["mod", "game"])
def test_long_version_name_keeps_actions_inside_viewport(qtbot, app_state, kind):
    scroll = QScrollArea()
    qtbot.addWidget(scroll)
    scroll.setWidgetResizable(True)
    scroll.resize(500, 380)
    name = "ChapterOne" * 30
    if kind == "mod":
        row = _VersionItemWidget({"name": name})
        buttons = [row._switch_btn, row._delete_btn]
    else:
        manager = Mock()
        manager.is_busy.return_value = False
        row = _VersionRecordWidget(
            GameVersionRecord(archive_path=name + ".zip"), manager, app_state
        )
        buttons = [row._apply_btn, row._export_btn, row._delete_btn]
    row.setFont(QFont("Arial", 16))
    scroll.setWidget(row)
    scroll.show()
    qtbot.waitUntil(lambda: row.isVisible())
    assert row.width() <= scroll.viewport().width()
    assert row._name_label.wordWrap()
    for button in buttons:
        assert button.visibleRegion().boundingRect() == button.rect()
