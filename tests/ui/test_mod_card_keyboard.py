from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from models.mod_models import ModInfo
from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget


def test_search_card_keyboard_selection_details_and_actions(qtbot):
    host = QWidget()
    host.app_state = SimpleNamespace(local_config={})
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    mod = ModInfo(
        id="keyboard_mod",
        name="Keyboard Mod",
        version="1.0.0",
        author="Author",
        description="Description",
        game_version="",
        description_url="",
        downloads=0,
        game="deltarune",
    )
    with patch("ui.widgets.mod.search_mod_card_widget.load_mod_icon_universal"):
        card = SearchModCardWidget(mod, parent=host)
        layout.addWidget(card)
        card.clicked.connect(lambda _: card.set_selected(True))
        host.show()
        host.activateWindow()
        card.setFocus()
        qtbot.waitUntil(card.hasFocus)
        assert card.accessibleName() == mod.name
        qtbot.keyClick(card, Qt.Key.Key_Space)
        assert card.is_selected
        with qtbot.waitSignal(card.details_requested) as signal:
            qtbot.keyClick(card, Qt.Key.Key_Return)
        assert signal.args == [mod]
        qtbot.keyClick(card, Qt.Key.Key_Tab)
        qtbot.waitUntil(card.details_button.hasFocus)
        assert card.is_selected
        assert card.details_button.isVisible()
        with qtbot.waitSignal(card.details_requested):
            qtbot.keyClick(card.details_button, Qt.Key.Key_Space)
        qtbot.keyClick(card.details_button, Qt.Key.Key_Tab)
        qtbot.waitUntil(card.action_button.hasFocus)
        assert card.is_selected
        assert card.action_button.isVisible()
