import importlib.util
from pathlib import Path
from types import SimpleNamespace

from models.game_modes import get_game


def _load_plugin_module():
    plugin_path = (
        Path(__file__).resolve().parents[2]
        / "catalog"
        / "plugins"
        / "custom_saves_folders"
        / "plugin.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_custom_saves_folders_plugin",
        plugin_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PluginSettings:
    def __init__(self) -> None:
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class _Localization:
    MESSAGES = {
        "ui.title": "Custom Save Folders",
        "ui.games_title": "Games",
        "ui.folders_title": "Custom Save Folders",
        "ui.empty_games": "No games available.",
        "ui.empty_folders": "No custom save folders yet.",
        "ui.empty_selection": "Select a game to manage custom save folders.",
        "ui.use_button": "Use Folder",
        "ui.folder_item_hint": "Hint",
        "ui.current_game_hint": "Hint",
        "ui.add_folder": "Add custom save folder",
        "ui.name_label": "Save folder name",
        "ui.name_placeholder": "Folder name",
        "ui.name_hint": "Name hint",
        "ui.create_button": "Create",
        "ui.cancel_button": "Cancel",
        "ui.delete_tooltip": "Delete",
        "ui.add_tooltip": "Add",
        "ui.applying_status": "Applying...",
        "ui.applying_progress": "Applying {current}/{total}...",
        "ui.applied_status": 'Applied custom save folder "{name}" for {game}.',
        "ui.restored_status": "Restored original data files.",
        "dialogs.delete_title": "Delete custom save folder?",
        "dialogs.delete_body": "{name}",
        "errors.name_required": "Enter a save folder name.",
        "errors.name_too_long": "Too long.",
        "errors.name_invalid_chars": "Invalid chars.",
        "errors.name_invalid_suffix": "Invalid suffix.",
        "errors.name_reserved": "Reserved.",
        "errors.folder_exists": "Already exists.",
        "errors.selection_missing": "Select a game first.",
        "errors.game_path_missing": "Game path missing.",
        "errors.data_file_missing": "Data file missing for {game}.",
        "errors.script_missing": "Script missing.",
        "errors.g3mtool_missing": "G3MTool missing.",
        "errors.apply_failed": "Apply failed: {error}",
        "errors.restore_failed": "Restore failed: {error}",
    }

    def get_plugin_tr(self, _plugin_id):
        def _tr(key, **kwargs):
            template = self.MESSAGES.get(key, key)
            return template.format(**kwargs) if kwargs else template

        return _tr


class _Feedback:
    def __init__(self) -> None:
        self.messages = []
        self.statuses = []

    def show_message(self, level, title, message):
        self.messages.append((level, title, message))

    def update_status(self, message, color):
        self.statuses.append((message, color))


def _build_context(plugin_settings, app_state, game_registry):
    return SimpleNamespace(
        plugin_settings=plugin_settings,
        app_state=app_state,
        game_registry_service=game_registry,
        feedback_service=_Feedback(),
        localization_service=_Localization(),
    )


def test_state_store_add_select_remove():
    module = _load_plugin_module()
    settings = _PluginSettings()
    state = module._StateStore(settings, None)

    assert state.add_folder("undertale", "Save One") is None
    assert state.get_folders("undertale") == ["Save One"]
    assert state.get_selected("undertale") == "Save One"

    assert state.add_folder("undertale", "Save One") == "errors.folder_exists"
    assert state.add_folder("undertale", "CON") == "errors.name_reserved"
    assert state.add_folder("undertale", "bad/name") == "errors.name_invalid_chars"

    assert state.add_folder("undertale", "Save Two") is None
    state.select_folder("undertale", "Save One")
    assert state.get_selected("undertale") == "Save One"

    state.remove_folder("undertale", "Save One")
    assert state.get_folders("undertale") == ["Save Two"]
    assert state.get_selected("undertale") == "Save Two"

    state.clear_selected("undertale")
    assert state.get_selected("undertale") == ""


def test_plugin_applies_and_restores_deltarune_targets(tmp_path, monkeypatch):
    module = _load_plugin_module()
    game_dir = tmp_path / "deltarune"
    game_dir.mkdir()
    targets = [game_dir / "data.win"]
    for chapter in range(1, 5):
        chapter_dir = game_dir / f"chapter{chapter}_windows"
        chapter_dir.mkdir()
        targets.append(chapter_dir / "data.win")
    for index, path in enumerate(targets):
        path.write_text(f"original-{index}", encoding="utf-8")

    class _FakeG3MTool:
        def __init__(self) -> None:
            self.calls = []

        def is_available(self):
            return True

        def execute(self, script_path, args=None, data_file=None, output_path=None, **_kwargs):
            self.calls.append((script_path, args, data_file, output_path))
            current_name = args[0]
            contents = Path(data_file).read_text(encoding="utf-8")
            Path(output_path).write_text(
                f"{contents}|name={current_name}",
                encoding="utf-8",
            )
            return 0, "", ""

    fake_tool = _FakeG3MTool()
    monkeypatch.setattr(module, "G3MToolManager", lambda: fake_tool)
    monkeypatch.setattr(module, "get_user_data_root", lambda: str(tmp_path / "user"))

    settings = _PluginSettings()
    settings.set("folders_by_game", {"deltarune": ["ModdedSave"]})
    settings.set("selected_by_game", {"deltarune": "ModdedSave"})
    app_state = SimpleNamespace(
        local_config={"game_path": str(game_dir)},
        game_mode=get_game("deltarune"),
    )
    game_registry = SimpleNamespace(list_visible_games=lambda: [])
    context = _build_context(settings, app_state, game_registry)

    plugin = module.create_plugin()
    plugin.on_load(context)

    assert plugin.on_after_mod_apply_before_launch(context, {}, True) is True
    assert len(fake_tool.calls) == 5
    for path in targets:
        assert path.read_text(encoding="utf-8").endswith("|name=ModdedSave")

    assert plugin.on_before_restore_after_exit(context, False) is True
    for index, path in enumerate(targets):
        assert path.read_text(encoding="utf-8") == f"original-{index}"


def test_plugin_main_widget_lists_visible_games(qapp):
    module = _load_plugin_module()
    settings = _PluginSettings()
    app_state = SimpleNamespace(local_config={})
    visible_games = [
        SimpleNamespace(id="undertale", display_name="UNDERTALE"),
        SimpleNamespace(id="custom_game_test", display_name="My Custom Game"),
    ]
    host_context = _build_context(
        settings,
        app_state,
        SimpleNamespace(list_visible_games=lambda: visible_games),
    )
    ui_context = SimpleNamespace(
        app_state=app_state,
        host_context=host_context,
    )

    plugin = module.create_plugin()
    plugin.on_load(host_context)
    widget = plugin.create_main_widget(ui_context, None)

    assert widget.games_list.count() == 2
    assert widget._game_rows["undertale"].title == "UNDERTALE"
    assert widget._game_rows["custom_game_test"].title == "My Custom Game"

    widget.deleteLater()


def test_plugin_cancellation_restores_files(tmp_path, monkeypatch):
    module = _load_plugin_module()
    game_dir = tmp_path / "deltarune"
    game_dir.mkdir()
    target = game_dir / "data.win"
    target.write_text("original", encoding="utf-8")

    class _FakeG3MTool:
        def is_available(self):
            return True

        def execute(self, script_path, args=None, data_file=None, output_path=None, **_kwargs):
            Path(output_path).write_text("patched", encoding="utf-8")
            return 0, "", ""

    class _TaskRuntime:
        def __init__(self) -> None:
            self.calls = 0

        def set_status(self, *_args):
            return None

        def set_progress(self, *_args):
            return None

        def raise_if_cancelled(self):
            self.calls += 1
            if self.calls > 1:
                raise InterruptedError("cancelled")

    monkeypatch.setattr(module, "G3MToolManager", lambda: _FakeG3MTool())
    monkeypatch.setattr(module, "get_user_data_root", lambda: str(tmp_path / "user"))
    monkeypatch.setattr(
        module,
        "get_game",
        lambda _game_id: SimpleNamespace(
            display_label="DELTARUNE",
            tabs=[SimpleNamespace(tab_id="deltarune_0")],
            get_game_path=lambda _config: str(game_dir),
        ),
    )
    monkeypatch.setattr(module, "find_chapter_resource_dir", lambda game_path, *_args, **_kwargs: game_path)
    monkeypatch.setattr(module, "find_supported_game_data_file", lambda resource_dir, **_kwargs: str(target))

    settings = _PluginSettings()
    settings.set("folders_by_game", {"deltarune": ["ModdedSave"]})
    settings.set("selected_by_game", {"deltarune": "ModdedSave"})
    app_state = SimpleNamespace(local_config={}, game_mode=SimpleNamespace(game_id="deltarune"))
    context = _build_context(settings, app_state, SimpleNamespace(list_visible_games=lambda: []))
    context.task_runtime = _TaskRuntime()

    plugin = module.create_plugin()
    plugin.on_load(context)

    assert plugin.on_after_mod_apply_before_launch(context, {}, False) is False
    assert target.read_text(encoding="utf-8") == "original"
