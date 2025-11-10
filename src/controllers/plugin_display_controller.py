import os
import shutil
import logging
import webbrowser
from typing import Dict, Any, List
from PyQt6.QtWidgets import QWidget, QDialog
from managers.localization_manager import tr
from config.constants import UI_COLORS
from ui.widgets.plugin.plugin_widget import PluginWidget
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from workers.plugin_install_worker import PluginInstallWorker


class PluginDisplayController:

    def __init__(self, app_state, feedback_manager, plugin_manager, app_window):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.plugin_manager = plugin_manager
        self.app = app_window
        self._plugin_widgets: Dict[str, PluginWidget] = {}

    def update_display(self):
        if not hasattr(self.app, 'plugins_layout') or not self.app.plugins_layout:
            return
        all_plugins = self.plugin_manager.get_all_plugins_info()
        if not all_plugins:
            clear_layout_widgets(self.app.plugins_layout)
            self._plugin_widgets.clear()
            show_empty_message_in_layout(self.app.plugins_layout, tr('plugins.no_plugins_installed'), self.app_state.local_config, font_size=16)
            return
        widgets_to_remove = []
        for i in range(self.app.plugins_layout.count() - 1):
            item = self.app.plugins_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if not isinstance(widget, PluginWidget):
                    widgets_to_remove.append(widget)
        for widget in widgets_to_remove:
            self.app.plugins_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        current_plugin_names = {p.get('name', '') for p in all_plugins}
        plugins_to_remove = []
        for plugin_name, widget in list(self._plugin_widgets.items()):
            if plugin_name not in current_plugin_names:
                plugins_to_remove.append(plugin_name)
            else:
                plugin_info = next((p for p in all_plugins if p.get('name') == plugin_name), None)
                if plugin_info:
                    widget.update_plugin_info(plugin_info)
        for plugin_name in plugins_to_remove:
            widget = self._plugin_widgets.pop(plugin_name, None)
            if widget:
                self.app.plugins_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
        existing_names = set(self._plugin_widgets.keys())
        for plugin_info in all_plugins:
            plugin_name = plugin_info.get('name', '')
            if plugin_name not in existing_names:
                plugin_widget = PluginWidget(plugin_info, parent=self.app.plugins_layout.parent(), parent_app=self.app)
                plugin_widget.clicked.connect(lambda name=plugin_name: self._on_plugin_clicked(name))
                plugin_widget.toggle_requested.connect(lambda name=plugin_name: self.on_plugin_toggle(name))
                plugin_widget.delete_requested.connect(lambda name=plugin_name: self.on_plugin_delete(name))
                self._plugin_widgets[plugin_name] = plugin_widget
                self.app.plugins_layout.insertWidget(self.app.plugins_layout.count() - 1, plugin_widget)
        logging.info(f'PluginDisplayController: Updated display with {len(all_plugins)} plugins')

    def _on_plugin_clicked(self, plugin_name: str):
        for name, widget in self._plugin_widgets.items():
            if name == plugin_name:
                widget.set_selected(not widget.is_selected)
            else:
                widget.set_selected(False)

    def on_plugin_toggle(self, plugin_name: str):
        try:
            plugin_info = next((p for p in self.plugin_manager.get_all_plugins_info() if p.get('name') == plugin_name), None)
            if not plugin_info:
                self.feedback_manager.show_message('error', 'errors.error', tr('plugins.plugin_not_found'))
                return
            status = plugin_info.get('status', 'enabled')
            if status == 'enabled':
                self.plugin_manager.disable_plugin(plugin_name)
                self.feedback_manager.update_status(tr('plugins.plugin_disabled', name=plugin_name), UI_COLORS['status_info'])
            else:
                self.plugin_manager.enable_plugin(plugin_name)
                self.feedback_manager.update_status(tr('plugins.plugin_enabled', name=plugin_name), UI_COLORS['status_success'])
            self.plugin_manager.reload_plugin(plugin_name)
            if hasattr(self.app, '_update_plugin_tabs'):
                self.app._update_plugin_tabs()
            self.update_display()
        except Exception as e:
            error_msg = str(e)
            logging.error(f'PluginDisplayController: Error toggling plugin {plugin_name}: {error_msg}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.toggle_error', error=error_msg))

    def on_plugin_delete(self, plugin_name: str):
        try:
            plugin_path = os.path.join(self.app_state.plugins_dir, plugin_name)
            if not os.path.exists(plugin_path):
                self.feedback_manager.show_message('error', 'errors.error', tr('plugins.plugin_not_found'))
                return
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(self.app, tr('plugins.delete_plugin_title'), tr('plugins.delete_plugin_message', name=plugin_name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            metadata = self.plugin_manager._read_plugins_metadata()
            if plugin_name in metadata:
                del metadata[plugin_name]
                self.plugin_manager._write_plugins_metadata(metadata)
            if os.path.exists(plugin_path):
                shutil.rmtree(plugin_path)
            self.plugin_manager.load_plugins()
            if hasattr(self.app, '_update_plugin_tabs'):
                self.app._update_plugin_tabs()
            self.update_display()
            self.feedback_manager.update_status(tr('plugins.plugin_deleted', name=plugin_name), UI_COLORS['status_success'])
        except Exception as e:
            error_msg = str(e)
            logging.error(f'PluginDisplayController: Error deleting plugin {plugin_name}: {error_msg}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.delete_error', error=error_msg))

    def on_search_plugins(self):
        try:
            webbrowser.open('https://github.com/y114git/ylauncherdata/blob/main/PLUGINS.md')
        except Exception as e:
            logging.error(f'PluginDisplayController: Error opening plugins page: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.open_page_error'))

    def on_import_plugin(self):
        from ui.dialogs.plugin_import_dialog import PluginImportDialog
        dialog = PluginImportDialog(self.app, self.plugin_manager, self.app_state, self.feedback_manager)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._install_plugin_from_file(dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._install_plugin_from_url(dialog.selected_url)

    def _install_plugin_from_file(self, file_path: str):
        try:
            worker = PluginInstallWorker(file_path, self.app_state.plugins_dir, self.plugin_manager, self.app)
            worker.status.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
            worker.finished.connect(self._on_plugin_install_finished)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(f'PluginDisplayController: Error installing plugin from file: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.installation_error', error=str(e)))

    def _install_plugin_from_url(self, url: str):
        try:
            worker = PluginInstallWorker(url, self.app_state.plugins_dir, self.plugin_manager, self.app)
            worker.status.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
            worker.finished.connect(self._on_plugin_install_finished)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(f'PluginDisplayController: Error installing plugin from URL: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.installation_error', error=str(e)))

    def _on_plugin_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.app_state.progress_bar_visible = False
        self.app_state.progress_bar_value = 0
        self.app_state.clear_current_task()
        if success:
            if self.plugin_manager:
                self.plugin_manager.convert_plugin_archives()
                self.plugin_manager.load_plugins()
            self.feedback_manager.update_status(message, UI_COLORS['status_success'])
            if hasattr(self.app, '_update_plugin_tabs'):
                self.app._update_plugin_tabs()
            self.update_display()
        else:
            self.feedback_manager.show_message('error', 'errors.error', message)

    def retranslate_plugin_widgets(self):
        for plugin_name, widget in self._plugin_widgets.items():
            if hasattr(widget, 'retranslate_texts'):
                widget.retranslate_texts()
