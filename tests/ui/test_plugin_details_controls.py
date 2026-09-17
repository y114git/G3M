from unittest.mock import Mock

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QLineEdit

from models.plugin_models import InstalledPluginRecord, PluginManifest
from ui.dialogs.plugin_details_dialog import PluginDetailsDialog


def test_plugin_setting_label_and_default_close(qtbot, app_state, tmp_path):
    manifest = PluginManifest(
        config_version=1,
        id="settings_check",
        name="Settings Check",
        description="Settings",
        author="Author",
        version="1.0",
        entry="plugin.py",
        settings_schema={
            "fields": [{"key": "name", "type": "string", "label": "Name"}]
        },
    )
    plugin = InstalledPluginRecord(manifest=manifest, path=str(tmp_path))
    dialog = PluginDetailsDialog(
        plugin,
        Mock(get_settings_widget=Mock(return_value=None)),
        Mock(get_plugin_setting=Mock(return_value="")),
        app_state,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    field = dialog.findChild(QLineEdit)
    assert any(label.buddy() is field for label in dialog.findChildren(QLabel))
    assert dialog._close_button.isVisible()
    field.setFocus()
    qtbot.keyClick(field, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not dialog.isVisible())
    assert not dialog.delete_requested
    assert not dialog.download_requested
