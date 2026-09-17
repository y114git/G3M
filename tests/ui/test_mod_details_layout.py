from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from models.mod_models import BrowserModInfo
from ui.widgets.mod_details_overlay import show_mod_details_overlay


def test_details_actions_stay_visible_above_scrolling_content(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(960, 600)
    host.show()
    mod = BrowserModInfo.from_dict(
        {
            "name": "Chapter One music pack",
            "author": "Music workshop",
            "game": "deltarune",
            "full_description": "<p>Battle and exploration tracks.</p>" * 50,
        }
    )
    overlay = show_mod_details_overlay(host, mod)
    qtbot.waitUntil(lambda: overlay.close_button.hasFocus())
    assert not overlay._img_label.parentWidget().isVisible()
    for button in (overlay.action_button, overlay.close_button):
        assert button.visibleRegion().boundingRect() == button.rect()
    qtbot.keyClick(overlay.close_button, Qt.Key.Key_Escape)
    assert overlay.dialog_closed
