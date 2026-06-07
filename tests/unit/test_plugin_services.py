import json
import os
import time
import zipfile
from unittest.mock import Mock

import pytest

from services.localization_service import localization_service, tr
from services.plugin_catalog_service import PluginCatalogService
from services.plugin_install_service import PluginInstallService
from services.plugin_runtime_service import PluginRuntimeService
from services.plugin_state_service import PluginStateService
from services.plugin_support import PluginValidationError, safe_extract_zip


class _DummySettingsService:
    def __init__(self) -> None:
        self._files = {}

    def read_json(self, path):
        return self._files.get(path)

    def write_json(self, path, data):
        self._files[path] = json.loads(json.dumps(data))


class _CatalogSpy:
    def __init__(self) -> None:
        self.calls = []

    def is_loaded(self):
        return False

    def get_entry(self, plugin_id, *, load_if_needed=True):
        self.calls.append((plugin_id, load_if_needed))
        return None


def _write_plugin(plugins_dir, plugin_id="sample_plugin", api_version=">=1.0.0"):
    plugin_dir = os.path.join(plugins_dir, plugin_id)
    os.makedirs(os.path.join(plugin_dir, "lang"), exist_ok=True)
    with open(
        os.path.join(plugin_dir, "plugin_config.json"),
        "w",
        encoding="utf-8",
        ) as handle:
        json.dump(
            {
                "config_version": 1,
                "id": plugin_id,
                "name": f"plugins.{plugin_id}.name",
                "description": f"plugins.{plugin_id}.description",
                "author": "Tester",
                "version": "1.0.0",
                "api_version": api_version,
                "entry": "plugin.py",
                "tags": ["tool"],
                "relations": {},
                "hooks": [],
                "settings_schema": {},
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    with open(os.path.join(plugin_dir, "plugin.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "class _Plugin:\n"
            "  def on_load(self, context):\n"
            "    self.context = context\n"
            "  def on_after_mod_apply_before_launch(self, context, *args):\n"
            "    self.hook_context = context\n"
            "    return True\n"
            "\n"
            "def create_plugin():\n"
            "  return _Plugin()\n"
        )
    with open(
        os.path.join(plugin_dir, "lang", "lang_en.json"),
        "w",
        encoding="utf-8",
        ) as handle:
        json.dump(
            {
                "name": "Sample Plugin",
                "description": "Sample description",
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )


def _write_dataclass_plugin(plugins_dir, plugin_id="dataclass_plugin"):
    plugin_dir = os.path.join(plugins_dir, plugin_id)
    os.makedirs(os.path.join(plugin_dir, "lang"), exist_ok=True)
    with open(
        os.path.join(plugin_dir, "plugin_config.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {
                "config_version": 1,
                "id": plugin_id,
                "name": f"plugins.{plugin_id}.name",
                "description": f"plugins.{plugin_id}.description",
                "author": "Tester",
                "version": "1.0.0",
                "api_version": ">=1.0.0",
                "entry": "plugin.py",
                "tags": ["tool"],
                "relations": {},
                "hooks": [],
                "settings_schema": {},
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    with open(os.path.join(plugin_dir, "plugin.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "from dataclasses import dataclass\n"
            "\n"
            "@dataclass\n"
            "class _State:\n"
            "  value: str = 'ok'\n"
            "\n"
            "class _Plugin:\n"
            "  def __init__(self):\n"
            "    self.state = _State()\n"
            "\n"
            "def create_plugin():\n"
            "  return _Plugin()\n"
        )
    with open(
        os.path.join(plugin_dir, "lang", "lang_en.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {
                "name": "Dataclass Plugin",
                "description": "Dataclass plugin description",
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )


def test_plugin_state_service_persists_settings_and_filters(temp_dir):
    """Checks that plugin state service persists settings and filters."""
    settings_service = _DummySettingsService()
    service = PluginStateService(settings_service, temp_dir)
    service.set_enabled("alpha", True)
    service.set_plugin_setting("alpha", "path", "C:/test")
    service.set_filters(installed_only=True, tags=["tool", "bad_tag"])
    reloaded = PluginStateService(settings_service, temp_dir)
    assert reloaded.is_enabled("alpha") is True
    assert reloaded.get_plugin_setting("alpha", "path") == "C:/test"
    assert reloaded.get_filters() == {"installed_only": True, "tags": ["tool"]}


def test_plugin_catalog_service_returns_empty_when_cache_is_empty(temp_dir):
    """Checks that plugin catalog service returns empty when cache is empty."""
    app_state = Mock()
    app_state.network_session = None
    settings_service = _DummySettingsService()
    service = PluginCatalogService(app_state, settings_service, temp_dir)
    catalog = service.load_catalog()
    assert service.is_loaded() is False
    assert catalog == {}
    assert service.get_entry("fallback_plugin") is None


def test_plugin_catalog_service_uses_in_memory_cache(temp_dir):
    """Checks that plugin catalog service uses in memory cache."""
    app_state = Mock()
    app_state.network_session = None
    settings_service = _DummySettingsService()
    service = PluginCatalogService(app_state, settings_service, temp_dir)
    service._catalog = {"plugins": [{"id": "cached_plugin", "name": "Cached"}]}
    service._catalog_loaded_at = time.time()

    catalog = service.load_catalog()

    assert catalog["plugins"][0]["id"] == "cached_plugin"
    assert service.get_entry("cached_plugin").name == "Cached"


def test_plugin_runtime_scan_merges_localizations_without_catalog_load(temp_dir):
    """Checks that plugin runtime scan merges localizations without catalog load."""
    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    catalog_spy = _CatalogSpy()
    _write_plugin(temp_dir)
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=catalog_spy,
        plugins_dir=temp_dir,
    )
    installed = runtime.scan_installed_plugins()
    assert "sample_plugin" in installed
    assert catalog_spy.calls == [("sample_plugin", False)]
    assert localization_service.get_text("plugins.sample_plugin.name") == "Sample Plugin"
    assert localization_service.get_text("plugins.sample_plugin.description") == "Sample description"
    localization_service.clear_plugin_strings("sample_plugin")


def test_plugin_runtime_loads_dataclass_plugin(temp_dir):
    """Checks that plugin runtime loads plugins that use dataclasses."""
    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    _write_dataclass_plugin(temp_dir)
    state_service.set_enabled("dataclass_plugin", True)
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=_CatalogSpy(),
        plugins_dir=temp_dir,
    )

    installed = runtime.scan_installed_plugins()

    assert "dataclass_plugin" in installed
    assert installed["dataclass_plugin"].status != "broken"


def test_plugin_runtime_scan_formats_validation_errors(temp_dir):
    """Checks that broken plugin scan errors are localized for the UI."""
    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    plugin_dir = os.path.join(temp_dir, "broken_plugin")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(
        os.path.join(plugin_dir, "plugin_config.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            {
                "config_version": 1,
                "id": "broken_plugin",
                "name": "Broken Plugin",
                "description": "Desc",
                "author": "Tester",
                "version": "1.0.0",
                "api_version": ">=1.0.0",
                "entry": "missing.py",
            },
            handle,
        )
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=_CatalogSpy(),
        plugins_dir=temp_dir,
    )

    installed = runtime.scan_installed_plugins()

    assert installed["broken_plugin"].error == tr(
        "plugins.error_missing_entry", path=plugin_dir
    )


def test_plugin_install_accepts_newer_plugin_api_requirement(temp_dir):
    """Checks that Plugin API mismatch does not block installation."""
    source_root = os.path.join(temp_dir, "source")
    plugins_dir = os.path.join(temp_dir, "installed")
    _write_plugin(source_root, "future_plugin", api_version=">=99.0.0")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    runtime = Mock()
    service = PluginInstallService(state_service, runtime, plugins_dir)

    installed_id = service.install_path(
        os.path.join(source_root, "future_plugin"),
        source="manual",
    )

    assert installed_id == "future_plugin"
    assert os.path.isdir(os.path.join(plugins_dir, "future_plugin"))
    runtime.scan_installed_plugins.assert_not_called()


def test_plugin_runtime_allows_enabling_newer_plugin_api_requirement(temp_dir):
    """Checks that Plugin API mismatch is not treated as runtime incompatibility."""
    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    _write_plugin(temp_dir, "future_plugin", api_version=">=99.0.0")
    state_service.set_enabled("future_plugin", True)
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=_CatalogSpy(),
        plugins_dir=temp_dir,
    )

    installed = runtime.scan_installed_plugins()

    assert installed["future_plugin"].compatible is True
    assert installed["future_plugin"].enabled is True
    assert installed["future_plugin"].status == "installed"
    assert "future_plugin" in runtime._enabled_instances


def test_plugin_runtime_reports_enabled_hook_and_passes_task_runtime(temp_dir):
    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    _write_plugin(temp_dir, "hook_plugin")
    state_service.set_enabled("hook_plugin", True)
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=_CatalogSpy(),
        plugins_dir=temp_dir,
    )

    runtime.scan_installed_plugins()

    assert runtime.has_enabled_hook("after_mod_apply_before_launch") is True
    task_runtime = Mock()
    results = runtime.execute_hook_with_runtime(
        "after_mod_apply_before_launch",
        task_runtime,
        {"deltarune_1": []},
        False,
    )

    assert results == [True]
    assert runtime._instances["hook_plugin"].hook_context.task_runtime is task_runtime


def test_plugin_runtime_reports_enabled_shortcut_hook_and_passes_shortcut_context(
    temp_dir,
):
    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    _write_plugin(temp_dir, "shortcut_hook_plugin")
    plugin_dir = os.path.join(temp_dir, "shortcut_hook_plugin")
    with open(os.path.join(plugin_dir, "plugin_config.json"), encoding="utf-8") as handle:
        plugin_config = json.load(handle)
    plugin_config["hooks"] = [
        "before_mod_apply_shortcut",
        "after_mod_apply_before_launch_shortcut",
    ]
    with open(
        os.path.join(plugin_dir, "plugin_config.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(plugin_config, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(plugin_dir, "plugin.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "class _Plugin:\n"
            "  def on_before_mod_apply_shortcut(self, context, shortcut_context, *args):\n"
            "    shortcut_context.set_plugin_state('shortcut_hook_plugin', {'selected': 'alpha'})\n"
            "    shortcut_context.add_summary_line('Collection', 'alpha')\n"
            "    self.capture_context = context\n"
            "    return True\n"
            "  def on_after_mod_apply_before_launch_shortcut(self, context, shortcut_context, *args):\n"
            "    self.launch_context = context\n"
            "    self.shortcut_context = shortcut_context\n"
            "    return shortcut_context.get_plugin_state('shortcut_hook_plugin')\n"
            "\n"
            "def create_plugin():\n"
            "  return _Plugin()\n"
        )
    state_service.set_enabled("shortcut_hook_plugin", True)
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=_CatalogSpy(),
        plugins_dir=temp_dir,
    )

    runtime.scan_installed_plugins()

    from services.shortcut_plugin_service import ShortcutPluginContext

    shortcut_context = ShortcutPluginContext({"game_id": "deltarune"})
    capture_results = runtime.execute_hook(
        "before_mod_apply_shortcut",
        shortcut_context,
    )
    launch_results = runtime.execute_hook(
        "after_mod_apply_before_launch_shortcut",
        shortcut_context,
    )

    assert runtime.has_enabled_hook("before_mod_apply_shortcut") is True
    assert capture_results == [True]
    assert launch_results == [{"selected": "alpha"}]
    assert shortcut_context.plugin_states == {
        "shortcut_hook_plugin": {"selected": "alpha"}
    }
    assert shortcut_context.summary_lines == [("Collection", "alpha")]


def test_plugin_runtime_context_uses_plugin_scoped_feedback(temp_dir, monkeypatch, qapp):
    from ui.common import feedback as feedback_module
    from ui.common.feedback import FeedbackManager

    localization_service.clear_plugin_strings()
    localization_service.load_language("en")
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, temp_dir)
    _write_plugin(temp_dir, "sample_plugin")
    runtime = PluginRuntimeService(
        app_state=Mock(local_config={}),
        feedback_service=FeedbackManager(),
        settings_service=Mock(),
        profile_service=Mock(),
        game_registry_service=Mock(),
        customization_service=Mock(),
        downloads_manager=Mock(),
        plugin_state_service=state_service,
        plugin_catalog_service=_CatalogSpy(),
        plugins_dir=temp_dir,
    )
    runtime.scan_installed_plugins()

    box = Mock()
    box.Icon = Mock()
    box.StandardButton = Mock(Yes=1, No=2)
    box.setIcon = Mock()
    box.setWindowTitle = Mock()
    box.setText = Mock()
    box.setStandardButtons = Mock()
    box.setDefaultButton = Mock()
    box.exec = Mock(return_value=1)
    factory = Mock(return_value=box)
    factory.Icon = feedback_module.QMessageBox.Icon
    factory.StandardButton = feedback_module.QMessageBox.StandardButton
    monkeypatch.setattr(feedback_module, "QMessageBox", factory)

    context = runtime._build_context("sample_plugin")
    context.feedback_service.ask_question("name", "description")

    box.setWindowTitle.assert_called_once_with("Sample Plugin")
    assert "Sample description" in box.setText.call_args.args[0]


def test_plugin_install_service_accepts_plugin_folder(temp_dir):
    """Checks that plugin install service accepts plugin folder."""
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, os.path.join(temp_dir, "state"))
    plugins_dir = os.path.join(temp_dir, "plugins")
    source_dir = os.path.join(temp_dir, "source_plugin")
    _write_plugin(source_dir, "folder_plugin")
    install_service = PluginInstallService(
        plugin_state_service=state_service,
        plugin_runtime_service=Mock(scan_installed_plugins=Mock()),
        plugins_dir=plugins_dir,
    )

    plugin_id = install_service.install_path(source_dir, source="manual")

    assert plugin_id == "folder_plugin"
    assert os.path.isfile(os.path.join(plugins_dir, "folder_plugin", "plugin_config.json"))
    assert os.path.isfile(os.path.join(source_dir, "folder_plugin", "plugin_config.json"))
    assert os.path.isfile(os.path.join(source_dir, "folder_plugin", "plugin.py"))
    assert state_service.get_install_meta("folder_plugin")["local"] is True
    install_service.plugin_runtime_service.scan_installed_plugins.assert_not_called()


def test_plugin_install_service_accepts_plugin_zip(temp_dir):
    """Checks that plugin install service accepts plugin zip."""
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, os.path.join(temp_dir, "state"))
    plugins_dir = os.path.join(temp_dir, "plugins")
    source_dir = os.path.join(temp_dir, "source_zip")
    _write_plugin(source_dir, "zip_plugin")
    archive_path = os.path.join(temp_dir, "plugin.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(source_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                archive.write(file_path, os.path.relpath(file_path, source_dir))
    install_service = PluginInstallService(
        plugin_state_service=state_service,
        plugin_runtime_service=Mock(scan_installed_plugins=Mock()),
        plugins_dir=plugins_dir,
    )

    plugin_id = install_service.install_path(archive_path, source="manual")

    assert plugin_id == "zip_plugin"
    assert os.path.isfile(os.path.join(plugins_dir, "zip_plugin", "plugin_config.json"))


def test_plugin_install_service_accepts_deeply_nested_plugin_zip(temp_dir):
    """Checks that plugin install service accepts deeply nested plugin zip."""
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, os.path.join(temp_dir, "state"))
    plugins_dir = os.path.join(temp_dir, "plugins")
    source_dir = os.path.join(temp_dir, "source_nested")
    _write_plugin(source_dir, "nested_plugin")
    archive_path = os.path.join(temp_dir, "nested_plugin.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(source_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                archive.write(
                    file_path,
                    os.path.join(
                        "level1",
                        "level2",
                        "level3",
                        os.path.relpath(file_path, source_dir),
                    ),
                )
    install_service = PluginInstallService(
        plugin_state_service=state_service,
        plugin_runtime_service=Mock(scan_installed_plugins=Mock()),
        plugins_dir=plugins_dir,
    )

    plugin_id = install_service.install_path(archive_path, source="manual")

    assert plugin_id == "nested_plugin"
    assert os.path.isfile(
        os.path.join(plugins_dir, "nested_plugin", "plugin_config.json")
    )


def test_plugin_install_delete_does_not_touch_runtime_from_install_service(temp_dir):
    """Checks that plugin file deletion does not execute runtime hooks directly."""
    settings_service = _DummySettingsService()
    state_service = PluginStateService(settings_service, os.path.join(temp_dir, "state"))
    plugins_dir = os.path.join(temp_dir, "plugins")
    _write_plugin(plugins_dir, "delete_plugin")
    runtime = Mock()
    install_service = PluginInstallService(
        plugin_state_service=state_service,
        plugin_runtime_service=runtime,
        plugins_dir=plugins_dir,
    )
    state_service.set_enabled("delete_plugin", True)

    install_service.delete_plugin("delete_plugin")

    runtime.disable_plugin.assert_not_called()
    assert not os.path.exists(os.path.join(plugins_dir, "delete_plugin"))
    assert state_service.is_enabled("delete_plugin") is False


def test_plugin_zip_extraction_rejects_excessive_uncompressed_size(
    temp_dir, monkeypatch
):
    """Checks that plugin archives are size-checked before extraction."""
    import services.plugin_support as plugin_support

    archive_path = os.path.join(temp_dir, "huge_plugin.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin_config.json", "{}")
    monkeypatch.setattr(plugin_support, "MAX_PLUGIN_ARCHIVE_UNCOMPRESSED_BYTES", 1)

    with pytest.raises(PluginValidationError) as exc_info:
        safe_extract_zip(archive_path, os.path.join(temp_dir, "out"))
    assert str(exc_info.value) == "archive_too_large"


def test_plugin_zip_extraction_rejects_too_many_members(temp_dir, monkeypatch):
    """Checks that plugin archives are member-count checked before extraction."""
    import services.plugin_support as plugin_support

    archive_path = os.path.join(temp_dir, "many_plugin.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.txt", "a")
        archive.writestr("b.txt", "b")
    monkeypatch.setattr(plugin_support, "MAX_PLUGIN_ARCHIVE_MEMBERS", 1)

    with pytest.raises(PluginValidationError) as exc_info:
        safe_extract_zip(archive_path, os.path.join(temp_dir, "out"))
    assert str(exc_info.value) == "archive_too_many_files"
