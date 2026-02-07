"""Controller for mod import and export operations."""
import os
import json
import shutil
import tempfile
import logging
import zipfile
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QListWidget, QListWidgetItem, QCheckBox
from PyQt6.QtCore import Qt
from services.localization_service import tr
from utils.file_utils import find_deltamod_info_file, save_json
from utils.archive_utils import extract_archive
from utils.mod_utils import get_mod_key
from config.constants import MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME


class ModImportExportController:
    """Manages mod import and export functionality."""

    def __init__(self, app_state, mod_service, app_window):
        self.app_state = app_state
        self.mod_service = mod_service
        self.app_window = app_window

    def _refresh_mod_list(self) -> None:
        self.mod_service.invalidate_mods_cache()
        self.mod_service.load_local_mods(_skip_conversion=True)
        self.mod_service.mod_list_updated.emit()

    def show_import_export_dialog(self):
        dialog = QDialog(self.app_window)
        dialog.setWindowTitle(tr('ui.import_export_mod'))
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        button_layout = QHBoxLayout()
        import_btn = QPushButton(tr('ui.import_mod'))
        import_btn.clicked.connect(lambda: (dialog.accept(), self._show_import_dialog()))
        button_layout.addWidget(import_btn)
        export_btn = QPushButton(tr('ui.export_mod'))
        export_btn.clicked.connect(lambda: (dialog.accept(), self._show_export_dialog()))
        button_layout.addWidget(export_btn)
        cancel_btn = QPushButton(tr('ui.cancel_button'))
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        dialog.exec()

    def _show_import_dialog(self):
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(self.app_window, self.app_window.feedback_service, 'mods')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._install_mod_from_file(dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._install_mod_from_url(dialog.selected_url)

    def _install_mod_from_file(self, file_path: str):
        from utils.file_utils import sanitize_filename, remove_archive_extension
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub_import_') as temp_dir:
                try:
                    extract_archive(file_path, temp_dir)
                except Exception as e:
                    if 'UnRAR utility is missing' in str(e):
                        if self._prompt_for_unrar_install():
                            extract_archive(file_path, temp_dir)
                        else:
                            return
                    else:
                        raise e
                content_path = temp_dir
                contents = os.listdir(temp_dir)
                if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                    content_path = os.path.join(temp_dir, contents[0])
                if find_deltamod_info_file(content_path):
                    from adapters.deltamod_adapter import DeltamodConverter
                    converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        self._refresh_mod_list()
                        QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                    else:
                        QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_import_failed', error='Conversion failed'))
                    return
                config_path_to_read = os.path.join(content_path, MOD_CONFIG_FILENAME)
                if not os.path.exists(config_path_to_read):
                    legacy_config_path = os.path.join(content_path, LEGACY_MOD_CONFIG_FILENAME)
                    if os.path.exists(legacy_config_path):
                        config_path_to_read = legacy_config_path
                if os.path.exists(config_path_to_read):
                    with open(config_path_to_read, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    key = config.get('key') or config.get('mod_key')
                    mod_name = config.get('name', 'Unknown')
                    mod_key_generated = False
                    if not key:
                        key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                        config['key'] = key
                        if 'mod_key' in config:
                            del config['mod_key']
                        save_json(config_path_to_read, config, indent=2)
                        mod_key_generated = True
                    archive_name = remove_archive_extension(os.path.basename(file_path))
                    folder_name = sanitize_filename(archive_name)
                    target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name)
                    counter = 1
                    while os.path.exists(target_mod_dir):
                        folder_name_with_counter = f'{folder_name}_{counter}'
                        target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name_with_counter)
                        counter += 1
                    shutil.copytree(content_path, target_mod_dir)
                    target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
                    target_old_config_path = os.path.join(target_mod_dir, LEGACY_MOD_CONFIG_FILENAME)
                    if os.path.exists(target_old_config_path) and (not os.path.exists(target_config_path)):
                        try:
                            shutil.move(target_old_config_path, target_config_path)
                        except Exception as e:
                            logging.warning(f'Failed to migrate config during import: {e}')
                    config_path = target_config_path
                    config_updated = False
                    if 'files' in config:
                        for chapter_key, chapter_data in config['files'].items():
                            if chapter_key == 'demo':
                                chapter_folder = os.path.join(target_mod_dir, 'demo')
                            elif chapter_key == 'undertale':
                                chapter_folder = os.path.join(target_mod_dir, 'undertale')
                            elif chapter_key in ['0', '1', '2', '3', '4']:
                                chapter_id = int(chapter_key)
                                from utils.file_utils import get_chapter_folder_name
                                folder_name = get_chapter_folder_name(chapter_id, game=config.get('game') or config.get('modgame'))
                                chapter_folder = os.path.join(target_mod_dir, folder_name)
                            else:
                                continue
                            if os.path.exists(chapter_folder):
                                if not chapter_data.get('data_file_url'):
                                    from config.constants import DATA_FILE_EXTENSIONS
                                    for file in os.listdir(chapter_folder):
                                        if file.lower().endswith(DATA_FILE_EXTENSIONS):
                                            chapter_data['data_file_url'] = file
                                            config_updated = True
                                            break
                    icon_path = os.path.join(target_mod_dir, '_icon.png')
                    if not os.path.exists(icon_path):
                        icon_path = os.path.join(target_mod_dir, 'icon.png')
                    if os.path.exists(icon_path) and (not config.get('icon_url')):
                        config['icon_url'] = '_icon.png' if os.path.basename(icon_path) == '_icon.png' else 'icon.png'
                        config_updated = True
                    if config_updated or mod_key_generated:
                        save_json(config_path, config, indent=2)
                    self._refresh_mod_list()
                    QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                else:
                    self._show_import_error_with_manual_install(file_path, tr('errors.invalid_mod_format'))
        except Exception as e:
            logging.error(f'[IMPORT] Mod import failed: {e}', exc_info=True)
            self._show_import_error_with_manual_install(file_path, tr('errors.mod_import_failed', error=str(e)))

    def _prompt_for_unrar_install(self) -> bool:
        reply = QMessageBox.question(self.app_window, tr('errors.unrar_missing_title'), tr('errors.unrar_missing_text'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            from utils.archive_utils import download_and_setup_unrar, _get_unrar_path
            success = download_and_setup_unrar(status_callback=lambda msg: self.app_window.feedback_service.update_status(msg, 'blue'))
            if success:
                self.app_window.feedback_service.update_status(tr('status.ready'), 'green')
                return True
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            import platform
            bin_path = os.path.dirname(_get_unrar_path())
            system_os = platform.system()
            platform_info = {'Linux': ('https://www.rarlab.com/rar_add.htm', 'errors.unrar_manual_install_linux'), 'Darwin': ('https://www.rarlab.com/rar/unrar_MacOSX_10.13.2_64bit.gz', 'errors.unrar_manual_install_mac')}
            url_to_open, msg_key = platform_info.get(system_os, ('https://www.rarlab.com/rar/unrarw64.exe', 'errors.unrar_manual_install_windows'))
            msg_text = tr(msg_key, url=url_to_open, path=bin_path)
            msg = QMessageBox(self.app_window)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle(tr('errors.error'))
            msg.setText(tr('errors.unrar_download_failed', error='Download failed/Platform not supported'))
            msg.setInformativeText(msg_text)
            open_btn = msg.addButton(tr('buttons.open_browser') if tr('buttons.open_browser') != 'buttons.open_browser' else 'Open Website', QMessageBox.ButtonRole.ActionRole)
            _ = msg.addButton(tr('buttons.ok'), QMessageBox.ButtonRole.AcceptRole)
            msg.exec()
            if msg.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl(url_to_open))
            return False
        return False

    def _install_mod_from_url(self, url: str):
        try:
            from workers.install.url_install_worker import UrlInstallThread
            worker = UrlInstallThread(self.app_window, url)
            worker.status.connect(lambda msg, color: self.app_window.feedback_service.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
            worker.finished.connect(self._on_mod_install_finished)
            worker.unrar_needed.connect(self._on_unrar_needed)
            worker.manual_install_required.connect(self._on_manual_install_required)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(f'ModImportExportController: Error installing mod from URL: {e}', exc_info=True)
            self.app_window.feedback_service.show_message('error', 'errors.error', tr('mods.installation_error', error=str(e)))

    def _on_unrar_needed(self):
        worker = self.app_state.current_task
        success = self._prompt_for_unrar_install()
        if success:
            logging.info('UnRAR installed successfully from worker request')
        else:
            logging.info('User declined UnRAR installation from worker request')
        if worker and hasattr(worker, 'signal_unrar_installed'):
            worker.signal_unrar_installed(success)

    def _open_manual_install_dialog(self, prepared_path, source_file_path, temp_dir, on_accept=None):
        from ui.dialogs.manual_install_dialog import ManualModInstallDialog
        from services.game_detection_service import get_game_type_string
        initial_game_type = None
        if self.app_state and hasattr(self.app_state, 'game_mode'):
            initial_game_type = get_game_type_string(self.app_state.game_mode)
        dialog = ManualModInstallDialog(self.app_window, prepared_path, gamebanana_metadata=None, source_file_path=source_file_path, initial_game_type=initial_game_type)
        dialog.temp_dir_to_cleanup = temp_dir
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if on_accept:
                on_accept()
            else:
                self._refresh_mod_list()
            QMessageBox.information(self.app_window, tr('dialogs.success'), tr('dialogs.mod_created_successfully'))
            return True
        return False

    def _on_manual_install_required(self, prepared_path: str, archive_path: str, temp_dir: str):
        try:
            self.app_state.reset_install_state()

            def _on_accept():
                from ui.utils.ui_utils import refresh_ui_after_mod_install
                refresh_ui_after_mod_install(self.app_window, self.mod_service)
            self._open_manual_install_dialog(prepared_path, archive_path, temp_dir, on_accept=_on_accept)
        except Exception as e:
            logging.error(f'Failed to open manual install dialog from URL: {e}', exc_info=True)
            self.app_window.feedback_service.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _show_import_error_with_manual_install(self, file_path: str, error_message: str):
        msg_box = QMessageBox(self.app_window)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(tr('errors.error'))
        msg_box.setText(error_message)
        msg_box.setInformativeText(tr('dialogs.manual_install_available'))
        manual_install_btn = msg_box.addButton(tr('ui.manual_install'), QMessageBox.ButtonRole.AcceptRole)
        ok_btn = msg_box.addButton(tr('buttons.ok'), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(ok_btn)
        msg_box.exec()
        if msg_box.clickedButton() == manual_install_btn:
            self._start_manual_install_from_file(file_path)

    def _start_manual_install_from_file(self, file_path: str):
        try:
            prepared_path, temp_dir = self._prepare_local_files_for_manual_install(file_path)
            if prepared_path:
                self._open_manual_install_dialog(prepared_path, file_path, temp_dir)
        except Exception as e:
            logging.error(f'Manual install from file failed: {e}', exc_info=True)
            QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))

    def _prepare_local_files_for_manual_install(self, file_path: str) -> str:
        temp_dir = tempfile.mkdtemp(prefix='deltahub_manual_install_')
        try:
            try:
                extract_archive(file_path, temp_dir)
            except Exception as e:
                if 'UnRAR utility is missing' in str(e):
                    if hasattr(self, '_prompt_for_unrar_install') and self._prompt_for_unrar_install():
                        extract_archive(file_path, temp_dir)
                    else:
                        raise Exception('UnRAR required')
                else:
                    raise e
            content_path = temp_dir
            contents = os.listdir(temp_dir)
            if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                content_path = os.path.join(temp_dir, contents[0])
            return (content_path, temp_dir)
        except Exception as e:
            logging.error(f'Failed to prepare local files: {e}', exc_info=True)
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            raise

    def _on_mod_install_finished(self, success: bool, message: str):
        self.app_state.reset_install_state()
        if success:
            self._refresh_mod_list()
            self.app_window.feedback_service.update_status(message, 'green')
            QMessageBox.information(self.app_window, tr('dialogs.success'), message)
        else:
            logging.warning(f'Mod installation failed: {message}')
            self.app_window.feedback_service.update_status(message or tr('errors.error'), 'red')
            self.app_window.feedback_service.show_message('error', 'errors.error', message)

    def _show_export_dialog(self):
        dialog = QDialog(self.app_window)
        dialog.setWindowTitle(tr('ui.export_mod'))
        dialog.setModal(True)
        dialog.resize(500, 400)
        layout = QVBoxLayout(dialog)
        filter_checkbox = QCheckBox(tr('ui.filter_by_game'))
        filter_checkbox.setChecked(True)
        layout.addWidget(filter_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        list_label = QLabel(tr('ui.select_mod_to_export'))
        layout.addWidget(list_label)
        mod_list = QListWidget()
        layout.addWidget(mod_list)
        current_game = None
        if hasattr(self.app_window, 'game_type_combo'):
            current_game = self.app_window.game_type_combo.currentData()

        def update_mod_list():
            mod_list.clear()
            installed_mods = self.mod_service.get_installed_mods_list()
            for mod_info in installed_mods:
                game = mod_info.get('game') or mod_info.get('modgame', 'deltarune')
                if filter_checkbox.isChecked() and current_game:
                    if game != current_game:
                        continue
                key = mod_info.get('key') or mod_info.get('mod_key')
                if not key:
                    continue
                mod_folder_path = self.mod_service.get_mod_folder_path(key)
                if not mod_folder_path or not os.path.exists(mod_folder_path):
                    continue
                mod_data = None
                if hasattr(self.app_state, 'all_mods'):
                    for mod in self.app_state.all_mods:
                        mod_key_attr = get_mod_key(mod)
                        if mod_key_attr == key:
                            mod_data = mod
                            break
                if not mod_data:
                    mod_data = self.mod_service.create_mod_object_from_info(mod_info, self.app_state.all_mods if hasattr(self.app_state, 'all_mods') else None)
                mod_name = mod_info.get('name', key)
                item = QListWidgetItem(mod_name)
                item.setData(Qt.ItemDataRole.UserRole, mod_data)
                mod_list.addItem(item)
        filter_checkbox.stateChanged.connect(update_mod_list)
        update_mod_list()
        button_layout = QHBoxLayout()
        export_btn = QPushButton(tr('ui.export_mod'))
        export_btn.clicked.connect(lambda: self._export_selected_mod(mod_list, dialog))
        button_layout.addWidget(export_btn)
        cancel_btn = QPushButton(tr('ui.cancel_button'))
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        dialog.exec()

    def _find_mod_dir_by_config(self, mod) -> str | None:
        if not os.path.exists(self.app_state.mods_dir):
            return None
        mod_key_attr = get_mod_key(mod)
        for entry in os.scandir(self.app_state.mods_dir):
            if not entry.is_dir():
                continue
            config_path = os.path.join(entry.path, MOD_CONFIG_FILENAME)
            if not os.path.exists(config_path):
                old_config_path = os.path.join(entry.path, LEGACY_MOD_CONFIG_FILENAME)
                if os.path.exists(old_config_path):
                    try:
                        shutil.move(old_config_path, config_path)
                    except Exception as e:
                        logging.warning(f'Error migrating config in {entry.path}: {e}')
                        continue
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                config_key = config.get('key') or config.get('mod_key')
                if config_key == mod_key_attr:
                    return entry.path
                if not config_key and config.get('name', '') == mod.name:
                    return entry.path
            except Exception as e:
                logging.warning(f'Error reading config {config_path}: {e}')
        return None

    def _export_selected_mod(self, mod_list, dialog):
        current_item = mod_list.currentItem()
        if not current_item:
            QMessageBox.warning(self.app_window, tr('errors.error'), tr('ui.no_mod_selected'))
            return
        mod = current_item.data(Qt.ItemDataRole.UserRole)
        if not mod:
            return
        export_path, _ = QFileDialog.getSaveFileName(self.app_window, tr('ui.select_export_location'), f'{mod.name}.zip', 'ZIP Archives (*.zip);;All Files (*)')
        if not export_path:
            return
        try:
            self.mod_service.invalidate_mods_cache()
            key = get_mod_key(mod)
            mod_dir = self.mod_service.get_mod_folder_path(key)
            if not mod_dir or not os.path.exists(mod_dir):
                mod_dir = self._find_mod_dir_by_config(mod)
            if not mod_dir or not os.path.exists(mod_dir):
                logging.error(f'Mod folder not found for mod: {mod.name}')
                mod_key_attr = get_mod_key(mod)
                QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_folder_not_found_simple', path=mod_dir or mod_key_attr))
                return
            game = getattr(mod, 'game', None) or getattr(mod, 'modgame', None)
            if not game:
                config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                            game = config.get('game') or config.get('modgame')
                    except Exception:
                        pass
            with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(mod_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, mod_dir)
                        zipf.write(file_path, arcname)
            QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_exported_success'))
            dialog.accept()
        except Exception as e:
            logging.error(f'Mod export failed: {e}', exc_info=True)
            QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_export_failed', error=str(e)))
