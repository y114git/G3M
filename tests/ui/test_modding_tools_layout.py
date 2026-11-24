
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QDialog, QLayout, QLayoutItem, QScrollArea

from ui.dialogs.modding_tools_dialog import (
    ModdingToolsDialog,
    _DiffTab,
    _MergeTab,
    _PatchTab,
)


@pytest.mark.parametrize("tab_type", [_MergeTab, _PatchTab])
def test_batch_form_scrolls_without_overlapping_controls(qtbot, app_state, tab_type):
    tab = tab_type(Mock(), app_state)
    qtbot.addWidget(tab)
    tab.setStyleSheet("QWidget { font-size: 16pt; }")
    tab.resize(900, 440)
    tab._batch_cb.setChecked(True)
    tab.show()
    scroll = tab.findChild(QScrollArea)
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().maximum() > 0)
    scroll.ensureWidgetVisible(tab._run_btn)
    qtbot.waitUntil(
        lambda: tab._run_btn.visibleRegion().boundingRect() == tab._run_btn.rect()
    )
    if isinstance(tab, _MergeTab):
        list_bottom = tab._file_list.mapTo(tab, QPoint(0, tab._file_list.height())).y()
        button_top = tab._add_btn.mapTo(tab, QPoint()).y()
        assert button_top >= list_bottom


def test_diff_tab_places_full_report_above_centered_compare(qtbot, app_state):
    tab = _DiffTab(Mock(), app_state)
    qtbot.addWidget(tab)
    tab.resize(1000, 500)
    tab.show()

    assert cast(QLayoutItem, cast(QLayout, tab.layout()).itemAt(0)).widget() is tab._full_report_cb
    assert abs(tab._run_btn.geometry().center().x() - tab.rect().center().x()) <= 1



def test_modding_tools_tabs_and_actions_fit_small_screen(qtbot, app_state, monkeypatch):
    available = QRect(0, 0, 800, 600)
    monkeypatch.setattr(QDialog, "screen", lambda _self: SimpleNamespace(availableGeometry=lambda: available))
    dialog = ModdingToolsDialog(Mock(), app_state)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.width() <= available.width()
    assert dialog.height() <= available.height()
    for index in range(dialog._tabs.count()):
        dialog._tabs.setCurrentIndex(index)
        page = dialog._tabs.currentWidget()
        assert page is not None
        assert page.isVisible()
        assert dialog._close_btn.visibleRegion().boundingRect() == dialog._close_btn.rect()
    qtbot.mouseClick(dialog._close_btn, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()


def test_open_in_studio_button_follows_the_file_and_the_setting(qtbot, app_state, tmp_path):
    tab = _DiffTab(Mock(), app_state)
    qtbot.addWidget(tab)
    tab.show()
    row = tab._file1_row
    assert row._studio_btn is not None
    assert row._studio_btn.isHidden()
    data = tmp_path / "data.win"
    data.write_bytes(b"x")
    row.set_path(str(data))
    assert not row._studio_btn.isHidden()
    app_state.local_config["show_open_in_studio"] = False
    row.set_path(str(data) + " ")
    assert row._studio_btn.isHidden()
