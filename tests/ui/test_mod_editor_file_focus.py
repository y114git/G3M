import pytest
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLineEdit, QWidget

from ui.builders.shared_filters_builder import create_downloads_button
from ui.dialogs.mod_editor.dialog import ModEditorDialog


@pytest.mark.parametrize("file_type", ["data", "extra"])
def test_added_file_path_is_focused_and_visible(qtbot, app_state, file_type):
    parent = QWidget()
    parent.app_state = app_state
    qtbot.addWidget(parent)
    dialog = ModEditorDialog(parent)
    dialog.setStyleSheet(dialog.styleSheet() + "QWidget { font-size: 16pt; }")
    dialog.resize(900, 600)
    dialog.show()
    dialog.activateWindow()
    tab = dialog.file_tabs.widget(0)
    if file_type == "data":
        dialog._on_add_data(tab, tab._file_layout)
    else:
        dialog._on_add_extra(tab._file_layout)
    property_name = "is_local_path" if file_type == "data" else "is_local_extra_path"
    path = next(w for w in tab.findChildren(QLineEdit) if w.property(property_name))
    qtbot.waitUntil(path.hasFocus)
    qtbot.waitUntil(lambda: path.visibleRegion().boundingRect() == path.rect())
    assert (
        dialog._save_button.visibleRegion().boundingRect() == dialog._save_button.rect()
    )
    dialog.close()


def test_icon_field_precedes_browse_button_and_preview(qtbot, app_state):
    parent = QWidget()
    parent.app_state = app_state
    qtbot.addWidget(parent)
    dialog = ModEditorDialog(parent)
    qtbot.addWidget(dialog)
    dialog.resize(1000, 700)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.icon_preview.width() == 72)
    assert dialog.icon_edit.x() < dialog.icon_browse_btn.x() < dialog.icon_preview.x()
    assert dialog.icon_edit.width() > dialog.icon_browse_btn.width()
    assert dialog.icon_browse_btn.objectName() == "downloadsBtn"
    downloads_button = create_downloads_button(app_state)
    qtbot.addWidget(downloads_button)
    downloads_button.show()
    assert dialog.icon_browse_btn.size() == downloads_button.size()

    image = QPixmap(16, 16)
    image.fill(QColor("#ff0000"))
    dialog._set_icon_pixmap(image)
    preview = dialog.icon_preview.pixmap().toImage()
    assert preview.pixelColor(1, 36) == QColor(dialog._color("border", "#039d5b"))
