from PyQt6.QtCore import QThread
from managers.localization_manager import tr
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from ui.dialogs.mod_priority_dialog import ModPriorityDialog
from models.game_modes import DemoGameMode, UndertaleGameMode
from config.constants import SLOT_ID_UNIVERSAL, SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4


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

    def update_for_chapter_mode(self, selected_chapter_id):
        if not hasattr(self.app, 'installed_mods_layout'):
            return
        if hasattr(self.app, '_updating_chapter_mods') and self.app._updating_chapter_mods:
            return
        if selected_chapter_id is None:
            if hasattr(self.app, '_show_chapter_mode_instruction'):
                self.app._show_chapter_mode_instruction()
                return
            return
        self.app._updating_chapter_mods = True
        clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
        installed_mods = self.mod_manager.get_installed_mods_list()
        if hasattr(self.app, 'library_sort_combo'):
            sort_type = self.app.library_sort_combo.currentIndex()
            reverse = not self.app.library_sort_ascending
            if sort_type == 0:
                installed_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
            elif sort_type == 1:

                def get_sort_date(mod):
                    if mod.get('is_local_mod'):
                        return mod.get('created_date', '0')
                    else:
                        return mod.get('updated_date') or mod.get('installed_date', '0')
                installed_mods.sort(key=get_sort_date, reverse=reverse)
        current_game_type = 'deltarune'
        if hasattr(self.app, 'game_type_combo'):
            current_game_type = self.app.game_type_combo.currentData() or 'deltarune'
        selected_tags = []
        if hasattr(self.app, 'library_tag_widgets'):
            tag_map = {self.app.library_tag_translation: 'translation', self.app.library_tag_customization: 'customization', self.app.library_tag_gameplay: 'gameplay', self.app.library_tag_other: 'other', self.app.library_tag_local: 'local'}
            for checkbox, tag in tag_map.items():
                if checkbox.isChecked():
                    selected_tags.append(tag)
        search_text = getattr(self.app, 'library_search_text', '').lower()
        for mod_info in installed_mods:
            mod_modgame = mod_info.get('modgame', 'deltarune')
            if mod_modgame != current_game_type:
                continue
            mod_tags = mod_info.get('tags', [])
            if mod_info.get('is_local_mod'):
                if 'local' not in mod_tags:
                    mod_tags.append('local')
            if selected_tags and (not all((tag in mod_tags for tag in selected_tags))):
                continue
            if search_text:
                mod_name_lower = mod_info.get('name', '').lower()
                mod_tagline = mod_info.get('tagline', '').lower()
                if search_text not in mod_name_lower and search_text not in mod_tagline:
                    continue
            mod_data_check = self.mod_manager.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
            if mod_data_check and (not self.mod_manager.mod_has_files_for_chapter(mod_data_check, selected_chapter_id)):
                continue
            is_local = mod_info.get('is_local_mod', False)
            is_available = mod_info.get('is_available_on_server', True)
            mod_data = self.mod_manager.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
            if mod_data:
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, parent=self.app)
                mod_widget.clicked.connect(self.on_mod_clicked)
                mod_widget.remove_requested.connect(self.on_mod_remove)
                mod_widget.use_requested.connect(lambda mod_data=mod_data: self.on_chapter_mode_mod_use(mod_data, selected_chapter_id))
                is_used = self.slot_manager.is_mod_used_for_chapter(mod_data, selected_chapter_id)
                mod_widget.set_in_slot(is_used)
                self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
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
            self.app.installed_mods_container.setUpdatesEnabled(False)
            clear_layout_widgets(self.app.installed_mods_layout, keep_last_n=1)
            self.cleanup_missing_mods(installed_mods)
            if hasattr(self.app, 'library_sort_combo'):
                sort_type = self.app.library_sort_combo.currentIndex()
                reverse = not self.app.library_sort_ascending
                if sort_type == 0:
                    installed_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
                elif sort_type == 1:

                    def get_sort_date(mod):
                        if mod.get('is_local_mod'):
                            return mod.get('created_date', '0')
                        else:
                            return mod.get('updated_date') or mod.get('installed_date', '0')
                    installed_mods.sort(key=get_sort_date, reverse=reverse)
            selected_tags = []
            if hasattr(self.app, 'library_tag_widgets'):
                tag_map = {self.app.library_tag_translation: 'translation', self.app.library_tag_customization: 'customization', self.app.library_tag_gameplay: 'gameplay', self.app.library_tag_other: 'other', self.app.library_tag_local: 'local'}
                for checkbox, tag in tag_map.items():
                    if checkbox.isChecked():
                        selected_tags.append(tag)
            search_text = getattr(self.app, 'library_search_text', '').lower()
            current_game_type = 'deltarune'
            if hasattr(self.app, 'game_type_combo'):
                current_game_type = self.app.game_type_combo.currentData() or 'deltarune'
            for idx, mod_info in enumerate(installed_mods):
                mod_exists = self.mod_manager.check_mod_exists(mod_info)
                if not mod_exists:
                    continue
                mod_modgame = mod_info.get('modgame', 'deltarune')
                if mod_modgame != current_game_type:
                    continue
                mod_tags = mod_info.get('tags', [])
                if mod_info.get('is_local_mod'):
                    if 'local' not in mod_tags:
                        mod_tags.append('local')
                if selected_tags and (not all((tag in mod_tags for tag in selected_tags))):
                    continue
                if search_text:
                    mod_name_lower = mod_info.get('name', '').lower()
                    mod_tagline = mod_info.get('tagline', '').lower()
                    if search_text not in mod_name_lower and search_text not in mod_tagline:
                        continue
                is_local = mod_info.get('is_local_mod', False)
                is_available = mod_info.get('is_available_on_server', True)
                has_update = False
                if not is_local and is_available:
                    public_mod = next((mod for mod in self.app_state.all_mods if mod.key == mod_info.get('key')), None)
                    if public_mod:
                        has_update = any((self.mod_manager.mod_has_files_for_chapter(public_mod, i) and self.mod_manager.get_mod_status(public_mod, i) == 'update' for i in range(5)))
                mod_data = self.mod_manager.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
                if mod_data:
                    mod_widget = InstalledModWidget(mod_data, is_local, is_available, has_update, parent=self.app)
                    mod_widget.clicked.connect(self.on_mod_clicked)
                    mod_widget.remove_requested.connect(self.on_mod_remove)
                    mod_widget.use_requested.connect(self.on_mod_use)
                    self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
            if self.app.installed_mods_layout.count() <= 1:
                show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
            self.update_mod_widgets_slot_status()
            self.app.game_launch.update_button_state()
            self.app.installed_mods_container.setUpdatesEnabled(True)
        except Exception:
            if hasattr(self.app, 'installed_mods_container'):
                self.app.installed_mods_container.setUpdatesEnabled(True)

    def cleanup_missing_mods(self, installed_mods):
        installed_mod_keys = {mod.get('mod_key') for mod in installed_mods if mod.get('mod_key')}
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
            dummy_mod_data = self.mod_manager.create_mod_object_from_info({'mod_key': orphaned_key, 'name': 'Orphaned Mod'}, getattr(self.app_state, 'all_mods', None))
            if not dummy_mod_data:
                continue
            self.slot_manager.remove_mod_from_all_chapters(dummy_mod_data)
            config_keys = ['used_mods_deltarune', 'used_mods_deltarune_chapter', 'used_mods_deltarunedemo', 'used_mods_undertale']
            for config_key in config_keys:
                used_mods_data = self.app_state.local_config.get(config_key, {})
                chapters_to_clear = []
                for chapter_id_str, mod_key in list(used_mods_data.items()):
                    if mod_key == orphaned_key:
                        chapters_to_clear.append(chapter_id_str)
                for chapter_id_str in chapters_to_clear:
                    del used_mods_data[chapter_id_str]
                if chapters_to_clear:
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
                        from models.game_modes import DemoGameMode, UndertaleGameMode
                        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
                        is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
                        if is_demo_mode:
                            check_chapter_id = SLOT_ID_DEMO
                        elif is_undertale_mode:
                            check_chapter_id = SLOT_ID_UNDERTALE
                        else:
                            check_chapter_id = SLOT_ID_UNIVERSAL
                        is_used = self.slot_manager.is_mod_used_for_chapter(widget.mod_data, check_chapter_id)
                    widget.set_in_slot(is_used)

    def on_mod_clicked(self, mod_data):
        for i in range(self.app.installed_mods_layout.count() - 1):
            try:
                item = self.app.installed_mods_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = getattr(widget.mod_data, 'key', None)
                        mod_data_key = getattr(mod_data, 'key', None)
                        if widget_mod_key == mod_data_key:
                            self.clear_all_selections()
                            widget.set_selected(True)
                            break
            except Exception:
                continue

    def on_mod_remove(self, mod_data):
        try:
            if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=getattr(mod_data, 'name', getattr(mod_data, 'key', 'Unknown'))):
                self.mod_manager.delete_mod_files(mod_data)
                self.slot_manager.remove_mod_from_all_chapters(mod_data)
                self.update_display()
                try:
                    self.app.search_display.update_search_plaques()
                except Exception as e:
                    import logging
                    logging.debug(f'Failed to update search plaques after mod removal: {e}')
        except (OSError, IOError, PermissionError) as e:
            import logging
            logging.error(f'File operation failed during mod removal: {e}', exc_info=True)
            self.feedback_manager.show_error('errors.mod_removal_failed', error=str(e))
        except Exception as e:
            import logging
            logging.error(f'Unexpected error during mod removal: {e}', exc_info=True)
            self.feedback_manager.show_error('errors.mod_removal_failed', error=str(e))

    def on_mod_use(self, mod_data):
        from models.game_modes import DemoGameMode
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        mod_widget = None
        for i in range(self.app.installed_mods_layout.count()):
            item = self.app.installed_mods_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                    widget_mod_data = getattr(widget, 'mod_data', None)
                    if widget_mod_data:
                        widget_mod_key = getattr(widget_mod_data, 'key', None) or getattr(widget_mod_data, 'mod_key', None) or getattr(widget_mod_data, 'name', None)
                        current_mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
                        if widget_mod_key == current_mod_key:
                            mod_widget = widget
                            break
        status = getattr(mod_widget, 'status', 'ready') if mod_widget else 'ready'
        if status == 'needs_update':
            self.mod_manager.update_mod(mod_data)
            return
        if is_demo_mode:
            target_chapter_id = SLOT_ID_DEMO
        elif hasattr(mod_data, 'modgame') and mod_data.modgame == 'undertale':
            target_chapter_id = SLOT_ID_UNDERTALE
        else:
            target_chapter_id = SLOT_ID_UNIVERSAL
        self.slot_manager.set_used_mod(target_chapter_id, mod_data)
        self.update_mod_widgets_slot_status()
        self._update_priority_button_visibility()
        if mod_widget:
            mod_widget.set_selected(False)

    def on_chapter_mode_mod_use(self, mod_data, chapter_id):
        mod_widget = None
        for i in range(self.app.installed_mods_layout.count()):
            item = self.app.installed_mods_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                    widget_mod_data = getattr(widget, 'mod_data', None)
                    if widget_mod_data:
                        widget_mod_key = getattr(widget_mod_data, 'key', None) or getattr(widget_mod_data, 'mod_key', None) or getattr(widget_mod_data, 'name', None)
                        current_mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
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
        elif isinstance(self.app_state.game_mode, DemoGameMode):
            logging.info('_get_current_chapter_id: DemoGameMode, returning SLOT_ID_DEMO')
            return SLOT_ID_DEMO
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            logging.info('_get_current_chapter_id: UndertaleGameMode, returning SLOT_ID_UNDERTALE')
            return SLOT_ID_UNDERTALE
        else:
            mods_universal = self.slot_manager.get_used_mods_list(SLOT_ID_UNIVERSAL)
            logging.info(f'_get_current_chapter_id: SLOT_ID_UNIVERSAL={SLOT_ID_UNIVERSAL} has {(len(mods_universal) if mods_universal else 0)} mods')
            if mods_universal and len(mods_universal) >= 2:
                logging.info(f'_get_current_chapter_id: Found {len(mods_universal)} mods for SLOT_ID_UNIVERSAL')
                return SLOT_ID_UNIVERSAL
            for chapter_id in range(5):
                mods_list = self.slot_manager.get_used_mods_list(chapter_id)
                if mods_list and len(mods_list) >= 2:
                    logging.info(f'_get_current_chapter_id: Found {len(mods_list)} mods for chapter {chapter_id}')
                    return chapter_id
            for slot_id in [SLOT_ID_DEMO, SLOT_ID_UNDERTALE]:
                mods_list = self.slot_manager.get_used_mods_list(slot_id)
                logging.info(f'_get_current_chapter_id: slot {slot_id} has {(len(mods_list) if mods_list else 0)} mods')
                if mods_list and len(mods_list) >= 2:
                    logging.info(f'_get_current_chapter_id: Found {len(mods_list)} mods for slot {slot_id}')
                    return slot_id
            if mods_universal and len(mods_universal) > 0:
                logging.info(f'_get_current_chapter_id: Found {len(mods_universal)} mods for SLOT_ID_UNIVERSAL (less than 2, but returning anyway)')
                return SLOT_ID_UNIVERSAL
            if self.slot_manager.used_mods:
                logging.debug(f'_get_current_chapter_id: All used_mods keys: {list(self.slot_manager.used_mods.keys())}')
                for key, mods_list in self.slot_manager.used_mods.items():
                    logging.debug(f'_get_current_chapter_id: used_mods[{key}] = {(len(mods_list) if mods_list else 0)} mods')
            logging.debug('_get_current_chapter_id: No chapter with mods found, returning SLOT_ID_UNIVERSAL as fallback')
            return SLOT_ID_UNIVERSAL

    def _update_priority_button_visibility(self, chapter_id=None):
        if not hasattr(self.app, 'priority_button'):
            return
        if chapter_id is None:
            chapter_id = self._get_current_chapter_id()
        if chapter_id is None:
            self.app.priority_button.setVisible(False)
            if hasattr(self.app, 'library_tab_builder') and 'priority_button_layout' in self.app.library_tab_builder.widgets:
                self.app.library_tab_builder.widgets['priority_button_layout'].setContentsMargins(0, 0, 0, 0)
            return
        mods_list = self.slot_manager.get_used_mods_list(chapter_id)
        mod_count = len(mods_list) if mods_list else 0
        should_show = mod_count >= 2
        if should_show:
            self.app.priority_button.setVisible(True)
            if hasattr(self.app, 'library_tab_builder'):
                widgets = self.app.library_tab_builder.widgets
                if 'priority_button_container' in widgets:
                    widgets['priority_button_container'].setFixedHeight(35 + 20)
                if 'priority_button_layout' in widgets:
                    widgets['priority_button_layout'].setContentsMargins(0, 10, 0, 10)
        else:
            self.app.priority_button.setVisible(False)
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
