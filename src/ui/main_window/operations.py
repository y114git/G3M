import os
import shutil
import threading
import logging
import base64
import json
from core.startup import ShortcutLaunchError
import subprocess
from typing import Optional, Any, cast
from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtWidgets import QTabWidget, QLabel, QWidget, QDialog, QDialogButtonBox, QVBoxLayout, QFileDialog
from PyQt6.QtGui import QMovie, QPixmap
from managers.localization_manager import tr, localization_manager
from managers.mod_manager import parse_mod_date
from config.constants import UI_COLORS
from utils.path_utils import get_legacy_ylauncher_path
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from ui.common.styling import clear_layout_widgets, load_mod_icon_universal, show_empty_message_in_layout
from models.game_modes import DemoGameMode, UndertaleGameMode, FullGameMode
from workers.background_workers import InstallModsThread, FullInstallThread
from workers.fetch_mods import FetchModsThread


class OperationsMixin:
    app_state: Any
    mod_manager: Any
    plugin_manager: Any
    shortcut_manager: Any
    feedback_manager: Any
    save_manager: Any
    slot_manager: Any
    settings_manager: Any
    main_tab_widget: Any
    game_type_combo: Any
    saves_button: Any
    save_tabs: Any
    _slot_labels: Any
    switch_collection_btn: Any
    left_col_btn: Any
    right_col_btn: Any
    rename_collection_btn: Any
    delete_collection_btn: Any
    copy_from_main_btn: Any
    copy_to_main_btn: Any
    collection_name_lbl: Any
    change_save_path_btn: Any
    installed_mods_layout: Any
    installed_mods_container: Any
    library_sort_combo: Any
    library_sort_ascending: Any
    library_tag_translation: Any
    library_tag_customization: Any
    library_tag_gameplay: Any
    library_tag_other: Any
    library_tag_local: Any
    mod_list_layout: Any
    mod_list_widget: Any
    mods_per_page: Any
    page_label: Any
    prev_page_btn: Any
    next_page_btn: Any
    search_text: Any
    tag_translation: Any
    tag_customization: Any
    tag_gameplay: Any
    tag_other: Any
    modgame_combo: Any
    sort_combo: Any
    sort_ascending: Any
    action_button: Any
    shortcut_button: Any
    change_path_button: Any
    change_background_button: Any
    top_refresh_button: Any
    settings_button: Any
    tab_widget: Any
    progress_bar: Any
    set_progress_signal: Any
    update_status_signal: Any
    presence_worker: Any
    current_install_thread: Any
    install_thread: Any
    is_shortcut_launch: Any
    online_label: Any
    status_label: Any
    chapter_mode_checkbox: Any
    show_btn: Any
    import_btn: Any
    erase_btn: Any
    export_btn: Any
    full_install_checkbox: Any
    game_launcher: Any
    restore_window_signal: Any
    customization_manager: Any
    language_combo: Any
    update_checker: Any
    mods_loaded_signal: Any

    def _load_local_data(self) -> None:
        ...

    def _get_current_game_path(self) -> str:
        return ''

    def _show_main_mod_management_dialog(self) -> None:
        ...

    def _on_xdelta_patch_click(self) -> None:
        ...

    def _on_installed_mod_clicked(self, *args, **kwargs) -> None:
        ...

    def _on_installed_mod_remove(self, *args, **kwargs) -> None:
        ...

    def _on_chapter_mode_mod_use(self, *args, **kwargs) -> None:
        ...

    def _on_installed_mod_use(self, *args, **kwargs) -> None:
        ...

    def _show_chapter_mode_instruction(self) -> None:
        ...

    def _update_action_button_state(self) -> None:
        ...

    def _refresh_mods_in_slots(self) -> None:
        ...

    def _retranslate_ui(self) -> None:
        ...

    def _update_background_button_state(self) -> None:
        ...

    def _on_mod_install_requested(self, *args, **kwargs) -> None:
        ...

    def _on_mod_uninstall_requested(self, *args, **kwargs) -> None:
        ...

    def _on_mod_clicked(self, *args, **kwargs) -> None:
        ...

    def _show_mod_details_dialog(self, *args, **kwargs) -> None:
        ...

    def _show_pending_dialogs(self) -> None:
        ...

    def _full_install_tooltip(self) -> str:
        ...

    def activateWindow(self) -> None:
        ...

    def raise_(self) -> None:
        ...

    def hide(self) -> None:
        ...

    def showNormal(self) -> None:
        ...

    def update(self) -> None:
        ...

    def size(self) -> Any:
        ...

    def isVisible(self) -> bool:
        ...

    def updateGeometry(self) -> None:
        ...

    def _shortcut_launch(self, args):
        try:
            settings_json = base64.b64decode(args.shortcut_launch).decode('utf-8')
            settings = json.loads(settings_json)
        except Exception as e:
            logging.error(f'Shortcut settings read error: {e}')
            raise ShortcutLaunchError('Failed to read shortcut settings')
        self._load_local_data()
        self.mod_manager.load_local_mods()
        try:
            if settings.get('is_undertale_mode', False):
                self.app_state.game_mode = UndertaleGameMode()
            else:
                self.app_state.game_mode = DemoGameMode() if settings.get('is_demo_mode', False) else FullGameMode()
            self.app_state.game_path = settings.get('game_path', '')
            self.app_state.demo_game_path = settings.get('demo_game_path', '')
            launch_via_steam = settings.get('launch_via_steam', False)
            use_custom_executable = settings.get('use_custom_executable', False)
            custom_exec_path = settings.get('custom_executable_path', '')
            demo_custom_exec_path = settings.get('demo_custom_executable_path', '')
            direct_launch_slot_id = settings.get('direct_launch_slot_id', -1)
            current_game_path = self._get_current_game_path()
            if not current_game_path or not os.path.exists(current_game_path):
                logging.error('Game files not found for launch')
                raise ShortcutLaunchError('Game files not found for launch')
            mods_settings = settings.get('mods', {}) or settings.get('selections', {})
            self.shortcut_manager.apply_shortcut_mods(mods_settings)
            self.shortcut_manager.launch_game_from_shortcut(launch_via_steam=launch_via_steam, use_custom_executable=use_custom_executable, custom_exec_path=custom_exec_path, demo_custom_exec_path=demo_custom_exec_path, direct_launch_slot_id=direct_launch_slot_id)
        except Exception as e:
            logging.error(f'Launch error: {e}')
            raise ShortcutLaunchError(str(e) or 'Shortcut launch failed')

    def _on_tab_changed(self, index):
        num_original_tabs = 4
        if getattr(self, '_suppress_tab_handlers', False):
            self.previous_tab_index = index
            return
        if index >= num_original_tabs:
            visible_plugins = [p for p in self.app_state.plugins if not p.get('tab_hide', False)]
            plugin_index = index - num_original_tabs
            if 0 <= plugin_index < len(visible_plugins):
                plugin = self._plugin_tab_map.get(index) or visible_plugins[plugin_index]
                current_widget = self.main_tab_widget.widget(index)
                is_placeholder = type(current_widget) is QWidget and current_widget.layout() is None
                if is_placeholder:
                    if self._handling_plugin_tab:
                        return
                    self._handling_plugin_tab = True
                    try:
                        bound = getattr(current_widget, '_plugin_info', None)
                        if isinstance(bound, dict):
                            plugin = bound
                    except Exception:
                        pass
                    try:
                        if current_widget is not None and hasattr(current_widget, 'property'):
                            name_key = current_widget.property('plugin_name_key')
                            if name_key:
                                for p in visible_plugins:
                                    if p.get('name_key') == name_key:
                                        plugin = p
                                        break
                    except Exception:
                        pass
                    try:
                        new_widget = None
                        handler = plugin.get('page_init') if callable(plugin.get('page_init')) else plugin.get('on_tab_open')
                        if callable(handler):
                            new_widget = handler(self)
                        if isinstance(new_widget, QWidget):
                            self.main_tab_widget.removeTab(index)
                            self.main_tab_widget.insertTab(index, new_widget, tr(plugin['name_key']))
                            self.main_tab_widget.setCurrentIndex(index)
                            self.previous_tab_index = index
                        else:
                            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
                    except Exception as e:
                        logging.error(f"Error running plugin '{plugin['name_key']}': {e}")
                        self.feedback_manager.show_error('errors.error', f"Failed to run plugin '{tr(plugin['name_key'])}':\n{e}")
                        self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
                    finally:
                        self._handling_plugin_tab = False
                    return
            self.previous_tab_index = index
            return
        if index == 2:
            self._show_main_mod_management_dialog()
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 3:
            self._on_xdelta_patch_click()
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 1:
            self._update_installed_mods_display()
            self.previous_tab_index = index
        else:
            self.previous_tab_index = index

    def _update_plugin_tabs(self):
        self._plugin_tab_map = self.plugin_manager.update_plugin_tabs(self.main_tab_widget, num_original_tabs=4)

    def _update_saves_button_state(self):
        game_type = self.game_type_combo.currentData()
        self.saves_button.setEnabled(game_type != 'undertale')

    def _refresh_save_slots(self):
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return
        chapter = self.save_tabs.currentIndex() + 1
        slots_data = self.save_manager.refresh_save_slots_data(chapter)
        for s, (active, text) in slots_data.items():
            self._slot_labels[chapter, s].setText(text)
        self._update_collection_ui()
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _update_collection_ui(self):
        ui_state = self.save_manager.get_collection_ui_state()
        in_col = ui_state['in_collection']
        self.switch_collection_btn.setText(tr('dialogs.main_slots') if in_col else tr('buttons.additional_slots'))
        self.left_col_btn.setEnabled(ui_state['can_navigate_left'])
        self.right_col_btn.setEnabled(ui_state['can_navigate_right'])
        self.rename_collection_btn.setVisible(in_col)
        self.delete_collection_btn.setVisible(in_col)
        self.copy_from_main_btn.setVisible(in_col)
        self.copy_to_main_btn.setVisible(in_col)
        if in_col and ui_state['collection_name']:
            self.collection_name_lbl.setText(ui_state['collection_name'])
            self.collection_name_lbl.setVisible(True)
        else:
            self.collection_name_lbl.setVisible(False)
        self.change_save_path_btn.setVisible(not in_col)

    def _update_installed_mods_for_chapter_mode(self, selected_chapter_id):
        if not hasattr(self, 'installed_mods_layout'):
            return
        if hasattr(self, '_updating_chapter_mods') and self._updating_chapter_mods:
            return
        self._updating_chapter_mods = True
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        installed_mods = self.mod_manager.get_installed_mods_list()
        if hasattr(self, 'library_sort_combo'):
            sort_type = self.library_sort_combo.currentIndex()
            reverse = not self.library_sort_ascending
            if sort_type == 0:
                installed_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
            elif sort_type == 1:

                def get_sort_date(mod):
                    if mod.get('is_local_mod'):
                        return mod.get('created_date', '0')
                    else:
                        return mod.get('updated_date') or mod.get('installed_date', '0')
                installed_mods.sort(key=get_sort_date, reverse=reverse)
        is_demo_mode = hasattr(self, 'game_type_combo') and self.game_type_combo.currentData() == 'deltarunedemo'
        selected_tags = []
        if hasattr(self, 'library_tag_widgets'):
            tag_map = {self.library_tag_translation: 'translation', self.library_tag_customization: 'customization', self.library_tag_gameplay: 'gameplay', self.library_tag_other: 'other', self.library_tag_local: 'local'}
            for checkbox, tag in tag_map.items():
                if checkbox.isChecked():
                    selected_tags.append(tag)
        search_text = getattr(self, 'library_search_text', '').lower()
        for mod_info in installed_mods:
            if is_demo_mode and (not mod_info.get('modgame', 'deltarune') == 'deltarunedemo'):
                continue
            elif not is_demo_mode and mod_info.get('modgame', 'deltarune') == 'deltarunedemo':
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
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, parent=self)
                mod_widget.clicked.connect(self._on_installed_mod_clicked)
                mod_widget.remove_requested.connect(self._on_installed_mod_remove)
                if selected_chapter_id is not None:
                    mod_widget.use_requested.connect(lambda mod_data=mod_data: self._on_chapter_mode_mod_use(mod_data, selected_chapter_id))
                    is_in_slot = self.slot_manager.is_mod_in_specific_slot(mod_data, selected_chapter_id)
                    mod_widget.set_in_slot(is_in_slot)
                else:
                    mod_widget.use_requested.connect(self._on_installed_mod_use)
                self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)
        if self.installed_mods_layout.count() <= 1:
            if selected_chapter_id is not None:
                chapter_names = {-1: tr('ui.mod_slot'), 0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                chapter_name = chapter_names.get(selected_chapter_id, tr('ui.chapter_n', chapter=str(selected_chapter_id)))
                show_empty_message_in_layout(self.installed_mods_layout, tr('ui.no_mods_for_chapter', chapter_name=chapter_name), self.app_state.local_config, font_size=16)
            else:
                show_empty_message_in_layout(self.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
        self._updating_chapter_mods = False

    def _update_installed_mods_display(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = self.app_state.selected_chapter_id
            if selected_id is not None:
                self._update_installed_mods_for_chapter_mode(selected_id)
                return
            else:
                self._update_installed_mods_for_chapter_mode(None)
                return
        self._refresh_installed_mods_async()

    def _update_installed_mods_display_from_list(self, installed_mods):
        try:
            is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
            if is_chapter_mode:
                selected_id = getattr(self, 'selected_chapter_id', None)
                if selected_id is None:
                    if hasattr(self, 'installed_mods_container') and hasattr(self, 'installed_mods_layout'):
                        self.installed_mods_container.setUpdatesEnabled(False)
                        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
                        self._show_chapter_mode_instruction()
                        self.installed_mods_container.setUpdatesEnabled(True)
                    return
                else:
                    self._update_installed_mods_for_chapter_mode(selected_id)
                    return
            self.installed_mods_container.setUpdatesEnabled(False)
            clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
            self._cleanup_missing_mods(installed_mods)
            if hasattr(self, 'library_sort_combo'):
                sort_type = self.library_sort_combo.currentIndex()
                reverse = not self.library_sort_ascending
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
            if hasattr(self, 'library_tag_widgets'):
                tag_map = {self.library_tag_translation: 'translation', self.library_tag_customization: 'customization', self.library_tag_gameplay: 'gameplay', self.library_tag_other: 'other', self.library_tag_local: 'local'}
                for checkbox, tag in tag_map.items():
                    if checkbox.isChecked():
                        selected_tags.append(tag)
            search_text = getattr(self, 'library_search_text', '').lower()
            current_game_type = 'deltarune'
            if hasattr(self, 'game_type_combo'):
                current_game_type = self.game_type_combo.currentData() or 'deltarune'
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
                    mod_widget = InstalledModWidget(mod_data, is_local, is_available, has_update, parent=self)
                    mod_widget.clicked.connect(self._on_installed_mod_clicked)
                    mod_widget.remove_requested.connect(self._on_installed_mod_remove)
                    mod_widget.use_requested.connect(self._on_installed_mod_use)
                    self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)
            if self.installed_mods_layout.count() <= 1:
                show_empty_message_in_layout(self.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
            self._update_mod_widgets_slot_status()
            self._update_action_button_state()
            self.installed_mods_container.setUpdatesEnabled(True)
        except Exception:
            if hasattr(self, 'installed_mods_container'):
                self.installed_mods_container.setUpdatesEnabled(True)

    def _refresh_installed_mods_async(self):
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = getattr(self, 'selected_chapter_id', None)
            if selected_id is None:
                if hasattr(self, 'installed_mods_container') and hasattr(self, 'installed_mods_layout'):
                    self.installed_mods_container.setUpdatesEnabled(False)
                    clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
                    self._show_chapter_mode_instruction()
                    self.installed_mods_container.setUpdatesEnabled(True)
                return
            else:
                self._update_installed_mods_for_chapter_mode(selected_id)
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
                self.outer._update_installed_mods_display_from_list(mods)
        try:
            self._installed_scan_thread = _Scan(self)
            self._installed_scan_thread.start()
        except Exception:
            mods = self.mod_manager.get_installed_mods_list()
            self._update_installed_mods_display_from_list(mods)

    def _cleanup_missing_mods(self, installed_mods):
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
                    self.settings_manager.write_local_config()

    def handle_one_click_install(self, url: str):
        from utils.game_utils import is_game_running
        if is_game_running():
            return
        self.activateWindow()
        self.raise_()
        if self.app_state.is_installing:
            self.feedback_manager.show_warning('dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
            return
        self.mod_manager.install_from_url(url)

    def _install_single_mod(self, mod, force=False):
        try:
            if self.app_state.is_installing and (not force):
                return
            available_chapters = []
            if mod.modgame == 'undertale':
                if mod.files.get('undertale'):
                    available_chapters.append(0)
            elif mod.modgame == 'deltarunedemo':
                if mod.files.get('demo'):
                    available_chapters.append(-1)
            else:
                for chapter_id in range(0, 5):
                    chapter_data = mod.get_chapter_data(chapter_id)
                    if chapter_data:
                        available_chapters.append(chapter_id)
            if not available_chapters:
                self.feedback_manager.show_warning('errors.mod_no_files', mod_name=mod.name)
                return
            was_installed_before = self.mod_manager.is_mod_installed(mod.key)
            is_xdelta_mod = getattr(mod, 'is_xdelta', False)
            if not is_xdelta_mod and (not was_installed_before):
                if not self.feedback_manager.ask_question('dialogs.file_replacement_warning_title', 'dialogs.file_replacement_warning_body', '', False):
                    self.feedback_manager.update_status(tr('status.install_cancelled_by_user'), UI_COLORS['status_info'])
                    return
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            try:
                self._operation_cancelled = False
            except Exception:
                pass
            self.app_state.is_installing = True
            self._set_install_buttons_enabled(False)
            self.action_button.setText(tr('ui.cancel_button'))
            self._install_op_id = getattr(self, '_install_op_id', 0) + 1
            op_id = self._install_op_id
            self.current_install_thread = InstallModsThread(self, install_tasks, was_installed_before)
            self.install_thread = self.current_install_thread
            self.install_thread.progress.connect(lambda v, oid=op_id: self._on_install_progress_token(v, oid))
            self.install_thread.status.connect(lambda msg, col, oid=op_id: self._on_install_status_token(msg, col, oid))
            self.install_thread.finished.connect(lambda ok, oid=op_id: self._on_install_finished_token(ok, oid))
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            try:
                self.feedback_manager.update_status(tr('status.preparing_download'), UI_COLORS['status_warning'])
            except Exception:
                pass
            self._update_action_button_state()
            self.install_thread.start()
        except Exception as e:
            self.feedback_manager.show_error('errors.mod_install_failed', error=str(e))

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
            try:
                if not was_installed_before:
                    self.feedback_manager.show_info('dialogs.mod_installed_title', tr('dialogs.mod_installed_apply_info'))
            except Exception:
                pass
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        self._update_action_button_state()

    def _refresh_specific_mod_widget_after_update(self):
        if not hasattr(self, 'current_install_thread') or not self.current_install_thread:
            return
        install_tasks = getattr(self.current_install_thread, 'install_tasks', [])
        if not install_tasks:
            return
        mod_data_tuple = install_tasks[0]
        mod_to_update = mod_data_tuple[0]
        mod_key_to_find = getattr(mod_to_update, 'key', None)
        if not mod_key_to_find:
            return
        if hasattr(self, 'installed_mods_layout'):
            for i in range(self.installed_mods_layout.count()):
                item = self.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = getattr(widget.mod_data, 'key', None)
                        if widget_mod_key == mod_key_to_find:
                            widget.update_status()
                            break

    def _uninstall_single_mod(self, mod):
        self.mod_manager.uninstall_mod(mod)
        self._update_search_mod_plaques()

    def _update_search_mod_plaques(self):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.update_installation_status()

    def _set_install_buttons_enabled(self, enabled: bool):
        try:
            self.action_button.setEnabled(True if self.app_state.is_installing else enabled)
            self.saves_button.setEnabled(True)
            self.shortcut_button.setEnabled(enabled)
        except Exception:
            pass

    def _update_change_path_button_text(self):
        self.change_path_button.setText(self.app_state.game_mode.path_change_button_text)

    def _update_mod_widgets_slot_status(self):
        if not hasattr(self, 'installed_mods_layout') or self.installed_mods_layout is None:
            return
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    is_in_slot = self.slot_manager.find_mod_in_slots(widget.mod_data) is not None
                    widget.set_in_slot(is_in_slot)

    def _refresh_all_slot_status_displays(self):
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod and slot_frame.content_widget:
                self._refresh_slot_status_display(slot_frame)
                if hasattr(slot_frame, 'mod_icon') and slot_frame.mod_icon:
                    load_mod_icon_universal(slot_frame.mod_icon, slot_frame.assigned_mod, 32)

    def _refresh_slot_status_display(self, slot_frame):
        if not slot_frame.assigned_mod or not slot_frame.content_widget:
            return
        mod_data = slot_frame.assigned_mod
        version_label = None
        content_layout = slot_frame.content_widget.layout()
        if content_layout:
            for i in range(content_layout.count()):
                item = content_layout.itemAt(i)
                if item and item.layout():
                    text_layout = item.layout()
                    if text_layout and text_layout.count() >= 2:
                        version_item = text_layout.itemAt(1)
                        if version_item and version_item.widget() and isinstance(version_item.widget(), QLabel):
                            version_label = version_item.widget()
                            break
        if version_label:
            is_large_slot = slot_frame.chapter_id < 0
            is_local_mod = getattr(mod_data, 'is_local_mod', False)
            if is_local_mod:
                if is_large_slot:
                    status_text, status_color = (tr('defaults.local_mod'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
                else:
                    status_text, status_color = (tr('tags.local'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            elif is_large_slot:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_available'), 'orange') if needs_update else (tr('status.version_current'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
            else:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_short'), 'orange') if needs_update else (tr('status.current_short'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            version_label.setText(status_text)

    def _update_filtered_mods(self):
        if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
            self.filtered_mods = []
            self._update_mod_display()
            return
        selected_tags = []
        if hasattr(self, 'tag_translation') and self.tag_translation.isChecked():
            selected_tags.append('translation')
        if hasattr(self, 'tag_customization') and self.tag_customization.isChecked():
            selected_tags.append('customization')
        if hasattr(self, 'tag_gameplay') and self.tag_gameplay.isChecked():
            selected_tags.append('gameplay')
        if hasattr(self, 'tag_other') and self.tag_other.isChecked():
            selected_tags.append('other')
        selected_modgame = ''
        if hasattr(self, 'modgame_combo'):
            selected_modgame = self.modgame_combo.currentData() or ''
        self.filtered_mods = []
        for mod in self.app_state.all_mods:
            if getattr(mod, 'hide_mod', False) in [True, 'true', 'True', 1]:
                continue
            if getattr(mod, 'ban_status', False) in [True, 'true', 'True', 1]:
                continue
            mod_status = getattr(mod, 'status', 'approved')
            if mod_status not in ['approved', 'pending']:
                continue
            if getattr(mod, 'is_local_mod', False):
                continue
            if selected_tags:
                mod_tags = getattr(mod, 'tags', []) or []
                if not all((tag in mod_tags for tag in selected_tags)):
                    continue
            if selected_modgame:
                mod_modgame = getattr(mod, 'modgame', 'deltarune')
                if mod_modgame != selected_modgame:
                    continue
            if hasattr(self, 'search_text') and self.search_text:
                search_text_lower = self.search_text.lower()
                mod_name = getattr(mod, 'name', '').lower()
                mod_tagline = getattr(mod, 'tagline', '').lower()
                if search_text_lower not in mod_name and search_text_lower not in mod_tagline:
                    continue
            self.filtered_mods.append(mod)
        self._sort_filtered_mods()
        self.current_page = 1
        self._update_mod_display()

    def _sort_filtered_mods(self):
        if not hasattr(self, 'sort_combo') or not self.filtered_mods:
            return
        sort_type = self.sort_combo.currentIndex()
        reverse = not self.sort_ascending
        if sort_type == 0:
            self.filtered_mods.sort(key=lambda mod: getattr(mod, 'downloads', 0), reverse=reverse)
        elif sort_type == 1:
            self.filtered_mods.sort(key=lambda mod: parse_mod_date(getattr(mod, 'last_updated', '')), reverse=reverse)
        elif sort_type == 2:
            self.filtered_mods.sort(key=lambda mod: parse_mod_date(getattr(mod, 'created_date', '')), reverse=reverse)

    def _update_mod_display(self):
        clear_layout_widgets(self.mod_list_layout, keep_last_n=1)
        start_index = (self.current_page - 1) * self.mods_per_page
        end_index = start_index + self.mods_per_page
        current_page_mods = self.filtered_mods[start_index:end_index]
        self.mod_list_widget.setUpdatesEnabled(False)
        try:
            for mod in current_page_mods:
                plaque = ModPlaqueWidget(mod, parent=self)
                plaque.install_requested.connect(self._on_mod_install_requested)
                plaque.uninstall_requested.connect(self._on_mod_uninstall_requested)
                plaque.clicked.connect(self._on_mod_clicked)
                plaque.details_requested.connect(self._show_mod_details_dialog)
                plaque.install_button.setEnabled(not self.app_state.is_installing)
                self.mod_list_layout.insertWidget(self.mod_list_layout.count() - 1, plaque)
        finally:
            self.mod_list_widget.setUpdatesEnabled(True)
        self._update_pagination_controls()

    def _update_pagination_controls(self):
        if not hasattr(self, 'page_label') or not hasattr(self, 'prev_page_btn') or (not hasattr(self, 'next_page_btn')):
            return
        total_mods = len(self.filtered_mods)
        total_pages = max(1, (total_mods - 1) // self.mods_per_page + 1) if total_mods > 0 else 1
        self.page_label.setText(tr('ui.page_label', current=self.current_page, total=total_pages))
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < total_pages)

    def _get_installed_mods_list(self):
        return self.mod_manager.get_installed_mods_list()

    def _clear_all_installed_mod_selections(self):
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _clear_all_mod_selections(self):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.set_selected(False)

    def _configure_hidden_tab_bar(self, tab_widget: QTabWidget):
        bar = tab_widget.tabBar()
        if bar:
            bar.hide()

    def _clear_selected_slot(self):
        self.app_state.selected_slot = None
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _update_slot_action_bar(self):
        in_main = self.app_state.current_collection_idx == -1
        visible = self.app_state.selected_slot is not None
        for b in (self.show_btn, self.import_btn, self.erase_btn, self.export_btn):
            b.setVisible(visible)
        has_data = False
        if self.app_state.selected_slot:
            ch, s = self.app_state.selected_slot
            idx = self.app_state.current_collection_idx
            base = self.save_manager.get_collection_path(idx)
            fp = os.path.join(base, f'filech{ch}_{s}')
            has_data = os.path.exists(fp) and os.path.getsize(fp) > 0
        self.erase_btn.setEnabled(has_data)
        self.export_btn.setEnabled(has_data)
        self.copy_from_main_btn.setEnabled(not in_main)
        self.copy_to_main_btn.setEnabled(not in_main)

    def _update_slot_highlight(self):
        user_bg = self.app_state.local_config.get('custom_color_background')
        if user_bg and self.settings_manager.is_valid_hex_color(user_bg):
            slot_bg = f"#80{user_bg.lstrip('#')}"
        else:
            slot_bg = '#80000000'
        for (ch, sl), lbl in self._slot_labels.items():
            if self.app_state.selected_slot == (ch, sl):
                lbl.setStyleSheet(f'border:2px solid white; background-color: {slot_bg}; padding:4px;')
            else:
                lbl.setStyleSheet(f'border:1px solid white; background-color: {slot_bg}; padding:4px;')

    def _run_presence_tick(self):
        if self.is_shortcut_launch:
            return
        if hasattr(self, 'presence_worker') and self.presence_worker:
            self.presence_worker.run()

    def _update_online_label(self, count: int):
        if not self.is_shortcut_launch:
            self._last_online_count = count
            display_count = '?' if count < 0 else count
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=display_count)}")

    def _update_status(self, message: str, color: str = 'white'):
        if not self.is_shortcut_launch:
            actual_color = UI_COLORS.get(color, color)
            self.status_label.setText(message)
            self.status_label.setStyleSheet(f'color: {actual_color};')

    def _perform_update_ui_prep(self):
        for widget in [self.action_button, self.saves_button, self.shortcut_button, self.change_path_button, self.change_background_button]:
            widget.setEnabled(False)
        try:
            if hasattr(self, 'top_refresh_button') and self.top_refresh_button:
                self.top_refresh_button.setEnabled(False)
        except Exception:
            pass
        self.settings_button.setEnabled(False)
        if not self.app_state.is_settings_view:
            self.tab_widget.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

    def _perform_full_install(self):
        if self.app_state.is_installing:
            return
        if hasattr(self, 'full_install_thread') and self.full_install_thread and self.full_install_thread.isRunning():
            return
        self.action_button.setEnabled(False)
        self.saves_button.setEnabled(False)
        dlg = QDialog(cast(QWidget, self))
        dlg.setWindowTitle(tr('dialogs.full_demo_install'))
        v = QVBoxLayout(dlg)
        lbl = QLabel(self._full_install_tooltip())
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.action_button.setEnabled(True)
            return
        base_dir = QFileDialog.getExistingDirectory(cast(QWidget, self), tr('dialogs.install_demo_location'))
        if not base_dir:
            self.action_button.setEnabled(True)
            return
        target_dir = os.path.join(base_dir, 'DELTARUNEdemo')
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            self.feedback_manager.show_error('errors.error', tr('errors.folder_creation_failed', error=str(e)))
            self.action_button.setEnabled(True)
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.full_install_thread = FullInstallThread(cast(Any, self), target_dir, False)
        self.full_install_thread.progress.connect(self.set_progress_signal)
        self.full_install_thread.progress.connect(self.progress_bar.setValue)
        self.full_install_thread.status.connect(self.update_status_signal)
        self.full_install_thread.progress.connect(self.progress_bar.setValue)
        self.full_install_thread.finished.connect(self._on_full_install_finished)
        self.full_install_thread.start()

    def _on_full_install_finished(self, success, target_dir):
        self.progress_bar.setVisible(False)
        self.full_install_checkbox.blockSignals(True)
        self.progress_bar.setValue(0)
        self.full_install_checkbox.setChecked(False)
        self.full_install_checkbox.blockSignals(False)
        if success:
            if isinstance(self.app_state.game_mode, DemoGameMode):
                self.app_state.demo_game_path = target_dir
                self.app_state.local_config['demo_game_path'] = target_dir
            else:
                self.app_state.game_path = target_dir
                self.app_state.local_config['game_path'] = target_dir
            self.settings_manager.write_local_config()
            self.feedback_manager.update_status(tr('status.game_files_install_complete'), UI_COLORS['status_success'])
            self._update_action_button_state()
            return
        else:
            self.feedback_manager.update_status(tr('status.game_files_install_failed'), UI_COLORS['status_error'])
        self.settings_manager.write_local_config()
        self._update_action_button_state()

    def _run_as_admin_windows(self, path: str) -> bool:
        script = f"import os, stat; p = r'{path}'; [os.chmod(os.path.join(r, f), os.stat(os.path.join(r, f)).st_mode | stat.S_IWRITE) for r, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE) if os.path.exists(p) else None"
        command = f'Start-Process python -ArgumentList "-c "{script}"" -Verb RunAs -WindowStyle Hidden'
        try:
            subprocess.run(['powershell', '-Command', command], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.feedback_manager.update_status(tr('status.permission_change_failed'), UI_COLORS['status_error'])
            return False

    def _launch_game_with_all_mods(self):
        self.game_launcher.launch_game_with_all_mods(execute_plugin_hooks=lambda hook_name: self.plugin_manager.execute_hooks(hook_name, self), restore_window_callback=self.restore_window_signal.emit)

    def _hide_window_for_game(self):
        try:
            self.customization_manager.stop_background_music()
        except Exception:
            pass
        self.app_state.game_is_running = True
        self.hide()

    def _restore_window_after_game(self):
        self.app_state.game_is_running = False
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.saves_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._update_action_button_state()
        QTimer.singleShot(100, self.updateGeometry)
        if hasattr(self, '_update_installed_mods_display'):
            self._update_installed_mods_display()
        if hasattr(self, '_update_mod_display'):
            self._update_mod_display()
        self.customization_manager.maybe_start_background_music(getattr(self, 'is_shown_to_user', False), self.isVisible())
        self._show_pending_dialogs()
        self.plugin_manager.execute_hooks('on_after_game_exit', self)

    def _on_refresh_clicked(self, is_initial=False):
        current_lang_code = localization_manager.get_current_language()
        localization_manager.rescan_languages()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        available_languages = localization_manager.get_available_languages()
        for code, name in available_languages.items():
            self.language_combo.addItem(name, code)
        index = self.language_combo.findData(current_lang_code)
        if index != -1:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)
        if not is_initial:
            self._retranslate_ui()
        from utils.game_utils import is_game_running
        if is_game_running():
            self.feedback_manager.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
            return
        self._stop_fetch_thread()
        threading.Thread(target=self.update_checker.check_for_updates, daemon=True).start()
        self.fetch_thread = FetchModsThread(self, force_update=True)
        self.fetch_thread.status.connect(self.update_status_signal)
        self.fetch_thread.result.connect(self._on_fetch_translations_finished)
        self.fetch_thread.start()

    def _stop_fetch_thread(self):
        self._safe_stop_thread(getattr(self, 'fetch_thread', None))
        self.fetch_thread = None

    def _safe_stop_thread(self, thr: Optional[QThread], timeout: int = 2000):
        if isinstance(thr, QThread) and thr.isRunning():
            thr.requestInterruption()
            thr.quit()
            if not thr.wait(timeout):
                thr.terminate()
                thr.wait()

    def _stop_presence_thread(self):
        self._safe_stop_thread(getattr(self, 'presence_thread', None))
        self.presence_thread = None
        self.presence_worker = None

    def _on_fetch_translations_finished(self, success: bool):
        try:
            self.mod_manager.load_local_mods()
            if hasattr(self, 'mod_list_layout'):
                self._update_filtered_mods()
                if not self.app_state.mods_loaded:
                    self.app_state.mods_loaded = True
                    self.mods_loaded_signal.emit()
            if hasattr(self, 'installed_mods_layout'):
                self._update_installed_mods_display()
            self._refresh_mods_in_slots()
            self.slot_manager.refresh_slots_content()
            self._update_action_button_state()
            if success:
                self.feedback_manager.update_status(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.app_state.all_mods else tr('ui.network_update_failed')
                self.feedback_manager.update_status(fallback_msg, UI_COLORS['status_error'])
            QTimer.singleShot(100, self.slot_manager.load_slots_state)
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])

    def _on_bg_ready(self, obj):
        if isinstance(obj, tuple):
            if obj[0] == 'gif':
                if self.background_movie is not None:
                    self.background_movie.stop()
                    self.background_movie.deleteLater()
                self.background_movie = QMovie(obj[1])
                self.background_movie.frameChanged.connect(self.update)
                self.background_movie.start()
                self.background_pixmap = None
            elif obj[0] == 'img':
                self.background_movie = None
                self.background_pixmap = QPixmap.fromImage(obj[1]).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.update()

    def _on_update_cleanup(self):
        try:
            self.progress_bar.setVisible(False)
        except Exception:
            pass
        self.app_state.update_in_progress = False
        try:
            if not self.app_state.is_settings_view:
                self.tab_widget.setEnabled(True)
            for w in [self.action_button, self.saves_button, self.shortcut_button, self.change_path_button, self.change_background_button]:
                w.setEnabled(True)
            try:
                if hasattr(self, 'top_refresh_button') and self.top_refresh_button:
                    self.top_refresh_button.setEnabled(True)
            except Exception:
                pass
            self.settings_button.setEnabled(True)
            self._update_action_button_state()
        except Exception:
            pass

    def _cleanup_legacy_ylauncher_folder(self):
        try:
            legacy_path = get_legacy_ylauncher_path()
            if legacy_path and os.path.isdir(legacy_path):
                try:
                    shutil.rmtree(legacy_path, ignore_errors=True)
                except Exception:
                    pass
                self.feedback_manager.show_info('dialogs.legacy_cleanup_title', tr('dialogs.legacy_cleanup_message'))
        except Exception:
            pass
