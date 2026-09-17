from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QScrollArea

from ui.dialogs.modding_tools_dialog import _DiffTab, _MergeTab, _PatchTab


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

    assert tab.layout().itemAt(0).widget() is tab._full_report_cb
    assert abs(tab._run_btn.geometry().center().x() - tab.rect().center().x()) <= 1
