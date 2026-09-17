from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from ui.widgets.shared.custom_title_bar import CustomTitleBar


def test_title_bar_menu_restores_focus(qapp) -> None:
    host = QWidget()
    title_bar = CustomTitleBar(host, SimpleNamespace(local_config={}))
    title_bar.set_localized_texts(
        "Windows",
        "Logs",
        "Support",
        "Help",
        "Changelog",
        "Tour",
        "About",
        "Minimize",
        "Maximize",
        "Restore",
        "Close",
    )
    host.show()
    qapp.processEvents()

    title_bar.windows_button.setFocus()
    QTest.keyClick(title_bar.windows_button, Qt.Key.Key_Space)
    qapp.processEvents()
    assert title_bar.windows_menu.isVisible()
    QTest.keyClick(title_bar.windows_menu, Qt.Key.Key_Escape)
    qapp.processEvents()

    assert title_bar.windows_button.hasFocus()
    host.close()
