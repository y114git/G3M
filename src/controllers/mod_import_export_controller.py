import os
import json
import shutil
import tempfile
import logging
import zipfile
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QListWidget, QListWidgetItem, QCheckBox
from PyQt6.QtCore import Qt
from managers.localization_manager import tr
from utils.archive_utils import extract_archive
from utils.file_utils import find_deltamod_info_file
from utils.deltamod_converter import DeltamodConverter
from utils.pizzaoven_converter import PizzaOvenConverter
from utils.pizzaoven_utils import find_pizzaoven_folder, is_pizzaoven_mod
from config.constants import MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME


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
        logging.info(f'[IMPORT] Starting mod import from file: {file_path}')
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub_import_') as temp_dir:
                logging.info(f'[IMPORT] Extracting archive to temporary directory: {temp_dir}')
                extract_archive(file_path, temp_dir)
                content_path = temp_dir
                contents = os.listdir(temp_dir)
                if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                    content_path = os.path.join(temp_dir, contents[0])
                    logging.info(f'[IMPORT] Archive contains single directory, using: {content_path}')
                pizzaoven_path = find_pizzaoven_folder(content_path)
                if pizzaoven_path:
                    logging.info(f'[IMPORT] PizzaOven format detected at: {pizzaoven_path}, converting...')
                    try:
                        from utils.file_utils import remove_archive_extension
                        archive_name = remove_archive_extension(os.path.basename(file_path))
                        if os.path.commonpath([content_path, pizzaoven_path]) == content_path:
                            converter = PizzaOvenConverter(content_path, self.app_state.mods_dir, archive_name=archive_name)
                        else:
                            converter = PizzaOvenConverter(pizzaoven_path, self.app_state.mods_dir, archive_name=archive_name)
                        new_mod_path = converter.convert()
                        if new_mod_path:
                            logging.info(f'[IMPORT] PizzaOven mod converted successfully to: {new_mod_path}')
                            self.mod_manager.invalidate_mods_cache()
                            self.mod_manager.load_local_mods(_skip_conversion=True)
                            self.mod_manager.mod_list_updated.emit()
                            QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                        else:
                            logging.error('[IMPORT] PizzaOven conversion failed')
                            QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_import_failed', error='Conversion failed'))
                    except Exception as e:
                        logging.error(f'[IMPORT] PizzaOven conversion error: {e}', exc_info=True)
                        QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_import_failed', error=str(e)))
                    return
                if find_deltamod_info_file(content_path):
                    logging.info('[IMPORT] DELTAMOD format detected, converting...')
                    converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                    new_mod_path = converter.convert()
                    if new_mod_path:
                        logging.info(f'[IMPORT] DELTAMOD converted successfully to: {new_mod_path}')
                        self.mod_manager.invalidate_mods_cache()
                        self.mod_manager.load_local_mods(_skip_conversion=True)
                        self.mod_manager.mod_list_updated.emit()
                        QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                    else:
                        logging.error('[IMPORT] DELTAMOD conversion failed')
                        QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.mod_import_failed', error='Conversion failed'))
                    return
                config_path_to_read = os.path.join(content_path, MOD_CONFIG_FILENAME)
                if not os.path.exists(config_path_to_read):
                    legacy_config_path = os.path.join(content_path, LEGACY_MOD_CONFIG_FILENAME)
                    if os.path.exists(legacy_config_path):
                        config_path_to_read = legacy_config_path
                        logging.info('[IMPORT] Found legacy config.json, will migrate to mod_config.json')
                logging.info(f'[IMPORT] Looking for mod config at: {config_path_to_read}')
                if os.path.exists(config_path_to_read):
                    logging.info('[IMPORT] Found mod config, reading...')
                    with open(config_path_to_read, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    key = config.get('key') or config.get('mod_key')
                    mod_name = config.get('name', 'Unknown')
                    logging.info(f'[IMPORT] Mod name: {mod_name}, key: {key}')
                    if not key:
                        from utils.file_utils import sanitize_filename, save_json
                        key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                        config['key'] = key
                        if 'mod_key' in config:
                            del config['mod_key']
                        config['is_local_mod'] = True
                        save_json(config_path_to_read, config, indent=2)
                        mod_key_generated = True
                        logging.info(f'[IMPORT] Generated key: {key}')
                    from utils.file_utils import remove_archive_extension
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
                    if config_updated or mod_key_generated:
                        from utils.file_utils import save_json
                        save_json(config_path, config, indent=2)
                    logging.info(f'[IMPORT] Mod installed successfully to: {target_mod_dir}')
                    self.mod_manager.invalidate_mods_cache()
                    self.mod_manager.load_local_mods(_skip_conversion=True)
                    self.mod_manager.mod_list_updated.emit()
                    logging.info('[IMPORT] Mod cache invalidated and mod list reloaded')
                    QMessageBox.information(self.app_window, tr('dialogs.success'), tr('status.mod_imported_success'))
                else:
                    logging.error(f'[IMPORT] Mod config not found at: {config_path_to_read}')
                    QMessageBox.critical(self.app_window, tr('errors.error'), tr('errors.invalid_mod_format'))
        except Exception as e:
            logging.error(f'[IMPORT] Mod import failed: {e}', exc_info=True)
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
            installed_mods = self.mod_manager.get_installed_mods_list()
            for mod_info in installed_mods:
                game = mod_info.get('game') or mod_info.get('modgame', 'deltarune')
                if filter_checkbox.isChecked() and current_game:
                    if game != current_game:
                        continue
                key = mod_info.get('key') or mod_info.get('mod_key')
                if not key:
                    continue
                mod_folder_path = self.mod_manager.get_mod_folder_path(key)
                if not mod_folder_path or not os.path.exists(mod_folder_path):
                    continue
                mod_data = None
                if hasattr(self.app_state, 'all_mods'):
                    for mod in self.app_state.all_mods:
                        mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                        if mod_key_attr == key:
                            mod_data = mod
                            break
                if not mod_data:
                    mod_data = self.mod_manager.create_mod_object_from_info(mod_info, self.app_state.all_mods if hasattr(self.app_state, 'all_mods') else None)
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
            key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
            mod_dir = self.mod_manager.get_mod_folder_path(key)
            if not mod_dir or not os.path.exists(mod_dir):
                mod_dir = None
                if os.path.exists(self.app_state.mods_dir):
                    for entry in os.scandir(self.app_state.mods_dir):
                        if not entry.is_dir():
                            continue
                        config_path = os.path.join(entry.path, MOD_CONFIG_FILENAME)
                        if os.path.exists(config_path):
                            try:
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = json.load(f)
                                config_key = config.get('key') or config.get('mod_key')
                                config_mod_name = config.get('name', '')
                                if config_key:
                                    mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                                    if config_key == mod_key_attr:
                                        mod_dir = entry.path
                                        break
                                elif config_mod_name == mod.name:
                                    mod_dir = entry.path
                                    break
                            except Exception as e:
                                logging.warning(f'Error reading config {config_path}: {e}')
                                continue
                        else:
                            old_config_path = os.path.join(entry.path, LEGACY_MOD_CONFIG_FILENAME)
                            if os.path.exists(old_config_path):
                                try:
                                    import shutil
                                    shutil.move(old_config_path, config_path)
                                    logging.info(f'Migrated mod config.json to mod_config.json during export in {entry.name}')
                                    with open(config_path, 'r', encoding='utf-8') as f:
                                        config = json.load(f)
                                    config_key = config.get('key') or config.get('mod_key')
                                    config_mod_name = config.get('name', '')
                                    if config_key:
                                        mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                                        if config_key == mod_key_attr:
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
                mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
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
                if game == 'pizzaoven' or is_pizzaoven_mod(mod):
                    config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
                    if os.path.exists(config_path):
                        zipf.write(config_path, MOD_CONFIG_FILENAME)
                    pizzaoven_path = find_pizzaoven_folder(mod_dir)
                    if pizzaoven_path and os.path.isdir(pizzaoven_path):
                        for root, dirs, files in os.walk(pizzaoven_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.join('pizzaoven', os.path.relpath(file_path, pizzaoven_path))
                                zipf.write(file_path, arcname)
                    icon_path = os.path.join(mod_dir, '_icon.png')
                    if os.path.exists(icon_path):
                        zipf.write(icon_path, '_icon.png')
                else:
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
