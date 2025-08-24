import os
import shutil
import sys
import tempfile
import logging
import platform
import subprocess
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QFileDialog, QMessageBox, QLineEdit, QWidget
from localization.manager import tr
from utils.file_utils import get_file_filter
from ui.widgets.custom_controls import NoScrollTabWidget
from ui.styling import create_file_group_universal
from utils.path_utils import resource_path

class XdeltaDialog(QDialog):

    def _get_xdelta_path(self):
        system = platform.system()
        exe_name = 'xdelta3.exe' if system == 'Windows' else 'xdelta3'

        path = resource_path(f'resources/bin/{exe_name}')

        # fallback для dev mode (не собранного приложения)
        if not os.path.exists(path) and not getattr(sys, 'frozen', False):
            dev_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'resources', 'bin', exe_name))
            if os.path.exists(dev_path):
                return dev_path

        return path if os.path.exists(path) else None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('ui.patching_tab'))
        self.resize(600, 525)
        self.init_ui()
        if parent:
            parent_geometry = parent.geometry()
            dialog_geometry = self.geometry()
            x = parent_geometry.x() + (parent_geometry.width() - dialog_geometry.width()) // 2
            y = parent_geometry.y() + (parent_geometry.height() - dialog_geometry.height()) // 2
            self.move(x, y)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        tabs = NoScrollTabWidget()
        tabs.setStyleSheet('\n            QTabWidget::tab-bar { alignment: center; }\n            QTabBar::tab { min-width: 120px; padding: 8px 16px; }\n        ')
        create_tab = QWidget()
        create_layout = QVBoxLayout(create_tab)
        self.original_create_edit = QLineEdit()
        self.modified_create_edit = QLineEdit()
        self.patch_output_edit = QLineEdit()
        create_layout.addWidget(self._create_file_group(tr('ui.original_file_label'), tr('ui.select_original_file'), get_file_filter('all_files'), self.original_create_edit))
        create_layout.addWidget(self._create_file_group(tr('ui.modified_file_label'), tr('ui.select_modified_file'), get_file_filter('all_files'), self.modified_create_edit))
        create_layout.addWidget(self._create_save_file_group(tr('ui.save_patch_as'), tr('ui.specify_patch_path'), get_file_filter('xdelta_files'), self.patch_output_edit))
        create_button = QPushButton(tr('ui.create_patch_button'))
        create_button.clicked.connect(self.create_patch)
        create_layout.addWidget(create_button)
        create_layout.addStretch()
        tabs.addTab(create_tab, tr('ui.create_patch_tab'))
        apply_tab = QWidget()
        apply_layout = QVBoxLayout(apply_tab)
        self.original_apply_edit = QLineEdit()
        self.patch_apply_edit = QLineEdit()
        self.output_apply_edit = QLineEdit()
        apply_layout.addWidget(self._create_file_group(tr('ui.original_file_label'), tr('ui.select_original_for_patch'), get_file_filter('all_files'), self.original_apply_edit))
        apply_layout.addWidget(self._create_file_group(tr('ui.patch_file_label'), tr('ui.select_patch_file'), get_file_filter('xdelta_files'), self.patch_apply_edit))
        apply_layout.addWidget(self._create_save_file_group(tr('ui.save_modified_as'), tr('ui.specify_save_path'), get_file_filter('all_files'), self.output_apply_edit))
        apply_button = QPushButton(tr('ui.apply_patch_button'))
        apply_button.clicked.connect(self.apply_patch)
        apply_layout.addWidget(apply_button)
        apply_layout.addStretch()
        tabs.addTab(apply_tab, tr('ui.apply_patch_tab'))
        main_layout.addWidget(tabs)

    def _create_file_group(self, label_text, button_text, file_filter, line_edit):
        group_box, button = create_file_group_universal(label_text, button_text, file_filter, line_edit, 'open')
        button.clicked.connect(lambda: self._browse_file(line_edit, file_filter))
        return group_box

    def _create_save_file_group(self, label_text, button_text, file_filter, line_edit):
        group_box, button = create_file_group_universal(label_text, button_text, file_filter, line_edit, 'save')
        if line_edit is getattr(self, 'output_apply_edit', None):
            button.clicked.connect(lambda: self._browse_save_output_file(line_edit, file_filter))
        else:
            button.clicked.connect(lambda: self._browse_save_file(line_edit, file_filter))
        return group_box

    def _browse_file(self, line_edit, file_filter):
        file_path, _ = QFileDialog.getOpenFileName(self, tr('ui.select_file'), '', file_filter)
        if file_path:
            line_edit.setText(file_path)

    def _browse_save_file(self, line_edit, file_filter, suggested_name=''):
        file_path, _ = QFileDialog.getSaveFileName(self, tr('ui.save_file'), suggested_name, file_filter)
        if file_path:
            line_edit.setText(os.path.abspath(os.path.normpath(file_path)))

    def _browse_save_output_file(self, line_edit, file_filter):
        original_file = self.original_apply_edit.text()
        suggested_name = ''
        if original_file and os.path.exists(original_file):
            base_name = os.path.basename(original_file)
            name, ext = os.path.splitext(base_name)
            suggested_name = f'{name}_patched{ext}'
        self._browse_save_file(line_edit, file_filter, suggested_name)

    def _show_message(self, title, message, icon=QMessageBox.Icon.Information):
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec()

    def create_patch(self):
        xdelta_path = self._get_xdelta_path()
        if not xdelta_path:
            self._show_message(tr('dialogs.error'), tr('errors.xdelta_unavailable'), QMessageBox.Icon.Critical)
            return
        original_file = self.original_create_edit.text()
        modified_file = self.modified_create_edit.text()
        output_patch = self.patch_output_edit.text()
        if not all((original_file, modified_file, output_patch)):
            self._show_message(tr('dialogs.error'), tr('ui.select_all_files'), QMessageBox.Icon.Warning)
            return
        if not os.path.exists(original_file):
            self._show_message(tr('dialogs.error'), tr('ui.original_file_not_found', path=original_file), QMessageBox.Icon.Warning)
            return
        if not os.path.exists(modified_file):
            self._show_message(tr('dialogs.error'), tr('ui.modified_file_not_found', path=modified_file), QMessageBox.Icon.Warning)
            return
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix='xdelta_temp_')
            temp_original = os.path.join(temp_dir, 'original_source.bin')
            temp_modified = os.path.join(temp_dir, 'modified_target.bin')
            temp_output = os.path.join(temp_dir, 'output.xdelta')
            shutil.copy2(original_file, temp_original)
            shutil.copy2(modified_file, temp_modified)
            command = [xdelta_path, '-e', '-s', temp_original, temp_modified, temp_output]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            if result.returncode == 0:
                shutil.move(temp_output, output_patch)
                self._show_message(tr('ui.success'), tr('ui.patch_success', path=output_patch))
            else:
                error_message = result.stderr or result.stdout
                logging.error(f'xdelta create patch failed: {error_message}')
                self._show_message(tr('errors.patch_create_error'), tr('errors.patch_create_failed_details', error=error_message), QMessageBox.Icon.Critical)
        except Exception as e:
            self._show_message(tr('errors.patch_create_error'), tr('errors.patch_create_exception', error=str(e)), QMessageBox.Icon.Critical)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logging.debug(f'Failed to remove temp dir {temp_dir}: {e}')

    def apply_patch(self):
        xdelta_path = self._get_xdelta_path()
        if not xdelta_path:
            self._show_message(tr('dialogs.error'), tr('errors.xdelta_unavailable'), QMessageBox.Icon.Critical)
            return
        original_file = self.original_apply_edit.text()
        patch_file = self.patch_apply_edit.text()
        output_file = self.output_apply_edit.text()
        if not all((original_file, patch_file, output_file)):
            self._show_message(tr('dialogs.error'), tr('ui.select_all_files'), QMessageBox.Icon.Warning)
            return
        if not os.path.exists(original_file):
            self._show_message(tr('dialogs.error'), tr('ui.original_file_not_found', path=original_file), QMessageBox.Icon.Warning)
            return
        if not os.path.exists(patch_file):
            self._show_message(tr('dialogs.error'), tr('ui.patch__not_found', path=patch_file), QMessageBox.Icon.Warning)
            return
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix='xdelta_temp_')
            temp_original = os.path.join(temp_dir, 'original_source_for_patch.bin')
            temp_patch = os.path.join(temp_dir, 'input_patch.xdelta')
            temp_output = os.path.join(temp_dir, 'patched_output.bin')
            shutil.copy2(original_file, temp_original)
            shutil.copy2(patch_file, temp_patch)
            command = [xdelta_path, '-d', '-s', temp_original, temp_patch, temp_output]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            if result.returncode == 0:
                shutil.move(temp_output, output_file)
                self._show_message(tr('ui.success'), tr('ui.patch_apply_success', path=output_file))
            else:
                error_message = result.stderr or result.stdout
                logging.error(f'xdelta apply patch failed: {error_message}')
                self._show_message(tr('errors.patch_apply_error'), tr('errors.patch_apply_failed_details', error=error_message), QMessageBox.Icon.Critical)
        except Exception as e:
            self._show_message(tr('errors.patch_apply_error'), tr('errors.patch_apply_exception', error=str(e)), QMessageBox.Icon.Critical)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logging.debug(f'Failed to remove temp dir {temp_dir}: {e}')
