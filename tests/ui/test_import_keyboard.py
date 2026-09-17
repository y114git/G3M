from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog

from ui.dialogs.import_dialog import ImportDialog


@pytest.mark.parametrize("kind", ["mods", "themes", "game_versions", "mod_versions"])
def test_enter_in_url_field_imports_url_without_opening_file_picker(
    qtbot, monkeypatch, kind
):
    file_picker = Mock(return_value=("", ""))
    monkeypatch.setattr("ui.dialogs.import_dialog.get_open_file_name", file_picker)
    dialog = ImportDialog(None, Mock(), kind)
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.url_import_button.isEnabled()
    assert dialog.url_label.buddy() is dialog.url_input
    dialog.url_input.setText(" https://example.com/mod.zip ")
    dialog.url_input.setFocus()
    assert dialog.url_import_button.isEnabled()
    qtbot.keyClick(dialog.url_input, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.import_method == "url"
    assert dialog.selected_url == "https://example.com/mod.zip"
    file_picker.assert_not_called()
