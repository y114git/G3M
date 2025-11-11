import os
import json
import shutil
import tempfile
import logging
import zipfile
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QListWidget, QListWidgetItem, QCheckBox
from PyQt6.QtCore import Qt
from managers.localization_manager import tr
from utils.file_utils import extract_archive
from utils.deltamod_converter import DeltamodConverter


class ModImportExportController:

    def __init__(self, app_state, mod_manager, app_window):
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.app_window = app_window

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
        dialog = ImportDialog(self.app_window, self.app_window.feedback_manager, 'mods')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.import_method == 'file' and dialog.selected_file:
                self._install_mod_from_file(dialog.selected_file)
            elif dialog.import_method == 'url' and dialog.selected_url:
                self._install_mod_from_url(dialog.selected_url)

    def _install_mod_from_file(self, file_path: str):
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub_import_') as temp_dir:
                extract_archive(file_path, temp_dir)
                content_path = temp_dir
                contents = os.listdir(temp_dir)
                if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                    content_path = os.path.join(temp_dir, contents[0])
                if os.path.exists(os.path.join(content_path, '_deltamodInfo.json')):
                    converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        self.mod_manager.invalidate_mods_cache()
                        self.mod_manager.load_local_mods(_skip_conversion=True)
                        self.mod_manager.mod_list_updated.emit()
                        QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                    else:
                        QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_import_failed', error='Conversion failed'))
                    return
                mod_config_path = os.path.join(content_path, 'mod_config.json')
                old_config_path = os.path.join(content_path, 'config.json')
                config_path_to_read = mod_config_path if os.path.exists(mod_config_path) else old_config_path
                if os.path.exists(config_path_to_read):
                    with open(config_path_to_read, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    mod_key = config.get('mod_key')
                    if not mod_key:
                        QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.invalid_mod_format'))
                        return
                    from utils.file_utils import remove_archive_extension, sanitize_filename
                    archive_name = remove_archive_extension(os.path.basename(file_path))
                    folder_name = sanitize_filename(archive_name)
                    target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name)
                    counter = 1
                    while os.path.exists(target_mod_dir):
                        folder_name_with_counter = f'{folder_name}_{counter}'
                        target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name_with_counter)
                        counter += 1
                    shutil.copytree(content_path, target_mod_dir)
                    target_old_config_path = os.path.join(target_mod_dir, 'config.json')
                    target_config_path = os.path.join(target_mod_dir, 'mod_config.json')
                    if os.path.exists(target_old_config_path) and (not os.path.exists(target_config_path)):
                        try:
                            shutil.move(target_old_config_path, target_config_path)
                            logging.info(f'Migrated mod config.json to mod_config.json during import in {folder_name}')
                        except Exception as e:
                            logging.warning(f'Failed to migrate mod config.json to mod_config.json during import in {folder_name}: {e}')
                    config_path = target_config_path
                    config_updated = False
                    if 'files' in config:
                        for chapter_key, chapter_data in config['files'].items():
                            if chapter_key == 'demo':
                                chapter_folder = os.path.join(target_mod_dir, 'demo')
                            elif chapter_key == 'undertale':
                                chapter_folder = os.path.join(target_mod_dir, 'undertale')
                            elif chapter_key in ['0', '1', '2', '3', '4']:
                                if chapter_key == '0':
                                    chapter_folder = os.path.join(target_mod_dir, 'chapter_0')
                                else:
                                    chapter_folder = os.path.join(target_mod_dir, f'chapter_{chapter_key}')
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
                    if config_updated:
                        with open(config_path, 'w', encoding='utf-8') as f:
                            json.dump(config, f, indent=2, ensure_ascii=False)
                    self.mod_manager.invalidate_mods_cache()
                    self.mod_manager.load_local_mods(_skip_conversion=True)
                    self.mod_manager.mod_list_updated.emit()
                    QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                else:
                    QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.invalid_mod_format'))
        except Exception as e:
            logging.error(f'Mod import failed: {e}', exc_info=True)
            QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_import_failed', error=str(e)))

    def _install_mod_from_url(self, url: str):
        try:
            from workers.mod_install_worker import ModInstallWorker
            worker = ModInstallWorker(url, self.app_state.mods_dir, self.mod_manager, self.app_window)
            worker.status.connect(lambda msg, color: self.app_window.feedback_manager.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))
            worker.finished.connect(self._on_mod_install_finished)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        except Exception as e:
            logging.error(f'ModImportExportController: Error installing mod from URL: {e}', exc_info=True)
            self.app_window.feedback_manager.show_message('error', 'errors.error', tr('mods.installation_error', error=str(e)))

    def _on_mod_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.app_state.progress_bar_visible = False
        self.app_state.progress_bar_value = 0
        self.app_state.clear_current_task()
        if success:
            self.mod_manager.invalidate_mods_cache()
            self.mod_manager.load_local_mods(_skip_conversion=True)
            self.mod_manager.mod_list_updated.emit()
            self.app_window.feedback_manager.update_status(message, 'green')
            QMessageBox.information(self.app_window, tr('dialogs.success'), message)
        else:
            logging.warning(f'Mod installation failed: {message}')
            self.app_window.feedback_manager.update_status(message or tr('errors.error'), 'red')
            self.app_window.feedback_manager.show_message('error', 'errors.error', message)

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
            all_mods = self.app_state.all_mods
            for mod in all_mods:
                if filter_checkbox.isChecked() and current_game:
                    if mod.modgame != current_game:
                        continue
                mod_folder_path = self.mod_manager.get_mod_folder_path(mod.key)
                if not mod_folder_path or not os.path.exists(mod_folder_path):
                    continue
                item = QListWidgetItem(mod.name)
                item.setData(Qt.ItemDataRole.UserRole, mod)
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
            self.mod_manager.invalidate_mods_cache()
            mod_dir = self.mod_manager.get_mod_folder_path(mod.key)
            if not mod_dir or not os.path.exists(mod_dir):
                mod_dir = None
                if os.path.exists(self.app_state.mods_dir):
                    for entry in os.scandir(self.app_state.mods_dir):
                        if not entry.is_dir():
                            continue
                        config_path = os.path.join(entry.path, 'mod_config.json')
                        old_config_path = os.path.join(entry.path, 'config.json')
                        if os.path.exists(config_path):
                            try:
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = json.load(f)
                                config_mod_key = config.get('mod_key')
                                config_mod_name = config.get('name', '')
                                if config_mod_key:
                                    if config_mod_key == mod.key:
                                        mod_dir = entry.path
                                        break
                                    elif config_mod_name == mod.name:
                                        mod_dir = entry.path
                                        break
                            except Exception as e:
                                logging.warning(f'Error reading config {config_path}: {e}')
                                continue
                        elif os.path.exists(old_config_path):
                            try:
                                import shutil
                                shutil.move(old_config_path, config_path)
                                logging.info(f'Migrated mod config.json to mod_config.json during export in {entry.name}')
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = json.load(f)
                                config_mod_key = config.get('mod_key')
                                config_mod_name = config.get('name', '')
                                if config_mod_key:
                                    if config_mod_key == mod.key:
                                        mod_dir = entry.path
                                        break
                                    elif config_mod_name == mod.name:
                                        mod_dir = entry.path
                                        break
                            except Exception as e:
                                logging.warning(f'Error migrating or reading config in {entry.path}: {e}')
                                continue
                else:
                    logging.error(f'Mods directory does not exist: {self.app_state.mods_dir}')
            if not mod_dir or not os.path.exists(mod_dir):
                logging.error(f'Mod folder not found for mod: {mod.name}')
                QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_folder_not_found_simple', path=mod_dir or mod.key))
                return
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
