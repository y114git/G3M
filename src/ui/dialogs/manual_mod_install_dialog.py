import os
import json
import shutil
import logging
import tempfile
import zipfile
from typing import Dict, List, Optional
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QWidget, QTableWidget, QTableWidgetItem, QCheckBox, QLineEdit, QComboBox, QDialogButtonBox, QScrollArea, QListWidget, QListWidgetItem
from managers.localization_manager import tr
from config.constants import DATA_FILE_EXTENSIONS, MOD_CONFIG_FILENAME
from utils.file_utils import get_chapter_folder_name, get_unique_mod_dir, sanitize_filename, save_json


class ManualModInstallDialog(QDialog):

    def __init__(self, parent, prepared_files_path: str, gamebanana_metadata: Optional[Dict] = None, source_file_path: Optional[str] = None, initial_game_type: Optional[str] = None):
        super().__init__(parent)
        self.prepared_files_path = prepared_files_path
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.source_file_path = source_file_path
        self.app_state = parent.app_state if hasattr(parent, 'app_state') else None
        self.mod_manager = parent.mod_manager if hasattr(parent, 'mod_manager') else None
        self.temp_dir_to_cleanup = None
        self.initial_game_type = initial_game_type
        self.data_file_selections = {}
        self.extra_files_mappings = {}
        self.all_files = []
        self.extra_file_widgets = {}
        self.unused_files = set()
        self.setWindowTitle(tr('dialogs.manual_install_title'))
        self.setModal(True)
        self.resize(900, 700)
        self.setMinimumSize(800, 600)
        self._scan_files()
        self.init_ui()

    def closeEvent(self, event):
        if self.temp_dir_to_cleanup and os.path.exists(self.temp_dir_to_cleanup):
            try:
                import shutil
                shutil.rmtree(self.temp_dir_to_cleanup, ignore_errors=True)
            except Exception as e:
                logging.warning(f'Failed to cleanup temp directory: {e}')
        super().closeEvent(event)

    def _scan_files(self):
        self.all_files = []
        if not os.path.exists(self.prepared_files_path):
            return
        for root, dirs, files in os.walk(self.prepared_files_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.prepared_files_path)
                self.all_files.append((file_path, rel_path))

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        game_layout = QHBoxLayout()
        game_layout.addStretch()
        game_layout.addWidget(QLabel(tr('ui.mod_type_label')))
        self.game_combo = QComboBox()
        self.game_combo.addItem('DELTARUNE', 'deltarune')
        self.game_combo.addItem('DELTARUNE DEMO', 'deltarunedemo')
        self.game_combo.addItem('UNDERTALE', 'undertale')
        self.game_combo.addItem('UNDERTALE Yellow', 'undertaleyellow')
        self.game_combo.addItem('Pizza Tower', 'pizzatower')
        self.game_combo.addItem('Sugary Spire', 'sugaryspire')
        game_value = None
        if self.initial_game_type:
            game_value = self.initial_game_type
        elif self.gamebanana_metadata.get('game'):
            game_value = self.gamebanana_metadata['game']
        elif self.app_state and hasattr(self.app_state, 'game_mode'):
            from utils.game_utils import get_game_type_string
            game_value = get_game_type_string(self.app_state.game_mode)
        if game_value:
            for i in range(self.game_combo.count()):
                if self.game_combo.itemData(i) == game_value:
                    self.game_combo.setCurrentIndex(i)
                    break
        self.game_combo.currentIndexChanged.connect(self._update_file_tabs)
        game_layout.addWidget(self.game_combo)
        game_layout.addStretch()
        main_layout.addLayout(game_layout)
        main_layout.addSpacing(20)
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet('QTabWidget::tab-bar { alignment: center; }')
        self._create_data_tab()
        self._create_extra_files_tab()
        main_layout.addWidget(self.tab_widget)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText(tr('dialogs.finish_creating_mod'))
        button_box.accepted.connect(self._on_finish)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _create_data_tab(self):
        data_widget = QWidget()
        data_layout = QVBoxLayout(data_widget)
        data_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label = QLabel(tr('dialogs.data_tab_info'))
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_layout.addWidget(info_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        self.data_tabs = QTabWidget()
        self.data_tabs.setStyleSheet('QTabWidget::tab-bar { alignment: center; }')
        self.data_tabs.currentChanged.connect(self._on_data_tab_changed)
        scroll_layout.addWidget(self.data_tabs)
        scroll.setWidget(scroll_content)
        data_layout.addWidget(scroll)
        self.tab_widget.addTab(data_widget, tr('dialogs.data_tab'))
        self._update_file_tabs()

    def _create_extra_files_tab(self):
        extra_widget = QWidget()
        extra_layout = QVBoxLayout(extra_widget)
        extra_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        instructions_text = tr('dialogs.extra_files_path_instructions')
        instructions_label = QLabel(instructions_text)
        instructions_label.setWordWrap(True)
        instructions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instructions_label.setStyleSheet('font-size: 11px; color: #888; padding: 10px;')
        extra_layout.addWidget(instructions_label)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setMaximumHeight(400)
        scroll_area.setMinimumHeight(200)
        scroll_content = QWidget()
        self.extra_files_list_layout = QVBoxLayout(scroll_content)
        self.extra_files_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.extra_files_list_layout.setSpacing(10)
        scroll_area.setWidget(scroll_content)
        extra_layout.addWidget(scroll_area, 1)
        self.tab_widget.addTab(extra_widget, tr('dialogs.extra_files_tab'))
        self._populate_extra_files_list()

    def _update_file_tabs(self):
        self.data_tabs.clear()
        game = self.game_combo.currentData()
        if game == 'deltarune':
            chapters = [(0, tr('tabs.menu_root')), (1, tr('tabs.chapter_1')), (2, tr('tabs.chapter_2')), (3, tr('tabs.chapter_3')), (4, tr('tabs.chapter_4'))]
            for chapter_id, chapter_name in chapters:
                chapter_widget = self._create_chapter_data_widget(chapter_id)
                self.data_tabs.addTab(chapter_widget, chapter_name)
        else:
            single_widget = self._create_chapter_data_widget(0)
            self.data_tabs.addTab(single_widget, tr('dialogs.data_file'))

    def _create_chapter_data_widget(self, chapter_id: int) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        game = self.game_combo.currentData()
        if game == 'deltarune':
            info_text = tr('dialogs.select_data_file_info', chapter=chapter_id)
        elif game == 'deltarunedemo':
            info_text = tr('dialogs.select_data_file_info_demo')
        elif game == 'undertale':
            info_text = tr('dialogs.select_data_file_info_undertale')
        elif game == 'undertaleyellow':
            info_text = tr('dialogs.select_data_file_info_undertaleyellow')
        elif game == 'pizzatower':
            info_text = tr('dialogs.select_data_file_info_pizzatower')
        elif game == 'sugaryspire':
            info_text = tr('dialogs.select_data_file_info_sugaryspire')
        else:
            info_text = tr('dialogs.select_data_file_info', chapter=chapter_id)
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)
        file_path_layout = QHBoxLayout()
        self.data_file_edits = getattr(self, 'data_file_edits', {})
        file_edit = QLineEdit()
        file_edit.setReadOnly(True)
        file_edit.setPlaceholderText(tr('dialogs.no_file_selected'))
        if chapter_id in self.data_file_selections:
            file_edit.setText(self.data_file_selections[chapter_id])
        self.data_file_edits[chapter_id] = file_edit
        file_path_layout.addWidget(file_edit)
        browse_btn = QPushButton(tr('ui.browse_button'))
        browse_btn.clicked.connect(lambda checked, cid=chapter_id: self._browse_data_file(cid))
        file_path_layout.addWidget(browse_btn)
        clear_btn = QPushButton(tr('ui.clear_button'))
        clear_btn.clicked.connect(lambda checked, cid=chapter_id: self._clear_data_file(cid))
        file_path_layout.addWidget(clear_btn)
        layout.addLayout(file_path_layout)
        layout.addStretch()
        return widget

    def _browse_data_file(self, chapter_id: int):
        extensions = list(DATA_FILE_EXTENSIONS) + ['.data', '.ios', '.droid', '.unx']
        selected_data_files = set(self.data_file_selections.values())
        found_files = []
        for file_path, rel_path in self.all_files:
            if file_path in selected_data_files:
                continue
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext in extensions:
                found_files.append((file_path, rel_path))
        if not found_files:
            QMessageBox.information(self, tr('dialogs.no_data_files'), tr('dialogs.no_data_files_in_directory'))
            return
        from PyQt6.QtWidgets import QListWidget
        file_dialog = QDialog(self)
        file_dialog.setWindowTitle(tr('dialogs.select_data_file', file_type='DATA'))
        file_dialog.resize(600, 400)
        layout = QVBoxLayout(file_dialog)
        label = QLabel(tr('dialogs.select_data_file_info', chapter=chapter_id))
        layout.addWidget(label)
        list_widget = QListWidget()
        for file_path, rel_path in found_files:
            item_text = f'{os.path.basename(file_path)} ({rel_path})'
            list_widget.addItem(item_text)
            list_widget.item(list_widget.count() - 1).setData(Qt.ItemDataRole.UserRole, file_path)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(file_dialog.accept)
        button_box.rejected.connect(file_dialog.reject)
        layout.addWidget(button_box)
        if file_dialog.exec() == QDialog.DialogCode.Accepted:
            current_item = list_widget.currentItem()
            if current_item:
                file_path = current_item.data(Qt.ItemDataRole.UserRole)
                self.data_file_selections[chapter_id] = file_path
                if chapter_id in self.data_file_edits:
                    self.data_file_edits[chapter_id].setText(os.path.basename(file_path))
                self._update_data_file_visibility()
                self._populate_extra_files_list()

    def _clear_data_file(self, chapter_id: int):
        if chapter_id in self.data_file_selections:
            del self.data_file_selections[chapter_id]
        if chapter_id in self.data_file_edits:
            self.data_file_edits[chapter_id].clear()
        self._update_data_file_visibility()
        self._populate_extra_files_list()

    def _update_data_file_visibility(self):
        pass

    def _on_data_tab_changed(self, index: int):
        pass

    def _populate_extra_files_list(self):
        if hasattr(self, 'extra_files_list_layout'):
            while self.extra_files_list_layout.count():
                item = self.extra_files_list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        selected_data_files = set(self.data_file_selections.values())
        extra_files = [(fp, rp) for fp, rp in self.all_files if fp not in selected_data_files]
        if not extra_files:
            no_files_label = QLabel(tr('dialogs.no_data_files'))
            no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.extra_files_list_layout.addWidget(no_files_label)
            return
        if not hasattr(self, 'extra_file_widgets'):
            self.extra_file_widgets = {}
        else:
            self.extra_file_widgets.clear()
        for file_path, rel_path in extra_files:
            file_widget = self._create_extra_file_widget(file_path, rel_path)
            self.extra_files_list_layout.addWidget(file_widget)
            self.extra_file_widgets[file_path] = file_widget
        self.extra_files_list_layout.addStretch()

    def _create_extra_file_widget(self, file_path: str, rel_path: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        file_name_label = QLabel(os.path.basename(file_path))
        file_name_label.setToolTip(rel_path)
        file_name_label.setMinimumWidth(150)
        file_name_label.setMaximumWidth(200)
        layout.addWidget(file_name_label)
        auto_path = ''
        if rel_path and os.path.dirname(rel_path):
            dir_part = os.path.dirname(rel_path)
            auto_path = dir_part.replace('\\', '/').strip('/')
            if auto_path:
                auto_path += '/'
        path_input = QLineEdit()
        path_input.setObjectName('path_input')
        path_input.setMinimumWidth(300)
        path_input.setMaximumWidth(300)
        if file_path in self.extra_files_mappings:
            path_input.setText(self.extra_files_mappings[file_path])
        elif auto_path:
            path_input.setText(auto_path)
            self.extra_files_mappings[file_path] = auto_path
        path_input.setPlaceholderText(tr('dialogs.enter_relative_path'))
        path_input.textChanged.connect(lambda text, fp=file_path: self._on_path_changed(fp, text))
        if file_path in self.unused_files:
            path_input.setEnabled(False)
        layout.addWidget(path_input)
        browse_btn = QPushButton(tr('ui.browse_button'))
        browse_btn.setMaximumWidth(80)
        browse_btn.clicked.connect(lambda checked, fp=file_path: self._browse_target_folder(fp))
        if file_path in self.unused_files:
            browse_btn.setEnabled(False)
        layout.addWidget(browse_btn)
        toggle_btn = QPushButton()
        toggle_btn.setMaximumWidth(70)
        toggle_btn.setObjectName(f'toggle_btn_{file_path}')
        if file_path in self.unused_files:
            toggle_btn.setText(tr('ui.use_button'))
        else:
            toggle_btn.setText(tr('ui.remove_button'))
        toggle_btn.clicked.connect(lambda checked, fp=file_path: self._toggle_file_usage(fp))
        layout.addWidget(toggle_btn)
        return widget

    def _on_path_changed(self, file_path: str, text: str):
        normalized = self._normalize_relative_path(text)
        if normalized != text:
            if file_path in self.extra_file_widgets:
                widget = self.extra_file_widgets[file_path]
                path_input = widget.findChild(QLineEdit, 'path_input')
                if path_input:
                    path_input.setText(normalized)
        if normalized:
            self.extra_files_mappings[file_path] = normalized
        elif file_path in self.extra_files_mappings:
            del self.extra_files_mappings[file_path]

    def _normalize_relative_path(self, path: str) -> str:
        if not path:
            return ''
        path = path.strip()
        has_trailing_slash = path.endswith('/') or path.endswith('\\')
        path = path.strip('/').strip('\\')
        path = path.replace('\\', '/')
        parts = path.split('/')
        valid_parts = []
        for part in parts:
            if part and part != '..' and (not os.path.isabs(part)):
                valid_parts.append(part)
        result = '/'.join(valid_parts)
        if result:
            result += '/'
        return result

    def _browse_target_folder(self, file_path: str):
        game_root = self._get_or_prompt_game_folder()
        if not game_root:
            return
        folder = QFileDialog.getExistingDirectory(self, tr('dialogs.select_target_folder'), game_root)
        if folder:
            game_root_normalized = os.path.normpath(os.path.abspath(game_root))
            folder_normalized = os.path.normpath(os.path.abspath(folder))
            if folder_normalized.startswith(game_root_normalized):
                rel_folder = os.path.relpath(folder, game_root)
                rel_folder = rel_folder.replace('\\', '/').strip('/')
                if rel_folder:
                    rel_folder += '/'
                if file_path in self.extra_file_widgets:
                    widget = self.extra_file_widgets[file_path]
                    path_input = widget.findChild(QLineEdit, 'path_input')
                    if path_input:
                        path_input.setText(rel_folder)
                        self.extra_files_mappings[file_path] = rel_folder
            else:
                QMessageBox.warning(self, tr('errors.error'), tr('dialogs.path_outside_game_folder'))

    def _get_or_prompt_game_folder(self) -> Optional[str]:
        game_root = None
        if self.app_state and hasattr(self.app_state, 'game_mode'):
            try:
                game_root = self.app_state.game_mode.get_game_path(self.app_state.local_config)
            except Exception:
                pass
        if not game_root or not os.path.exists(game_root):
            settings_manager = None
            if hasattr(self.parent(), 'settings_manager'):
                settings_manager = self.parent().settings_manager
            elif self.app_state and hasattr(self.app_state, 'settings_manager'):
                settings_manager = self.app_state.settings_manager
            if settings_manager:
                if settings_manager.prompt_for_game_path(is_initial=False):
                    try:
                        game_root = self.app_state.game_mode.get_game_path(self.app_state.local_config)
                    except Exception:
                        pass
        return game_root if game_root and os.path.exists(game_root) else None

    def _toggle_file_usage(self, file_path: str):
        if file_path in self.unused_files:
            self.unused_files.remove(file_path)
        else:
            self.unused_files.add(file_path)
            if file_path in self.extra_files_mappings:
                del self.extra_files_mappings[file_path]
        if file_path in self.extra_file_widgets:
            widget = self.extra_file_widgets[file_path]
            toggle_btn = widget.findChild(QPushButton, f'toggle_btn_{file_path}')
            if toggle_btn:
                if file_path in self.unused_files:
                    toggle_btn.setText(tr('ui.use_button'))
                else:
                    toggle_btn.setText(tr('ui.remove_button'))
            path_input = widget.findChild(QLineEdit, 'path_input')
            if path_input:
                if file_path in self.unused_files:
                    path_input.setEnabled(False)
                    path_input.clear()
                else:
                    path_input.setEnabled(True)
            browse_btn = None
            for child in widget.findChildren(QPushButton):
                if child.objectName() != f'toggle_btn_{file_path}' and child.text() == tr('ui.browse_button'):
                    browse_btn = child
                    break
            if browse_btn:
                browse_btn.setEnabled(file_path not in self.unused_files)

    def _on_finish(self):
        if not self.data_file_selections:
            QMessageBox.warning(self, tr('errors.error'), tr('dialogs.no_data_file_selected'))
            return
        try:
            self._create_mod_from_files()
            self.accept()
        except Exception as e:
            logging.error(f'Failed to create mod: {e}', exc_info=True)
            QMessageBox.critical(self, tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))

    def _create_mod_from_files(self):
        if not self.app_state or not self.mod_manager:
            raise ValueError('app_state or mod_manager not available')
        if self.gamebanana_metadata.get('mod_id'):
            mod_key = f"gb_{self.gamebanana_metadata['mod_id']}"
            is_local_mod = False
        else:
            import time
            mod_key = f'local_manual_{int(time.time())}'
            is_local_mod = True
        if self.gamebanana_metadata.get('name'):
            mod_name = self.gamebanana_metadata['name']
        elif self.source_file_path:
            from utils.file_utils import remove_archive_extension
            archive_name = os.path.basename(self.source_file_path)
            mod_name = remove_archive_extension(archive_name)
        else:
            mod_name = 'Manual Mod'
        folder_name = get_unique_mod_dir(self.app_state.mods_dir, mod_name)
        target_mod_dir = os.path.join(self.app_state.mods_dir, folder_name)
        os.makedirs(target_mod_dir, exist_ok=True)
        files_structure = {}
        game = self.game_combo.currentData()
        for chapter_id, data_file_path in self.data_file_selections.items():
            if game == 'deltarune':
                if chapter_id == 0:
                    chapter_key = '0'
                elif chapter_id > 0:
                    chapter_key = str(chapter_id)
                else:
                    continue
            elif game == 'deltarunedemo':
                chapter_key = 'demo'
            elif game == 'undertale':
                chapter_key = 'undertale'
            elif game == 'undertaleyellow':
                chapter_key = 'undertaleyellow'
            elif game == 'pizzatower':
                chapter_key = 'pizzatower'
            elif game == 'sugaryspire':
                chapter_key = 'sugaryspire'
            else:
                chapter_key = '0'
            if chapter_key not in files_structure:
                files_structure[chapter_key] = {}
            if game == 'deltarune':
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
            else:
                chapter_folder_name = chapter_key
            chapter_folder = os.path.join(target_mod_dir, chapter_folder_name)
            os.makedirs(chapter_folder, exist_ok=True)
            data_file_name = os.path.basename(data_file_path)
            target_data_path = os.path.join(chapter_folder, data_file_name)
            shutil.copy2(data_file_path, target_data_path)
            files_structure[chapter_key]['data_file_url'] = data_file_name
            pass
        for extra_file_path, relative_path in self.extra_files_mappings.items():
            if extra_file_path in self.unused_files:
                continue
            is_data_file = False
            for ch_id, data_path in self.data_file_selections.items():
                if extra_file_path == data_path:
                    is_data_file = True
                    break
            if is_data_file:
                continue
            relative_path = relative_path.strip().strip('/').strip('\\') if relative_path else ''
            target_chapter_id = 0
            if game == 'deltarune' and self.data_file_selections:
                target_chapter_id = min(self.data_file_selections.keys())
            if game == 'deltarune':
                if target_chapter_id == 0:
                    chapter_key = '0'
                elif target_chapter_id > 0:
                    chapter_key = str(target_chapter_id)
                else:
                    chapter_key = '0'
            elif game == 'deltarunedemo':
                chapter_key = 'demo'
            elif game == 'undertale':
                chapter_key = 'undertale'
            elif game == 'undertaleyellow':
                chapter_key = 'undertaleyellow'
            elif game == 'pizzatower':
                chapter_key = 'pizzatower'
            elif game == 'sugaryspire':
                chapter_key = 'sugaryspire'
            else:
                chapter_key = '0'
            if chapter_key not in files_structure:
                continue
            if game == 'deltarune':
                chapter_folder_name = get_chapter_folder_name(target_chapter_id, game=game)
            else:
                chapter_folder_name = chapter_key
            chapter_folder = os.path.join(target_mod_dir, chapter_folder_name)
            extra_file_name = os.path.basename(extra_file_path)
            clean_path = relative_path.rstrip('/') if relative_path else ''
            if clean_path:
                archive_key = clean_path.replace('/', '_').replace('\\', '_').strip('_')
                if not archive_key:
                    archive_key = 'root'
            else:
                archive_key = 'root'
            if 'extra_files' not in files_structure[chapter_key]:
                files_structure[chapter_key]['extra_files'] = {}
            if archive_key not in files_structure[chapter_key]['extra_files']:
                files_structure[chapter_key]['extra_files'][archive_key] = []
            archive_name = f'extra_file_{archive_key}.zip'
            archive_path = os.path.join(chapter_folder, archive_name)
            clean_relative_path = relative_path.rstrip('/') if relative_path else ''
            if clean_relative_path:
                archive_internal_path = f'{clean_relative_path}/{extra_file_name}'
            else:
                archive_internal_path = extra_file_name
            try:
                os.makedirs(os.path.dirname(archive_path), exist_ok=True)
                with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(extra_file_path, archive_internal_path)
                logging.debug(f'Created extra_file archive: {archive_path} with internal path: {archive_internal_path}')
            except Exception as e:
                logging.error(f'Failed to create extra_file archive {archive_path}: {e}', exc_info=True)
                raise
            files_structure[chapter_key]['extra_files'][archive_key].append(archive_name)
        config_data = {'key': mod_key, 'name': mod_name, 'game': game, 'is_local_mod': is_local_mod, 'files': files_structure}
        if self.gamebanana_metadata:
            if self.gamebanana_metadata.get('author'):
                config_data['author'] = self.gamebanana_metadata['author']
            if self.gamebanana_metadata.get('tagline'):
                config_data['tagline'] = self.gamebanana_metadata['tagline']
            if self.gamebanana_metadata.get('icon_url'):
                config_data['icon_url'] = self.gamebanana_metadata['icon_url']
            if self.gamebanana_metadata.get('external_url'):
                config_data['external_url'] = self.gamebanana_metadata['external_url']
            if self.gamebanana_metadata.get('tags'):
                config_data['tags'] = self.gamebanana_metadata['tags']
            if self.gamebanana_metadata.get('version'):
                config_data['version'] = self.gamebanana_metadata['version']
            else:
                config_data['version'] = '1.0.0'
        else:
            config_data['author'] = 'Unknown'
            config_data['version'] = '1.0.0'
        config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
        save_json(config_path, config_data, indent=2)
        logging.info(f'Manual mod created: {target_mod_dir}')
