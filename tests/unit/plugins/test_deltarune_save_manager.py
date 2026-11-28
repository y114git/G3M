from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QComboBox, QFrame, QLabel, QLineEdit, QVBoxLayout

PLUGIN_DIR = (
    Path(__file__).resolve().parents[3]
    / "catalog"
    / "plugins"
    / "deltarune_save_manager"
)
SAVE_MANAGER_PATH = PLUGIN_DIR / "save_manager.py"
SAVE_EDITOR_PATH = PLUGIN_DIR / "save_editor.py"
PLUGIN_PATH = PLUGIN_DIR / "plugin.py"


class _PluginSettings:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def get_config(self, key, default=None):
        return self.get(key, default)

    def set_config(self, key, value):
        self.set(key, value)


class _Feedback:
    def __init__(self) -> None:
        self.messages = []

    def show_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    def ask_question(self, *_args, **_kwargs):
        return True


class _SettingsManager:
    def __init__(self) -> None:
        self.picked_path = ""

    def pick_directory(self, *_args, **_kwargs):
        return self.picked_path


def _module():
    name = "_deltarune_save_manager_for_test"
    spec = importlib.util.spec_from_file_location(name, SAVE_MANAGER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _editor_module():
    name = "_deltarune_save_editor_for_test"
    spec = importlib.util.spec_from_file_location(name, SAVE_EDITOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _plugin_module():
    name = "_deltarune_save_manager_plugin_for_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _manager(module, tmp_path: Path):
    return module.SaveManager(
        app_state=SimpleNamespace(
            local_config={},
            game_mode=SimpleNamespace(game_id="deltarune", steam_app_id="1671210"),
        ),
        feedback_manager=_Feedback(),
        settings_manager=_SettingsManager(),
        plugin_api=_PluginSettings(),
        parent=None,
    )


def _write_save(path: Path, chapter: int = 1, slot: int = 0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / f"filech{chapter}_{slot}").write_text("KRIS\n", encoding="utf-8")


def test_find_and_validate_save_path_keeps_explicit_custom_path(tmp_path):
    module = _module()
    manager = _manager(module, tmp_path)
    custom_path = tmp_path / "custom_saves"
    _write_save(custom_path)
    manager.save_path = str(custom_path)

    assert manager.find_and_validate_save_path() is True
    assert Path(manager.save_path) == custom_path


def test_find_and_validate_save_path_resets_deleted_explicit_path(tmp_path):
    module = _module()
    manager = _manager(module, tmp_path)
    deleted_path = tmp_path / "missing_saves"
    manager.save_path = str(deleted_path)
    manager.settings_manager.picked_path = ""

    assert manager.find_and_validate_save_path() is False
    assert manager.save_path == ""


def test_find_and_validate_save_path_uses_deltarune_data_folder(tmp_path, monkeypatch):
    module = _module()
    manager = _manager(module, tmp_path)
    configured_path = tmp_path / "configured_saves"
    _write_save(configured_path)
    manager.app_state.game_mode = SimpleNamespace(game_id="pizzatower")
    monkeypatch.setattr(
        module,
        "get_game",
        lambda game_id: (
            SimpleNamespace(get_data_path=lambda _config: str(configured_path))
            if game_id == "deltarune"
            else None
        ),
    )

    assert manager.find_and_validate_save_path() is True
    assert Path(manager.save_path) == configured_path


def test_launch_collection_prompt_skips_when_path_missing(tmp_path):
    module = _module()
    manager = _manager(module, tmp_path)
    manager.save_path = str(tmp_path / "missing_saves")

    assert manager.prompt_for_save_collection_on_launch() == -1


@pytest.mark.parametrize("selection", [-1, 0, None, "cancel_task"])
@pytest.mark.parametrize("create_in_worker", [False, True])
def test_launch_collection_prompt_runs_on_gui_thread(
    tmp_path, qapp, qtbot, selection, create_in_worker
):
    module = _module()
    manager = _manager(module, tmp_path)
    _write_save(tmp_path / "saves")
    _write_save(tmp_path / "saves" / "Collection_0")
    manager.save_path = str(tmp_path / "saves")
    cancelled = Event()
    runtime = SimpleNamespace(is_cancelled=cancelled.is_set)
    results = []
    errors = []
    shown = []

    class Worker(QThread):
        def run(self):
            try:
                current = _manager(module, tmp_path) if create_in_worker else manager
                if create_in_worker:
                    current.save_path = manager.save_path
                results.append(current.prompt_for_save_collection_on_launch(runtime))
            except Exception as error:
                errors.append(error)

    worker = Worker()
    timer = QTimer()

    def choose():
        dialog = next(
            (
                w
                for w in qapp.topLevelWidgets()
                if isinstance(w, module.DynamicDialog) and w.isVisible()
            ),
            None,
        )
        if dialog is None:
            return
        timer.stop()
        combo = dialog.findChild(QComboBox)
        combo.setCurrentIndex(1)
        dialog._app_state.local_config["custom_background_color"] = "#123456"
        dialog.apply_theme()
        dialog.rescale_ui()
        dialog.relocalize_ui()
        assert combo.currentData() == 0
        assert "#123456" in dialog.styleSheet()
        shown.append((QThread.currentThread(), dialog.thread(), dialog.styleSheet()))
        if selection == "cancel_task":
            cancelled.set()
        elif selection is None:
            dialog.reject()
        else:
            combo.setCurrentIndex(combo.findData(selection))
            dialog.accept()

    timer.timeout.connect(choose)
    timer.start(10)
    worker.start()
    try:
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)
        qtbot.waitUntil(
            lambda: (
                not any(
                    isinstance(w, module.DynamicDialog) and w.isVisible()
                    for w in qapp.topLevelWidgets()
                )
            ),
            timeout=2000,
        )
        assert not errors
        assert results == [None if selection == "cancel_task" else selection]
        assert len(shown) == 1
        assert shown[0][0] == qapp.thread() == shown[0][1]
        assert shown[0][2]
    finally:
        timer.stop()
        worker.requestInterruption()
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=3000)
        worker.wait()


def test_slot_height_sync_settles_and_stops_when_deleted(qapp, qtbot):
    module = _plugin_module()._load_local_module(
        "save_manager_view_builder.py", "_save_view_for_test"
    )
    calls = []

    class Label(module._SlotHeightSyncMixin, QLabel):
        def _sync_slot_height(self):
            calls.append(self.text())
            super()._sync_slot_height()

    row = QFrame()
    qtbot.addWidget(row)
    layout = QVBoxLayout(row)
    label = Label("KRIS", row)
    label._slot_row = row
    layout.addWidget(label)
    row.show()
    for _ in range(20):  # slow runners deliver the last layout events late
        seen = len(calls)
        qtbot.wait(100)
        if len(calls) == seen:
            break
    initial = len(calls)
    qtbot.wait(100)
    assert len(calls) == initial
    label.setText("KRIS\nLevel 1")
    qtbot.wait(100)
    assert label.height() == row.height()
    assert label.height() >= label.fontMetrics().lineSpacing() * 2
    label.setText("Pending update")
    label.deleteLater()
    qtbot.wait(30)


def test_rebuilding_panel_disconnects_deleted_controller(tmp_path, qapp, qtbot):
    from PyQt6 import sip

    module = _plugin_module()
    manager = _manager(_module(), tmp_path)
    state = manager.app_state
    plugin = module.DRSaveManagerPlugin()
    plugin._save_manager_instance = lambda parent=None: manager
    plugin._tr = lambda: (lambda key, **kwargs: key)
    controllers = []
    for _ in range(3):
        widget = plugin.create_main_widget(SimpleNamespace(app_state=state), None)
        controller = widget._plugin_controller
        controllers.append(controller)
        assert manager.receivers(manager.slots_updated) == 1
        widget.deleteLater()
        qtbot.waitUntil(lambda current=widget: sip.isdeleted(current))
        assert sip.isdeleted(controller)
        assert manager.receivers(manager.slots_updated) == 0
        manager.slots_updated.emit()
        plugin.on_theme_changed(None)
        plugin.on_language_changed(None)


@pytest.mark.parametrize("cancel_launch", [False, True])
def test_collection_launch_hook_round_trip(tmp_path, qapp, qtbot, cancel_launch):
    from workers.plugin_hook_worker import PluginHookThread

    module = _plugin_module()
    manager_module = _module()
    manager = _manager(manager_module, tmp_path)
    saves = tmp_path / "saves"
    _write_save(saves)
    _write_save(saves / "Collection_0")
    (saves / "filech1_0").write_text("original", encoding="utf-8")
    (saves / "Collection_0" / "filech1_0").write_text("collection", encoding="utf-8")
    manager.save_path = str(saves)
    plugin = module.DRSaveManagerPlugin()
    plugin._save_manager_instance = lambda: manager

    def execute(hook, task_runtime, *args):
        context = SimpleNamespace(
            app_state=manager.app_state, task_runtime=task_runtime
        )
        return [getattr(plugin, "on_" + hook)(context, *args)]

    worker = PluginHookThread(
        SimpleNamespace(execute_hook_with_runtime=execute),
        "before_mod_apply",
        (),
        base_progress=0,
        progress_span=100,
    )
    results = []
    worker.result_ready.connect(results.append)
    timer = QTimer()

    def choose():
        dialog = next(
            (
                w
                for w in qapp.topLevelWidgets()
                if isinstance(w, manager_module.DynamicDialog) and w.isVisible()
            ),
            None,
        )
        if dialog is None:
            return
        timer.stop()
        if cancel_launch:
            worker.cancel()
        else:
            dialog.findChild(QComboBox).setCurrentIndex(1)
            dialog.accept()

    timer.timeout.connect(choose)
    timer.start(10)
    worker.start()
    try:
        qtbot.waitUntil(lambda: bool(results) and not worker.isRunning(), timeout=5000)
        qtbot.waitUntil(
            lambda: (
                not any(
                    isinstance(w, manager_module.DynamicDialog) and w.isVisible()
                    for w in qapp.topLevelWidgets()
                )
            ),
            timeout=2000,
        )
        assert results == [not cancel_launch]
        assert (saves / "filech1_0").read_text(encoding="utf-8") == (
            "original" if cancel_launch else "collection"
        )
        plugin.on_after_restore_after_exit(None)
        assert (saves / "filech1_0").read_text(encoding="utf-8") == "original"
        assert not list(saves.glob("*.g3m_backup"))
    finally:
        timer.stop()
        worker.cancel()
        qtbot.waitUntil(lambda: not worker.isRunning(), timeout=3000)
        worker.wait()


def test_other_game_does_not_prompt_for_deltarune_saves():
    plugin = _plugin_module().DRSaveManagerPlugin()
    plugin._save_manager_instance = Mock()
    context = SimpleNamespace(
        app_state=SimpleNamespace(game_mode=SimpleNamespace(game_id="undertale"))
    )
    assert plugin.on_before_mod_apply(context) is True
    plugin._save_manager_instance.assert_not_called()


def test_keep_changes_retains_save_backup_until_game_exit(tmp_path, monkeypatch):
    manager = _manager(_module(), tmp_path)
    plugin = _plugin_module().DRSaveManagerPlugin()
    active_save = tmp_path / "filech1_0"
    backup = tmp_path / "filech1_0.g3m_backup"
    active_save.write_text("selected collection", encoding="utf-8")
    backup.write_text("original save", encoding="utf-8")
    plugin._backup_info = {str(active_save): str(backup), "__empty_slots__": {}}
    monkeypatch.setattr(plugin, "_save_manager_instance", lambda: manager)

    assert (
        plugin.on_after_mod_apply_committed(None, {"mode": "launch_keep_changes"})
        is True
    )

    assert active_save.read_text(encoding="utf-8") == "selected collection"
    assert backup.read_text(encoding="utf-8") == "original save"
    plugin.on_after_restore_after_exit(None)
    assert active_save.read_text(encoding="utf-8") == "original save"
    assert not backup.exists()
    assert plugin._backup_info == {}


def test_patching_only_restores_selected_save_collection(monkeypatch):
    module = _plugin_module()
    plugin = module.DRSaveManagerPlugin()
    manager = SimpleNamespace(
        restore_original_saves_after_launch=Mock(),
    )
    plugin._backup_info = {"active": "backup"}
    monkeypatch.setattr(plugin, "_save_manager_instance", lambda: manager)

    assert (
        plugin.on_after_mod_apply_committed(None, {"mode": "launch_patching_only"})
        is True
    )

    manager.restore_original_saves_after_launch.assert_called_once_with(
        {"active": "backup"}
    )
    assert plugin._backup_info == {}


def test_current_tenna_data_includes_all_five_chapters_and_associations():
    module = _editor_module()
    data = module.load_simple_mode_data()

    assert set(data["chapters"]["meta"]) == {"1", "2", "3", "4", "5"}
    assert len(data["flags"]["ids"]) >= 1400
    assert len(data["rooms"]["ids"]) >= 1000
    assert data["storySections"]["5"]
    assert data["plotPoints"]["5"]["ids"]
    assert data["flagBitfields"]["meta"]


def test_save_editor_mode_pages_use_the_theme_background(tmp_path, qapp):
    module = _editor_module()
    save_path = tmp_path / "filech1_0"
    save_path.write_text("KRIS\n", encoding="utf-8")
    app_state = SimpleNamespace(local_config={"custom_background_color": "#123456"})
    dialog = module.SaveEditorDialog(str(save_path), app_state)

    try:
        assert dialog._simple_tab.objectName() == "saveEditorModePage"
        assert dialog._advanced_tab.objectName() == "saveEditorModePage"
        assert "QWidget#saveEditorModePage" in dialog.styleSheet()
        assert "rgba(18, 52, 86, 128)" in dialog.styleSheet()
    finally:
        dialog.close()


def test_operation_round_trip_preserves_extended_flag_tail():
    module = _editor_module()
    character = {
        "health": 1,
        "maxHealth": 1,
        "attack": 1,
        "defence": 1,
        "magic": 1,
        "guts": 1,
        "weapon": 0,
        "primaryArmor": 0,
        "secondaryArmor": 0,
        "weaponStyle": 0,
        "weaponStats": [
            {
                "attack": 0,
                "defence": 0,
                "magic": 0,
                "bolts": 0,
                "grazeAmount": 0,
                "grazeSize": 0,
                "boltSpeed": 0,
                "special": 0,
                "element": 0,
                "elementAmount": 0,
            }
            for _ in range(4)
        ],
        "spells": [0] * 12,
    }
    save = {
        "meta": {"format": 2, "chapter": 5, "slot": 0},
        "playerName": "KRIS",
        "vesselName": "",
        "party": [0, 1, 2],
        "money": 0,
        "xp": 0,
        "lv": 1,
        "inv": 0,
        "invc": 0,
        "inDarkWorld": True,
        "characters": [dict(character) for _ in range(5)],
        "battle": {
            "boltSpeed": 0,
            "grazeAmount": 0,
            "grazeSize": 0,
            "tension": 0,
            "maxTension": 100,
        },
        "inventory": {
            "consumables": [0] * 13,
            "keyItems": [0] * 13,
            "weapons": [0] * 48,
            "armors": [0] * 48,
            "storage": [0] * 72,
        },
        "lightWorld": {
            "weapon": 0,
            "armor": 0,
            "experience": 0,
            "level": 1,
            "money": 0,
            "health": 1,
            "maxHealth": 1,
            "attack": 1,
            "defence": 1,
            "weaponStrength": 0,
            "armorDefence": 0,
            "items": [0] * 8,
            "phone": [0] * 8,
        },
        "flags": [0] * 2509,
        "plot": 0,
        "room": 0,
        "time": 0,
    }
    save["flags"][-1] = 123

    lines = module.serialize_save_data(save)
    parsed = module.parse_save_lines(lines, 5, 0)

    assert len(parsed["flags"]) == 2509
    assert parsed["flags"][-1] == 123
    assert module.serialize_save_data(parsed) == lines


def test_save_editor_cell_editor_fits_its_row(tmp_path, qapp, qtbot):
    module = _editor_module()
    save_path = tmp_path / "filech1_0"
    save_path.write_text("KRIS\n", encoding="utf-8")
    dialog = module.SaveEditorDialog(str(save_path), SimpleNamespace(local_config={}))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.mode_tabs.setCurrentWidget(dialog._advanced_tab)
    dialog.table.editItem(dialog.table.item(0, 2))
    viewport = dialog.table.viewport()
    qtbot.waitUntil(lambda: bool(viewport.findChildren(QLineEdit)))
    editor = viewport.findChildren(QLineEdit)[0]
    # the dialog-wide field padding and height must neither squash the in-cell editor nor spill it over other rows
    assert editor.sizeHint().height() <= editor.height() <= dialog.table.rowHeight(0)
