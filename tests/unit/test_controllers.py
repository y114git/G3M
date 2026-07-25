"""Unit tests for test controllers."""

import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from utils.file_utils import save_json


class TestModOperationsController:
    """Tests for controllers."""

    def test_mod_operations_controller_initialization(
        self, app_state, feedback_service
    ):
        """Checks that mod operations controller initialization."""
        from controllers.mod.operations_controller import ModOperationsController
        from services.mod.service import ModManager

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
        from controllers.mod.operations_controller import ModOperationsController

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
        from controllers.mod.operations_controller import ModOperationsController
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

    def test_install_mod_start_failure_resets_state_without_raising(
        self, app_state, feedback_service
    ):
        from controllers.mod.operations_controller import ModOperationsController
        from models.mod_models import LocalModInfo, ModFileData

        mod = LocalModInfo(
            id="local_start_fail",
            name="Start Fail",
            version="1.0.0",
            author="Author",
            description="Desc",
            game="deltarune",
            files={
                "deltarune_1": ModFileData(data_file_url="https://example.com/a.xdelta")
            },
        )
        mod_service = Mock()
        mod_service.is_mod_installed.return_value = False
        app_window = Mock()
        app_window._install_op_id = 0
        app_window.action_button = Mock()
        app_window.game_launch = Mock()
        feedback_service = Mock()
        controller = ModOperationsController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            app_window=app_window,
        )

        with patch(
            "controllers.mod.operations_controller.InstallModsThread",
            side_effect=RuntimeError("worker construction failed"),
        ):
            controller.install_mod(mod)

        assert app_state.is_installing is False
        assert app_state.current_task is None
        assert getattr(app_state, "_scan_blocked", False) is False
        feedback_service.show_message.assert_called_once()

    def test_install_complete_success_ignores_broken_status_feedback(self, app_state):
        from controllers.mod.operations_controller import ModOperationsController

        feedback_service = Mock()
        feedback_service.update_status.side_effect = RuntimeError(
            "status widget deleted"
        )
        current_task = Mock()
        current_task.mod_info = SimpleNamespace(id="mod_a", name="Mod A")
        app_state.current_task = current_task
        app_state.is_installing = True
        app_state._scan_blocked = True
        app_state.filtered_mods = []
        app_window = Mock()
        app_window.game_launch.update_button_state = Mock()
        next_mod = SimpleNamespace(id="mod_b", name="Mod B")
        app_window.pending_updates = [next_mod]
        mod_service = Mock()
        controller = ModOperationsController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            app_window=app_window,
        )
        controller.set_install_buttons_enabled = Mock()
        controller.refresh_specific_mod_widget_after_update = Mock()

        with patch(
            "controllers.mod.operations_controller.QTimer.singleShot",
            side_effect=lambda _ms, callback: callback(),
        ):
            controller._on_install_complete(True)

        assert app_state.is_installing is False
        assert app_state._scan_blocked is False
        mod_service.update_mod.assert_called_once_with(next_mod)
        assert app_window.game_launch.update_button_state.called

    def test_install_status_token_ignores_broken_window_status(self, app_state):
        from controllers.mod.operations_controller import ModOperationsController

        app_window = Mock()
        app_window._install_op_id = 7
        app_window._update_status.side_effect = RuntimeError("status widget deleted")
        app_state.is_installing = True
        controller = ModOperationsController(
            app_state=app_state,
            feedback_service=Mock(),
            mod_service=Mock(),
            app_window=app_window,
        )

        controller.on_install_status_token("Downloading", "yellow", 7)

        app_window._update_status.assert_called_once_with("Downloading", "yellow")


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
        from app.tab.handler import handle_tab_changed

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
        from services.mod.service import ModManager
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

    def test_summary_delete_confirmation_failure_does_not_log_delete_failure(
        self, app_state, feedback_service, caplog
    ):
        """Checks that a broken confirmation dialog does not masquerade as deletion."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            app_window=app_window,
        )
        mod = SimpleNamespace(id="ghost_mod", name="Ghost Mod")

        with (
            patch(
                "PyQt6.QtWidgets.QMessageBox.question",
                side_effect=RuntimeError("dialog deleted"),
            ),
            caplog.at_level("WARNING"),
        ):
            controller._on_summary_delete(mod)

        controller.mod_service.uninstall_mod.assert_not_called()
        controller.used_mods_service.remove_mod_from_all_chapters.assert_not_called()
        assert "Delete confirmation dialog failed" in caplog.text
        assert "Failed to delete mod" not in caplog.text

    def test_summary_readme_missing_info_failure_does_not_log_readme_failure(
        self, app_state, feedback_service, tmp_path, caplog
    ):
        """Checks that a broken missing-README notice is logged as feedback only."""
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            app_window=app_window,
        )
        controller.mod_service.get_mod_folder_path.return_value = str(tmp_path)
        mod = SimpleNamespace(id="ghost_mod", name="Ghost Mod")

        with (
            patch(
                "PyQt6.QtWidgets.QMessageBox.information",
                side_effect=RuntimeError("dialog deleted"),
            ),
            caplog.at_level("WARNING"),
        ):
            controller._on_summary_readme(mod)

        assert "Library information dialog failed" in caplog.text
        assert "Failed to open mod README dialog" not in caplog.text

    def test_modpack_failure_ignores_broken_feedback(
        self, app_state, feedback_service, tmp_path
    ):
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        mod_service = Mock()
        feedback = Mock()
        feedback.show_message.side_effect = RuntimeError("feedback deleted")
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        modpack_dir = tmp_path / "failed_modpack"
        modpack_dir.mkdir()
        app_state.current_task = object()

        controller._on_modpack_finished(False, str(modpack_dir))

        assert not modpack_dir.exists()
        assert app_state.current_task is None
        feedback.show_message.assert_called_once()


class TestModImportExportController:
    """Tests for controllers."""

    def test_format_import_exception_reports_archive_not_found(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController
        from services.localization_service import tr

        controller = ModImportExportController(
            Mock(mods_dir=temp_dir, all_mods=[]), Mock(), Mock()
        )

        assert controller._format_import_exception(
            FileNotFoundError(2, "No such file", os.path.join(temp_dir, "missing.zip")),
            file_path=os.path.join(temp_dir, "missing.zip"),
        ) == tr("errors.archive_not_found")

    def test_materialize_local_import_raises_localized_permission_error(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController
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
                "controllers.mod.import_export_controller.extract_archive",
                side_effect=PermissionError(13, "Permission denied", source_file),
            ),
        ):
            with pytest.raises(ValueError) as exc_info:
                controller._materialize_local_import(source_file, extract_dir)
            assert str(exc_info.value) == tr(
                "errors.permission_denied", path=source_file
            )

    def test_manual_import_error_dialog_failure_is_suppressed(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController

        controller = ModImportExportController(
            Mock(mods_dir=temp_dir, all_mods=[]), Mock(), Mock()
        )
        controller._prepare_local_files_for_manual_install = Mock(
            side_effect=RuntimeError("archive broken")
        )

        with patch(
            "controllers.mod.import_export_controller.QMessageBox.critical",
            side_effect=RuntimeError("dialog already deleted"),
        ):
            controller._show_import_error_with_manual_install(
                os.path.join(temp_dir, "broken.zip"), "broken"
            )

    def test_remote_import_finished_ui_failure_is_suppressed(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        app_state.reset_install_state = Mock()
        app_window = Mock()
        app_window.feedback_service.update_status.side_effect = RuntimeError(
            "status widget deleted"
        )
        app_window.feedback_service.show_message.side_effect = RuntimeError(
            "dialog already deleted"
        )
        controller = ModImportExportController(app_state, Mock(), app_window)
        controller._active_remote_import_source = "url"

        controller._on_mod_install_finished(False, "download failed")

        app_state.reset_install_state.assert_called_once()

    def test_remote_import_success_information_failure_is_suppressed(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        app_state.reset_install_state = Mock()
        controller = ModImportExportController(app_state, Mock(), Mock())
        controller._active_remote_import_source = "url"
        controller._refresh_mod_list = Mock()

        with patch(
            "controllers.mod.import_export_controller.QMessageBox.information",
            side_effect=RuntimeError("dialog already deleted"),
        ):
            controller._on_mod_install_finished(True, "done")

        app_state.reset_install_state.assert_called_once()
        controller._refresh_mod_list.assert_called_once()

    def test_show_mod_details_config_error_dialog_failure_is_suppressed(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController

        mod_data = SimpleNamespace(id="broken_mod", name="Broken Mod")
        mod_folder = os.path.join(temp_dir, "broken_mod")
        os.makedirs(mod_folder, exist_ok=True)
        with open(
            os.path.join(mod_folder, "mod_config.json"), "w", encoding="utf-8"
        ) as handle:
            handle.write("{bad json")
        mod_service = Mock(get_mod_folder_path=Mock(return_value=mod_folder))
        controller = ModImportExportController(
            Mock(mods_dir=temp_dir, all_mods=[]), mod_service, Mock()
        )

        with patch(
            "controllers.mod.import_export_controller.QMessageBox.critical",
            side_effect=RuntimeError("dialog already deleted"),
        ):
            controller.show_mod_details_dialog(mod_data)

    def test_local_import_success_information_failure_does_not_trigger_manual_fallback(
        self, temp_dir
    ):
        from controllers.mod.import_export_controller import ModImportExportController

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        controller = ModImportExportController(app_state, Mock(), Mock())
        content_path = os.path.join(temp_dir, "extract")
        os.makedirs(content_path, exist_ok=True)
        save_json(
            os.path.join(content_path, "mod_config.json"),
            {
                "id": "success_mod",
                "name": "Success Mod",
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
        controller._show_import_error_with_manual_install = Mock()

        with (
            patch(
                "controllers.mod.import_export_controller.QMessageBox.information",
                side_effect=RuntimeError("dialog already deleted"),
            ),
            patch(
                "controllers.mod.import_export_controller.find_deltamod_info_file",
                return_value=False,
            ),
        ):
            controller._install_mod_from_file(os.path.join(temp_dir, "success.zip"))

        assert os.path.isdir(os.path.join(temp_dir, "Success Mod"))
        controller._refresh_mod_list.assert_called_once()
        controller._show_import_error_with_manual_install.assert_not_called()

    def test_url_import_start_failure_feedback_failure_is_suppressed(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        app_window = Mock()
        app_window.feedback_service.show_message.side_effect = RuntimeError(
            "toast deleted"
        )
        controller = ModImportExportController(app_state, Mock(), app_window)

        with patch(
            "workers.install.url_install_worker.UrlInstallThread",
            side_effect=RuntimeError("worker failed"),
        ):
            controller._install_mod_from_url("https://example.com/mod.zip")

        app_window.feedback_service.show_message.assert_called_once()

    def test_url_import_worker_status_uses_safe_feedback(self, temp_dir):
        from controllers.mod.import_export_controller import ModImportExportController

        class Signal:
            def __init__(self) -> None:
                self.callback = None

            def connect(self, callback):
                self.callback = callback

        class Worker:
            def __init__(self, *_args) -> None:
                self.status = Signal()
                self.progress = Signal()
                self.result_ready = Signal()
                self.manual_install_required = Signal()
                self.started = False

            def start(self):
                self.started = True

        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        app_window = Mock()
        app_window.feedback_service.update_status.side_effect = RuntimeError(
            "status deleted"
        )
        controller = ModImportExportController(app_state, Mock(), app_window)

        with patch(
            "workers.install.url_install_worker.UrlInstallThread",
            Worker,
        ):
            controller._install_mod_from_url("https://example.com/mod.zip")

        worker = app_state.current_task
        worker.status.callback("Downloading", "yellow")

        app_window.feedback_service.update_status.assert_called_once_with(
            "Downloading", "yellow"
        )

    def test_manual_install_required_error_feedback_failure_still_cleans_temp_dir(
        self, temp_dir
    ):
        from controllers.mod.import_export_controller import ModImportExportController

        manual_temp = os.path.join(temp_dir, "manual_temp")
        os.makedirs(manual_temp, exist_ok=True)
        app_state = Mock(mods_dir=temp_dir, all_mods=[])
        app_state.reset_install_state = Mock(side_effect=RuntimeError("reset failed"))
        app_window = Mock()
        app_window.feedback_service.show_message.side_effect = RuntimeError(
            "toast deleted"
        )
        controller = ModImportExportController(app_state, Mock(), app_window)

        controller._on_manual_install_required(
            os.path.join(temp_dir, "prepared"),
            os.path.join(temp_dir, "archive.zip"),
            manual_temp,
        )

        assert not os.path.exists(manual_temp)
        app_window.feedback_service.show_message.assert_called_once()


class TestModManagerErrorFormatting:
    def test_describe_uninstall_error_reports_missing_file(self):
        from services.localization_service import tr
        from services.mod.service import ModManager

        assert ModManager._describe_uninstall_error(
            FileNotFoundError(2, "No such file", "C:/mods/missing")
        ) == tr("errors.file_not_found", path="C:/mods/missing")

    def test_materialize_local_import_keeps_plain_files(self, temp_dir):
        """Checks that materializeing local import keeps plain files."""
        from controllers.mod.import_export_controller import ModImportExportController

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
        from controllers.mod.import_export_controller import ModImportExportController

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
            patch("controllers.mod.import_export_controller.QMessageBox.information"),
            patch(
                "controllers.mod.import_export_controller.find_deltamod_info_file",
                return_value=False,
            ),
        ):
            controller._install_mod_from_file(
                os.path.join(temp_dir, "archive-name.zip")
            )

        assert os.path.isdir(os.path.join(temp_dir, "Real Mod Name"))
        assert not os.path.exists(os.path.join(temp_dir, "archive-name"))

    def test_local_import_ignores_stale_in_memory_mod_with_missing_folder(
        self, temp_dir
    ):
        """A deleted mod id can be imported again without a manual refresh."""
        from controllers.mod.import_export_controller import ModImportExportController

        stale_mod = SimpleNamespace(id="maustweaks", name="MausTweaks")
        app_state = Mock(mods_dir=temp_dir, all_mods=[stale_mod])
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = None
        controller = ModImportExportController(app_state, mod_service, Mock())
        content_path = os.path.join(temp_dir, "extracted")
        os.makedirs(content_path, exist_ok=True)
        save_json(
            os.path.join(content_path, "mod_config.json"),
            {
                "id": "maustweaks",
                "name": "MausTweaks",
                "version": "1.0.0",
                "author": "Y114",
                "game": "deltarune",
                "files": {"deltarune_1": {"data_file_path": "patch.g3mpatch"}},
            },
            indent=2,
        )
        with open(
            os.path.join(content_path, "patch.g3mpatch"), "wb"
        ) as patch_file:
            patch_file.write(b"patch")
        controller._materialize_local_import = Mock(return_value=content_path)
        controller._refresh_mod_list = Mock()
        controller._merge_into_existing_mod = Mock()

        with (
            patch("controllers.mod.import_export_controller.QMessageBox.information"),
            patch(
                "controllers.mod.import_export_controller.find_deltamod_info_file",
                return_value=False,
            ),
        ):
            controller._install_mod_from_file(os.path.join(temp_dir, "maus.zip"))

        controller._merge_into_existing_mod.assert_not_called()
        assert os.path.isdir(os.path.join(temp_dir, "MausTweaks"))

    def test_install_mod_from_file_uses_metadata_name_for_target_folder(self, temp_dir):
        """Checks that nested metadata configs import with the normalized mod name."""
        from controllers.mod.import_export_controller import ModImportExportController

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
            patch("controllers.mod.import_export_controller.QMessageBox.information"),
            patch(
                "controllers.mod.import_export_controller.find_deltamod_info_file",
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

    def test_steam_launch_direct_conflict_ignores_broken_feedback(self, app_state):
        """Checks steam toggle conflict still reverts when warning feedback is gone."""
        from controllers.settings_controller import SettingsController

        app_state.current_mode = "chapter"
        app_state.local_config["direct_launch_chapter"] = "deltarune_1"
        app_state.game_mode = SimpleNamespace(block_steam_with_direct_launch=True)
        feedback_service = Mock()
        feedback_service.show_message.side_effect = RuntimeError("toast deleted")
        settings_service = Mock()
        app_window = Mock()
        app_window.launch_via_steam_checkbox.isChecked.return_value = True

        controller = SettingsController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            used_mods_service=Mock(),
            customization_service=Mock(),
            app_window=app_window,
        )

        controller.on_toggle_steam_launch()

        feedback_service.show_message.assert_called_once()
        app_window.launch_via_steam_checkbox.setChecked.assert_called_once_with(False)
        settings_service.on_toggle_steam_launch.assert_not_called()


class TestSearchDisplayController:
    """Tests for controllers."""

    def test_search_display_controller_initialization(
        self, app_state, feedback_service
    ):
        """Checks that searching display controller initialization."""
        from controllers.mod.operations_controller import ModOperationsController
        from controllers.search_display_controller import SearchDisplayController
        from services.mod.service import ModManager

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

    def test_library_summary_readme_opens_dialog_without_status_announcement(
        self, app_state, feedback_service, monkeypatch, temp_dir
    ):
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = temp_dir
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        mod_data = SimpleNamespace(name="Test Mod", id="test_mod")

        monkeypatch.setattr(
            "utils.mod.readme_utils.find_mod_readme_files",
            lambda _path: [str(Path(temp_dir) / "README.md")],
        )

        class _Dialog:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def exec(self):
                return 0

        monkeypatch.setattr(
            "ui.dialogs.mod.readme_dialog.ModReadmeDialog",
            _Dialog,
        )

        controller._on_summary_readme(mod_data)

    def test_library_summary_readme_passes_mod_name_into_dialog(
        self, app_state, feedback_service, monkeypatch, temp_dir, caplog
    ):
        from controllers.library_display_controller import LibraryDisplayController

        app_window = Mock()
        mod_service = Mock()
        mod_service.get_mod_folder_path.return_value = temp_dir
        controller = LibraryDisplayController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=mod_service,
            used_mods_service=Mock(),
            app_window=app_window,
        )
        mod_data = SimpleNamespace(name="Named Mod", id="named_mod")
        monkeypatch.setattr(
            "utils.mod.readme_utils.find_mod_readme_files",
            lambda _path: [str(Path(temp_dir) / "README.md")],
        )
        captured = {}

        class _Dialog:
            def __init__(
                self, app_state_arg, mod_name_arg, readme_files_arg, parent=None
            ) -> None:
                captured["app_state"] = app_state_arg
                captured["mod_name"] = mod_name_arg
                captured["readme_files"] = readme_files_arg
                captured["parent"] = parent

            def exec(self):
                return 0

        monkeypatch.setattr("ui.dialogs.mod.readme_dialog.ModReadmeDialog", _Dialog)

        with caplog.at_level("ERROR"):
            controller._on_summary_readme(mod_data)

        assert captured["mod_name"] == "Named Mod"
        assert captured["parent"] is app_window
        assert "Failed to open mod README dialog" not in caplog.text


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
        from services.mod.service import ModManager
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
            patch(
                "controllers.theme_controller.add_application_font_from_file"
            ) as add_mock,
        ):
            controller._reload_custom_font()
        remove_mock.assert_not_called()
        add_mock.assert_not_called()

    def test_reload_custom_font_unregisters_removed_font(
        self, app_state, feedback_service
    ):
        from controllers.theme_controller import ThemeController

        customization_service = Mock()
        customization_service.get_custom_font_path.return_value = None
        app_window = Mock()
        app_window._custom_font_id = 7
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=Mock(),
            customization_service=customization_service,
            app_window=app_window,
        )

        with (
            patch(
                "PyQt6.QtGui.QFontDatabase.removeApplicationFont"
            ) as remove_mock,
            patch(
                "controllers.theme_controller.localization_service.load_font",
                return_value="Default Font",
            ),
        ):
            controller._reload_custom_font()

        remove_mock.assert_called_once_with(7)
        assert app_window._custom_font_id is None
        assert app_window.custom_font_family == "Default Font"

    def test_theme_save_success_ignores_broken_feedback(self, app_state, tmp_path):
        """Checks theme export remains complete when success feedback is gone."""
        from controllers.theme_controller import ThemeController

        feedback_service = Mock()
        feedback_service.show_message.side_effect = RuntimeError("toast deleted")
        settings_service = Mock()
        app_window = Mock()
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=settings_service,
            customization_service=Mock(),
            app_window=app_window,
        )
        controller.init_theme_list = Mock()

        with (
            patch(
                "PyQt6.QtWidgets.QInputDialog.getText",
                return_value=("Saved Theme", True),
            ),
            patch(
                "utils.path_utils.get_user_themes_dir",
                return_value=str(tmp_path),
            ),
        ):
            controller.on_theme_save_clicked()

        settings_service.write_theme_archive.assert_called_once()
        controller.init_theme_list.assert_called_once()
        feedback_service.show_message.assert_called_once()

    def test_builtin_theme_delete_warning_ignores_broken_feedback(
        self, app_state, tmp_path
    ):
        """Checks built-in theme delete warning cannot crash theme controller."""
        from controllers.theme_controller import ThemeController

        builtin_theme = tmp_path / "Builtin.zip"
        builtin_theme.write_bytes(b"theme")
        feedback_service = Mock()
        feedback_service.show_message.side_effect = RuntimeError("toast deleted")
        app_window = Mock()
        app_window.themes_list_widget.currentText.return_value = "Builtin"
        controller = ThemeController(
            app_state=app_state,
            feedback_service=feedback_service,
            settings_service=Mock(),
            customization_service=Mock(),
            app_window=app_window,
        )

        with patch(
            "utils.path_utils.resource_path",
            return_value=str(builtin_theme),
        ):
            controller.on_theme_delete_clicked()

        feedback_service.show_message.assert_called_once()

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
        from services.mod.service import ModManager
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

    def test_external_game_process_blocks_launch_button(self, qapp):
        from config.config import UI_COLORS
        from controllers.game_launch_controller import GameLaunchController
        from services.localization_service import tr

        app_state = SimpleNamespace(
            game_mode=SimpleNamespace(supports_full_install=False),
            game_is_running=False,
            external_game_process_name="DELTARUNE.exe",
            is_installing=False,
            operation_cancelled=False,
            is_patching=False,
            initialization_completed=True,
            local_config={},
            action_button_text=None,
            action_button_enabled=True,
            progress_bar_visible=False,
            progress_bar_value=0,
        )
        feedback_service = Mock()
        used_mods_service = Mock()
        used_mods_service.check_used_mods_need_updates.return_value = False
        game_launcher = Mock()
        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=used_mods_service,
            settings_service=Mock(),
            game_launcher=game_launcher,
            customization_service=Mock(),
            app_window=Mock(),
        )

        controller.update_button_state()
        controller.on_action_button_click()

        assert app_state.action_button_text == tr("ui.launch_button")
        assert app_state.action_button_enabled is False
        feedback_service.update_status.assert_called_with(
            tr(
                "status.close_current_process_to_launch",
                process_name="DELTARUNE.exe",
            ),
            UI_COLORS["status_warning"],
        )
        game_launcher.launch_game_with_all_mods.assert_not_called()
        qapp.processEvents()

    def test_external_game_process_status_clears_after_exit(self, qapp):
        from config.config import UI_COLORS
        from controllers.game_launch_controller import GameLaunchController
        from services.localization_service import tr

        app_state = SimpleNamespace(
            game_mode=SimpleNamespace(supports_full_install=False),
            game_is_running=False,
            external_game_process_name="DELTARUNE.exe",
            is_installing=False,
            operation_cancelled=False,
            is_patching=False,
            initialization_completed=True,
            local_config={},
            action_button_text=None,
            action_button_enabled=True,
        )
        feedback_service = Mock()
        used_mods_service = Mock()
        used_mods_service.check_used_mods_need_updates.return_value = False
        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=used_mods_service,
            settings_service=Mock(),
            game_launcher=Mock(),
            customization_service=Mock(),
            app_window=Mock(),
        )

        with patch(
            "controllers.game_launch_controller.get_running_game_process_name",
            return_value=None,
        ):
            controller.refresh_external_game_process()

        assert app_state.external_game_process_name is None
        assert app_state.action_button_enabled is True
        feedback_service.update_status.assert_called_with(
            tr("status.ready"), UI_COLORS["status_info"]
        )
        controller._external_game_timer.stop()
        qapp.processEvents()

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

    def test_full_install_finished_ignores_broken_status_feedback(self):
        from controllers.game_launch_controller import GameLaunchController

        app_state = Mock()
        app_state.game_mode = Mock(
            game_id="deltarune",
            supports_full_install=True,
        )
        app_state.local_config = {}
        app_state.clear_current_task = Mock()
        feedback_service = Mock()
        feedback_service.update_status.side_effect = RuntimeError(
            "status widget deleted"
        )
        settings_service = Mock()
        app_window = Mock()
        app_window.full_install_checkbox = Mock()
        controller = GameLaunchController(
            app_state=app_state,
            feedback_service=feedback_service,
            mod_service=Mock(),
            used_mods_service=Mock(),
            settings_service=settings_service,
            game_launcher=Mock(),
            customization_service=Mock(),
            app_window=app_window,
        )
        controller.update_button_state = Mock()

        controller.on_full_install_finished(True, "C:/Games/Deltarune")

        app_state.game_mode.set_game_path.assert_called_once_with(
            app_state.local_config, "C:/Games/Deltarune"
        )
        settings_service.write_local_config.assert_called_once()
        controller.update_button_state.assert_called_once()


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


@pytest.mark.parametrize("mode", ["chapter", "normal"])
def test_modpack_step_plans_do_not_add_unrelated_chapters(
    app_state, feedback_service, tmp_path, monkeypatch, mode
):
    from PyQt6.QtWidgets import QDialog

    from controllers.library_display_controller import LibraryDisplayController
    from models.game_modes import get_game

    selected = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    app_state.game_mode = get_game("deltarune")
    app_state.current_mode = mode
    app_state.mods_dir = str(tmp_path)
    used = Mock()
    used.get_used_mods_list.return_value = selected
    used.get_active_mod_steps.return_value = {
        "deltarune_1": [selected],
        "deltarune_5": [[SimpleNamespace(id="stale")]],
    }
    app = Mock()
    app.create_modpack_button = object()
    controller = LibraryDisplayController(app_state, feedback_service, Mock(), used, app)
    monkeypatch.setattr(controller, "_get_current_chapter_id", lambda: "deltarune_1")
    monkeypatch.setattr(
        controller,
        "_distribute_mods_across_chapters",
        lambda _mods: {"deltarune_1": selected},
    )
    dialog = Mock()
    dialog.exec.return_value = QDialog.DialogCode.Accepted
    dialog.get_modpack_name.return_value = "Pack"
    dialog.get_xdelta_modpack.return_value = False
    monkeypatch.setattr(
        "ui.dialogs.mod.pack_create_dialog.CreateModpackDialog",
        lambda *_args, **_kwargs: dialog,
    )
    created = {}

    class FakeThread:
        progress_update = Mock()
        status_update = Mock()
        warning_confirmation_needed = Mock()
        result_ready = Mock()

        def __init__(self, chapter_mods, *_args, **_kwargs) -> None:
            created.update(chapter_mods)

        def start(self):
            return None

    monkeypatch.setattr("workers.modpack_create_worker.CreateModpackThread", FakeThread)

    controller.on_create_modpack_button_click()

    assert set(created) == {"deltarune_1"}
