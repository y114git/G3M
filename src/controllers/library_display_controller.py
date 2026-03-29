"""Controller for managing the library display of installed mods."""

import contextlib
import logging
import os
import shutil

from PyQt6.QtCore import QEventLoop, QObject, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication

from app.game_ui import show_chapter_mode_instruction
from services.game_detection_service import get_chapter_id_for_game_mode
from services.localization_service import tr
from services.mod_filter_service import filter_and_sort_mods
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from ui.dialogs.mod_priority_dialog import ModPriorityDialog
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from utils.mod_utils import get_mod_id


def _bound_checkbox_is_checked(owner, attr_name: str) -> bool:
    checkbox = getattr(owner, "__dict__", {}).get(attr_name)
    is_checked = getattr(checkbox, "isChecked", None)
    return bool(checkbox and callable(is_checked) and is_checked())


class LibraryDisplayController:
    """Manages the display and interaction of installed mods in the library."""

    def __init__(
        self, app_state, feedback_service, mod_service, used_mods_service, app_window
    ) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.used_mods_service = used_mods_service
        self.app = app_window
        self._updating_display = False
        self._last_render_signature = None
        self._pending_view_signature = None

    def _current_view_signature(self):
        current_game = (
            getattr(
                self.app,
                "game_type_combo",
                type("", (), {"currentData": lambda: "deltarune"}),
            ).currentData()
            if hasattr(self.app, "game_type_combo")
            else "deltarune"
        ) or "deltarune"
        is_chapter_mode = (
            hasattr(self.app, "chapter_mode_checkbox")
            and self.app.chapter_mode_checkbox.isChecked()
        )
        sort_type = (
            self.app.library_sort_combo.currentIndex()
            if hasattr(self.app, "library_sort_combo")
            else 0
        )
        selected_tags = tuple(
            sorted(
                tag
                for tag in (
                    "textedit"
                    if _bound_checkbox_is_checked(self.app, "library_tag_textedit")
                    else None,
                    "customization"
                    if _bound_checkbox_is_checked(
                        self.app, "library_tag_customization"
                    )
                    else None,
                    "gameplay"
                    if _bound_checkbox_is_checked(self.app, "library_tag_gameplay")
                    else None,
                    "other"
                    if _bound_checkbox_is_checked(self.app, "library_tag_other")
                    else None,
                    "CYOP/AFOM"
                    if current_game == "pizzatower"
                    and _bound_checkbox_is_checked(self.app, "library_tag_cyop_afom")
                    else None,
                )
                if tag
            )
        )
        return (
            bool(is_chapter_mode),
            getattr(self.app_state, "selected_chapter_id", None)
            if is_chapter_mode
            else None,
            getattr(
                self.app,
                "game_type_combo",
                type("", (), {"currentData": lambda: "deltarune"}),
            ).currentData()
            if hasattr(self.app, "game_type_combo")
            else "deltarune",
            sort_type,
            bool(getattr(self.app, "library_sort_ascending", False)),
            bool(
                _bound_checkbox_is_checked(self.app, "library_tag_gamebanana")
            ),
            selected_tags,
            getattr(self.app, "library_search_text", "") or "",
        )

    @staticmethod
    def _installed_mods_signature(installed_mods) -> tuple:
        return tuple(
            (
                mod.get("id") or "",
                mod.get("added_date") or "",
                mod.get("name") or "",
                mod.get("version") or "",
                mod.get("game") or "",
                mod.get("folder_name") or "",
            )
            for mod in installed_mods
        )

    def _has_rendered_library_widgets(self) -> bool:
        layout = getattr(self.app, "installed_mods_layout", None)
        if layout is None:
            return False
        return layout.count() > 1

    def _installed_mods_cache_is_valid(self) -> bool:
        return bool(getattr(self.mod_service, "_installed_mods_cache_valid", False))

    def _show_chapter_mode_instruction(self) -> None:
        if hasattr(self.app, "installed_mods_container") and hasattr(
            self.app, "installed_mods_layout"
        ):
            self.app.installed_mods_container.setUpdatesEnabled(False)
            try:
                clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
                show_chapter_mode_instruction(self.app)
            finally:
                self.app.installed_mods_container.setUpdatesEnabled(True)

    def update_display(self):
        if not hasattr(self.app, "installed_mods_layout"):
            return
        self._clear_summary()
        is_chapter_mode = (
            hasattr(self.app, "chapter_mode_checkbox")
            and self.app.chapter_mode_checkbox.isChecked()
        )
        if is_chapter_mode:
            self.update_for_chapter_mode(self.app_state.selected_chapter_id)
            return
        view_signature = self._current_view_signature()
        if (
            self._installed_mods_cache_is_valid()
            and self._has_rendered_library_widgets()
            and self._last_render_signature
            and self._last_render_signature[0] == view_signature
        ):
            self.update_mod_widgets_active_status()
            with contextlib.suppress(Exception):
                self.app.game_launch.update_button_state()
            return
        self._pending_view_signature = view_signature
        self.refresh_async()

    def _filter_and_sort_installed(self, installed_mods):
        filters, _ = self._build_library_filters_and_sort()
        filtered_mods = filter_and_sort_mods(installed_mods, filters)
        if hasattr(self.app, "library_sort_combo"):
            sort_type = self.app.library_sort_combo.currentIndex()
            is_asc = self.app.library_sort_ascending
            reverse = not is_asc if sort_type == 0 else is_asc
            filtered_mods.sort(
                key=lambda mod: (
                    mod.get("name", "").lower()
                    if sort_type == 0
                    else mod.get("added_date") or ""
                ),
                reverse=reverse,
            )
        return filtered_mods

    def _distribute_mods_across_chapters(self, mods_list):
        chapter_mods = {}
        for tab in self.app_state.game_mode.tabs:
            tab_mods = [
                mod
                for mod in mods_list
                if hasattr(mod, "get_chapter_data") and mod.get_chapter_data(tab.tab_id)
            ]
            if tab_mods:
                chapter_mods[tab.tab_id] = tab_mods
        return chapter_mods

    def _build_library_filters_and_sort(self):
        current_game_type = (
            getattr(
                self.app,
                "game_type_combo",
                type("", (), {"currentData": lambda: "deltarune"}),
            ).currentData()
            or "deltarune"
        )
        selected_tags = []
        only_gamebanana = False
        if hasattr(self.app, "library_tag_widgets"):
            tag_map = {
                self.app.library_tag_textedit: "textedit",
                self.app.library_tag_customization: "customization",
                self.app.library_tag_gameplay: "gameplay",
                self.app.library_tag_other: "other",
            }
            if current_game_type == "pizzatower":
                tag_map[self.app.library_tag_cyop_afom] = "CYOP/AFOM"
            selected_tags = [
                tag for checkbox, tag in tag_map.items() if checkbox.isChecked()
            ]
            only_gamebanana = _bound_checkbox_is_checked(
                self.app, "library_tag_gamebanana"
            )
        search_text = getattr(self.app, "library_search_text", "").lower()
        filters = {
            "tags": selected_tags,
            "game": current_game_type,
            "search_text": search_text,
            "hide_banned": False,
            "only_gamebanana": only_gamebanana,
            "status_filter": ["approved", "pending", "unknown"],
        }
        sort_config = None
        if (
            hasattr(self.app, "library_sort_combo")
            and self.app.library_sort_combo.currentIndex() == 1
        ):
            sort_config = {"sort_type": 1, "reverse": self.app.library_sort_ascending}
        return (filters, sort_config)

    def enter_chapter_mode(self):
        """Called when entering chapter mode to clear summary and disable priority widgets."""
        self._clear_summary()
        if hasattr(self.app, "priority_button"):
            self._set_priority_widgets_enabled(False)

    def update_for_chapter_mode(self, selected_chapter_id):
        if (
            not hasattr(self.app, "installed_mods_layout")
            or (
                hasattr(self.app, "_updating_chapter_mods")
                and self.app._updating_chapter_mods
            )
            or selected_chapter_id is None
        ):
            if selected_chapter_id is None:
                show_chapter_mode_instruction(self.app)
            return
        self._clear_summary()
        self.app._updating_chapter_mods = True
        container = getattr(self.app, "installed_mods_container", None)
        cards_parent = getattr(self.app, "installed_mods_widget", None) or getattr(
            self.app, "installed_mods_scroll", None
        )
        if container:
            container.setUpdatesEnabled(False)
        try:
            clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
            installed_mods = self.mod_service.get_installed_mods_list()
            filtered_mods = self._filter_and_sort_installed(installed_mods)
            for mod_info in filtered_mods:
                mod_data = self.mod_service.create_mod_object_from_info(
                    mod_info, getattr(self.app_state, "all_mods", None)
                )
                if mod_data and self.mod_service.mod_has_files_for_chapter(
                    mod_data, selected_chapter_id
                ):
                    mod_widget = InstalledModWidget(
                        mod_data,
                        parent=cards_parent,
                        parent_app=self.app,
                    )
                    mod_widget.clicked.connect(self.on_mod_clicked)
                    mod_widget.details_requested.connect(self._on_summary_edit)
                    mod_widget.use_requested.connect(
                        lambda md=mod_data: self._handle_mod_use(
                            md, selected_chapter_id
                        )
                    )
                    mod_widget.set_active(
                        self.used_mods_service.is_mod_used_for_chapter(
                            mod_data, selected_chapter_id
                        )
                    )
                    self.app.installed_mods_layout.insertWidget(
                        self.app.installed_mods_layout.count() - 1, mod_widget
                    )
                    mod_widget.show()
            if self.app.installed_mods_layout.count() <= 1:
                tab = self.app_state.game_mode.get_tab(selected_chapter_id)
                chapter_name = tr(tab.name_key) if tab else str(selected_chapter_id)
                show_empty_message_in_layout(
                    self.app.installed_mods_layout,
                    tr("ui.no_mods_for_chapter", chapter_name=chapter_name),
                    self.app_state.local_config,
                    font_size=16,
                )
            self._update_priority_button_visibility(selected_chapter_id)
        finally:
            if container:
                container.setUpdatesEnabled(True)
            self.app._updating_chapter_mods = False

    def refresh_async(self):
        if (
            hasattr(self.app, "_installed_scan_thread")
            and self.app._installed_scan_thread
            and self.app._installed_scan_thread.isRunning()
        ):
            return
        is_chapter_mode = (
            hasattr(self.app, "chapter_mode_checkbox")
            and self.app.chapter_mode_checkbox.isChecked()
        )
        if is_chapter_mode:
            selected_id = self.app_state.selected_chapter_id
            if selected_id is None:
                self._show_chapter_mode_instruction()
            else:
                self.update_for_chapter_mode(selected_id)
            return

        class _Scan(QThread):
            result_ready = pyqtSignal(list)

            def __init__(self, outer) -> None:
                super().__init__(outer if isinstance(outer, QObject) else None)
                self.outer = outer

            def run(self):
                try:
                    self.result_ready.emit(
                        self.outer.mod_service.get_installed_mods_list()
                    )
                except Exception:
                    self.result_ready.emit([])

        try:
            if (
                hasattr(self.app, "_installed_scan_thread")
                and self.app._installed_scan_thread
            ):
                if self.app._installed_scan_thread.isRunning():
                    self.app._installed_scan_thread.requestInterruption()
                    self.app._installed_scan_thread.wait(100)
                self.app._installed_scan_thread.deleteLater()
            self.app._installed_scan_thread = _Scan(self)
            self.app._installed_scan_thread.result_ready.connect(
                self.update_display_from_list
            )
            self.app._installed_scan_thread.start()
        except Exception:
            self.update_display_from_list(self.mod_service.get_installed_mods_list())

    def update_display_from_list(self, installed_mods):
        if self._updating_display:
            return
        self._updating_display = True
        try:
            is_chapter_mode = (
                hasattr(self.app, "chapter_mode_checkbox")
                and self.app.chapter_mode_checkbox.isChecked()
            )
            if is_chapter_mode:
                selected_id = self.app_state.selected_chapter_id
                if selected_id is None:
                    self._show_chapter_mode_instruction()
                else:
                    self.update_for_chapter_mode(selected_id)
                return
            view_signature = (
                self._pending_view_signature or self._current_view_signature()
            )
            render_signature = (
                view_signature,
                self._installed_mods_signature(installed_mods),
            )
            if (
                self._installed_mods_cache_is_valid()
                and self._has_rendered_library_widgets()
                and self._last_render_signature == render_signature
            ):
                self.update_mod_widgets_active_status()
                with contextlib.suppress(Exception):
                    self.app.game_launch.update_button_state()
                return
            container = getattr(self.app, "installed_mods_container", None)
            if container:
                container.setUpdatesEnabled(False)
            cards_parent = getattr(self.app, "installed_mods_widget", None) or getattr(
                self.app, "installed_mods_scroll", None
            )

            def _finish_display():
                if container:
                    container.setUpdatesEnabled(True)
                self.app._library_batch_render_in_progress = False

            try:
                clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
                existing_mods = [
                    mod_info
                    for mod_info in installed_mods
                    if self.mod_service.check_mod_exists(mod_info)
                ]
                filtered_mods = self._filter_and_sort_installed(existing_mods)
                mods = list(filtered_mods)
                batch_index = 0
            except Exception:
                _finish_display()
                raise

            def _build_next_batch(batch_size=25):
                nonlocal batch_index
                try:
                    self.app._library_batch_render_in_progress = True
                    start = batch_index
                    end = min(start + batch_size, len(mods))
                    for idx in range(start, end):
                        mod_info = mods[idx]
                        mod_data = self.mod_service.create_mod_object_from_info(
                            mod_info, getattr(self.app_state, "all_mods", None)
                        )
                        if mod_data:
                            mod_widget = InstalledModWidget(
                                mod_data,
                                parent=cards_parent,
                                parent_app=self.app,
                            )
                            mod_widget.clicked.connect(self.on_mod_clicked)
                            mod_widget.details_requested.connect(self._on_summary_edit)
                            mod_widget.use_requested.connect(self.on_mod_use)
                            self.app.installed_mods_layout.insertWidget(
                                self.app.installed_mods_layout.count() - 1, mod_widget
                            )
                            mod_widget.show()
                    batch_index = end
                    if end >= len(mods):
                        if self.app.installed_mods_layout.count() <= 1:
                            show_empty_message_in_layout(
                                self.app.installed_mods_layout,
                                tr("ui.empty"),
                                self.app_state.local_config,
                                font_size=18,
                            )
                        self.update_mod_widgets_active_status()
                        self.app.game_launch.update_button_state()
                        self._refresh_summary_from_selection()
                        self._last_render_signature = render_signature
                        _finish_display()
                    else:
                        QTimer.singleShot(0, _build_next_batch)
                except Exception as e:
                    logging.debug("_build_next_batch failed", exc_info=e)
                    try:
                        if self.app.installed_mods_layout.count() <= 1:
                            show_empty_message_in_layout(
                                self.app.installed_mods_layout,
                                tr("ui.empty"),
                                self.app_state.local_config,
                                font_size=18,
                            )
                        self.update_mod_widgets_active_status()
                        self.app.game_launch.update_button_state()
                        self._refresh_summary_from_selection()
                    except Exception as e2:
                        logging.debug(
                            "Cleanup after _build_next_batch failure failed",
                            exc_info=e2,
                        )
                    _finish_display()

            _build_next_batch()
        except Exception as e:
            logging.debug("update_display failed", exc_info=e)
        finally:
            self._pending_view_signature = None
            self._updating_display = False

    def update_mod_widgets_active_status(self):
        if (
            not hasattr(self.app, "installed_mods_layout")
            or self.app.installed_mods_layout is None
        ):
            return
        is_chapter_mode = (
            hasattr(self.app, "chapter_mode_checkbox")
            and self.app.chapter_mode_checkbox.isChecked()
        )
        selected_chapter_id = (
            self.app_state.selected_chapter_id if is_chapter_mode else None
        )
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    if selected_chapter_id is not None:
                        is_used = self.used_mods_service.is_mod_used_for_chapter(
                            widget.mod_data, selected_chapter_id
                        )
                    else:
                        check_chapter_id = get_chapter_id_for_game_mode(
                            self.app_state.game_mode
                        )
                        is_used = self.used_mods_service.is_mod_used_for_chapter(
                            widget.mod_data, check_chapter_id
                        )
                    widget.set_active(is_used)

    def on_mod_clicked(self, mod_data):
        target_widget = None
        mod_data_key = get_mod_id(mod_data)
        for i in range(self.app.installed_mods_layout.count() - 1):
            try:
                item = self.app.installed_mods_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_id = get_mod_id(widget.mod_data)
                        if widget_mod_id == mod_data_key:
                            target_widget = widget
                            break
            except Exception as e:
                logging.debug(
                    "on_mod_clicked: failed while scanning installed mods layout",
                    exc_info=e,
                )
                continue
        if target_widget:
            self.clear_all_selections()
            target_widget.set_selected(True)
            self._show_mod_in_summary(mod_data)

    def _show_mod_in_summary(self, mod_data):
        summary = getattr(self.app, "mod_summary_panel", None)
        if not summary:
            return
        key = get_mod_id(mod_data)
        mod_folder = self.mod_service.get_mod_folder_path(key) if key else None
        if (not mod_folder or not os.path.isdir(mod_folder)) and hasattr(mod_data, "folder_path"):
            candidate = getattr(mod_data, "folder_path", None)
            if candidate and os.path.isdir(candidate):
                mod_folder = candidate
        if (not mod_folder or not os.path.isdir(mod_folder)) and hasattr(mod_data, "folder_name"):
            folder_name = getattr(mod_data, "folder_name", None)
            if folder_name:
                candidate = os.path.join(self.app_state.mods_dir, folder_name)
                if os.path.isdir(candidate):
                    mod_folder = candidate
        is_chapter_mode = (
            hasattr(self.app, "chapter_mode_checkbox")
            and self.app.chapter_mode_checkbox.isChecked()
        )
        chapter_id = (
            self.app_state.selected_chapter_id
            if is_chapter_mode
            else get_chapter_id_for_game_mode(self.app_state.game_mode)
        )
        is_active = (
            self.used_mods_service.is_mod_used_for_chapter(mod_data, chapter_id)
            if chapter_id is not None
            else False
        )
        summary.show_mod(mod_data, mod_folder=mod_folder, is_active=is_active)

    def _get_selected_widget(self):
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, InstalledModWidget) and getattr(widget, "is_selected", False):
                return widget
        return None

    def _refresh_summary_from_selection(self):
        summary = getattr(self.app, "mod_summary_panel", None)
        if not summary:
            return
        selected_widget = self._get_selected_widget()
        if selected_widget and getattr(selected_widget, "mod_data", None):
            self._show_mod_in_summary(selected_widget.mod_data)
            return
        current_mod = getattr(summary, "_current_mod", None)
        current_mod_id = get_mod_id(current_mod)
        if not current_mod_id:
            summary.show_empty()
            return
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            widget = item.widget() if item else None
            if not isinstance(widget, InstalledModWidget):
                continue
            if get_mod_id(getattr(widget, "mod_data", None)) == current_mod_id:
                self._show_mod_in_summary(widget.mod_data)
                return
        summary.show_empty()

    def _clear_summary(self):
        summary = getattr(self.app, "mod_summary_panel", None)
        if summary:
            summary.show_empty()

    def connect_summary_panel(self):
        """Connect summary panel action signals. Called from app_window after setup."""
        summary = getattr(self.app, "mod_summary_panel", None)
        if not summary:
            return
        summary.use_requested.connect(self.on_mod_use)
        summary.edit_requested.connect(self._on_summary_edit)
        summary.export_requested.connect(self._on_summary_export)
        summary.folder_requested.connect(self._on_summary_folder)
        summary.versions_requested.connect(self._on_summary_versions)
        summary.delete_requested.connect(self._on_summary_delete)
        summary.homepage_requested.connect(self._on_summary_homepage)
        summary.readme_requested.connect(self._on_summary_readme)

    def _on_summary_edit(self, mod_data):
        try:
            controller = getattr(self.app, "mod_import_export_controller", None)
            if controller:
                controller.show_mod_details_dialog(mod_data)
        except Exception as e:
            logging.error(f"Failed to open mod details: {e}", exc_info=True)

    def _on_summary_export(self, mod_data):
        try:
            controller = getattr(self.app, "mod_import_export_controller", None)
            if not controller:
                return
            from PyQt6.QtWidgets import QFileDialog

            mod_name = getattr(mod_data, "name", "mod") or "mod"
            safe_name = "".join(
                c if c.isalnum() or c in " _-" else "_" for c in mod_name
            ).strip()
            path, _ = QFileDialog.getSaveFileName(
                self.app,
                tr("ui.select_export_location"),
                f"{safe_name}.zip",
                "Zip (*.zip)",
            )
            if path:
                controller.export_mod_to_path(mod_data, path)
        except Exception as e:
            logging.error(f"Failed to export mod: {e}", exc_info=True)

    def _on_summary_folder(self, mod_data):
        try:
            key = get_mod_id(mod_data)
            mod_folder = self.mod_service.get_mod_folder_path(key) if key else None
            if mod_folder and os.path.isdir(mod_folder):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.normpath(mod_folder)))
        except Exception as e:
            logging.error(f"Failed to open mod folder: {e}", exc_info=True)

    def _on_summary_versions(self, mod_data):
        try:
            key = get_mod_id(mod_data)
            mod_folder = self.mod_service.get_mod_folder_path(key) if key else None
            if not mod_folder or not os.path.isdir(mod_folder):
                return
            from ui.dialogs.mod_versions_dialog import ModVersionsDialog

            dialog = ModVersionsDialog(
                mod_folder, mod_data, self.app_state, parent=self.app
            )
            dialog.exec()
        except Exception as e:
            logging.error(f"Failed to open versions dialog: {e}", exc_info=True)

    def _on_summary_delete(self, mod_data):
        try:
            from PyQt6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self.app,
                tr("dialogs.delete_confirmation"),
                tr("dialogs.delete_mod_confirmation"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.mod_service.uninstall_mod(mod_data)
                self._clear_summary()
                self._safe_update_after_mod_deletion()
        except Exception as e:
            logging.error(f"Failed to delete mod: {e}", exc_info=True)

    def _on_summary_homepage(self, mod_data):
        try:
            url = getattr(mod_data, "homepage", None) or getattr(
                mod_data, "description_url", None
            )
            if url:
                import webbrowser

                webbrowser.open(url)
        except Exception as e:
            logging.error(f"Failed to open homepage: {e}", exc_info=True)

    def _on_summary_readme(self, mod_data):
        try:
            key = get_mod_id(mod_data)
            mod_folder = self.mod_service.get_mod_folder_path(key) if key else None
            if not mod_folder or not os.path.isdir(mod_folder):
                return
            from PyQt6.QtWidgets import QMessageBox

            from utils.mod_readme_utils import find_mod_readme_files

            readme_files = find_mod_readme_files(mod_folder)
            if not readme_files:
                mod_name = getattr(mod_data, "name", "") or "Mod"
                QMessageBox.information(
                    self.app,
                    tr("dialogs.info"),
                    tr("dialogs.no_readme_files", mod_name=mod_name),
                )
                return
            from ui.dialogs.mod_readme_dialog import ModReadmeDialog

            dialog = ModReadmeDialog(
                self.app_state,
                getattr(mod_data, "name", "") or "Mod",
                readme_files,
                parent=self.app,
            )
            dialog.exec()
        except Exception as e:
            logging.error(f"Failed to open mod README dialog: {e}", exc_info=True)

    def _refresh_mod_list_targeted(self):
        """Refresh the mod list by only adding/removing changed widgets for smooth animation"""
        if self._updating_display:
            return

        self._updating_display = True
        try:
            current_mods = []
            layout = self.app.installed_mods_layout

            for i in range(layout.count() - 1):
                item = layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if hasattr(widget, "mod_data"):
                        current_mods.append(widget.mod_data)

            installed_mods = self.mod_service.get_installed_mods_list()
            existing_mods = [
                mod_info
                for mod_info in installed_mods
                if self.mod_service.check_mod_exists(mod_info)
            ]
            filtered_mods = self._filter_and_sort_installed(existing_mods)
            expected_mods = []

            for mod_info in filtered_mods:
                mod_data = self.mod_service.create_mod_object_from_info(
                    mod_info, getattr(self.app_state, "all_mods", None)
                )
                if mod_data:
                    expected_mods.append(mod_data)

            current_keys = {
                get_mod_id(mod) for mod in current_mods if get_mod_id(mod)
            }
            expected_keys = {
                get_mod_id(mod) for mod in expected_mods if get_mod_id(mod)
            }

            keys_to_add = expected_keys - current_keys
            keys_to_remove = current_keys - expected_keys

            widgets_to_remove = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if hasattr(widget, "mod_data"):
                        mod_id = get_mod_id(widget.mod_data)
                        if mod_id in keys_to_remove:
                            widgets_to_remove.append(widget)

            for widget in widgets_to_remove:
                widget.hide()
                widget.deleteLater()

            for mod_data in expected_mods:
                mod_id = get_mod_id(mod_data)
                if mod_id in keys_to_add:
                    cards_parent = getattr(
                        self.app, "installed_mods_widget", None
                    ) or getattr(self.app, "installed_mods_scroll", None)
                    mod_widget = InstalledModWidget(
                        mod_data,
                        parent=cards_parent,
                        parent_app=self.app,
                    )
                    mod_widget.clicked.connect(self.on_mod_clicked)
                    mod_widget.details_requested.connect(self._on_summary_edit)
                    mod_widget.use_requested.connect(self.on_mod_use)

                    insert_index = 0
                    for i, expected_mod in enumerate(expected_mods):
                        if get_mod_id(expected_mod) == mod_id:
                            insert_index = i
                            break

                    actual_count = layout.count()
                    insert_index = min(insert_index, actual_count)

                    layout.insertWidget(insert_index, mod_widget)
                    mod_widget.show()

            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            )
            self.update_mod_widgets_active_status()
            self.app.game_launch.update_button_state()
            self._refresh_summary_from_selection()

        except Exception as e:
            logging.error(f"Error in targeted refresh: {e}", exc_info=True)

            self.update_display()
        finally:
            self._updating_display = False

    def _safe_update_after_mod_deletion(self):
        try:
            self._refresh_mod_list_targeted()
            if hasattr(self.app, "search_display"):
                self.app.search_display.update_search_cards()
                self.app.search_display.update_filtered_mods(preserve_page=True)
        except Exception as e:
            logging.error(
                f"Error updating display after mod deletion: {e}", exc_info=True
            )

            try:
                self.update_display()
                if hasattr(self.app, "search_display"):
                    self.app.search_display.update_search_cards()
                    self.app.search_display.update_filtered_mods(preserve_page=True)
            except Exception as e2:
                logging.error(f"Fallback refresh also failed: {e2}", exc_info=True)

    def on_mod_use(self, mod_data):
        target_chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
        self._handle_mod_use(mod_data, target_chapter_id)

    def _handle_mod_use(self, mod_data, chapter_id):
        mod_widget = None
        for i in range(self.app.installed_mods_layout.count()):
            item = self.app.installed_mods_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, "mod_data") and hasattr(widget, "use_button"):
                    widget_mod_data = getattr(widget, "mod_data", None)
                    if widget_mod_data:
                        widget_mod_id = get_mod_id(widget_mod_data)
                        current_mod_id = get_mod_id(mod_data)
                        if widget_mod_id == current_mod_id:
                            mod_widget = widget
                            break
        self.used_mods_service.set_used_mod(chapter_id, mod_data)
        self.update_mod_widgets_active_status()
        self._update_priority_button_visibility(chapter_id)
        self._show_mod_in_summary(mod_data)
        if mod_widget:
            mod_widget.set_selected(False)

    def clear_all_selections(self):
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _get_current_chapter_id(self):
        if self.app_state.current_mode == "chapter":
            return self.app_state.selected_chapter_id
        gm = self.app_state.game_mode
        default_id = get_chapter_id_for_game_mode(gm)

        def _has_mods(tid, min_count=2):
            mods_list = self.used_mods_service.get_used_mods_list(tid)
            return len(mods_list) >= min_count if mods_list else False

        if _has_mods(default_id):
            return default_id
        for tab in gm.tabs:
            if _has_mods(tab.tab_id):
                return tab.tab_id
        return default_id

    def _set_priority_widgets_enabled(self, enabled: bool):
        self.app.priority_button.setEnabled(enabled)
        for attr in ("create_modpack_button",):
            if hasattr(self.app, attr):
                getattr(self.app, attr).setEnabled(enabled)

    def _update_priority_button_visibility(self, chapter_id=None):
        if not hasattr(self.app, "priority_button"):
            return
        if chapter_id is None:
            chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            self._set_priority_widgets_enabled(False)
            return
        mods_list = self.used_mods_service.get_used_mods_list(chapter_id)
        self._set_priority_widgets_enabled(len(mods_list) >= 2 if mods_list else False)

    def on_priority_button_click(self):
        if not hasattr(self.app, "priority_button"):
            return
        chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            return
        mods_list = self.used_mods_service.get_used_mods_list(chapter_id)
        if not mods_list or len(mods_list) < 2:
            return
        from PyQt6.QtWidgets import QDialog

        try:
            dialog = ModPriorityDialog(
                mods_list, chapter_id, self.app_state, parent=self.app
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_order = dialog.get_result()
                if new_order:
                    self.used_mods_service.set_mods_list(chapter_id, new_order)
                    if self.app_state.current_mode == "chapter":
                        self.update_for_chapter_mode(chapter_id)
                    else:
                        self.update_display()
                    self._update_priority_button_visibility(chapter_id)
        except Exception as e:
            logging.error(f"Error opening priority dialog: {e}", exc_info=True)

    def on_create_modpack_button_click(self):
        if not hasattr(self.app, "create_modpack_button"):
            return
        from PyQt6.QtWidgets import QDialog

        from ui.dialogs.modpack_create_dialog import CreateModpackDialog
        from utils.file_utils import get_unique_mod_dir

        is_chapter_mode = self.app_state.current_mode == "chapter"
        chapter_mods = {}
        if is_chapter_mode:
            chapter_id = self._get_current_chapter_id()
            if chapter_id is None:
                return
            mods_list = self.used_mods_service.get_used_mods_list(chapter_id)
            if not mods_list or len(mods_list) < 2:
                return
            chapter_mods = {chapter_id: mods_list}
        else:
            chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
            mods_list = self.used_mods_service.get_used_mods_list(chapter_id)
            if mods_list and len(mods_list) >= 2:
                if self.app_state.game_mode.is_multi_tab:
                    chapter_mods = self._distribute_mods_across_chapters(mods_list)
                else:
                    chapter_mods = {chapter_id: mods_list}
            else:
                default_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
                mods_list = self.used_mods_service.get_used_mods_list(default_id)
                if mods_list and len(mods_list) >= 2:
                    chapter_mods = self._distribute_mods_across_chapters(mods_list)
        if not chapter_mods:
            return
        try:
            dialog = CreateModpackDialog(self.app_state, parent=self.app)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            modpack_name = dialog.get_modpack_name()
            if not modpack_name:
                return
            xdelta_modpack = dialog.get_xdelta_modpack()
            unique_mod_folder = get_unique_mod_dir(
                self.app_state.mods_dir, modpack_name
            )
            modpack_dir = os.path.join(self.app_state.mods_dir, unique_mod_folder)
            from workers.modpack_create_worker import CreateModpackThread

            thread = CreateModpackThread(
                chapter_mods,
                modpack_name,
                modpack_dir,
                self.app_state,
                self.mod_service,
                self.app,
                xdelta_modpack=xdelta_modpack,
            )
            thread.progress_update.connect(self._on_modpack_progress)
            thread.status_update.connect(self._on_modpack_status)
            thread.warning_confirmation_needed.connect(
                self._on_modpack_warning_confirmation_needed
            )
            thread.finished.connect(
                lambda success: self._on_modpack_finished(success, modpack_dir)
            )
            self.app_state.current_task = thread
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_patching = True
            self.app_state.action_button_text = tr("ui.cancel_button")
            self.app_state.action_button_enabled = True
            self._modpack_thread = thread
            self._modpack_dir = modpack_dir
            thread.start()
        except Exception as e:
            logging.error(f"Error creating modpack: {e}", exc_info=True)
            self.feedback_service.show_message("error", "errors.error", str(e))

    def _on_modpack_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        if message:
            from config.config import UI_COLORS

            self.feedback_service.update_status(message, UI_COLORS["status_info"])

    def _on_modpack_status(self, message: str, status_type: str):
        from config.config import UI_COLORS

        color = UI_COLORS.get(f"status_{status_type}", UI_COLORS["status_error"])
        self.feedback_service.update_status(message, color)

    def _on_modpack_warning_confirmation_needed(
        self, message: str, details: str, report_path: str | None
    ):
        thread = getattr(self, "_modpack_thread", None)
        if not thread:
            return
        should_continue = self.feedback_service.ask_patching_warning(
            message, details, report_path
        )
        thread.confirm_warning(should_continue)

    def _safe_update_after_modpack_creation(self, modpack_dir: str):
        try:
            self._refresh_mod_list_targeted()
            if hasattr(self.app, "search_display"):
                self.app.search_display.update_filtered_mods(preserve_page=True)
                self.app.search_display.update_search_cards()
            self.feedback_service.show_message(
                "success",
                "dialogs.modpack_created_title",
                tr("dialogs.modpack_created_message", modpack_dir=modpack_dir),
            )
        except Exception as e:
            logging.error(
                f"Error updating UI after modpack creation: {e}", exc_info=True
            )

            try:
                self.update_display()
                if hasattr(self.app, "search_display"):
                    self.app.search_display.update_filtered_mods(preserve_page=True)
                    self.app.search_display.update_search_cards()
            except Exception as e2:
                logging.error(f"Fallback refresh also failed: {e2}", exc_info=True)

    def _on_modpack_finished(self, success: bool, modpack_dir: str):
        self.app_state.is_patching = False
        self.app_state.progress_bar_visible = False
        self.app_state.action_button_text = tr("ui.launch_button")
        self.app_state.action_button_enabled = True
        self.app_state.clear_current_task()

        if success:
            self.mod_service.invalidate_mods_cache()
            self.mod_service.load_local_mods()
            self.mod_service.mod_list_updated.emit()
            QTimer.singleShot(
                100, lambda: self._safe_update_after_modpack_creation(modpack_dir)
            )
        else:
            if os.path.exists(modpack_dir):
                try:
                    shutil.rmtree(modpack_dir, ignore_errors=True)
                except Exception as e:
                    logging.warning(
                        f"Failed to remove modpack directory {modpack_dir}: {e}"
                    )
            self.feedback_service.show_message(
                "error", "errors.error", tr("errors.modpack_creation_failed")
            )
