from PyQt6.QtWidgets import QInputDialog
from managers.localization_manager import tr
from ui.common.styling import clear_layout_widgets
from ui.dialogs.mod_details import open_mod_details_dialog
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
from utils.mod_filter_utils import filter_and_sort_mods


class SearchDisplayController:

    def __init__(self, app_state, feedback_manager, mod_manager, mod_ops, app_window):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.mod_ops = mod_ops
        self.app = app_window

    def prev_page(self):
        if self.app_state.current_page > 1:
            self.app_state.current_page -= 1
            self.update_display()

    def next_page(self):
        total_pages = (len(self.app_state.filtered_mods) - 1) // self.app_state.mods_per_page + 1
        if self.app_state.current_page < total_pages:
            self.app_state.current_page += 1
            self.update_display()

    def show_search_dialog(self):
        if self.app_state.search_text:
            self.app_state.search_text = ''
            self.app.search_button.setText('🔍')
            self.app.search_button.setToolTip(tr('ui.search_placeholder'))
            self.update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self.app, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.app_state.search_text = text.strip()
                self.app.search_button.setText('↻')
                self.app.search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.app_state.search_text))
                self.update_filtered_mods()

    def _build_filters_and_sort(self):
        selected_tags = []
        tag_checkboxes = {'tag_translation': 'translation', 'tag_customization': 'customization', 'tag_gameplay': 'gameplay', 'tag_other': 'other'}
        for attr_name, tag_value in tag_checkboxes.items():
            if hasattr(self.app, attr_name) and getattr(self.app, attr_name).isChecked():
                selected_tags.append(tag_value)
        selected_modgame = ''
        if hasattr(self.app, 'modgame_combo'):
            selected_modgame = self.app.modgame_combo.currentData() or ''
        filters = {'tags': selected_tags, 'modgame': selected_modgame, 'search_text': self.app_state.search_text, 'hide_banned': True, 'hide_local': True, 'status_filter': ['approved', 'pending']}
        sort_config = None
        if hasattr(self.app, 'sort_combo'):
            sort_type = self.app.sort_combo.currentIndex()
            reverse = not self.app.sort_ascending
            sort_config = {'sort_type': sort_type, 'reverse': reverse}
        return (filters, sort_config)

    def update_filtered_mods(self):
        if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
            self.app_state.filtered_mods = []
            self.update_display()
            return
        filters, sort_config = self._build_filters_and_sort()
        self.app_state.filtered_mods = filter_and_sort_mods(self.app_state.all_mods, filters, sort_config)
        self.app_state.current_page = 1
        self.update_display()

    def sort_filtered_mods(self):
        if not hasattr(self.app, 'sort_combo') or not self.app_state.filtered_mods:
            return
        filters, sort_config = self._build_filters_and_sort()
        self.app_state.filtered_mods = filter_and_sort_mods(self.app_state.all_mods, filters, sort_config)

    def update_display(self):
        clear_layout_widgets(self.app.mod_list_layout, keep_last_n=1)
        start_index = (self.app_state.current_page - 1) * self.app_state.mods_per_page
        end_index = start_index + self.app_state.mods_per_page
        current_page_mods = self.app_state.filtered_mods[start_index:end_index]
        self.app.mod_list_widget.setUpdatesEnabled(False)
        try:
            for mod in current_page_mods:
                plaque = ModPlaqueWidget(mod, parent=self.app)
                plaque.install_requested.connect(self.mod_ops.on_mod_install_requested)
                plaque.uninstall_requested.connect(self.mod_ops.on_mod_uninstall_requested)
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
        total_mods = len(self.app_state.filtered_mods)
        total_pages = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
        self.app.page_label.setText(tr('ui.page_label', current=self.app_state.current_page, total=total_pages))
        self.app.prev_page_btn.setEnabled(self.app_state.current_page > 1)
        self.app.next_page_btn.setEnabled(self.app_state.current_page < total_pages)

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
