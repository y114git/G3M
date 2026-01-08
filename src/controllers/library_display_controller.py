import logging
from PyQt6.QtCore import QThread, QTimer
from managers.localization_manager import tr
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from ui.dialogs.mod_priority_dialog import ModPriorityDialog
from config.constants import SLOT_ID_UNIVERSAL, SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_SUGARY_SPIRE, SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
from utils.mod_filter_utils import filter_and_sort_mods
from utils.mod_utils import get_mod_key
from utils.game_utils import get_chapter_id_for_game_mode


class LibraryDisplayController:

    def __init__(self, app_state, feedback_manager, mod_manager, slot_manager, app_window):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.slot_manager = slot_manager
        self.app = app_window

    def update_display(self):
        if not hasattr(self.app, 'installed_mods_layout'):
            return
        is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = self.app_state.selected_chapter_id
            if selected_id is not None:
                self.update_for_chapter_mode(selected_id)
                return
            else:
                self.update_for_chapter_mode(None)
                return
        self.refresh_async()

    def _build_library_filters_and_sort(self):
        selected_tags = []
        if hasattr(self.app, 'library_tag_widgets'):
            tag_map = {self.app.library_tag_textedit: 'textedit', self.app.library_tag_customization: 'customization', self.app.library_tag_gameplay: 'gameplay', self.app.library_tag_other: 'other', self.app.library_tag_local: 'local'}
            for checkbox, tag in tag_map.items():
                if checkbox.isChecked():
                    selected_tags.append(tag)
        search_text = getattr(self.app, 'library_search_text', '').lower()
        current_game_type = 'deltarune'
        if hasattr(self.app, 'game_type_combo'):
            current_game_type = self.app.game_type_combo.currentData() or 'deltarune'
        filters = {'tags': selected_tags, 'game': current_game_type, 'search_text': search_text, 'hide_banned': False, 'hide_local': False, 'show_only_local': False, 'status_filter': ['approved', 'pending', 'unknown']}
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
        clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
        installed_mods = self.mod_manager.get_installed_mods_list()
        filters, sort_config = self._build_library_filters_and_sort()
        filtered_mods = filter_and_sort_mods(installed_mods, filters, sort_config)
        if hasattr(self.app, 'library_sort_combo'):
            sort_type = self.app.library_sort_combo.currentIndex()
            if sort_type == 0:
                reverse = not self.app.library_sort_ascending
                filtered_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
        for mod_info in filtered_mods:
            mod_data = self.mod_manager.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
            if not mod_data or not self.mod_manager.mod_has_files_for_chapter(mod_data, selected_chapter_id):
                continue
            is_local = getattr(mod_data, 'is_local_mod', False) or mod_data.is_local
            is_available = not is_local
            if not is_available and hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                key = mod_info.get('key') or mod_info.get('mod_key', '')
                if key and key.startswith('gb_'):
                    is_available = any((mod for mod in self.app_state.all_mods if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key))
                if not is_available:
                    is_available = mod_info.get('is_available_on_server', False)
            if mod_data:
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, parent=self.app)
                mod_widget.clicked.connect(self.on_mod_clicked)
                mod_widget.remove_requested.connect(self.on_mod_remove)
                mod_widget.use_requested.connect(lambda mod_data=mod_data: self._handle_mod_use(mod_data, selected_chapter_id))
                is_used = self.slot_manager.is_mod_used_for_chapter(mod_data, selected_chapter_id)
                mod_widget.set_in_slot(is_used)
                self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
                mod_widget.show()
        if self.app.installed_mods_layout.count() <= 1:
            chapter_names = {SLOT_ID_UNIVERSAL: tr('ui.mod_slot'), SLOT_ID_MENU: tr('chapters.menu'), SLOT_ID_CHAPTER_1: tr('tabs.chapter_1'), SLOT_ID_CHAPTER_2: tr('tabs.chapter_2'), SLOT_ID_CHAPTER_3: tr('tabs.chapter_3'), SLOT_ID_CHAPTER_4: tr('tabs.chapter_4')}
            chapter_name = chapter_names.get(selected_chapter_id, tr('ui.chapter_n', chapter=str(selected_chapter_id)))
            show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.no_mods_for_chapter', chapter_name=chapter_name), self.app_state.local_config, font_size=16)
        self._update_priority_button_visibility(selected_chapter_id)
        self.app._updating_chapter_mods = False

    def refresh_async(self):
        is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = self.app_state.selected_chapter_id
            if selected_id is None:
                if hasattr(self.app, 'installed_mods_container') and hasattr(self.app, 'installed_mods_layout'):
                    self.app.installed_mods_container.setUpdatesEnabled(False)
                    clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
                    self.app._show_chapter_mode_instruction()
                    self.app.installed_mods_container.setUpdatesEnabled(True)
                return
            else:
                self.update_for_chapter_mode(selected_id)
                return

        class _Scan(QThread):

            def __init__(self, outer):
                super().__init__(outer)
                self.outer = outer

            def run(self):
                try:
                    mods = self.outer.mod_manager.get_installed_mods_list()
                except Exception:
                    mods = []
                self.outer.update_display_from_list(mods)
        try:
            self.app._installed_scan_thread = _Scan(self)
            self.app._installed_scan_thread.start()
        except Exception:
            mods = self.mod_manager.get_installed_mods_list()
            self.update_display_from_list(mods)

    def update_display_from_list(self, installed_mods):
        try:
            is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
            if is_chapter_mode:
                selected_id = self.app_state.selected_chapter_id
                if selected_id is None:
                    if hasattr(self.app, 'installed_mods_container') and hasattr(self.app, 'installed_mods_layout'):
                        self.app.installed_mods_container.setUpdatesEnabled(False)
                        clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
                        self.app._show_chapter_mode_instruction()
                        self.app.installed_mods_container.setUpdatesEnabled(True)
                    return
                else:
                    self.update_for_chapter_mode(selected_id)
                    return
            clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
            self.cleanup_missing_mods(installed_mods)
            existing_mods = [mod_info for mod_info in installed_mods if self.mod_manager.check_mod_exists(mod_info)]
            filters, sort_config = self._build_library_filters_and_sort()
            filtered_mods = filter_and_sort_mods(existing_mods, filters, sort_config)
            if hasattr(self.app, 'library_sort_combo'):
                sort_type = self.app.library_sort_combo.currentIndex()
                if sort_type == 0:
                    reverse = not self.app.library_sort_ascending
                    filtered_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
            from PyQt6.QtCore import QTimer
            mods = list(filtered_mods)
            batch_index = 0

            def _build_next_batch(batch_size=25):
                nonlocal batch_index, mods
                try:
                    start = batch_index
                    end = min(start + batch_size, len(mods))
                    for idx in range(start, end):
                        mod_info = mods[idx]
                        mod_data = self.mod_manager.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
                        if not mod_data:
                            continue
                        is_local = getattr(mod_data, 'is_local_mod', False) or mod_data.is_local
                        is_available = not is_local
                        if not is_available and hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                            key = mod_info.get('key') or mod_info.get('mod_key', '')
                            if key and key.startswith('gb_'):
                                is_available = any((mod for mod in self.app_state.all_mods if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == key))
                            if not is_available:
                                is_available = mod_info.get('is_available_on_server', False)
                        has_update = False
                        if not is_local and is_available and hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                            mod_key_attr = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                            public_mod = next((mod for mod in self.app_state.all_mods if (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) == mod_key_attr), None)
                            if public_mod:
                                has_update = any((self.mod_manager.mod_has_files_for_chapter(public_mod, i) and self.mod_manager.get_mod_status(public_mod, i) == 'update' for i in range(5)))
                        mod_widget = InstalledModWidget(mod_data, is_local, is_available, has_update, parent=self.app)
                        mod_widget.clicked.connect(self.on_mod_clicked)
                        mod_widget.remove_requested.connect(self.on_mod_remove)
                        mod_widget.use_requested.connect(self.on_mod_use)
                        self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
                        mod_widget.show()
                    batch_index = end
                    if end >= len(mods):
                        if self.app.installed_mods_layout.count() <= 1:
                            show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
                        self.update_mod_widgets_slot_status()
                        self.app.game_launch.update_button_state()
                    else:
                        QTimer.singleShot(0, _build_next_batch)
                except Exception:
                    try:
                        if self.app.installed_mods_layout.count() <= 1:
                            show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
                        self.update_mod_widgets_slot_status()
                        self.app.game_launch.update_button_state()
                    except Exception:
                        pass
            _build_next_batch()
        except Exception:
            pass

    def cleanup_missing_mods(self, installed_mods):
        installed_mod_keys = {mod.get('key') or mod.get('mod_key') for mod in installed_mods if mod.get('key') or mod.get('mod_key')}
        mods_metadata = self.mod_manager._read_metadata()
        metadata_updated = False
        orphaned_keys = set(mods_metadata.keys()) - installed_mod_keys
        if orphaned_keys:
            for key in orphaned_keys:
                del mods_metadata[key]
            metadata_updated = True
        if metadata_updated:
            self.mod_manager._write_metadata(mods_metadata)
        for orphaned_key in orphaned_keys:
            dummy_mod_data = self.mod_manager.create_mod_object_from_info({'key': orphaned_key, 'name': 'Orphaned Mod'}, getattr(self.app_state, 'all_mods', None))
            if not dummy_mod_data:
                continue
            self.slot_manager.remove_mod_from_all_chapters(dummy_mod_data)
            config_keys = ['used_mods_deltarune', 'used_mods_deltarune_chapter', 'used_mods_deltarunedemo', 'used_mods_undertale', 'used_mods_undertaleyellow', 'used_mods_pizzatower']
            for config_key in list(self.app_state.local_config.keys()):
                if config_key.startswith('used_mods_') and config_key not in config_keys:
                    config_keys.append(config_key)
            for config_key in config_keys:
                used_mods_data = self.app_state.local_config.get(config_key, {})
                if not used_mods_data:
                    continue
                chapters_to_clear = []
                config_updated = False
                for chapter_id_str, mod_data_raw in list(used_mods_data.items()):
                    if isinstance(mod_data_raw, str):
                        if mod_data_raw == orphaned_key:
                            chapters_to_clear.append(chapter_id_str)
                            config_updated = True
                    elif isinstance(mod_data_raw, list):
                        if orphaned_key in mod_data_raw:
                            updated_list = [k for k in mod_data_raw if k != orphaned_key]
                            if updated_list:
                                used_mods_data[chapter_id_str] = updated_list
                                config_updated = True
                            else:
                                chapters_to_clear.append(chapter_id_str)
                                config_updated = True
                for chapter_id_str in chapters_to_clear:
                    del used_mods_data[chapter_id_str]
                if config_updated:
                    self.app_state.local_config[config_key] = used_mods_data
                    self.app.settings_manager.write_local_config()

    def update_mod_widgets_slot_status(self):
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
                        is_used = self.slot_manager.is_mod_used_for_chapter(widget.mod_data, selected_chapter_id)
                    else:
                        check_chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
                        is_used = self.slot_manager.is_mod_used_for_chapter(widget.mod_data, check_chapter_id)
                    widget.set_in_slot(is_used)

    def on_mod_clicked(self, mod_data):
        for i in range(self.app.installed_mods_layout.count() - 1):
            try:
                item = self.app.installed_mods_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = get_mod_key(widget.mod_data)
                        mod_data_key = get_mod_key(mod_data)
                        if widget_mod_key == mod_data_key:
                            self.clear_all_selections()
                            widget.set_selected(True)
                            break
            except Exception:
                continue

    def on_mod_remove(self, mod_data):
        try:
            from utils.mod_utils import get_mod_key, get_mod_name
            key = get_mod_key(mod_data)
            mod_name = get_mod_name(mod_data)
            if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod_name):
                self.mod_manager.delete_mod_files(mod_data)
                if key:
                    minimal_mod_data = {'key': key}
                    if mod_name:
                        minimal_mod_data['name'] = mod_name
                    try:
                        self.slot_manager.remove_mod_from_all_chapters(minimal_mod_data)
                    except Exception as e:
                        import logging
                        logging.warning(f'Failed to remove mod from chapters after deletion: {e}', exc_info=True)
                else:
                    try:
                        self.slot_manager.remove_mod_from_all_chapters(mod_data)
                    except Exception as e:
                        import logging
                        logging.warning(f'Failed to remove mod from chapters after deletion: {e}', exc_info=True)
                try:
                    self.mod_manager.invalidate_mods_cache()
                    self.mod_manager.load_local_mods()
                    self.mod_manager.mod_list_updated.emit()
                    self.update_display()
                except Exception as e:
                    import logging
                    logging.error(f'Failed to reload mods after deletion: {e}', exc_info=True)
                    try:
                        self.mod_manager.mod_list_updated.emit()
                        self.update_display()
                    except Exception as e2:
                        logging.error(f'Failed to update display after mod deletion: {e2}', exc_info=True)
                try:
                    self.app.search_display.update_search_plaques()
                    self.app.search_display.update_filtered_mods(preserve_page=True)
                except Exception as e:
                    import logging
                    logging.debug(f'Failed to update search plaques after mod removal: {e}')
        except (OSError, IOError, PermissionError) as e:
            import logging
            logging.error(f'File operation failed during mod removal: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.mod_removal_failed', error=str(e))
        except Exception as e:
            import logging
            logging.error(f'Unexpected error during mod removal: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.mod_removal_failed', error=str(e))

    def on_mod_use(self, mod_data):
        target_chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
        game_value = getattr(mod_data, 'game', None) or getattr(mod_data, 'modgame', None)
        if target_chapter_id == SLOT_ID_UNIVERSAL and game_value == 'undertale':
            target_chapter_id = SLOT_ID_UNDERTALE
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
        status = getattr(mod_widget, 'status', 'ready') if mod_widget else 'ready'
        if status == 'needs_update':
            self.mod_manager.update_mod(mod_data)
            return
        self.slot_manager.set_used_mod(chapter_id, mod_data)
        self.update_mod_widgets_slot_status()
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
        import logging
        logging.info(f'_get_current_chapter_id: current_mode={self.app_state.current_mode}, game_mode={type(self.app_state.game_mode).__name__}')
        if self.app_state.current_mode == 'chapter':
            chapter_id = self.app_state.selected_chapter_id
            logging.info(f'_get_current_chapter_id: chapter mode, selected_chapter_id={chapter_id}')
            return chapter_id
        chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
        if chapter_id != SLOT_ID_UNIVERSAL:
            logging.info(f'_get_current_chapter_id: {type(self.app_state.game_mode).__name__}, returning {chapter_id}')
            return chapter_id

        def _check_slot_for_mods(slot_id, min_count=2):
            mods_list = self.slot_manager.get_used_mods_list(slot_id)
            count = len(mods_list) if mods_list else 0
            if count >= min_count:
                logging.info(f'_get_current_chapter_id: Found {count} mod(s) for slot {slot_id}')
                return True
            return False
        mods_universal = self.slot_manager.get_used_mods_list(SLOT_ID_UNIVERSAL)
        logging.info(f'_get_current_chapter_id: SLOT_ID_UNIVERSAL={SLOT_ID_UNIVERSAL} has {(len(mods_universal) if mods_universal else 0)} mods')
        if _check_slot_for_mods(SLOT_ID_UNIVERSAL):
            return SLOT_ID_UNIVERSAL
        for chapter_id in range(5):
            if _check_slot_for_mods(chapter_id):
                return chapter_id
        for slot_id in [SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_SUGARY_SPIRE]:
            if _check_slot_for_mods(slot_id):
                return slot_id
        if mods_universal and len(mods_universal) > 0:
            logging.info(f'_get_current_chapter_id: Found {len(mods_universal)} mod(s) for SLOT_ID_UNIVERSAL (less than 2, but returning anyway)')
            return SLOT_ID_UNIVERSAL
        if self.slot_manager.used_mods:
            logging.debug(f'_get_current_chapter_id: All used_mods keys: {list(self.slot_manager.used_mods.keys())}')
            for key, mods_list in self.slot_manager.used_mods.items():
                logging.debug(f'_get_current_chapter_id: used_mods[{key}] = {(len(mods_list) if mods_list else 0)} mod(s)')
        logging.debug('_get_current_chapter_id: No chapter with mods found, returning SLOT_ID_UNIVERSAL as fallback')
        return SLOT_ID_UNIVERSAL

    def _update_priority_button_visibility(self, chapter_id=None):
        if not hasattr(self.app, 'priority_button'):
            return
        if chapter_id is None:
            chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            self.app.priority_button.setVisible(False)
            if hasattr(self.app, 'create_modpack_button'):
                self.app.create_modpack_button.setVisible(False)
            if hasattr(self.app, 'library_tab_builder') and 'priority_button_layout' in self.app.library_tab_builder.widgets:
                self.app.library_tab_builder.widgets['priority_button_layout'].setContentsMargins(0, 0, 0, 0)
            return
        mods_list = self.slot_manager.get_used_mods_list(chapter_id)
        mod_count = len(mods_list) if mods_list else 0
        should_show = mod_count >= 2
        if should_show:
            self.app.priority_button.setVisible(True)
            if hasattr(self.app, 'create_modpack_button'):
                self.app.create_modpack_button.setVisible(True)
            if hasattr(self.app, 'library_tab_builder'):
                widgets = self.app.library_tab_builder.widgets
                if 'priority_button_container' in widgets:
                    widgets['priority_button_container'].setFixedHeight(35 + 20)
                if 'priority_button_layout' in widgets:
                    widgets['priority_button_layout'].setContentsMargins(0, 10, 0, 10)
        else:
            self.app.priority_button.setVisible(False)
            if hasattr(self.app, 'create_modpack_button'):
                self.app.create_modpack_button.setVisible(False)
            if hasattr(self.app, 'library_tab_builder'):
                widgets = self.app.library_tab_builder.widgets
                if 'priority_button_container' in widgets:
                    widgets['priority_button_container'].setFixedHeight(0)
                if 'priority_button_layout' in widgets:
                    widgets['priority_button_layout'].setContentsMargins(0, 0, 0, 0)

    def on_priority_button_click(self):
        if not hasattr(self.app, 'priority_button'):
            return
        chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            return
        mods_list = self.slot_manager.get_used_mods_list(chapter_id)
        if not mods_list or len(mods_list) < 2:
            return
        from PyQt6.QtWidgets import QDialog
        try:
            dialog = ModPriorityDialog(mods_list, chapter_id, self.app_state, parent=self.app)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_order = dialog.get_result()
                if new_order:
                    self.slot_manager.set_mods_list(chapter_id, new_order)
                    if self.app_state.current_mode == 'chapter':
                        self.update_for_chapter_mode(chapter_id)
                    else:
                        self.update_display()
                    self._update_priority_button_visibility(chapter_id)
        except Exception as e:
            import logging
            logging.error(f'Error opening priority dialog: {e}', exc_info=True)

    def on_create_modpack_button_click(self):
        if not hasattr(self.app, 'create_modpack_button'):
            return
        import logging
        from ui.dialogs.create_modpack_dialog import CreateModpackDialog
        from PyQt6.QtWidgets import QDialog
        from utils.file_utils import get_unique_mod_dir
        import os
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        chapter_mods = {}
        if is_chapter_mode:
            chapter_id = self._get_current_chapter_id()
            if chapter_id is None:
                return
            mods_list = self.slot_manager.get_used_mods_list(chapter_id)
            if not mods_list or len(mods_list) < 2:
                return
            chapter_mods = {chapter_id: mods_list}
        else:
            chapter_id = get_chapter_id_for_game_mode(self.app_state.game_mode)
            mods_list = self.slot_manager.get_used_mods_list(chapter_id)
            if mods_list and len(mods_list) >= 2:
                if chapter_id == SLOT_ID_UNIVERSAL:
                    for ch_id in range(5):
                        chapter_mods_for_chapter = []
                        for mod in mods_list:
                            if hasattr(mod, 'get_chapter_data') and mod.get_chapter_data(ch_id):
                                chapter_mods_for_chapter.append(mod)
                        if chapter_mods_for_chapter:
                            chapter_mods[ch_id] = chapter_mods_for_chapter
                else:
                    chapter_mods = {chapter_id: mods_list}
            else:
                mods_list = self.slot_manager.get_used_mods_list(SLOT_ID_UNIVERSAL)
                if mods_list and len(mods_list) >= 2:
                    for chapter_id in range(5):
                        chapter_mods_for_chapter = []
                        for mod in mods_list:
                            if hasattr(mod, 'get_chapter_data') and mod.get_chapter_data(chapter_id):
                                chapter_mods_for_chapter.append(mod)
                        if chapter_mods_for_chapter:
                            chapter_mods[chapter_id] = chapter_mods_for_chapter
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
            fast_merge = getattr(self.app, 'fast_merging_checkbox', None) and self.app.fast_merging_checkbox.isChecked()
            from workers.create_modpack_thread import CreateModpackThread
            thread = CreateModpackThread(chapter_mods, modpack_name, modpack_dir, self.app_state, self.mod_manager, self.app, fast_merge=fast_merge, xdelta_modpack=xdelta_modpack)
            thread.progress_update.connect(self._on_modpack_progress)
            thread.status_update.connect(self._on_modpack_status)
            thread.finished.connect(lambda success: self._on_modpack_finished(success, modpack_dir))
            self.app_state.current_task = thread
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.is_merging = True
            self.app_state.action_button_text = tr('ui.cancel_button')
            self.app_state.action_button_enabled = True
            self._modpack_thread = thread
            self._modpack_dir = modpack_dir
            thread.start()
        except Exception as e:
            logging.error(f'Error creating modpack: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', str(e))

    def _on_modpack_progress(self, progress: int, message: str):
        self.app_state.progress_bar_value = progress
        if message:
            from config.constants import UI_COLORS
            self.feedback_manager.update_status(message, UI_COLORS['status_info'])

    def _on_modpack_status(self, message: str, status_type: str):
        from config.constants import UI_COLORS
        color = UI_COLORS.get(f'status_{status_type}', UI_COLORS['status_error'])
        self.feedback_manager.update_status(message, color)

    def _on_modpack_finished(self, success: bool, modpack_dir: str):
        import os
        self.app_state.is_merging = False
        self.app_state.progress_bar_visible = False
        self.app_state.action_button_text = tr('ui.launch_button')
        self.app_state.action_button_enabled = True
        self.app_state.clear_current_task()
        if success:
            self.mod_manager.invalidate_mods_cache()
            self.mod_manager.load_local_mods()
            self.mod_manager.mod_list_updated.emit()
            self.update_display()
            if hasattr(self.app, 'search_display'):
                self.app.search_display.update_filtered_mods(preserve_page=True)
                self.app.search_display.update_search_plaques()
            QTimer.singleShot(200, self.refresh_async)
            self.feedback_manager.show_message('success', 'dialogs.modpack_created_title', tr('dialogs.modpack_created_message', modpack_dir=modpack_dir))
        else:
            if os.path.exists(modpack_dir):
                try:
                    import shutil
                    shutil.rmtree(modpack_dir, ignore_errors=True)
                except Exception as e:
                    logging.warning(f'Failed to remove modpack directory {modpack_dir}: {e}')
            self.feedback_manager.show_message('error', 'errors.error', tr('errors.modpack_creation_failed'))
