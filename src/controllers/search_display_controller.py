from PyQt6.QtWidgets import QInputDialog
from managers.localization_manager import tr
from managers.mod_manager import parse_mod_date
from ui.common.styling import clear_layout_widgets
from ui.dialogs.mod_details import open_mod_details_dialog
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget


class SearchDisplayController:

    def __init__(self, app_window):
        self.app = app_window
        self.app_state = app_window.app_state
        self.feedback_manager = app_window.feedback_manager
        self.mod_manager = app_window.mod_manager

    def prev_page(self):
        if self.app.current_page > 1:
            self.app.current_page -= 1
            self.update_display()

    def next_page(self):
        total_pages = (len(self.app.filtered_mods) - 1) // self.app.mods_per_page + 1
        if self.app.current_page < total_pages:
            self.app.current_page += 1
            self.update_display()

    def show_search_dialog(self):
        if self.app.search_text:
            self.app.search_text = ''
            self.app.search_button.setText('🔍')
            self.app.search_button.setToolTip(tr('ui.search_placeholder'))
            self.update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self.app, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.app.search_text = text.strip()
                self.app.search_button.setText('↻')
                self.app.search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.app.search_text))
                self.update_filtered_mods()

    def update_filtered_mods(self):
        if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
            self.app.filtered_mods = []
            self.update_display()
            return
        selected_tags = []
        if hasattr(self.app, 'tag_translation') and self.app.tag_translation.isChecked():
            selected_tags.append('translation')
        if hasattr(self.app, 'tag_customization') and self.app.tag_customization.isChecked():
            selected_tags.append('customization')
        if hasattr(self.app, 'tag_gameplay') and self.app.tag_gameplay.isChecked():
            selected_tags.append('gameplay')
        if hasattr(self.app, 'tag_other') and self.app.tag_other.isChecked():
            selected_tags.append('other')
        selected_modgame = ''
        if hasattr(self.app, 'modgame_combo'):
            selected_modgame = self.app.modgame_combo.currentData() or ''
        self.app.filtered_mods = []
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
            if hasattr(self.app, 'search_text') and self.app.search_text:
                search_text_lower = self.app.search_text.lower()
                mod_name = getattr(mod, 'name', '').lower()
                mod_tagline = getattr(mod, 'tagline', '').lower()
                if search_text_lower not in mod_name and search_text_lower not in mod_tagline:
                    continue
            self.app.filtered_mods.append(mod)
        self.sort_filtered_mods()
        self.app.current_page = 1
        self.update_display()

    def sort_filtered_mods(self):
        if not hasattr(self.app, 'sort_combo') or not self.app.filtered_mods:
            return
        sort_type = self.app.sort_combo.currentIndex()
        reverse = not self.app.sort_ascending
        if sort_type == 0:
            self.app.filtered_mods.sort(key=lambda mod: getattr(mod, 'downloads', 0), reverse=reverse)
        elif sort_type == 1:
            self.app.filtered_mods.sort(key=lambda mod: parse_mod_date(getattr(mod, 'last_updated', '')), reverse=reverse)
        elif sort_type == 2:
            self.app.filtered_mods.sort(key=lambda mod: parse_mod_date(getattr(mod, 'created_date', '')), reverse=reverse)

    def update_display(self):
        clear_layout_widgets(self.app.mod_list_layout, keep_last_n=1)
        start_index = (self.app.current_page - 1) * self.app.mods_per_page
        end_index = start_index + self.app.mods_per_page
        current_page_mods = self.app.filtered_mods[start_index:end_index]
        self.app.mod_list_widget.setUpdatesEnabled(False)
        try:
            for mod in current_page_mods:
                plaque = ModPlaqueWidget(mod, parent=self.app)
                plaque.install_requested.connect(self.app.mod_ops.on_mod_install_requested)
                plaque.uninstall_requested.connect(self.app.mod_ops.on_mod_uninstall_requested)
                plaque.clicked.connect(self.on_mod_clicked)
                plaque.details_requested.connect(self.show_details)
                plaque.install_button.setEnabled(not self.app_state.is_installing)
                self.app.mod_list_layout.insertWidget(self.app.mod_list_layout.count() - 1, plaque)
        finally:
            self.app.mod_list_widget.setUpdatesEnabled(True)
        self.update_pagination()

    def update_pagination(self):
        if not hasattr(self.app, 'page_label') or not hasattr(self.app, 'prev_page_btn') or (not hasattr(self.app, 'next_page_btn')):
            return
        total_mods = len(self.app.filtered_mods)
        total_pages = max(1, (total_mods - 1) // self.app.mods_per_page + 1) if total_mods > 0 else 1
        self.app.page_label.setText(tr('ui.page_label', current=self.app.current_page, total=total_pages))
        self.app.prev_page_btn.setEnabled(self.app.current_page > 1)
        self.app.next_page_btn.setEnabled(self.app.current_page < total_pages)

    def update_search_plaques(self):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.update_installation_status()

    def on_mod_clicked(self, mod):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget) and widget.mod_data == mod:
                    self.clear_all_selections()
                    widget.set_selected(True)
                    break

    def show_details(self, mod_data):
        open_mod_details_dialog(self.app, mod_data)

    def clear_all_selections(self):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.set_selected(False)
