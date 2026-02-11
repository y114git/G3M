"""Controller for managing the library display of installed mods."""
import logging
import os
import shutil
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from services.localization_service import tr
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from ui.dialogs.mod_priority_dialog import ModPriorityDialog
from services.mod_filter_service import filter_and_sort_mods
from utils.mod_utils import get_mod_key, get_mod_name
from services.game_detection_service import get_chapter_id_for_game_mode


class LibraryDisplayController:
    """Manages the display and interaction of installed mods in the library."""

    def __init__(self, app_state, feedback_service, mod_service, used_mods_service, app_window):
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.used_mods_service = used_mods_service
        self.app = app_window
        self._updating_display = False

    def _show_chapter_mode_instruction(self) -> None:
        if hasattr(self.app, 'installed_mods_container') and hasattr(self.app, 'installed_mods_layout'):
            self.app.installed_mods_container.setUpdatesEnabled(False)
            clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
            self.app._show_chapter_mode_instruction()
            self.app.installed_mods_container.setUpdatesEnabled(True)

    def update_display(self):
        if not hasattr(self.app, 'installed_mods_layout'):
            return
        is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            self.update_for_chapter_mode(self.app_state.selected_chapter_id)
            return
        self.refresh_async()

    def _filter_and_sort_installed(self, installed_mods):
        filters, _ = self._build_library_filters_and_sort()
        filtered_mods = filter_and_sort_mods(installed_mods, filters)
        if hasattr(self.app, 'library_sort_combo'):
            sort_type = self.app.library_sort_combo.currentIndex()
            reverse = not self.app.library_sort_ascending
            if sort_type == 0:
                filtered_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
            else:
                filtered_mods.sort(key=lambda mod: mod.get('added_date') or '', reverse=reverse)
        return filtered_mods

    def _distribute_mods_across_chapters(self, mods_list):
        chapter_mods = {}
        for tab in self.app_state.game_mode.tabs:
            tab_mods = [mod for mod in mods_list if hasattr(mod, 'get_chapter_data') and mod.get_chapter_data(tab.tab_id)]
            if tab_mods:
                chapter_mods[tab.tab_id] = tab_mods
        return chapter_mods

    def _build_library_filters_and_sort(self):
        selected_tags = []
        only_gamebanana = False
        if hasattr(self.app, 'library_tag_widgets'):
            tag_map = {self.app.library_tag_textedit: 'textedit', self.app.library_tag_customization: 'customization', self.app.library_tag_gameplay: 'gameplay', self.app.library_tag_other: 'other'}
            for checkbox, tag in tag_map.items():
                if checkbox.isChecked():
                    selected_tags.append(tag)
            if hasattr(self.app, 'library_tag_gamebanana') and self.app.library_tag_gamebanana.isChecked():
                only_gamebanana = True
        search_text = getattr(self.app, 'library_search_text', '').lower()
        current_game_type = 'deltarune'
        if hasattr(self.app, 'game_type_combo'):
            current_game_type = self.app.game_type_combo.currentData() or 'deltarune'
        filters = {'tags': selected_tags, 'game': current_game_type, 'search_text': search_text, 'hide_banned': False, 'only_gamebanana': only_gamebanana, 'status_filter': ['approved', 'pending', 'unknown']}
        sort_config = None
        if hasattr(self.app, 'library_sort_combo'):
            sort_type = self.app.library_sort_combo.currentIndex()
            reverse = not self.app.library_sort_ascending
            if sort_type == 1:
                sort_config = {'sort_type': 1, 'reverse': reverse}
        return (filters, sort_config)

    def update_for_chapter_mode(self, selected_chapter_id):
        if not hasattr(self.app, 'installed_mods_layout'):
            return
        if hasattr(self.app, '_updating_chapter_mods') and self.app._updating_chapter_mods:
            return
        if selected_chapter_id is None:
            if hasattr(self.app, '_show_chapter_mode_instruction'):
                self.app._show_chapter_mode_instruction()
            return
        self.app._updating_chapter_mods = True
        container = getattr(self.app, 'installed_mods_container', None)
        if container:
            container.setUpdatesEnabled(False)
        clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
        installed_mods = self.mod_service.get_installed_mods_list()
        filtered_mods = self._filter_and_sort_installed(installed_mods)
        for mod_info in filtered_mods:
            mod_data = self.mod_service.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
            if not mod_data or not self.mod_service.mod_has_files_for_chapter(mod_data, selected_chapter_id):
                continue
            if mod_data:
                added_date = mod_info.get('added_date')
                mod_widget = InstalledModWidget(mod_data, parent=self.app, installed_date=added_date)
                mod_widget.clicked.connect(self.on_mod_clicked)
                mod_widget.remove_requested.connect(self.on_mod_remove)
                mod_widget.use_requested.connect(lambda mod_data=mod_data: self._handle_mod_use(mod_data, selected_chapter_id))
                is_used = self.used_mods_service.is_mod_used_for_chapter(mod_data, selected_chapter_id)
                mod_widget.set_active(is_used)
                self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
                mod_widget.show()
        if self.app.installed_mods_layout.count() <= 1:
            tab = self.app_state.game_mode.get_tab(selected_chapter_id)
            chapter_name = tr(tab.name_key) if tab else str(selected_chapter_id)
            show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.no_mods_for_chapter', chapter_name=chapter_name), self.app_state.local_config, font_size=16)
        self._update_priority_button_visibility(selected_chapter_id)
        if container:
            container.setUpdatesEnabled(True)
        self.app._updating_chapter_mods = False

    def refresh_async(self):
        if hasattr(self.app, '_installed_scan_thread') and self.app._installed_scan_thread and self.app._installed_scan_thread.isRunning():
            return
        is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = self.app_state.selected_chapter_id
            if selected_id is None:
                self._show_chapter_mode_instruction()
            else:
                self.update_for_chapter_mode(selected_id)
            return

        class _Scan(QThread):
            result_ready = pyqtSignal(list)

            def __init__(self, outer):
                super().__init__(outer)
                self.outer = outer

            def run(self):
                try:
                    mods = self.outer.mod_service.get_installed_mods_list()
                except Exception:
                    mods = []
                self.result_ready.emit(mods)
        try:
            if hasattr(self.app, '_installed_scan_thread') and self.app._installed_scan_thread:
                if self.app._installed_scan_thread.isRunning():
                    self.app._installed_scan_thread.requestInterruption()
                    self.app._installed_scan_thread.wait(100)
                self.app._installed_scan_thread.deleteLater()
            self.app._installed_scan_thread = _Scan(self)
            self.app._installed_scan_thread.result_ready.connect(self.update_display_from_list)
            self.app._installed_scan_thread.start()
        except Exception:
            mods = self.mod_service.get_installed_mods_list()
            self.update_display_from_list(mods)

    def update_display_from_list(self, installed_mods):
        if self._updating_display:
            return
        self._updating_display = True
        try:
            is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
            if is_chapter_mode:
                selected_id = self.app_state.selected_chapter_id
                if selected_id is None:
                    self._show_chapter_mode_instruction()
                    return
                self.update_for_chapter_mode(selected_id)
                return
            container = getattr(self.app, 'installed_mods_container', None)
            if container:
                container.setUpdatesEnabled(False)
            clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
            self.cleanup_missing_mods(installed_mods)
            existing_mods = [mod_info for mod_info in installed_mods if self.mod_service.check_mod_exists(mod_info)]
            filtered_mods = self._filter_and_sort_installed(existing_mods)
            mods = list(filtered_mods)
            batch_index = 0

            def _finish_display():
                if container:
                    container.setUpdatesEnabled(True)

            def _build_next_batch(batch_size=25):
                nonlocal batch_index, mods
                try:
                    start = batch_index
                    end = min(start + batch_size, len(mods))
                    for idx in range(start, end):
                        mod_info = mods[idx]
                        mod_data = self.mod_service.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
                        if not mod_data:
                            continue
                        added_date = mod_info.get('added_date')
                        mod_widget = InstalledModWidget(mod_data, parent=self.app, installed_date=added_date)
                        mod_widget.clicked.connect(self.on_mod_clicked)
                        mod_widget.remove_requested.connect(self.on_mod_remove)
                        mod_widget.use_requested.connect(self.on_mod_use)
                        self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
                        mod_widget.show()
                    batch_index = end
                    if end >= len(mods):
                        if self.app.installed_mods_layout.count() <= 1:
                            show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
                        self.update_mod_widgets_active_status()
                        self.app.game_launch.update_button_state()
                        _finish_display()
                    else:
                        QTimer.singleShot(0, _build_next_batch)
                except Exception:
                    try:
                        if self.app.installed_mods_layout.count() <= 1:
                            show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
                        self.update_mod_widgets_active_status()
                        self.app.game_launch.update_button_state()
                    except Exception:
                        pass
                    _finish_display()
            _build_next_batch()
        except Exception:
            pass
        finally:
            self._updating_display = False

    def cleanup_missing_mods(self, installed_mods):
        installed_mod_keys = {mod.get('key') or mod.get('mod_key') for mod in installed_mods if mod.get('key') or mod.get('mod_key')}
        mods_metadata = self.mod_service._read_metadata()
        metadata_updated = False
        orphaned_keys = set(mods_metadata.keys()) - installed_mod_keys
        if orphaned_keys:
            for key in orphaned_keys:
                del mods_metadata[key]
            metadata_updated = True
        if metadata_updated:
            self.mod_service._write_metadata(mods_metadata)
        for orphaned_key in orphaned_keys:
            dummy_mod_data = self.mod_service.create_mod_object_from_info({'key': orphaned_key, 'name': 'Orphaned Mod'}, getattr(self.app_state, 'all_mods', None))
            if not dummy_mod_data:
                continue
            self.used_mods_service.remove_mod_from_all_chapters(dummy_mod_data)

    def update_mod_widgets_active_status(self):
        if not hasattr(self.app, 'installed_mods_layout') or self.app.installed_mods_layout is None:
            return
        is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
        selected_chapter_id = self.app_state.selected_chapter_id if is_chapter_mode else None
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    if selected_chapter_id is not None:
                        is_used = self.used_mods_service.is_mod_used_for_chapter(widget.mod_data, selected_chapter_id)
                    else:
                        check_chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
                        is_used = self.used_mods_service.is_mod_used_for_chapter(widget.mod_data, check_chapter_id)
                    widget.set_active(is_used)

    def on_mod_clicked(self, mod_data):
        target_widget = None
        mod_data_key = get_mod_key(mod_data)
        for i in range(self.app.installed_mods_layout.count() - 1):
            try:
                item = self.app.installed_mods_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = get_mod_key(widget.mod_data)
                        if widget_mod_key == mod_data_key:
                            target_widget = widget
                            break
            except Exception:
                continue
        if target_widget:
            self.clear_all_selections()
            target_widget.set_selected(True)

    def on_mod_remove(self, mod_data):
        try:
            key = get_mod_key(mod_data)
            mod_name = get_mod_name(mod_data)
            if self.feedback_service.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod_name):
                self.mod_service.delete_mod_files(mod_data)
                removal_data = {'key': key, **(({'name': mod_name} if mod_name else {}))} if key else mod_data
                try:
                    self.used_mods_service.remove_mod_from_all_chapters(removal_data)
                except Exception as e:
                    logging.warning(f'Failed to remove mod from chapters after deletion: {e}', exc_info=True)
                try:
                    self.mod_service.invalidate_mods_cache()
                    self.mod_service.load_local_mods()
                    self.mod_service.mod_list_updated.emit()
                    QTimer.singleShot(100, lambda: self._safe_update_after_mod_deletion())
                except Exception as e:
                    logging.error(f'Failed to reload mods after deletion: {e}', exc_info=True)
                    try:
                        self.mod_service.mod_list_updated.emit()
                        QTimer.singleShot(100, lambda: self._safe_update_after_mod_deletion())
                    except Exception as e2:
                        logging.error(f'Failed to update display after mod deletion: {e2}', exc_info=True)
        except (OSError, IOError, PermissionError) as e:
            logging.error(f'File operation failed during mod removal: {e}', exc_info=True)
            self.feedback_service.show_message('error', 'errors.mod_removal_failed', error=str(e))
        except Exception as e:
            logging.error(f'Unexpected error during mod removal: {e}', exc_info=True)
            self.feedback_service.show_message('error', 'errors.mod_removal_failed', error=str(e))

    def _safe_update_after_mod_deletion(self):
        try:
            self.update_display()
            if hasattr(self.app, 'search_display'):
                self.app.search_display.update_search_cards()
                self.app.search_display.update_filtered_mods(preserve_page=True)
        except Exception as e:
            logging.error(f'Error updating UI after mod deletion: {e}', exc_info=True)

    def on_mod_use(self, mod_data):
        target_chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
        self._handle_mod_use(mod_data, target_chapter_id)

    def _handle_mod_use(self, mod_data, chapter_id):
        mod_widget = None
        for i in range(self.app.installed_mods_layout.count()):
            item = self.app.installed_mods_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                    widget_mod_data = getattr(widget, 'mod_data', None)
                    if widget_mod_data:
                        widget_mod_key = get_mod_key(widget_mod_data)
                        current_mod_key = get_mod_key(mod_data)
                        if widget_mod_key == current_mod_key:
                            mod_widget = widget
                            break
        self.used_mods_service.set_used_mod(chapter_id, mod_data)
        self.update_mod_widgets_active_status()
        self._update_priority_button_visibility(chapter_id)
        if mod_widget:
            mod_widget.set_selected(False)
        if hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked():
            self.update_for_chapter_mode(chapter_id)

    def clear_all_selections(self):
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _get_current_chapter_id(self):
        if self.app_state.current_mode == 'chapter':
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

    def _set_priority_widgets_visible(self, visible: bool):
        self.app.priority_button.setVisible(visible)
        for attr in ('create_modpack_button', 'fast_merging_checkbox', 'fast_merging_label'):
            if hasattr(self.app, attr):
                getattr(self.app, attr).setVisible(visible)
        if hasattr(self.app, 'library_tab_builder'):
            widgets = self.app.library_tab_builder.widgets
            if 'priority_button_container' in widgets:
                widgets['priority_button_container'].setFixedHeight(55 if visible else 0)
            if 'priority_button_layout' in widgets:
                margins = (0, 10, 0, 10) if visible else (0, 0, 0, 0)
                widgets['priority_button_layout'].setContentsMargins(*margins)

    def _update_priority_button_visibility(self, chapter_id=None):
        if not hasattr(self.app, 'priority_button'):
            return
        if chapter_id is None:
            chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            self._set_priority_widgets_visible(False)
            return
        mods_list = self.used_mods_service.get_used_mods_list(chapter_id)
        self._set_priority_widgets_visible(len(mods_list) >= 2 if mods_list else False)

    def on_priority_button_click(self):
        if not hasattr(self.app, 'priority_button'):
            return
        chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            return
        mods_list = self.used_mods_service.get_used_mods_list(chapter_id)
        if not mods_list or len(mods_list) < 2:
            return
        from PyQt6.QtWidgets import QDialog
        try:
            dialog = ModPriorityDialog(mods_list, chapter_id, self.app_state, parent=self.app)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_order = dialog.get_result()
                if new_order:
                    self.used_mods_service.set_mods_list(chapter_id, new_order)
                    if self.app_state.current_mode == 'chapter':
                        self.update_for_chapter_mode(chapter_id)
                    else:
                        self.update_display()
                    self._update_priority_button_visibility(chapter_id)
        except Exception as e:
            logging.error(f'Error opening priority dialog: {e}', exc_info=True)

    def on_create_modpack_button_click(self):
        if not hasattr(self.app, 'create_modpack_button'):
            return
        from ui.dialogs.modpack_create_dialog import CreateModpackDialog
        from PyQt6.QtWidgets import QDialog
        from utils.file_utils import get_unique_mod_dir
        is_chapter_mode = self.app_state.current_mode == 'chapter'
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
            unique_mod_folder = get_unique_mod_dir(self.app_state.mods_dir, modpack_name)
            modpack_dir = os.path.join(self.app_state.mods_dir, unique_mod_folder)
            fast_patch = getattr(self.app, 'fast_merging_checkbox', None) and self.app.fast_merging_checkbox.isChecked()
            from workers.modpack_create_worker import CreateModpackThread
            thread = CreateModpackThread(chapter_mods, modpack_name, modpack_dir, self.app_state, self.mod_service, self.app, fast_patch=fast_patch, xdelta_modpack=xdelta_modpack)
            thread.progress_update.connect(self._on_modpack_progress)
            thread.status_update.connect(self._on_modpack_status)
            thread.finished.connect(lambda success: self._on_modpack_finished(success, modpack_dir))
            self.app_state.current_task = thread
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_patching = True
            self.app_state.action_button_text = tr('ui.cancel_button')
            self.app_state.action_button_enabled = True
            self._modpack_thread = thread
            self._modpack_dir = modpack_dir
            thread.start()
        except Exception as e:
            logging.error(f'Error creating modpack: {e}', exc_info=True)
            self.feedback_service.show_message('error', 'errors.error', str(e))

    def _on_modpack_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        if message:
            from config.constants import UI_COLORS
            self.feedback_service.update_status(message, UI_COLORS['status_info'])

    def _on_modpack_status(self, message: str, status_type: str):
        from config.constants import UI_COLORS
        color = UI_COLORS.get(f'status_{status_type}', UI_COLORS['status_error'])
        self.feedback_service.update_status(message, color)

    def _safe_update_after_modpack_creation(self, modpack_dir: str):
        try:
            self.update_display()
            if hasattr(self.app, 'search_display'):
                self.app.search_display.update_filtered_mods(preserve_page=True)
                self.app.search_display.update_search_cards()
            QTimer.singleShot(300, self.refresh_async)
            self.feedback_service.show_message('success', 'dialogs.modpack_created_title', tr('dialogs.modpack_created_message', modpack_dir=modpack_dir))
        except Exception as e:
            logging.error(f'Error updating UI after modpack creation: {e}', exc_info=True)

    def _on_modpack_finished(self, success: bool, modpack_dir: str):
        self.app_state.is_patching = False
        self.app_state.progress_bar_visible = False
        self.app_state.action_button_text = tr('ui.launch_button')
        self.app_state.action_button_enabled = True
        self.app_state.clear_current_task()
        if success:
            self.mod_service.invalidate_mods_cache()
            self.mod_service.load_local_mods()
            self.mod_service.mod_list_updated.emit()
            QTimer.singleShot(100, lambda: self._safe_update_after_modpack_creation(modpack_dir))
        else:
            if os.path.exists(modpack_dir):
                try:
                    shutil.rmtree(modpack_dir, ignore_errors=True)
                except Exception as e:
                    logging.warning(f'Failed to remove modpack directory {modpack_dir}: {e}')
            self.feedback_service.show_message('error', 'errors.error', tr('errors.modpack_creation_failed'))
