import json
import os
import time
import zipfile
from unittest.mock import Mock

from services.localization_service import localization_service
from services.plugin_catalog_service import PluginCatalogService
from services.plugin_install_service import PluginInstallService
from services.plugin_runtime_service import PluginRuntimeService
from services.plugin_state_service import PluginStateService


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


def _write_plugin(plugins_dir, plugin_id="sample_plugin"):
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
                "api_version": "1.0.0",
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
            "    def on_load(self, context):\n"
            "        self.context = context\n"
            "\n"
            "def create_plugin():\n"
            "    return _Plugin()\n"
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


def test_plugin_state_service_persists_settings_and_filters(temp_dir):
    """Checks that plugining state service persists settings and filters."""
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
    """Checks that plugining catalog service returns empty when cache is empty."""
    app_state = Mock()
    app_state.network_session = None
    settings_service = _DummySettingsService()
    service = PluginCatalogService(app_state, settings_service, temp_dir)
    catalog = service.load_catalog()
    assert service.is_loaded() is False
    assert catalog == {}
    assert service.get_entry("fallback_plugin") is None


def test_plugin_catalog_service_uses_in_memory_cache(temp_dir):
    """Checks that plugining catalog service uses in memory cache."""
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
    """Checks that plugining runtime scan merges localizations without catalog load."""
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


def test_plugin_install_service_accepts_plugin_folder(temp_dir):
    """Checks that plugining install service accepts plugin folder."""
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


def test_plugin_install_service_accepts_plugin_zip(temp_dir):
    """Checks that plugining install service accepts plugin zip."""
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
    """Checks that plugining install service accepts deeply nested plugin zip."""
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
