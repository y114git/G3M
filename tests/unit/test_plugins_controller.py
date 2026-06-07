from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtWidgets import QPushButton

from app.dialogs import on_downloads_record_updated
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
    plugin_runtime_service = Mock()
    plugin_runtime_service.get_plugin.return_value = None
    controller = PluginsController(
        app_state=Mock(local_config={}),
        feedback_service=Mock(),
        downloads_manager=downloads_manager,
        plugin_catalog_service=plugin_catalog_service,
        plugin_state_service=Mock(),
        plugin_runtime_service=plugin_runtime_service,
        plugin_install_service=Mock(),
        app_window=Mock(),
    )
    return controller, downloads_manager, plugin_catalog_service


def test_plugin_download_button_disables_while_busy(qapp, temp_dir):
    """Checks that plugin download button disables while busy."""
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


def test_plugin_download_button_allows_incompatible_api(qapp, temp_dir):
    """Checks that Plugin API mismatch warns but does not disable download."""
    controller, _downloads_manager, _catalog = _make_controller(temp_dir)
    entry = CatalogPluginEntry(
        id="future_plugin",
        name="Future Plugin",
        description="Desc",
        author="Author",
        version="1.0.0",
        api_version=">=99.0.0",
        download_link="https://example.com/plugin.zip",
    )
    button = QPushButton()

    controller._apply_download_button_state(button, entry, False)

    assert button.isEnabled() is True
    assert button.text() == tr("plugins.action_download")


def test_incompatible_plugin_download_requires_confirmation(qapp, temp_dir, monkeypatch):
    """Checks that users can cancel an incompatible Plugin API download."""
    controller, _downloads_manager, _catalog = _make_controller(temp_dir)
    controller.downloads_manager.enqueue_with_feedback = Mock()
    entry = CatalogPluginEntry(
        id="future_plugin",
        name="Future Plugin",
        description="Desc",
        author="Author",
        version="1.0.0",
        api_version=">=99.0.0",
        download_link="https://example.com/plugin.zip",
    )

    class FakeMessageBox:
        Icon = SimpleNamespace(Warning="warning")
        ButtonRole = SimpleNamespace(AcceptRole="accept")
        StandardButton = SimpleNamespace(Cancel="cancel")
        accept_next = False

        def __init__(self, parent=None) -> None:
            self.accept_button = object()
            self.clicked = None

        def setIcon(self, icon):  # noqa: N802
            self.icon = icon

        def setWindowTitle(self, title):  # noqa: N802
            self.title = title

        def setText(self, text):  # noqa: N802
            self.text = text

        def addButton(self, *args):  # noqa: N802
            if len(args) == 2:
                return self.accept_button
            return object()

        def setDefaultButton(self, button):  # noqa: N802
            self.default = button

        def exec(self):
            self.clicked = self.accept_button if self.accept_next else object()

        def clickedButton(self):  # noqa: N802
            return self.clicked

    monkeypatch.setattr("controllers.plugins_controller.QMessageBox", FakeMessageBox)

    controller.download_plugin(entry)

    controller.downloads_manager.enqueue_with_feedback.assert_not_called()

    FakeMessageBox.accept_next = True
    controller.download_plugin(entry)

    controller.downloads_manager.enqueue_with_feedback.assert_called_once()


def test_catalog_details_dialog_replaces_homepage_open(qapp, temp_dir, monkeypatch):
    """Checks that catalog Details opens a dialog instead of opening homepage."""
    controller, _downloads_manager, plugin_catalog_service = _make_controller(temp_dir)
    entry = CatalogPluginEntry(
        id="catalog_plugin",
        name="Catalog Plugin",
        description="Desc",
        author="Author",
        version="1.0.0",
        api_version=">=1.0.0",
        homepage="https://example.com",
        download_link="https://example.com/plugin.zip",
    )
    plugin_catalog_service.get_entry.return_value = entry
    created = {}

    class FakeDialog:
        def __init__(self, plugin, runtime_service, state_service, app_state, **kwargs) -> None:
            created["plugin"] = plugin
            created["kwargs"] = kwargs
            self.download_requested = False
            self.delete_requested = False

        def exec(self):
            created["exec"] = True

    monkeypatch.setattr("controllers.plugins_controller.PluginDetailsDialog", FakeDialog)
    controller.render = Mock()

    controller.show_plugin_details("catalog_plugin")

    assert created["plugin"] is None
    assert created["kwargs"]["catalog_entry"] is entry
    assert created["kwargs"]["can_download"] is True
    assert created["exec"] is True
    controller.render.assert_called_once()


def test_plugin_active_download_update_does_not_rerender_tab(qapp, temp_dir):
    """Checks that plugin active download update does not rerender tab."""
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


def test_plugin_installed_record_update_scans_on_main_thread(qapp, temp_dir):
    """Checks that plugin installs are scanned by the controller after UseWorker finishes."""
    controller, _downloads_manager, _catalog = _make_controller(temp_dir)
    controller.render = Mock()
    controller.refresh_main_tabs = Mock()
    controller._loaded = True
    record = DownloadRecord(
        id="rec3",
        display_name="Sample Plugin",
        target_kind=TargetKind.PLUGIN,
        download_status=DownloadStatus.DOWNLOADED,
        use_status="ready_to_use",
        file_exists=True,
        ever_installed=True,
        metadata={"plugin_id": "sample_plugin"},
    )

    controller._on_download_record_updated(record)

    controller.plugin_runtime_service.scan_installed_plugins.assert_called_once()
    controller.refresh_main_tabs.assert_called_once()
    controller.render.assert_called_once()


def test_window_download_record_callback_leaves_plugin_refresh_to_controller():
    """Checks that plugin download records are not refreshed twice by window callbacks."""
    window = SimpleNamespace(
        feedback_service=Mock(),
        plugins_ui=Mock(),
    )
    record = DownloadRecord(
        id="rec4",
        display_name="Sample Plugin",
        target_kind=TargetKind.PLUGIN,
        download_status=DownloadStatus.DOWNLOADED,
        metadata={"plugin_id": "sample_plugin"},
    )

    on_downloads_record_updated(window, record)

    window.plugins_ui.handle_external_refresh.assert_not_called()


def test_delete_plugin_reports_filesystem_error_with_plugin_path(temp_dir):
    """Checks that plugin delete errors use the plugin folder path in UI messages."""
    controller, _downloads_manager, _catalog = _make_controller(temp_dir)
    plugin = SimpleNamespace(
        manifest=SimpleNamespace(name="Sample Plugin", version="1.0.0"),
        path="C:/plugins/sample_plugin",
    )
    controller.plugin_runtime_service.get_plugin.return_value = plugin
    controller.plugin_install_service.delete_plugin.side_effect = PermissionError(
        13, "Permission denied", "C:/plugins/sample_plugin"
    )
    controller.feedback_service.show_message = Mock()
    controller.refresh_main_tabs = Mock()
    controller.render = Mock()

    controller.delete_plugin("sample_plugin")

    controller.feedback_service.show_message.assert_called_once_with(
        "error",
        "errors.error",
        tr("errors.permission_denied", path="C:/plugins/sample_plugin"),
    )
