"""Controller for plugin display and management.

This module handles the display of installed plugins, plugin installation,
and plugin lifecycle operations.
"""
import os
import shutil
import logging
import webbrowser
from typing import Dict
from PyQt6.QtWidgets import QDialog
from managers.localization_manager import tr
from config.constants import UI_COLORS
from ui.widgets.plugin.plugin_widget import PluginWidget
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from workers.plugin_install_worker import PluginInstallWorker


class PluginDisplayController:
    """Manages plugin display and interaction in the UI."""

    def __init__(self, app_state, feedback_manager, plugin_manager, app_window):
        """Initialize the plugin display controller.

        Args:
            app_state: Application state manager.
            feedback_manager: User feedback and dialog manager.
            plugin_manager: Plugin management operations.
            app_window: Main application window reference.
        """
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.plugin_manager = plugin_manager
        self.app = app_window
        self._plugin_widgets: Dict[str, PluginWidget] = {}

    def _get_plugin_info(self, plugin_name: str):
        """Get plugin information by name.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Plugin info dictionary or None if not found.
        """
        return next((p for p in self.plugin_manager.get_all_plugins_info() if p.get('name') == plugin_name), None)

    def _remove_plugin_widget(self, widget: PluginWidget) -> None:
        """Remove a plugin widget from the layout.

        Args:
            widget: Plugin widget to remove.
        """
        self.app.plugins_layout.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()

    def _install_plugin(self, source: str, source_label: str) -> None:
        """Install a plugin from a source.

        Args:
            source: Plugin source path or URL.
            source_label: Label describing the source for error messages.
        """
        try:
            worker = PluginInstallWorker(source, self.app_state.plugins_dir, self.plugin_manager, self.app)
            self._start_plugin_install(worker)
        except Exception as e:
            logging.error(f'PluginDisplayController: Error installing plugin from {source_label}: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.installation_error', error=str(e)))

    def update_display(self):
        """Update the plugin display with current plugin list."""
        if not hasattr(self.app, 'plugins_layout') or not self.app.plugins_layout:
            return
        all_plugins = self.plugin_manager.get_all_plugins_info()
        if not all_plugins:
            clear_layout_widgets(self.app.plugins_layout)
            self._plugin_widgets.clear()
            show_empty_message_in_layout(self.app.plugins_layout, tr('plugins.no_plugins_installed'), self.app_state.local_config, font_size=16)
            return
        plugins_by_name = {plugin.get('name', ''): plugin for plugin in all_plugins}
        widgets_to_remove = []
        for i in range(self.app.plugins_layout.count() - 1):
            item = self.app.plugins_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if not isinstance(widget, PluginWidget):
                    widgets_to_remove.append(widget)
        for widget in widgets_to_remove:
            self._remove_plugin_widget(widget)
        current_plugin_names = set(plugins_by_name)
        plugins_to_remove = []
        for plugin_name, widget in list(self._plugin_widgets.items()):
            if plugin_name not in current_plugin_names:
                plugins_to_remove.append(plugin_name)
            else:
                plugin_info = plugins_by_name.get(plugin_name)
                if plugin_info:
                    widget.update_plugin_info(plugin_info)
        for plugin_name in plugins_to_remove:
            widget = self._plugin_widgets.pop(plugin_name, None)
            if widget:
                self._remove_plugin_widget(widget)
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
        """Handle plugin widget click event.

        Args:
            plugin_name: Name of the plugin that was clicked.

        Toggles selection state of the clicked plugin and deselects others.
        """
        for name, widget in self._plugin_widgets.items():
            if name == plugin_name:
                widget.set_selected(not widget.is_selected)
            else:
                widget.set_selected(False)

    def on_plugin_toggle(self, plugin_name: str):
        """Toggle plugin enabled/disabled state.

        Args:
            plugin_name: Name of the plugin to toggle.

        Enables or disables the plugin and updates the display.
        """
        try:
            plugin_info = self._get_plugin_info(plugin_name)
            if not plugin_info:
                self.feedback_manager.show_message('error', 'errors.error', tr('plugins.plugin_not_found'))
                return
            name_key = plugin_info.get('name_key')
            localized_name = tr(name_key) if name_key else plugin_name
            status = plugin_info.get('status', 'enabled')
            if status == 'enabled':
                self.plugin_manager.disable_plugin(plugin_name)
                self.feedback_manager.update_status(tr('plugins.plugin_disabled', name=localized_name), UI_COLORS['status_info'])
            else:
                self.plugin_manager.enable_plugin(plugin_name)
                self.feedback_manager.update_status(tr('plugins.plugin_enabled', name=localized_name), UI_COLORS['status_success'])
            self.plugin_manager.reload_plugin(plugin_name)
            if hasattr(self.app, '_update_plugin_tabs'):
                self.app._update_plugin_tabs()
            self.update_display()
        except Exception as e:
            error_msg = str(e)
            logging.error(f'PluginDisplayController: Error toggling plugin {plugin_name}: {error_msg}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.toggle_error', error=error_msg))

    def on_plugin_delete(self, plugin_name: str):
        """Delete a plugin from the system.

        Args:
            plugin_name: Name of the plugin to delete.

        Shows confirmation dialog, removes plugin files and metadata.
        """
        try:
            plugin_path = os.path.join(self.app_state.plugins_dir, plugin_name)
            if not os.path.exists(plugin_path):
                self.feedback_manager.show_message('error', 'errors.error', tr('plugins.plugin_not_found'))
                return
            plugin_info = self._get_plugin_info(plugin_name)
            name_key = plugin_info.get('name_key') if plugin_info else None
            localized_name = tr(name_key) if name_key else plugin_name
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(self.app, tr('plugins.delete_plugin_title'), tr('plugins.delete_plugin_message', name=localized_name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
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
            self.feedback_manager.update_status(tr('plugins.plugin_deleted', name=localized_name), UI_COLORS['status_success'])
        except Exception as e:
            error_msg = str(e)
            logging.error(f'PluginDisplayController: Error deleting plugin {plugin_name}: {error_msg}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.delete_error', error=error_msg))

    def on_search_plugins(self):
        """Open the plugins documentation page in web browser.

        Opens the GitHub plugins page for users to find available plugins.
        """
        try:
            webbrowser.open('https://github.com/y114git/ylauncherdata/blob/main/PLUGINS.md')
        except Exception as e:
            logging.error(f'PluginDisplayController: Error opening plugins page: {e}', exc_info=True)
            self.feedback_manager.show_message('error', 'errors.error', tr('plugins.open_page_error'))

    def on_import_plugin(self):
        """Show plugin import dialog.

        Opens dialog for importing plugins from file or URL.
        """
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(self.app, self.feedback_manager, 'plugins')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._install_plugin_from_file(dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._install_plugin_from_url(dialog.selected_url)

    def _start_plugin_install(self, worker: PluginInstallWorker):
        """Start plugin installation worker.

        Args:
            worker: PluginInstallWorker to start.

        Connects signals and starts the plugin installation process.
        """
        worker.status.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
        worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
        worker.finished.connect(self._on_plugin_install_finished)
        worker.unrar_needed.connect(self._on_unrar_needed)
        self.app_state.is_installing = True
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        self.app_state.current_task = worker
        worker.start()

    def _install_plugin_from_file(self, file_path: str):
        """Install plugin from local file.

        Args:
            file_path: Path to the plugin file to install.
        """
        self._install_plugin(file_path, 'file')

    def _install_plugin_from_url(self, url: str):
        """Install plugin from URL.

        Args:
            url: URL of the plugin to install.
        """
        self._install_plugin(url, 'URL')

    def _on_unrar_needed(self):
        """Handle UnRAR requirement from plugin install worker.

        Prompts for UnRAR installation and signals result back to worker.
        """
        try:
            from utils.archive_utils import prompt_for_unrar_install
            worker = self.app_state.current_task
            success = prompt_for_unrar_install(parent_widget=self.app)
            if success:
                logging.info('UnRAR installed successfully from plugin worker request')
            else:
                logging.info('User declined UnRAR installation from plugin worker request')
            if worker and hasattr(worker, 'signal_unrar_installed'):
                worker.signal_unrar_installed(success)
        except Exception as e:
            logging.error(f'PluginDisplayController: Error handling UnRAR installation request: {e}')
            if self.app_state.current_task and hasattr(self.app_state.current_task, 'signal_unrar_installed'):
                self.app_state.current_task.signal_unrar_installed(False)

    def _on_plugin_install_finished(self, success: bool, message: str):
        """Handle completion of plugin installation.

        Args:
            success: Whether installation succeeded.
            message: Status message to display.

        Resets UI state and updates plugin list on success.
        """
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
        """Update text for all plugin widgets for localization.

        Calls retranslate_texts on all plugin widgets to update
        their text to the current language.
        """
        for plugin_name, widget in self._plugin_widgets.items():
            if hasattr(widget, 'retranslate_texts'):
                widget.retranslate_texts()
