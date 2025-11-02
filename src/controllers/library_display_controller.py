from PyQt6.QtCore import QThread
from managers.localization_manager import tr
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
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
            if selected_chapter_id is not None:
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
                if selected_chapter_id is not None:
                    mod_widget.use_requested.connect(lambda mod_data=mod_data: self.on_chapter_mode_mod_use(mod_data, selected_chapter_id))
                    is_in_slot = self.slot_manager.is_mod_in_specific_slot(mod_data, selected_chapter_id)
                    mod_widget.set_in_slot(is_in_slot)
                else:
                    mod_widget.use_requested.connect(self.on_mod_use)
                self.app.installed_mods_layout.insertWidget(self.app.installed_mods_layout.count() - 1, mod_widget)
        if self.app.installed_mods_layout.count() <= 1:
            if selected_chapter_id is not None:
                chapter_names = {SLOT_ID_UNIVERSAL: tr('ui.mod_slot'), SLOT_ID_MENU: tr('chapters.menu'), SLOT_ID_CHAPTER_1: tr('tabs.chapter_1'), SLOT_ID_CHAPTER_2: tr('tabs.chapter_2'), SLOT_ID_CHAPTER_3: tr('tabs.chapter_3'), SLOT_ID_CHAPTER_4: tr('tabs.chapter_4')}
                chapter_name = chapter_names.get(selected_chapter_id, tr('ui.chapter_n', chapter=str(selected_chapter_id)))
                show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.no_mods_for_chapter', chapter_name=chapter_name), self.app_state.local_config, font_size=16)
            else:
                show_empty_message_in_layout(self.app.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
        self.app._updating_chapter_mods = False

    def refresh_async(self):
        is_chapter_mode = hasattr(self.app, 'chapter_mode_checkbox') and self.app.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = getattr(self.app, 'selected_chapter_id', None)
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
                selected_id = getattr(self.app, 'selected_chapter_id', None)
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
            self.slot_manager.remove_mod_from_all_slots(dummy_mod_data)
            config_keys = ['saved_slots_deltarune', 'saved_slots_deltarune_chapter', 'saved_slots_deltarunedemo', 'saved_slots_undertale']
            for config_key in config_keys:
                slots_data = self.app_state.local_config.get(config_key, {})
                slots_to_clear = []
                for slot_id_str, slot_info in list(slots_data.items()):
                    if isinstance(slot_info, dict):
                        saved_mod_key = slot_info.get('mod_key')
                        if saved_mod_key == orphaned_key:
                            slots_to_clear.append(slot_id_str)
                for slot_id_str in slots_to_clear:
                    del slots_data[slot_id_str]
                if slots_to_clear:
                    self.app_state.local_config[config_key] = slots_data
                    self.app.settings_manager.write_local_config()

    def update_mod_widgets_slot_status(self):
        if not hasattr(self.app, 'installed_mods_layout') or self.app.installed_mods_layout is None:
            return
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    is_in_slot = self.slot_manager.find_mod_in_slots(widget.mod_data) is not None
                    widget.set_in_slot(is_in_slot)

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
                self.slot_manager.remove_mod_from_all_slots(mod_data)
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
        current_slot = self.slot_manager.find_mod_in_slots(mod_data)
        if current_slot:
            self.slot_manager.remove_mod_from_slot(current_slot, mod_data)
            self.slot_manager.save_slots_state()
        else:
            is_chapter_mode = self.app.chapter_mode_checkbox.isChecked()
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
            elif not is_chapter_mode or is_demo_mode:
                target_slot = None
                if is_demo_mode:
                    target_slot_id = SLOT_ID_DEMO
                elif hasattr(mod_data, 'modgame') and mod_data.modgame == 'undertale':
                    target_slot_id = SLOT_ID_UNDERTALE
                else:
                    target_slot_id = SLOT_ID_UNIVERSAL
                for key, slot_frame in self.app_state.slots.items():
                    if slot_frame.chapter_id == target_slot_id:
                        target_slot = slot_frame
                        break
                if target_slot:
                    self.slot_manager.assign_mod_to_slot(target_slot, mod_data)
            else:
                self.app._show_slot_selection_dialog(mod_data)

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
        target_slot = None
        for slot_frame in self.app_state.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break
        if target_slot and target_slot.assigned_mod:
            assigned_mod_key = getattr(target_slot.assigned_mod, 'key', None) or getattr(target_slot.assigned_mod, 'mod_key', None) or getattr(target_slot.assigned_mod, 'name', None)
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
            if assigned_mod_key == mod_key:
                self.slot_manager.remove_mod_from_slot(target_slot, mod_data)
                self.update_for_chapter_mode(chapter_id)
                return
        target_slot = None
        for slot_frame in self.app_state.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break
        if target_slot:
            self.slot_manager.assign_mod_to_slot(target_slot, mod_data)
            self.update_for_chapter_mode(chapter_id)
        else:
            self.feedback_manager.show_warning('errors.target_slot_not_found')

    def clear_all_selections(self):
        for i in range(self.app.installed_mods_layout.count() - 1):
            item = self.app.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)
