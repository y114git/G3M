
from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from ui.dialogs.mod.updates_dialog import ModUpdatesDialog


def test_mod_updates_dialog_groups_and_emits_selected_updates(qapp):
    dialog = ModUpdatesDialog(
        SimpleNamespace(local_config={}), ["Default"], "Default"
    )
    requested = []
    dialog.updates_requested.connect(lambda updates, replace: requested.append((updates, replace)))
    candidate = {
        "id": "gb_mod_123",
        "name": "Example",
        "game": "deltarune",
        "version": "1.0.0",
        "resolved": {"metadata": {"version": "2.0.0"}},
    }
    second_candidate = {**candidate, "id": "gb_mod_456", "name": "Another"}

    dialog.set_candidates([candidate, second_candidate])
    dialog._request_updates()

    assert dialog._tree.topLevelItemCount() == 1
    assert dialog.minimumWidth() >= 840
    game_item = dialog._tree.topLevelItem(0)
    assert dialog._tree.rootIsDecorated()
    assert dialog._tree.itemsExpandable()
    assert game_item is not None
    assert game_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert game_item is not None
    assert game_item.childCount() == 2
    assert game_item is not None
    game_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert game_item is not None
    assert all(
        cast(QTreeWidgetItem, game_item.child(index)).checkState(0) == Qt.CheckState.Unchecked
        for index in range(game_item.childCount())
    )
    assert game_item is not None
    cast(QTreeWidgetItem, game_item.child(0)).setCheckState(0, Qt.CheckState.Checked)
    dialog.relocalize_ui()
    game_item = dialog._tree.topLevelItem(0)
    assert game_item is not None
    assert cast(QTreeWidgetItem, game_item.child(0)).checkState(0) == Qt.CheckState.Checked
    assert game_item is not None
    assert cast(QTreeWidgetItem, game_item.child(1)).checkState(0) == Qt.CheckState.Unchecked
    assert "QTreeWidget::indicator" in dialog.styleSheet()
    assert requested == [([second_candidate, candidate], False)]


def test_mod_updates_dialog_keeps_manual_install_outcome_after_refresh(qapp):
    dialog = ModUpdatesDialog(
        SimpleNamespace(local_config={}), ["Default"], "Default"
    )

    dialog.set_outcome("Manual installation is required in Downloads.")
    dialog.set_checking(preserve_outcome=True)
    dialog.set_candidates([])

    assert not dialog._outcome.isHidden()
    assert dialog._outcome.text() == "Manual installation is required in Downloads."


def test_mod_updates_dialog_progress_reaches_the_final_value(qapp):
    dialog = ModUpdatesDialog(
        SimpleNamespace(local_config={"disable_animations": True}), ["Default"], "Default"
    )

    dialog.set_progress(1, 4, "First")
    dialog.set_progress(4, 4, "Last")

    assert dialog._progress.value() == dialog._progress.maximum()


def test_mod_updates_dialog_one_mod_fills_the_bar_in_many_small_steps(qapp):
    dialog = ModUpdatesDialog(
        SimpleNamespace(local_config={"disable_animations": True}), ["Default"], "Default"
    )
    values = []
    for fraction in (0.0, 0.1, 0.35, 0.6, 0.85):
        dialog.set_progress(0, 1, "Only mod", fraction)
        values.append(dialog._progress.value())

    assert values == sorted(set(values))
    assert 0 < values[1] < values[2] < values[3] < values[4] < dialog._progress.maximum()


def test_mod_updates_dialog_keeps_moving_while_a_mod_installs(qapp):
    dialog = ModUpdatesDialog(
        SimpleNamespace(local_config={"disable_animations": True}), ["Default"], "Default"
    )
    dialog.set_progress(1, 2, "Second", 0.85, installing=True)
    start = dialog._progress.value()
    for _ in range(20):
        dialog._creep_installing()
    creeping = dialog._progress.value()
    dialog.set_progress(2, 2, "Done")

    assert start < creeping < dialog._progress.maximum()
    assert not dialog._creep.isActive()
    assert dialog._progress.value() == dialog._progress.maximum()


def test_mod_updates_dialog_stops_creeping_when_the_batch_ends(qapp):
    dialog = ModUpdatesDialog(
        SimpleNamespace(local_config={"disable_animations": True}), ["Default"], "Default"
    )
    dialog.set_progress(0, 1, "Only mod", 0.85, installing=True)
    assert dialog._creep.isActive()

    dialog.set_busy(False)

    assert not dialog._creep.isActive()
