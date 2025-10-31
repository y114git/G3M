from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout, QInputDialog, QWidget
from PyQt6.QtCore import Qt, QTimer
from ui.dialogs.mod.details import open_mod_details_dialog
from managers.localization_manager import tr, localization_manager
from config.constants import LAUNCHER_VERSION, UI_COLORS
from models.game_modes import DemoGameMode, UndertaleGameMode, FullGameMode


class UiControlsMixin:

    def _current_tab_names(self):
        return self.app_state.game_mode.tab_names

    def _prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._update_mod_display()

    def _next_page(self):
        total_pages = (len(self.filtered_mods) - 1) // self.mods_per_page + 1
        if self.current_page < total_pages:
            self.current_page += 1
            self._update_mod_display()

    def _switch_settings_page(self, page: QWidget):
        if self.app_state.current_settings_page and self.app_state.current_settings_page is not page:
            self.app_state.settings_nav_stack.append(self.app_state.current_settings_page)
            if len(self.app_state.settings_nav_stack) > 20:
                self.app_state.settings_nav_stack.pop(0)
            self.app_state.current_settings_page.setVisible(False)
        page.setVisible(True)
        self.app_state.current_settings_page = page

    def _go_back_or_to_main_menu(self):
        if hasattr(self, 'settings_nav_stack') and self.app_state.settings_nav_stack:
            prev = self.app_state.settings_nav_stack.pop()
            if self.app_state.current_settings_page:
                self.app_state.current_settings_page.setVisible(False)
            prev.setVisible(True)
            self.app_state.current_settings_page = prev
        else:
            self._toggle_settings_view()

    def _go_back_to_settings_menu(self):
        if self.app_state.current_settings_page and self.app_state.current_settings_page is not self.settings_menu_page:
            self.app_state.current_settings_page.setVisible(False)
        self.settings_menu_page.setVisible(True)
        self.app_state.current_settings_page = self.settings_menu_page
        if self.app_state.settings_nav_stack and self.app_state.settings_nav_stack[-1] is self.settings_menu_page:
            self.app_state.settings_nav_stack.pop()

    def _show_library_search_dialog(self):
        if self.library_search_text:
            self.library_search_text = ''
            self.library_search_button.setText('🔍')
            self.library_search_button.setToolTip(tr('ui.search_placeholder'))
            self._update_installed_mods_display()
        else:
            text, ok = QInputDialog.getText(self, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.library_search_text = text.strip()
                self.library_search_button.setText('↻')
                self.library_search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.library_search_text))
                self._update_installed_mods_display()

    def _show_search_dialog(self):
        if self.search_text:
            self.search_text = ''
            self.search_button.setText('🔍')
            self.search_button.setToolTip(tr('ui.search_placeholder'))
            self._update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.search_text = text.strip()
                self.search_button.setText('↻')
                self.search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.search_text))
                self._update_filtered_mods()

    def _show_slot_selection_dialog(self, mod_data):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.select_slot'))
        dialog.setFixedSize(300, 200)
        layout = QVBoxLayout(dialog)
        label = QLabel(tr('ui.select_slot_for_mod', mod_name=mod_data.name))
        layout.addWidget(label)
        slot_list = QListWidget()
        available_slots = []
        for key, slot_frame in self.app_state.slots.items():
            if slot_frame.assigned_mod is None:
                if slot_frame.chapter_id == -1:
                    slot_name = tr('ui.mod_slot')
                else:
                    chapter_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
                    slot_name = chapter_names[slot_frame.chapter_id]
                slot_list.addItem(slot_name)
                available_slots.append(slot_frame)
        if not available_slots:
            self.feedback_manager.show_info('dialogs.no_free_slots', tr('dialogs.all_slots_occupied'))
            return
        layout.addWidget(slot_list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = slot_list.selectedItems()
            if selected_items:
                selected_index = slot_list.row(selected_items[0])
                selected_slot = available_slots[selected_index]
                self.slot_manager.assign_mod_to_slot(selected_slot, mod_data)

    def _show_mod_details_dialog(self, mod_data):
        open_mod_details_dialog(self, mod_data)

    def _show_chapter_mode_instruction(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        from ui.common.styling import clear_layout_widgets
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        instruction_widget = QLabel(tr('ui.chapter_mode_instruction'))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_widget.setStyleSheet('\n            QLabel {\n                color: #CCCCCC;\n                font-size: 14px;\n                font-style: italic;\n                padding: 20px;\n                border: 2px dashed #666666;\n                background-color: rgba(255, 255, 255, 0.1);\n            }\n        ')
        instruction_widget.setWordWrap(True)
        instruction_widget.setMinimumHeight(80)
        self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, instruction_widget)

    def _prompt_for_update(self, update_info):
        if self.app_state.update_in_progress:
            return
        if self.app_state.game_is_running:
            self.app_state.pending_dialogs.append(('update', update_info))
            return
        self.app_state.update_in_progress = True
        update_message = f"<b>{tr('dialogs.new_version_banner', version=update_info['version']).replace('<br>', '')}</b><br>"
        update_message += tr('dialogs.current_version_banner', current_version=LAUNCHER_VERSION).replace('<br><br>', '') + '<br><br>'
        if localization_manager.get_current_language() == 'ru':
            message_text = update_info.get('message_ru') or update_info.get('message', '')
        else:
            message_text = update_info.get('message_en') or update_info.get('message', '')
        update_message += f"<b>{tr('dialogs.whats_new')}</b><br>{message_text}<br><br>"
        update_message += tr('dialogs.want_download_install_now') + tr('dialogs.app_will_restart')
        if self.feedback_manager.ask_question('status.update_available', 'status.update_available', update_message, True):
            self._perform_update_ui_prep()
            self.update_checker.perform_update(update_info)
        else:
            self.app_state.update_in_progress = False
            from config.constants import UI_COLORS
            self.feedback_manager.update_status(tr('status.update_rejected'), UI_COLORS['status_info'])

    def _show_pending_dialogs(self):
        if not self.app_state.pending_dialogs:
            return
        pending = self.app_state.pending_dialogs.copy()
        self.app_state.pending_dialogs.clear()
        for dialog_type, dialog_data in pending:
            if dialog_type == 'update':
                self._prompt_for_update(dialog_data)

    def _prompt_for_game_path(self, is_initial=False):
        result = self.settings_manager.prompt_for_game_path(is_initial)
        if result:
            self._update_action_button_state()
        if is_initial and (not result):
            self.customization_manager.start_background_music()
            self.initialization_finished.emit()

    def _on_library_filter_changed(self):
        self._update_installed_mods_display()

    def _on_game_type_changed(self, index):
        game_type = self.game_type_combo.itemData(index)
        if not game_type:
            return
        self.slot_manager.save_slots_state()
        if game_type == 'deltarunedemo':
            self.app_state.game_mode = DemoGameMode()
        elif game_type == 'undertale':
            self.app_state.game_mode = UndertaleGameMode()
        else:
            self.app_state.game_mode = FullGameMode()
        self._update_checkbox_visibility()
        self.slot_manager.update_slots_display(self.active_slots_layout)
        self.slot_manager.load_slots_state()
        self._update_installed_mods_display()
        self._update_change_path_button_text()
        self._update_saves_button_state()
        self.app_state.local_config['selected_game_type'] = game_type
        self.settings_manager.write_local_config()

    def _on_chapter_mode_changed(self, state):
        game_type = self.game_type_combo.currentData()
        if game_type != 'deltarune':
            return
        old_mode = getattr(self, 'current_mode', 'normal')
        self._previous_mode = old_mode
        is_chapter = bool(state)
        old_is_chapter = self.app_state.current_mode == 'chapter'
        if old_is_chapter != is_chapter:
            self.slot_manager.save_slots_state()
        self.app_state.current_mode = 'chapter' if is_chapter else 'normal'
        self.game_type_combo.setEnabled(not is_chapter)
        self.slot_manager.update_slots_display(self.active_slots_layout)
        self._update_mod_widgets_slot_status()
        self._update_action_button_state()
        if is_chapter:
            for slot_frame in self.app_state.slots.values():
                slot_frame.is_selected = False
                self.slot_manager.update_slot_visual_state(slot_frame)
            self.app_state.selected_chapter_id = None
            self._show_chapter_mode_instruction()
        else:
            self.app_state.selected_chapter_id = None
            self._update_installed_mods_display()
            if self.app_state.local_config.get('direct_launch_slot_id', -1) >= 0:
                self.app_state.local_config['direct_launch_slot_id'] = -1
        self._update_change_path_button_text()
        self.app_state.local_config['chapter_mode_enabled'] = is_chapter
        self.settings_manager.write_local_config()

    def _on_installed_mod_clicked(self, mod_data):
        for i in range(self.installed_mods_layout.count() - 1):
            try:
                item = self.installed_mods_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = getattr(widget.mod_data, 'key', None)
                        mod_data_key = getattr(mod_data, 'key', None)
                        if widget_mod_key == mod_data_key:
                            self._clear_all_installed_mod_selections()
                            widget.set_selected(True)
                            break
            except Exception:
                continue

    def _on_installed_mod_remove(self, mod_data):
        try:
            if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=getattr(mod_data, 'name', getattr(mod_data, 'key', 'Unknown'))):
                self.mod_manager.delete_mod_files(mod_data)
                self.slot_manager.remove_mod_from_all_slots(mod_data)
                self._update_installed_mods_display()
                try:
                    self._update_search_mod_plaques()
                except Exception:
                    pass
        except Exception as e:
            self.feedback_manager.show_error('errors.mod_removal_failed', error=str(e))

    def _on_installed_mod_use(self, mod_data):
        current_slot = self.slot_manager.find_mod_in_slots(mod_data)
        if current_slot:
            self.slot_manager.remove_mod_from_slot(current_slot, mod_data)
            self.slot_manager.save_slots_state()
        else:
            is_chapter_mode = self.chapter_mode_checkbox.isChecked()
            is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
            mod_widget = None
            for i in range(self.installed_mods_layout.count()):
                item = self.installed_mods_layout.itemAt(i)
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
                    target_slot_id = -10
                elif hasattr(mod_data, 'modgame') and mod_data.modgame == 'undertale':
                    target_slot_id = -20
                else:
                    target_slot_id = -1
                for key, slot_frame in self.app_state.slots.items():
                    if slot_frame.chapter_id == target_slot_id:
                        target_slot = slot_frame
                        break
                if target_slot:
                    self.slot_manager.assign_mod_to_slot(target_slot, mod_data)
            else:
                self._show_slot_selection_dialog(mod_data)

    def _on_mod_install_requested(self, mod):
        if self.app_state.is_installing:
            return
        self._install_single_mod(mod)

    def _on_install_progress_token(self, value: int, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.app_state.is_installing:
            self.progress_bar.setValue(value)

    def _on_install_status_token(self, message: str, color: str, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.app_state.is_installing:
            self._update_status(message, color)

    def _on_install_finished_token(self, success: bool, op_id: int):
        if getattr(self, '_install_op_id', 0) != op_id:
            return
        self._on_single_mod_install_finished(success)

    def _on_single_mod_install_finished(self, success):
        was_installed_before = False
        if hasattr(self, 'current_install_thread') and self.current_install_thread:
            was_installed_before = getattr(self.current_install_thread, 'was_installed_before', False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        if success:
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        else:
            if getattr(self, '_operation_cancelled', False):
                try:
                    self._operation_cancelled = False
                except Exception:
                    pass
            else:
                self.feedback_manager.update_status(tr('status.mod_install_error'), UI_COLORS['status_error'])
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        if success:
            self.mod_manager.load_local_mods()
            self._update_search_mod_plaques()
            if hasattr(self, '_update_installed_mods_display'):
                self._update_installed_mods_display()
            QTimer.singleShot(100, self._refresh_specific_mod_widget_after_update)
            if not was_installed_before:
                self.feedback_manager.show_info('dialogs.mod_installed_title', tr('dialogs.mod_installed_apply_info'))
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        self._update_action_button_state()

    def _on_mod_uninstall_requested(self, mod):
        if self.app_state.is_installing:
            return
        if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod.name):
            self._uninstall_single_mod(mod)

    def _on_mod_clicked(self, mod):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget) and widget.mod_data == mod:
                    self._clear_all_mod_selections()
                    widget.set_selected(True)
                    break

    def _on_mod_install_finished(self, success, from_gb=False):
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        self.progress_bar.setVisible(False)
        self._update_action_button_state()

    def _on_mod_installation_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self._update_action_button_state()

    def _on_toggle_full_install(self, state):
        self.app_state.is_full_install = bool(state)
        if platform.system() == 'Darwin' and self.app_state.is_full_install:
            self.feedback_manager.show_info('dialogs.unavailable', tr('dialogs.macos_install_unavailable'))
            self.full_install_checkbox.blockSignals(True)
            self.full_install_checkbox.setChecked(False)
            self.full_install_checkbox.blockSignals(False)
            return
        self._update_action_button_state()

    def _on_reset_settings_click(self):
        self.customization_manager.stop_background_music()
        callbacks = {'migrate_config': lambda: (self._load_local_data(), self.settings_manager.migrate_config_if_needed())}
        self.settings_manager.on_reset_settings_click(callbacks)
        self.launch_via_steam_checkbox.setChecked(False)
        self.use_custom_executable_checkbox.setChecked(False)
        self.chapter_mode_checkbox.setChecked(False)
        self.beta_updates_checkbox.setChecked(False)
        self.fullscreen_checkbox.setChecked(False)
        self.hide_library_filters_checkbox.setChecked(False)
        self.full_install_checkbox.setChecked(False)
        self.disable_background_checkbox.setChecked(False)
        self.disable_splash_checkbox.setChecked(False)
        self._update_custom_executable_ui()
        self._update_checkbox_visibility()
        self.slot_manager.clear_all_slots()
        self.slot_manager.save_slots_state()
        self.slot_manager.load_slots_state()
        self._update_settings_page_visibility()
        self.customization_manager.load_custom_style_settings(self.color_widgets, self.apply_theme)
        self._update_action_button_state()
        self.background_music_button.setText(self.customization_manager.get_background_music_button_text())
        self.startup_sound_button.setText(self.customization_manager.get_startup_sound_button_text())

    def _on_background_button_click(self):
        self.settings_manager.on_background_button_click()
        self._update_background_button_state()

    def _on_background_music_button_click(self):
        self.customization_manager.stop_background_music()
        self.settings_manager.on_background_music_button_click()
        self.background_music_button.setText(self.customization_manager.get_background_music_button_text())
        self.customization_manager.maybe_start_background_music(getattr(self, 'is_shown_to_user', False), self.isVisible())

    def _on_startup_sound_button_click(self):
        self.settings_manager.on_startup_sound_button_click()
        self.startup_sound_button.setText(self.customization_manager.get_startup_sound_button_text())
