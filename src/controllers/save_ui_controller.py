import os
from PyQt6.QtWidgets import QTabWidget
from managers.localization_manager import tr
from config.constants import UI_COLORS
from ui.dialogs.save_editor import SaveEditorDialog


class SaveUiController:

    def __init__(self, app_window):
        self.app = app_window
        self.app_state = app_window.app_state
        self.feedback_manager = app_window.feedback_manager
        self.save_manager = app_window.save_manager
        self.settings_manager = app_window.settings_manager

    def configure_hidden_tab_bar(self, tab_widget: QTabWidget):
        bar = tab_widget.tabBar()
        if bar:
            bar.hide()

    def show_save_manager(self):
        if not self.save_manager.find_and_validate_save_path():
            return
        self.app_state.is_save_manager_view = True
        self.app.main_tab_widget.setVisible(False)
        self.app.bottom_widget.setVisible(False)
        self.app.settings_widget.setVisible(False)
        self.app.save_manager_widget.setVisible(True)
        self.app_state.selected_slot = None
        self.refresh_slots()
        self.feedback_manager.update_status(tr('status.save_path_info', save_path=self.app_state.save_path), UI_COLORS['status_info'])
        self.app.settings_button.setText(tr('ui.back_button'))
        try:
            self.app.settings_button.clicked.disconnect(self.app._toggle_settings_view)
        except TypeError:
            pass
        self.app.settings_button.clicked.connect(self.return_from_save_manager)

    def hide_save_manager(self):
        self.app.save_manager_widget.setVisible(False)
        self.app_state.is_save_manager_view = False
        if self.app_state.is_settings_view:
            self.app.settings_widget.setVisible(True)
        else:
            self.app.main_tab_widget.setVisible(True)
            self.app.bottom_widget.setVisible(True)

    def return_from_save_manager(self):
        self.hide_save_manager()
        self.app.settings_button.setText(tr('ui.settings_title'))
        try:
            self.app.settings_button.clicked.disconnect(self.return_from_save_manager)
        except TypeError:
            pass
        self.app.settings_button.clicked.connect(self.app._toggle_settings_view)

    def refresh_slots(self):
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return
        chapter = self.app.save_tabs.currentIndex() + 1
        slots_data = self.save_manager.refresh_save_slots_data(chapter)
        for s, (active, text) in slots_data.items():
            self.app._slot_labels[chapter, s].setText(text)
        self.update_collection_ui()
        self.update_slot_highlight()
        self.update_slot_action_bar()

    def update_collection_ui(self):
        ui_state = self.save_manager.get_collection_ui_state()
        in_col = ui_state['in_collection']
        self.app.switch_collection_btn.setText(tr('dialogs.main_slots') if in_col else tr('buttons.additional_slots'))
        self.app.left_col_btn.setEnabled(ui_state['can_navigate_left'])
        self.app.right_col_btn.setEnabled(ui_state['can_navigate_right'])
        self.app.rename_collection_btn.setVisible(in_col)
        self.app.delete_collection_btn.setVisible(in_col)
        self.app.copy_from_main_btn.setVisible(in_col)
        self.app.copy_to_main_btn.setVisible(in_col)
        if in_col and ui_state['collection_name']:
            self.app.collection_name_lbl.setText(ui_state['collection_name'])
            self.app.collection_name_lbl.setVisible(True)
        else:
            self.app.collection_name_lbl.setVisible(False)
        self.app.change_save_path_btn.setVisible(not in_col)

    def update_slot_highlight(self):
        user_bg = self.app_state.local_config.get('custom_color_background')
        if user_bg and self.settings_manager.is_valid_hex_color(user_bg):
            slot_bg = f"#80{user_bg.lstrip('#')}"
        else:
            slot_bg = '#80000000'
        for (ch, sl), lbl in self.app._slot_labels.items():
            if self.app_state.selected_slot == (ch, sl):
                lbl.setStyleSheet(f'border:2px solid white; background-color: {slot_bg}; padding:4px;')
            else:
                lbl.setStyleSheet(f'border:1px solid white; background-color: {slot_bg}; padding:4px;')

    def update_slot_action_bar(self):
        in_main = self.app_state.current_collection_idx == -1
        visible = self.app_state.selected_slot is not None
        for b in (self.app.show_btn, self.app.import_btn, self.app.erase_btn, self.app.export_btn):
            b.setVisible(visible)
        has_data = False
        if self.app_state.selected_slot:
            ch, s = self.app_state.selected_slot
            idx = self.app_state.current_collection_idx
            base = self.save_manager.get_collection_path(idx)
            fp = os.path.join(base, f'filech{ch}_{s}')
            has_data = os.path.exists(fp) and os.path.getsize(fp) > 0
        self.app.erase_btn.setEnabled(has_data)
        self.app.export_btn.setEnabled(has_data)
        self.app.copy_from_main_btn.setEnabled(not in_main)
        self.app.copy_to_main_btn.setEnabled(not in_main)

    def on_slot_clicked(self, chapter: int, slot: int):
        self.app_state.selected_slot = (chapter, slot)
        self.update_slot_highlight()
        self.update_slot_action_bar()

    def on_slot_double_clicked(self, chapter: int, slot: int):
        idx = self.app_state.current_collection_idx
        base = self.save_manager.get_collection_path(idx)
        fp = os.path.join(base, f'filech{chapter}_{slot}')
        if not (os.path.exists(fp) and os.path.getsize(fp) > 0):
            return
        dlg = SaveEditorDialog(fp, self.app)
        if dlg.exec():
            self.refresh_slots()

    def on_chapter_tab_changed(self):
        self.app_state.selected_slot = None
        self.refresh_slots()

    def clear_selected_slot(self):
        self.app_state.selected_slot = None
        self.update_slot_highlight()
        self.update_slot_action_bar()
