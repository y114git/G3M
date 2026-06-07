import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from utils.file_utils import save_json


class TestModOperationsController:
    """Tests for controllers."""

    def test_mod_operations_controller_initialization(
        self, app_state, feedback_service
    ):
        """Checks that mod operations controller initialization."""
        from controllers.mod_operations_controller import ModOperationsController
        from services.mod_service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        app_window = Mock()
        controller = ModOperationsController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            app_window=app_window,
        )
        assert controller is not None
        assert controller.app_state == app_state
        assert controller.mod_service == mod_service

    def test_uninstall_mod_removes_deleted_mod_from_used_mods(
        self, app_state, feedback_service
    ):
        """Checks that uninstalling mod clears it from used mods immediately."""
        from controllers.mod_operations_controller import ModOperationsController

        mod = SimpleNamespace(id="ghost_mod", name="Ghost Mod")
        mod_service = Mock()
        app_window = Mock()
        app_window.used_mods_service = Mock()
        app_window.search_display = Mock()
        app_window.library_display = Mock()
        controller = ModOperationsController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            app_window=app_window,
        )

        controller.uninstall_mod(mod)

        app_window.used_mods_service.remove_mod_from_all_chapters.assert_called_once_with(
            mod
        )

    def test_uninstall_mod_reports_localized_filesystem_error(self, app_state):
        from controllers.mod_operations_controller import ModOperationsController
        from services.localization_service import tr

        mod = SimpleNamespace(id="ghost_mod", name="Ghost Mod")
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = "C:/mods/ghost_mod"
        mod_service.delete_mod_files.side_effect = PermissionError(
            13, "Permission denied", "C:/mods/ghost_mod"
        )
        app_window = Mock()
        feedback_service = Mock()
        controller = ModOperationsController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            app_window=app_window,
        )

        controller.uninstall_mod(mod)

        feedback_service.show_message.assert_called_once_with(
            "error",
            tr("errors.error"),
            tr(
                "errors.mod_uninstall_failed",
                error=tr("errors.permission_denied", path="C:/mods/ghost_mod"),
            ),
        )


class TestGameLaunchControllerRefresh:
    def test_refresh_mods_in_use_replaces_mod_objects_inside_lists(
        self, app_state, feedback_service
    ):
        from controllers.game_launch_controller import GameLaunchController
        from models.mod_models import LocalModInfo, ModFileData

        stale_mod = LocalModInfo(
            id="chapter_swap_mod",
            name="Old",
            version="1.0.0",
            author="Author",
            description="Desc",
            game="deltarune",
            files={"deltarune_4": ModFileData(data_file_path="chapter4/DATA.win")},
        )
        refreshed_mod = LocalModInfo(
            id="chapter_swap_mod",
            name="New",
            version="1.0.0",
            author="Author",
            description="Desc",
            game="deltarune",
            files={"deltarune_0": ModFileData(data_file_path="menu/DATA.win")},
        )
        app_state.all_mods = [refreshed_mod]
        used_mods_service = Mock()
        used_mods_service.used_mods = {"deltarune_0": [stale_mod]}
        mod_service = Mock()

        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=used_mods_service,
            settings_service=Mock(),
            game_launcher=Mock(),
            customization_service=Mock(),
            app_window=Mock(),
        )

        controller.refresh_mods_in_use()

        assert used_mods_service.used_mods["deltarune_0"] == [refreshed_mod]
        assert (
            used_mods_service.used_mods["deltarune_0"][0].get_chapter_data(
                "deltarune_4"
            )
            is None
        )
        assert (
            used_mods_service.used_mods["deltarune_0"][0].get_chapter_data(
                "deltarune_0"
            )
            is not None
        )


class TestTabHandler:
    def test_handle_tab_changed_clears_search_selection_on_switch(self):
        from app.tab_handler import handle_tab_changed

        w = Mock()
        w._suppress_tab_handlers = False
        w.app_state = Mock(library_initialized=False)
        w.search_display = Mock()
        w.library_display = Mock()

        handle_tab_changed(w, 0)

        w.search_display.clear_all_selections.assert_called_once_with()


class TestLibraryDisplayController:
    """Tests for controllers."""

    def test_library_display_controller_initialization(
        self, app_state, feedback_service
    ):
        """Checks that library display controller initialization."""
        from controllers.library_display_controller import LibraryDisplayController
        from services.localization_service import localization_service
        from services.mod_service import ModManager
        from services.settings_service import SettingsManager
        from services.used_mods_service import UsedModsManager

        mod_service = ModManager(app_state, feedback_service)
        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=None,
        )
        used_mods_service = UsedModsManager(
            app_state, mod_service, feedback_service, settings_service, None
        )
        app_window = Mock()
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=used_mods_service,
            app_window=app_window,
        )
        assert controller is not None
        assert controller.app_state == app_state

    def test_library_display_skips_refresh_for_unchanged_valid_cached_view(
        self, app_state, feedback_service
    ):
        """Checks that library display skips refresh for unchanged valid cached view."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.game_type_combo.currentData.return_value = "deltarune"
        app_window.library_search_text = ""
        app_window.installed_mods_layout.count.return_value = 2
        app_window.game_launch = Mock()
        mod_service = SimpleNamespace(_installed_mods_cache_valid=True)
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        controller.refresh_async = Mock()
        controller.update_mod_widgets_active_status = Mock()
        controller._last_render_signature = (
            controller._current_view_signature(),
            (("mod_id",),),
        )
        controller.update_display()
        controller.refresh_async.assert_not_called()
        controller.update_mod_widgets_active_status.assert_called_once()

    def test_library_display_refreshes_when_installed_cache_is_invalid(
        self, app_state, feedback_service
    ):
        """Checks that library display refreshes when installed cache is invalid."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.game_type_combo.currentData.return_value = "deltarune"
        app_window.library_search_text = ""
        app_window.installed_mods_layout.count.return_value = 2
        app_window.game_launch = Mock()
        mod_service = SimpleNamespace(_installed_mods_cache_valid=False)
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        controller.refresh_async = Mock()
        controller._last_render_signature = (
            controller._current_view_signature(),
            (("mod_id",),),
        )
        controller.update_display()
        controller.refresh_async.assert_called_once()

    def test_library_display_refresh_async_clears_render_signature(
        self, app_state, feedback_service
    ):
        """Checks that library refresh async clears cached render signature."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit = Mock()
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization = Mock()
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay = Mock()
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other = Mock()
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana = Mock()
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.installed_mods_layout = Mock()
        app_window.installed_mods_layout.count.return_value = 0
        app_window.installed_mods_container = Mock()
        app_window.game_launch = Mock()
        app_window.game_type_combo.currentData.return_value = "deltarune"
        app_window._installed_scan_thread = None

        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            app_window=app_window,
        )
        controller._last_render_signature = (1,)

        controller.refresh_async()

        assert controller._last_render_signature is None

    def test_library_display_refresh_async_accepts_non_qobject_controller_parent(
        self, app_state, feedback_service
    ):
        """Checks that library display refresh async accepts non qobject controller parent."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window._installed_scan_thread = None
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = []
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        controller.update_display_from_list = Mock()

        def _slow_scan():
            time.sleep(0.2)
            return []

        mod_service.get_installed_mods_list.side_effect = _slow_scan
        controller.refresh_async()

        assert app_window._installed_scan_thread is not None
        controller.update_display_from_list.assert_not_called()
        app_window._installed_scan_thread.wait(1000)

    def test_library_display_clears_summary_when_selected_mod_disappears(
        self, app_state, feedback_service
    ):
        """Checks that library display clears summary when selected mod disappears."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.mod_summary_panel = Mock()
        app_window.installed_mods_layout.count.return_value = 1
        app_window.installed_mods_layout.itemAt.return_value = None
        app_window.game_launch = Mock()
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            app_window=app_window,
        )
        app_window.mod_summary_panel._current_mod = Mock()

        controller._refresh_summary_from_selection()

        app_window.mod_summary_panel.show_empty.assert_called_once()

    def test_summary_delete_removes_deleted_mod_from_used_mods(
        self, app_state, feedback_service
    ):
        """Checks that deleting from summary clears used mod selections."""
        from PyQt6.QtWidgets import QMessageBox

        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.mod_summary_panel = Mock()
        app_window.installed_mods_layout.count.return_value = 1
        app_window.game_launch = Mock()
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            app_window=app_window,
        )
        mod = SimpleNamespace(id="ghost_mod", name="Ghost Mod")
        controller._clear_summary = Mock()
        controller._safe_update_after_mod_deletion = Mock()

        with patch(
            "PyQt6.QtWidgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            controller._on_summary_delete(mod)

        controller.mod_service.uninstall_mod.assert_called_once_with(mod)
        controller.used_mods_service.remove_mod_from_all_chapters.assert_called_once_with(
            mod
        )


class TestModImportExportController:
    """Tests for controllers."""

    def test_format_import_exception_reports_archive_not_found(self, temp_dir):
        from controllers.mod_import_export_controller import ModImportExportController
        from services.localization_service import tr

        controller = ModImportExportController(
            Mock(mods_dir=temp_dir, all_mods=[]), Mock(), Mock()
        )

        assert (
            controller._format_import_exception(
                FileNotFoundError(2, "No such file", os.path.join(temp_dir, "missing.zip")),
                file_path=os.path.join(temp_dir, "missing.zip"),
            )
            == tr("errors.archive_not_found")
        )

    def test_materialize_local_import_raises_localized_permission_error(self, temp_dir):
        from controllers.mod_import_export_controller import ModImportExportController
        from services.localization_service import tr

        source_file = os.path.join(temp_dir, "sample.zip")
        with open(source_file, "wb") as handle:
            handle.write(b"zip")

        controller = ModImportExportController(
            Mock(mods_dir=temp_dir, all_mods=[]), Mock(), Mock()
        )

        with (
            tempfile.TemporaryDirectory() as extract_dir,
            patch(
                "controllers.mod_import_export_controller.extract_archive",
                side_effect=PermissionError(13, "Permission denied", source_file),
            ),
        ):
            try:
                controller._materialize_local_import(source_file, extract_dir)
            except ValueError as exc:
                assert str(exc) == tr("errors.permission_denied", path=source_file)
            else:
                raise AssertionError("Expected ValueError")


class TestModManagerErrorFormatting:
    def test_describe_uninstall_error_reports_missing_file(self):
        from services.localization_service import tr
        from services.mod_service import ModManager

        assert (
            ModManager._describe_uninstall_error(
                FileNotFoundError(2, "No such file", "C:/mods/missing")
            )
            == tr("errors.file_not_found", path="C:/mods/missing")
        )

    def test_materialize_local_import_keeps_plain_files(self, temp_dir):
        """Checks that materializeing local import keeps plain files."""
        from controllers.mod_import_export_controller import ModImportExportController

        source_file = os.path.join(temp_dir, "sample.png")
        with open(source_file, "wb") as handle:
            handle.write(b"png")

        controller = ModImportExportController(
            Mock(mods_dir=temp_dir, all_mods=[]), Mock(), Mock()
        )

        with tempfile.TemporaryDirectory() as extract_dir:
            content_path = controller._materialize_local_import(
                source_file, extract_dir
            )
            assert content_path == extract_dir
            assert os.path.isfile(os.path.join(extract_dir, "sample.png"))

    def test_install_mod_from_file_uses_config_name_for_target_folder(self, temp_dir):
        """Checks that installing mod from file uses config name for target folder."""
        from controllers.mod_import_export_controller import ModImportExportController

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        mod_service = Mock()
        controller = ModImportExportController(app_state, mod_service, Mock())
        content_path = os.path.join(temp_dir, "extract")
        os.makedirs(content_path, exist_ok=True)
        save_json(
            os.path.join(content_path, "mod_config.json"),
            {
                "id": "test_mod",
                "name": "Real Mod Name",
                "author": "Author",
                "version": "1.0.0",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "patch.xdelta"}},
            },
            indent=2,
        )
        with open(
            os.path.join(content_path, "patch.xdelta"), "w", encoding="utf-8"
        ) as handle:
            handle.write("patch")

        controller._materialize_local_import = Mock(return_value=content_path)
        controller._refresh_mod_list = Mock()

        with (
            patch("controllers.mod_import_export_controller.QMessageBox.information"),
            patch(
                "controllers.mod_import_export_controller.find_deltamod_info_file",
                return_value=False,
            ),
        ):
            controller._install_mod_from_file(
                os.path.join(temp_dir, "archive-name.zip")
            )

        assert os.path.isdir(os.path.join(temp_dir, "Real Mod Name"))
        assert not os.path.exists(os.path.join(temp_dir, "archive-name"))

    def test_install_mod_from_file_uses_metadata_name_for_target_folder(self, temp_dir):
        """Checks that nested metadata configs import with the normalized mod name."""
        from controllers.mod_import_export_controller import ModImportExportController

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        mod_service = Mock()
        controller = ModImportExportController(app_state, mod_service, Mock())
        content_path = os.path.join(temp_dir, "extract_metadata")
        os.makedirs(content_path, exist_ok=True)
        save_json(
            os.path.join(content_path, "mod_config.json"),
            {
                "config_version": "1.0.0",
                "metadata": {
                    "id": "meta_mod",
                    "name": "Metadata Mod Name",
                    "author": "Author",
                    "version": "1.0.0",
                    "game": "pizzatower",
                },
                "files": {"pizzatower": {"data_file_path": "patch.g3mpatch"}},
            },
            indent=2,
        )
        with open(
            os.path.join(content_path, "patch.g3mpatch"), "w", encoding="utf-8"
        ) as handle:
            handle.write("patch")

        controller._materialize_local_import = Mock(return_value=content_path)
        controller._refresh_mod_list = Mock()

        with (
            patch("controllers.mod_import_export_controller.QMessageBox.information"),
            patch(
                "controllers.mod_import_export_controller.find_deltamod_info_file",
                return_value=False,
            ),
        ):
            controller._install_mod_from_file(os.path.join(temp_dir, "metadata.zip"))

        assert os.path.isdir(os.path.join(temp_dir, "Metadata Mod Name"))
        assert not os.path.exists(os.path.join(temp_dir, "Unknown"))

    def test_library_sort_order_name_ascending_and_date_descending(
        self, app_state, feedback_service
    ):
        """Checks that library sort order name ascending and date descending."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.chapter_mode_checkbox.isChecked.return_value = False
        app_window.library_sort_combo.currentIndex.return_value = 0
        app_window.library_sort_ascending = True
        app_window.library_tag_textedit.isChecked.return_value = False
        app_window.library_tag_customization.isChecked.return_value = False
        app_window.library_tag_gameplay.isChecked.return_value = False
        app_window.library_tag_other.isChecked.return_value = False
        app_window.library_tag_gamebanana.isChecked.return_value = False
        app_window.game_type_combo.currentData.return_value = "deltarune"
        app_window.library_search_text = ""
        app_window.game_launch = Mock()
        mod_service = Mock()
        mod_service.get_installed_mods_list.return_value = [
            {
                "id": "b",
                "name": "Beta",
                "game": "deltarune",
                "added_date": "2024-01-01 00:00:00",
            },
            {
                "id": "a",
                "name": "Alpha",
                "game": "deltarune",
                "added_date": "2025-06-01 00:00:00",
            },
            {
                "id": "c",
                "name": "Charlie",
                "game": "deltarune",
                "added_date": "2024-06-01 00:00:00",
            },
        ]
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        result = controller._filter_and_sort_installed(
            mod_service.get_installed_mods_list()
        )
        names = [m["name"] for m in result]
        assert names == ["Alpha", "Beta", "Charlie"], (
            f"Name sort ascending should be A→Z, got {names}"
        )
        app_window.library_sort_combo.currentIndex.return_value = 1
        result = controller._filter_and_sort_installed(
            mod_service.get_installed_mods_list()
        )
        dates = [m["added_date"] for m in result]
        assert dates == [
            "2025-06-01 00:00:00",
            "2024-06-01 00:00:00",
            "2024-01-01 00:00:00",
        ], f"Date sort ascending should be newest first, got {dates}"


class TestSettingsController:
    """Tests for controllers."""

    def test_update_tab_visibility_shows_placeholder_when_no_main_tabs_remain(
        self, app_state
    ):
        """Checks that updating tab visibility shows placeholder when no main tabs remain."""
        from controllers.settings_controller import SettingsController

        app_window = Mock()
        app_window.main_tab_widget.count.return_value = 0
        app_window.main_tab_widget.currentIndex.return_value = 0
        app_window.main_tab_widget.removeTab = Mock()
        app_window.main_tab_widget.addTab = Mock()
        app_window.main_tab_widget.tabBar.return_value = Mock()
        app_window._show_empty_main_tabs_placeholder = Mock()
        app_window._restore_main_tabs_bar = Mock()
        app_state.local_config["hide_mods_browser_tab"] = True
        app_state.local_config["hide_library_tab"] = True

        controller = SettingsController(
            app_state=app_state,
            feedback_service=Mock(),
            settings_service=Mock(),
            used_mods_service=Mock(),
            customization_service=Mock(),
            app_window=app_window,
        )

        controller._update_tab_visibility()

        app_window._show_empty_main_tabs_placeholder.assert_called_once()
        app_window._restore_main_tabs_bar.assert_not_called()


class TestSearchDisplayController:
    """Tests for controllers."""

    def test_search_display_controller_initialization(
        self, app_state, feedback_service
    ):
        """Checks that searching display controller initialization."""
        from controllers.mod_operations_controller import ModOperationsController
        from controllers.search_display_controller import SearchDisplayController
        from services.mod_service import ModManager

        mod_service = ModManager(app_state, feedback_service)
        mod_ops = ModOperationsController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            app_window=Mock(),
        )
        app_window = Mock()
        app_window.mod_list_layout = Mock()
        app_window.mod_list_widget = Mock()
        app_window.modgame_combo = Mock()
        app_window.modgame_combo.currentData = Mock(return_value="deltarune")
        app_window.sort_combo = Mock()
        app_window.sort_combo.currentIndex = Mock(return_value=0)
        app_window.sort_ascending = True
        app_window.page_label = Mock()
        app_window.prev_page_btn = Mock()
        app_window.next_page_btn = Mock()

        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            mod_ops=mod_ops,
            app_window=app_window,
        )
        assert controller is not None
        assert controller.app_state == app_state
        assert hasattr(controller, "card_widget_cache")
        assert hasattr(controller, "_update_display_debounce")

    def test_event_filter_queues_layout_refresh_on_viewport_show(
        self, app_state, feedback_service
    ):
        """Checks that eventing filter queues layout refresh on viewport show."""
        from PyQt6.QtCore import QEvent

        from controllers.search_display_controller import SearchDisplayController

        viewport = Mock()
        scroll = Mock()
        scroll.viewport.return_value = viewport
        app_window = Mock(mods_browser_scroll=scroll)
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )
        controller._queue_layout_refresh = Mock()

        controller.eventFilter(viewport, Mock(type=Mock(return_value=QEvent.Type.Show)))

        controller._queue_layout_refresh.assert_called_once_with(force=True)

    def test_search_display_refresh_visible_layout_skips_relayout_when_grid_metrics_do_not_change(
        self, app_state, feedback_service
    ):
        """Checks that refreshing visible layout skips relayout when grid metrics do not change."""
        from controllers.search_display_controller import SearchDisplayController

        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=Mock(mod_list_layout=Mock(), mod_list_widget=Mock()),
        )
        controller._sync_mod_grid_metrics = Mock(return_value=False)
        controller._place_layout_widget = Mock()
        controller.update_pagination = Mock()
        controller.ui_widget_updates_enabled = Mock()

        controller.refresh_visible_layout()

        controller._place_layout_widget.assert_not_called()
        controller.update_pagination.assert_not_called()
        controller.ui_widget_updates_enabled.emit.assert_not_called()

    def test_update_display_finalizes_layout_refresh_after_processing(
        self, app_state, feedback_service
    ):
        """Checks that update display finalizes layout refresh after processing cards."""
        from controllers.search_display_controller import SearchDisplayController

        layout = Mock()
        layout.count.return_value = 0
        layout.itemAt.return_value = None
        mod_list_widget = Mock()
        scroll = Mock()
        scroll.viewport.return_value = Mock()
        app_window = Mock(
            mod_list_layout=layout,
            mod_list_widget=mod_list_widget,
            mods_browser_scroll=scroll,
        )
        app_state.filtered_mods = []
        app_state.mods_loaded = True
        app_state.gamebanana_loading = False

        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )
        controller._sync_mod_grid_metrics = Mock(return_value=False)
        controller._finalize_mod_list_layout_refresh = Mock()
        controller.ui_widget_updates_enabled = Mock()

        controller._do_update_display()

        controller._finalize_mod_list_layout_refresh.assert_called_once_with()

    def test_maybe_load_more_for_short_viewport_loads_when_tag_filter_active(
        self, app_state, feedback_service
    ):
        """Checks that maybeing load more for short viewport still loads when tag filter active."""
        from controllers.search_display_controller import SearchDisplayController

        scroll = Mock()
        scroll.viewport.return_value.height.return_value = 1000
        app_window = Mock(
            mods_browser_scroll=scroll, mod_list_widget=Mock(), mod_list_layout=Mock()
        )
        app_window.tag_textedit = Mock()
        app_window.tag_customization = Mock()
        app_window.tag_gameplay = Mock()
        app_window.tag_other = Mock()
        app_window.tag_textedit.isChecked.return_value = True
        app_window.tag_customization.isChecked.return_value = False
        app_window.tag_gameplay.isChecked.return_value = False
        app_window.tag_other.isChecked.return_value = False
        app_window.mod_list_widget.sizeHint.return_value.height.return_value = 100
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )
        controller._load_more_gamebanana_mods_if_needed = Mock()

        controller._maybe_load_more_for_short_viewport()

        controller._load_more_gamebanana_mods_if_needed.assert_called_once_with()

    def test_show_bottom_loading_indicator_places_label_on_next_full_row(
        self, app_state, feedback_service, monkeypatch
    ):
        """Checks that bottom loading indicator starts on a new row without extra columns."""
        from controllers.search_display_controller import SearchDisplayController

        layout = Mock()
        layout.count.return_value = 5
        layout.itemAt.return_value = None
        app_window = Mock(mod_list_layout=layout)
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )
        controller._mod_list_column_count = Mock(return_value=4)
        placed = []

        def _capture(widget, position, column_span=1, alignment=None):
            placed.append((position, column_span))

        controller._place_layout_widget = _capture

        controller._show_bottom_loading_indicator()

        assert placed == [(8, 1)]

    def test_on_scroll_value_changed_prefetches_before_reaching_bottom(
        self, app_state, feedback_service
    ):
        """Checks that scrolling prefetches before reaching the exact bottom."""
        from controllers.search_display_controller import SearchDisplayController

        scroll = Mock()
        bar = Mock()
        bar.maximum.return_value = 2000
        scroll.verticalScrollBar.return_value = bar
        viewport = Mock()
        viewport.height.return_value = 900
        scroll.viewport.return_value = viewport
        app_window = Mock(mods_browser_scroll=scroll, mod_list_widget=Mock())
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )
        controller._virtual_scroll_debounce = Mock()
        controller._virtual_scroll_debounce.call = Mock()
        controller._load_more_gamebanana_mods_if_needed = Mock()

        controller.on_scroll_value_changed(1450)

        controller._load_more_gamebanana_mods_if_needed.assert_called_once_with()

    def test_load_more_prefetch_threshold_covers_viewport(
        self, app_state, feedback_service
    ):
        """Checks that prefetch starts early enough to avoid reaching an empty bottom."""
        from controllers.search_display_controller import SearchDisplayController

        scroll = Mock()
        viewport = Mock()
        viewport.height.return_value = 900
        scroll.viewport.return_value = viewport
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=Mock(mods_browser_scroll=scroll, mod_list_layout=Mock()),
        )
        controller._first_visible_card_height = Mock(return_value=260)
        controller._mod_list_spacing = Mock(return_value=18)

        assert controller._load_more_prefetch_threshold() >= 2250

    def test_search_filters_include_cyop_afom_only_for_pizzatower(
        self, app_state, feedback_service
    ):
        from controllers.search_display_controller import SearchDisplayController

        app_window = Mock()
        app_window.tag_textedit = Mock()
        app_window.tag_customization = Mock()
        app_window.tag_gameplay = Mock()
        app_window.tag_other = Mock()
        app_window.tag_cyop_afom = Mock()
        app_window.show_nsfw_checkbox = Mock()
        app_window.modgame_combo = Mock()
        app_window.modgame_combo.currentData = Mock(return_value="pizzatower")
        for attr in (
            "tag_textedit",
            "tag_customization",
            "tag_gameplay",
            "tag_other",
        ):
            getattr(app_window, attr).isChecked.return_value = False
        app_window.tag_cyop_afom.isChecked.return_value = True
        app_window.show_nsfw_checkbox.isChecked.return_value = False
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )

        filters, _ = controller._build_filters_and_sort()
        assert filters["tags"] == ["CYOP/AFOM"]

        app_window.modgame_combo.currentData.return_value = "deltarune"
        filters, _ = controller._build_filters_and_sort()
        assert filters["tags"] == []

    def test_search_display_cleanup_cancels_and_stops_threads(
        self, app_state, feedback_service, monkeypatch
    ):
        from controllers.search_display_controller import SearchDisplayController

        app_window = Mock()
        controller = SearchDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            mod_ops=Mock(),
            app_window=app_window,
        )
        thread = Mock()
        controller._load_more_threads = [thread]
        controller._clear_search_timers = Mock()
        controller._cleanup_load_thread = Mock()
        safe_stop = Mock()
        monkeypatch.setattr(
            "controllers.search_display_controller.safe_stop_thread",
            safe_stop,
        )

        controller.cleanup()

        controller._clear_search_timers.assert_called_once_with()
        thread.cancel.assert_called_once_with()
        safe_stop.assert_called_once_with(thread, timeout=500, blocking=False)
        controller._cleanup_load_thread.assert_called_once_with(thread)


class TestLibraryCyopAfomFilter:
    def test_library_filters_include_cyop_afom_only_for_pizzatower(
        self, app_state, feedback_service
    ):
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        app_window.library_tag_widgets = []
        app_window.library_tag_textedit = Mock()
        app_window.library_tag_customization = Mock()
        app_window.library_tag_gameplay = Mock()
        app_window.library_tag_other = Mock()
        app_window.library_tag_cyop_afom = Mock()
        app_window.library_tag_gamebanana = Mock()
        app_window.game_type_combo = Mock()
        app_window.library_search_text = ""
        app_window.game_launch = Mock()
        for attr in (
            "library_tag_textedit",
            "library_tag_customization",
            "library_tag_gameplay",
            "library_tag_other",
            "library_tag_gamebanana",
        ):
            getattr(app_window, attr).isChecked.return_value = False
        app_window.library_tag_cyop_afom.isChecked.return_value = True
        app_window.library_tag_widgets = [
            app_window.library_tag_textedit,
            app_window.library_tag_customization,
            app_window.library_tag_gameplay,
            app_window.library_tag_other,
            app_window.library_tag_cyop_afom,
            app_window.library_tag_gamebanana,
        ]
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            app_window=app_window,
        )

        app_window.game_type_combo.currentData.return_value = "pizzatower"
        filters, _ = controller._build_library_filters_and_sort()
        assert filters["tags"] == ["CYOP/AFOM"]

        app_window.game_type_combo.currentData.return_value = "deltarune"
        filters, _ = controller._build_library_filters_and_sort()
        assert filters["tags"] == []


class TestSettingsUiController:
    """Tests for controllers."""

    def test_settings_ui_controller_initialization(
        self, app_state, feedback_service, qapp
    ):
        """Checks that settings ui controller initialization."""
        from controllers.settings_controller import SettingsUiController
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        from services.customization_service import CustomizationManager
        from services.mod_service import ModManager
        from services.used_mods_service import UsedModsManager

        mod_service = ModManager(app_state, feedback_service)
        used_mods_service = UsedModsManager(
            app_state, mod_service, feedback_service, settings_service, None
        )
        customization_service = CustomizationManager(app_state)
        app_window = Mock()
        controller = SettingsUiController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            used_mods_service=used_mods_service,
            customization_service=customization_service,
            app_window=app_window,
        )
        assert controller is not None
        assert controller.app_state == app_state

    def test_settings_view_status_is_relocalizable(self, app_state, feedback_service):
        from config.config import UI_COLORS
        from controllers.settings_controller import SettingsUiController

        settings_service = Mock()
        used_mods_service = Mock()
        customization_service = Mock()
        app_window = Mock()
        app_window.color_widgets = {}
        app_window.settings_button = Mock()
        app_window.tab_widget = Mock()
        app_window.bottom_widget = Mock()
        app_window.settings_widget = Mock()
        app_window._update_localized_status = Mock()
        app_state.is_settings_view = False
        controller = SettingsUiController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            used_mods_service=used_mods_service,
            customization_service=customization_service,
            app_window=app_window,
        )

        controller.toggle_settings_view()

        app_window._update_localized_status.assert_called_once_with(
            "status.launcher_settings",
            UI_COLORS["status_info"],
        )


class TestThemeController:
    """Tests for controllers."""

    def test_theme_controller_initialization(self, app_state, feedback_service, qapp):
        """Checks that themeing controller initialization."""
        from controllers.theme_controller import ThemeController
        from services.customization_service import CustomizationManager
        from services.localization_service import localization_service
        from services.settings_service import SettingsManager

        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        customization_service = CustomizationManager(app_state)
        app_window = Mock()
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            customization_service=customization_service,
            app_window=app_window,
        )
        assert controller is not None
        assert controller.app_state == app_state

    def test_apply_theme_skips_cache_invalidation_when_params_unchanged(
        self, app_state, feedback_service
    ):
        """Checks that applying theme skips cache invalidation when params unchanged."""
        from PyQt6.QtWidgets import QApplication as RealQApplication

        from controllers.theme_controller import ThemeController

        app_state.local_config = {"custom_main_text_color": "#FF0000"}
        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = Mock()
        app_window.custom_font_family = None
        app_window.palette.return_value = Mock()
        app_window.status_label = Mock()
        app_window.color_widgets = {
            "hover": Mock(text=lambda: ""),
            "select": Mock(text=lambda: ""),
        }
        app_window.installed_mods_label = None
        app_window.title_bar = None
        app_window.top_panel_widget = Mock()
        app_window.logo_placeholder = Mock()
        app_window.launcher_icon_label = Mock()
        app_window.findChildren.return_value = []
        app_window.library_tag_widgets = []
        app_window.search_display = None
        app_window.library_tab_builder = Mock()
        app_window.library_tab_builder.update_priority_button_style = Mock()
        app_window._apply_window_corner_mask = Mock()
        app_window.update = Mock()
        app_window.size.return_value = Mock()
        with (
            patch(
                "controllers.theme_controller.DEFAULT_THEME",
                {
                    "background": "images/background.png",
                    "colors": {
                        "main_text": "#FFFFFF",
                        "background": "#000000",
                        "elements": "#333333",
                        "border": "#444444",
                        "hover": "#555555",
                        "select": "#666666",
                    },
                    "font_family": "Arial",
                    "font_size_main": 12,
                    "font_size_small": 10,
                },
            ),
            patch("controllers.theme_controller.BgLoader"),
            patch(
                "controllers.theme_controller.invalidate_stylesheet_cache"
            ) as invalidate_stylesheet_cache_mock,
            patch(
                "ui.common.styling.invalidate_theme_color_cache"
            ) as invalidate_theme_color_cache_mock,
            patch("controllers.theme_controller.build_stylesheet", return_value=""),
            patch.object(RealQApplication, "instance", return_value=None),
            patch("controllers.theme_controller.QApplication", RealQApplication),
        ):
            controller = ThemeController(
                app_state=app_state,
                feedback_service=feedback_service,
                settings_service=settings_service,
                customization_service=customization_service,
                app_window=app_window,
            )
            controller.apply_theme()
            invalidate_stylesheet_cache_mock.reset_mock()
            invalidate_theme_color_cache_mock.reset_mock()
            controller.apply_theme()
        invalidate_stylesheet_cache_mock.assert_not_called()
        invalidate_theme_color_cache_mock.assert_not_called()

    def test_apply_theme_resets_tooltip_size_cache_key(
        self, app_state, feedback_service
    ):
        """Checks that applying theme resets tooltip size cache key."""
        from PyQt6.QtWidgets import QApplication as RealQApplication

        from controllers.theme_controller import ThemeController

        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = Mock()
        app_window.custom_font_family = None
        app_window.palette.return_value = Mock()
        app_window.status_label = Mock()
        app_window.color_widgets = {
            "hover": Mock(text=lambda: ""),
            "select": Mock(text=lambda: ""),
        }
        app_window.installed_mods_label = None
        app_window.title_bar = None
        app_window.top_panel_widget = Mock()
        app_window.logo_placeholder = Mock()
        app_window.launcher_icon_label = Mock()
        app_window.findChildren.return_value = []
        app_window.library_tag_widgets = []
        app_window.search_display = None
        app_window.library_tab_builder = Mock()
        app_window.library_tab_builder.update_priority_button_style = Mock()
        app_window._apply_window_corner_mask = Mock()
        app_window.update = Mock()
        app_window.size.return_value = Mock()
        app_window._last_tooltip_size_key = "tooltip-text"
        with (
            patch(
                "controllers.theme_controller.DEFAULT_THEME",
                {
                    "background": "images/background.png",
                    "colors": {
                        "main_text": "#FFFFFF",
                        "background": "#000000",
                        "elements": "#333333",
                        "border": "#444444",
                        "hover": "#555555",
                        "select": "#666666",
                    },
                    "font_family": "Arial",
                    "font_size_main": 12,
                    "font_size_small": 10,
                },
            ),
            patch("controllers.theme_controller.BgLoader"),
            patch("controllers.theme_controller.build_stylesheet", return_value=""),
            patch.object(RealQApplication, "instance", return_value=None),
            patch("controllers.theme_controller.QApplication", RealQApplication),
        ):
            controller = ThemeController(
                app_state=app_state,
                feedback_service=feedback_service,
                settings_service=settings_service,
                customization_service=customization_service,
                app_window=app_window,
            )
            controller.apply_theme(force=True)
        assert app_window._last_tooltip_size_key is None

    def test_apply_theme_refreshes_open_version_dialogs(
        self, app_state, feedback_service
    ):
        """Checks that applying theme refreshes open version dialogs."""
        from PyQt6.QtWidgets import QApplication as RealQApplication

        from controllers.theme_controller import ThemeController

        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = Mock()
        app_window.custom_font_family = None
        app_window.palette.return_value = Mock()
        app_window.status_label = Mock()
        app_window.color_widgets = {
            "hover": Mock(text=lambda: ""),
            "select": Mock(text=lambda: ""),
        }
        app_window.installed_mods_label = None
        app_window.title_bar = None
        app_window.top_panel_widget = Mock()
        app_window.logo_placeholder = Mock()
        app_window.launcher_icon_label = Mock()
        app_window.findChildren.return_value = []
        app_window.library_tag_widgets = []
        app_window.search_display = None
        app_window.library_tab_builder = Mock()
        app_window.library_tab_builder.update_priority_button_style = Mock()
        app_window._apply_window_corner_mask = Mock()
        app_window.update = Mock()
        app_window.size.return_value = Mock()
        app_window._game_versions_dialog = Mock()
        app_window._game_versions_dialog.refresh_theme = Mock()
        app_window._mod_versions_dialog = Mock()
        app_window._mod_versions_dialog.refresh_theme = Mock()
        app_window._downloads_dialog = Mock()
        app_window._downloads_dialog.refresh_theme = Mock()
        app_window._modding_tools_dialog = Mock()
        app_window._modding_tools_dialog.refresh_theme = Mock()
        with (
            patch(
                "controllers.theme_controller.DEFAULT_THEME",
                {
                    "background": "images/background.png",
                    "colors": {
                        "main_text": "#FFFFFF",
                        "background": "#000000",
                        "elements": "#333333",
                        "border": "#444444",
                        "hover": "#555555",
                        "select": "#666666",
                    },
                    "font_family": "Arial",
                    "font_size_main": 12,
                    "font_size_small": 10,
                },
            ),
            patch("controllers.theme_controller.BgLoader"),
            patch("controllers.theme_controller.build_stylesheet", return_value=""),
            patch(
                "PyQt6.QtCore.QTimer.singleShot", side_effect=lambda _delay, cb: cb()
            ),
            patch.object(RealQApplication, "instance", return_value=None),
            patch("controllers.theme_controller.QApplication", RealQApplication),
        ):
            controller = ThemeController(
                app_state=app_state,
                feedback_service=feedback_service,
                settings_service=settings_service,
                customization_service=customization_service,
                app_window=app_window,
            )
            controller.apply_theme(force=True)
        app_window._game_versions_dialog.refresh_theme.assert_called_once()
        app_window._mod_versions_dialog.refresh_theme.assert_called_once()
        app_window._downloads_dialog.refresh_theme.assert_called_once()
        app_window._modding_tools_dialog.refresh_theme.assert_called_once()

    def test_update_dynamic_elements_refreshes_theme_dependent_widgets(
        self, app_state, feedback_service
    ):
        """Checks that updating dynamic elements refreshes theme dependent widgets."""
        from controllers.theme_controller import ThemeController

        settings_service = Mock()
        settings_service.is_valid_hex_color = lambda x: bool(x and x.startswith("#"))
        customization_service = Mock()
        app_window = Mock()
        app_window.library_tab_builder = Mock()
        library_search_button = Mock()
        library_downloads_button = Mock()
        library_sort_order_btn = Mock()
        library_game_versions_button = Mock()
        library_modding_tools_button = Mock()
        library_tag_widgets_items = [Mock(), Mock()]
        app_window.library_tab_builder.widgets = {
            "library_search_button": library_search_button,
            "library_downloads_button": library_downloads_button,
            "library_sort_order_btn": library_sort_order_btn,
            "library_game_versions_button": library_game_versions_button,
            "library_modding_tools_button": library_modding_tools_button,
            "library_tag_widgets": library_tag_widgets_items,
        }
        app_window.search_tab_builder = Mock()
        search_button = Mock()
        downloads_button = Mock()
        sort_order_btn = Mock()
        blocklist_button = Mock()
        chapter_mode_checkbox = Mock()
        full_install_checkbox = Mock()
        app_window.search_tab_builder.widgets = {
            "search_button": search_button,
            "downloads_button": downloads_button,
            "sort_order_btn": sort_order_btn,
            "blocklist_button": blocklist_button,
            "chapter_mode_checkbox": chapter_mode_checkbox,
            "full_install_checkbox": full_install_checkbox,
        }
        app_window.mods_browser_container = Mock()
        app_window.installed_mods_container = Mock()
        app_window.mod_list_widget = Mock()
        app_window.installed_mods_widget = Mock()
        app_window.mod_summary_panel = Mock()
        app_window._section_lines = []
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            customization_service=customization_service,
            app_window=app_window,
        )
        with (
            patch("ui.common.styling.apply_panel_style") as panel_style_mock,
            patch("ui.common.styling.refresh_themed_button_icon") as refresh_icon_mock,
        ):
            controller.update_dynamic_elements()
        assert panel_style_mock.call_count == 2
        actual_calls = [call.args for call in refresh_icon_mock.call_args_list]

        called_widgets = [call[0] for call in actual_calls]

        assert library_search_button in called_widgets
        assert library_downloads_button in called_widgets
        assert library_game_versions_button in called_widgets
        assert library_modding_tools_button in called_widgets
        assert search_button in called_widgets
        assert downloads_button in called_widgets
        assert sort_order_btn in called_widgets
        assert blocklist_button in called_widgets
        assert chapter_mode_checkbox in called_widgets
        assert full_install_checkbox in called_widgets

        for item in library_tag_widgets_items:
            assert item in called_widgets

        expected_widgets = [
            library_search_button,
            library_downloads_button,
            library_game_versions_button,
            library_modding_tools_button,
            search_button,
            downloads_button,
            sort_order_btn,
            blocklist_button,
            chapter_mode_checkbox,
            full_install_checkbox,
            *library_tag_widgets_items,
        ]

        for widget in expected_widgets:
            assert widget in called_widgets, (
                f"Expected widget {widget} not found in refresh calls"
            )

        assert refresh_icon_mock.call_count >= len(expected_widgets)
        app_window.mod_summary_panel.refresh_theme.assert_called_once()

    def test_reload_custom_font_skips_reloading_unchanged_file(
        self, app_state, feedback_service, tmp_path
    ):
        """Checks that reloading custom font skips reloading unchanged file."""
        from controllers.theme_controller import ThemeController

        font_path = tmp_path / "custom_font.ttf"
        font_path.write_bytes(b"font")
        settings_service = Mock()
        customization_service = Mock()
        customization_service.get_custom_font_path.return_value = str(font_path)
        app_window = Mock()
        app_window._custom_font_id = 7
        app_window.custom_font_family = "Loaded Font"
        app_window._custom_font_file_key = (
            str(font_path),
            font_path.stat().st_mtime_ns,
            font_path.stat().st_size,
        )
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            customization_service=customization_service,
            app_window=app_window,
        )
        with (
            patch("PyQt6.QtGui.QFontDatabase.removeApplicationFont") as remove_mock,
            patch("PyQt6.QtGui.QFontDatabase.addApplicationFont") as add_mock,
        ):
            controller._reload_custom_font()
        remove_mock.assert_not_called()
        add_mock.assert_not_called()

    def test_resync_filter_scroll_heights_applies_current_size_hint(
        self, app_state, feedback_service
    ):
        from controllers.theme_controller import ThemeController

        settings_service = Mock()
        customization_service = Mock()
        app_window = Mock()
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            customization_service=customization_service,
            app_window=app_window,
        )

        search_widget = Mock()
        search_widget.sizeHint.return_value.height.return_value = 68
        search_scroll = Mock()
        search_scroll.widget.return_value = search_widget

        library_widget = Mock()
        library_widget.sizeHint.return_value.height.return_value = 74
        library_scroll = Mock()
        library_scroll.widget.return_value = library_widget

        controller._iter_filter_scrolls = Mock(
            return_value=iter((search_scroll, library_scroll))
        )

        controller._resync_filter_scroll_heights()

        search_widget.adjustSize.assert_called_once()
        search_widget.updateGeometry.assert_called_once()
        search_scroll.updateGeometry.assert_called_once()
        search_scroll.setMaximumHeight.assert_called_once_with(68)

        library_widget.adjustSize.assert_called_once()
        library_widget.updateGeometry.assert_called_once()
        library_scroll.updateGeometry.assert_called_once()
        library_scroll.setMaximumHeight.assert_called_once_with(74)


class TestGameLaunchController:
    """Tests for controllers."""

    def test_game_launch_controller_initialization(
        self, app_state, feedback_service, qapp
    ):
        """Checks that gameing launch controller initialization."""
        from controllers.game_launch_controller import GameLaunchController
        from services.customization_service import CustomizationManager
        from services.launch_service import GameLauncher
        from services.localization_service import localization_service
        from services.mod_service import ModManager
        from services.settings_service import SettingsManager
        from services.used_mods_service import UsedModsManager

        mod_service = ModManager(app_state, feedback_service)
        settings_service = SettingsManager(
            app_state=app_state,
            feedback_service=feedback_service,
            localization_service=localization_service,
            parent=qapp,
        )
        used_mods_service = UsedModsManager(
            app_state, mod_service, feedback_service, settings_service, None
        )
        game_launcher = GameLauncher(app_state, feedback_service, mod_service)
        customization_service = CustomizationManager(app_state)
        app_window = Mock()
        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=used_mods_service,
            settings_service=settings_service,
            game_launcher=game_launcher,
            customization_service=customization_service,
            app_window=app_window,
        )
        assert controller is not None
        assert controller.app_state == app_state

    def test_hide_window_with_dont_hide_updates_close_text_and_border_status_color(
        self,
    ):
        """Checks that hideing window with dont hide updates close text and border status color."""
        from controllers.game_launch_controller import GameLaunchController
        from services.localization_service import tr

        app_state = SimpleNamespace(
            game_mode=SimpleNamespace(supports_full_install=False),
            game_is_running=False,
            is_installing=False,
            operation_cancelled=False,
            is_patching=False,
            initialization_completed=True,
            local_config={
                "dont_hide_window_on_launch": True,
                "custom_border_color": "#123456",
            },
            action_button_text=None,
            action_button_enabled=False,
            progress_bar_visible=False,
            progress_bar_value=0,
        )
        feedback_service = Mock()
        settings_service = Mock()
        used_mods_service = Mock()
        used_mods_service.check_used_mods_need_updates.return_value = False
        customization_service = Mock()
        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=used_mods_service,
            settings_service=settings_service,
            game_launcher=Mock(),
            customization_service=customization_service,
            app_window=Mock(),
        )

        controller.hide_window()

        assert app_state.game_is_running is True
        assert app_state.action_button_text == tr("ui.close_game")
        feedback_service.update_status.assert_called_once_with(
            tr("status.game_launched_waiting_for_exit"), "#123456"
        )
        settings_service.save_window_geometry.assert_called_once()


class TestAppWindowRestore:
    """Tests for controllers."""

    def test_on_window_restore_requested_uses_show_maximized_for_saved_maximized_state(
        self,
    ):
        """Checks that oning window restore requested uses show maximized for saved maximized state."""
        from PyQt6.QtCore import Qt

        from app.window import AppWindow

        window = Mock()
        window.settings_service.was_window_maximized.return_value = True
        window.settings_service.load_window_geometry.return_value = True
        window.windowState.return_value = Qt.WindowState.WindowMaximized
        window._restoring_window_geometry = False
        window._finish_window_restore = Mock()

        with patch(
            "app.window.QTimer.singleShot", side_effect=lambda _ms, callback: callback()
        ):
            AppWindow._on_window_restore_requested(window)

        window.settings_service.was_window_maximized.assert_called_once_with()
        window.settings_service.load_window_geometry.assert_called_once_with(
            window, apply_maximized_state=False
        )
        window.setWindowState.assert_called_once()
        window.show.assert_called_once_with()
        window.showMaximized.assert_called_once_with()
        window.showNormal.assert_not_called()
        window._finish_window_restore.assert_called_once_with()
        window.activateWindow.assert_called_once_with()
        window.raise_.assert_called_once_with()
        assert window._restoring_window_geometry is True

    def test_restore_last_active_main_tab_clamps_saved_index(self):
        """Checks that restoring last active main tab clamps saved index."""
        from app.window import AppWindow

        window = Mock()
        window.main_tab_widget.count.return_value = 2
        window.app_state.local_config = {"last_active_tab": 5}
        window.previous_tab_index = 0

        AppWindow._restore_last_active_main_tab(window)

        window.main_tab_widget.setCurrentIndex.assert_called_once_with(1)
        assert window.previous_tab_index == 1
