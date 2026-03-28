from unittest.mock import Mock

from PyQt6.QtWidgets import QPushButton

from controllers.plugins_controller import PluginsController
from models.download_models import DownloadRecord, DownloadStatus, TargetKind
from models.plugin_models import CatalogPluginEntry
from services.downloads_manager import DownloadsManager
from services.localization_service import tr


def _make_controller(temp_dir):
    downloads_manager = DownloadsManager(temp_dir, lambda: {})
    downloads_manager.startup()
    plugin_catalog_service = Mock()
    plugin_catalog_service.is_loaded.return_value = False
    plugin_catalog_service.get_entry.return_value = None
    controller = PluginsController(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        downloads_manager=downloads_manager,
        plugin_catalog_service=plugin_catalog_service,
        plugin_state_service=Mock(),
        plugin_runtime_service=Mock(),
        plugin_install_service=Mock(),
        app_window=Mock(),
    )
    return controller, downloads_manager, plugin_catalog_service


def test_plugin_download_button_disables_while_busy(qapp, temp_dir):
    controller, downloads_manager, _catalog = _make_controller(temp_dir)
    entry = CatalogPluginEntry(
        id="sample_plugin",
        name="Sample Plugin",
        description="Desc",
        author="Author",
        version="1.0.0",
        api_version=">=1.0.0",
        download_link="https://example.com/plugin.zip",
    )
    button = QPushButton()

    downloads_manager.store.add(
        DownloadRecord(
            id="rec1",
            display_name="Sample Plugin",
            target_kind=TargetKind.PLUGIN,
            download_status=DownloadStatus.DOWNLOADING,
            progress=37,
            metadata={"plugin_id": "sample_plugin"},
        )
    )

    controller._apply_download_button_state(button, entry, True)

    assert button.isEnabled() is False
    assert button.text() == tr("downloads.status_downloading", progress=37)


def test_plugin_active_download_update_does_not_rerender_tab(qapp, temp_dir):
    controller, _downloads_manager, plugin_catalog_service = _make_controller(temp_dir)
    controller.render = Mock()
    controller.refresh_main_tabs = Mock()
    controller._loaded = True
    controller._download_buttons["sample_plugin"] = QPushButton()
    plugin_catalog_service.get_entry.return_value = CatalogPluginEntry(
        id="sample_plugin",
        name="Sample Plugin",
        description="Desc",
        author="Author",
        version="1.0.0",
        api_version=">=1.0.0",
        download_link="https://example.com/plugin.zip",
    )
    record = DownloadRecord(
        id="rec1",
        display_name="Sample Plugin",
        target_kind=TargetKind.PLUGIN,
        download_status=DownloadStatus.DOWNLOADING,
        progress=10,
        metadata={"plugin_id": "sample_plugin"},
    )

    controller._on_download_record_updated(record)

    controller.render.assert_not_called()
    controller.refresh_main_tabs.assert_not_called()
    controller.plugin_runtime_service.scan_installed_plugins.assert_not_called()

    controller.render.reset_mock()
    controller.refresh_main_tabs.reset_mock()
    controller.plugin_runtime_service.scan_installed_plugins.reset_mock()

    completed_record = DownloadRecord(
        id="rec2",
        display_name="Sample Plugin",
        target_kind=TargetKind.PLUGIN,
        download_status=DownloadStatus.DOWNLOADED,
        progress=100,
        metadata={"plugin_id": "sample_plugin"},
    )

    controller._on_download_record_removed(completed_record)

    controller.render.assert_not_called()
    controller.refresh_main_tabs.assert_called_once()
    controller.plugin_runtime_service.scan_installed_plugins.assert_called_once()
