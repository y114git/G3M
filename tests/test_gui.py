import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QTabWidget, QLabel, QProgressBar, QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QFileDialog, QDialog
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor


class PytestRunnerThread(QThread):
    test_output = pyqtSignal(str)
    test_finished = pyqtSignal(int, int, int)
    test_started = pyqtSignal(str)

    def __init__(self, test_path: str, test_args: Optional[List[str]] = None):
        super().__init__()
        self.test_path = test_path
        self.test_args = test_args if test_args is not None else []
        self._cancelled = False
        self._process: Optional[subprocess.Popen] = None

    def cancel(self):
        self._cancelled = True
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

    def run(self):
        try:
            tests_dir = Path(__file__).parent
            project_root = tests_dir.parent
            cmd = [sys.executable, '-m', 'pytest', str(tests_dir / self.test_path), '-v', '--tb=short', '--color=no', '-q']
            cmd.extend(self.test_args)
            self.test_started.emit(' '.join(cmd))
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(project_root), bufsize=1, universal_newlines=True)
            if self._process.stdout:
                for line in iter(self._process.stdout.readline, ''):
                    if self._cancelled:
                        if self._process:
                            self._process.terminate()
                        break
                    if line:
                        self.test_output.emit(line.rstrip())
            if self._process:
                self._process.wait()
            exit_code = self._process.returncode if self._process else 1
            if exit_code == 0:
                self.test_finished.emit(1, 0, 0)
            else:
                self.test_finished.emit(0, 1, 0)
        except Exception as e:
            self.test_output.emit(f'ERROR: {str(e)}')
            self.test_finished.emit(0, 1, 0)
        finally:
            self._process = None


class CategoryTabWidget(QWidget):

    def __init__(self, category_name: str, test_files: List[Dict[str, str]], parent=None):
        super().__init__(parent)
        self.category_name = category_name
        self.test_files = test_files
        self.category_key = None
        self.current_thread: Optional[PytestRunnerThread] = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        controls_layout = QHBoxLayout()
        self.run_all_btn = QPushButton(f'Run All {self.category_name} Tests')
        self.run_all_btn.clicked.connect(self.run_all_tests)
        controls_layout.addWidget(self.run_all_btn)
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.clicked.connect(self.stop_tests)
        self.stop_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addStretch()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        controls_layout.addWidget(self.progress_bar)
        layout.addLayout(controls_layout)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        test_list_widget = QWidget()
        test_list_layout = QVBoxLayout(test_list_widget)
        test_list_layout.addWidget(QLabel(f'{self.category_name} Tests:'))
        self.test_tree = QTreeWidget()
        self.test_tree.setHeaderLabel('Test Files')
        self.test_tree.itemDoubleClicked.connect(self.on_test_double_clicked)
        for test_file in self.test_files:
            item = QTreeWidgetItem([test_file['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, test_file['path'])
            item.setToolTip(0, test_file.get('description', ''))
            self.test_tree.addTopLevelItem(item)
        test_list_layout.addWidget(self.test_tree)
        splitter.addWidget(test_list_widget)
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_layout.addWidget(QLabel('Test Output:'))
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont('Courier', 9))
        output_layout.addWidget(self.output_text)
        self.results_label = QLabel('No tests run yet')
        output_layout.addWidget(self.results_label)
        splitter.addWidget(output_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    def on_test_double_clicked(self, item: QTreeWidgetItem, column: int):
        test_path = item.data(0, Qt.ItemDataRole.UserRole)
        if test_path:
            self.run_test(test_path)

    def run_test(self, test_path: str):
        if self.current_thread and self.current_thread.isRunning():
            QMessageBox.warning(self, 'Test Running', 'Please wait for current test to finish')
            return
        self.output_text.clear()
        self.output_text.append(f"Running: {test_path}\n{'=' * 60}\n")
        self.progress_bar.setVisible(True)
        self.run_all_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.current_thread = PytestRunnerThread(test_path)
        self.current_thread.test_output.connect(self.append_output)
        self.current_thread.test_finished.connect(self.on_test_finished)
        self.current_thread.test_started.connect(self.append_output)
        self.current_thread.start()

    def run_all_tests(self):
        if self.current_thread and self.current_thread.isRunning():
            QMessageBox.warning(self, 'Test Running', 'Please wait for current test to finish')
            return
        self.output_text.clear()
        self.output_text.append(f"Running all {self.category_name} tests...\n{'=' * 60}\n")
        self.progress_bar.setVisible(True)
        self.run_all_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        tests_dir = Path(__file__).parent
        if self.category_key:
            category_dir_name = self.category_key
        else:
            category_dir_name = self.category_name.lower().replace(' ', '_')
        category_path = tests_dir / category_dir_name
        self.current_thread = PytestRunnerThread(str(category_path))
        self.current_thread.test_output.connect(self.append_output)
        self.current_thread.test_finished.connect(self.on_test_finished)
        self.current_thread.test_started.connect(self.append_output)
        self.current_thread.start()

    def stop_tests(self):
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.cancel()
            if not self.current_thread.wait(5000):
                self.current_thread.terminate()
                self.current_thread.wait(1000)
            self.append_output('\n\nTest run cancelled by user')
            self.on_test_finished(0, 0, 0)

    def append_output(self, text: str):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        format_normal = QTextCharFormat()
        format_error = QTextCharFormat()
        format_error.setForeground(QColor('red'))
        format_success = QTextCharFormat()
        format_success.setForeground(QColor('green'))
        format_warning = QTextCharFormat()
        format_warning.setForeground(QColor('orange'))
        if 'FAILED' in text or 'ERROR' in text or 'FAIL' in text:
            cursor.insertText(text + '\n', format_error)
        elif 'PASSED' in text or 'PASS' in text:
            cursor.insertText(text + '\n', format_success)
        elif 'WARNING' in text or 'WARN' in text:
            cursor.insertText(text + '\n', format_warning)
        else:
            cursor.insertText(text + '\n', format_normal)
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

    def on_test_finished(self, passed: int, failed: int, skipped: int):
        self.progress_bar.setVisible(False)
        self.run_all_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        total = passed + failed + skipped
        if total > 0:
            self.results_label.setText(f'Results: {passed} passed, {failed} failed, {skipped} skipped')
            if failed > 0:
                self.results_label.setStyleSheet('color: red;')
            else:
                self.results_label.setStyleSheet('color: green;')
        else:
            self.results_label.setText('No tests run')
            self.results_label.setStyleSheet('')
        if self.current_thread:
            if self.current_thread.isRunning():
                self.current_thread.wait(1000)
            self.current_thread.deleteLater()
        self.current_thread = None


class GUIWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('DELTAHUB Test Suite')
        self.setGeometry(100, 100, 1200, 800)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        header = QLabel('DELTAHUB Test Suite - Interactive Test Runner')
        header.setFont(QFont('Arial', 14, QFont.Weight.Bold))
        layout.addWidget(header)
        global_controls = QHBoxLayout()
        run_all_btn = QPushButton('Run All Tests')
        run_all_btn.clicked.connect(self.run_all_tests)
        global_controls.addWidget(run_all_btn)
        export_btn = QPushButton('Export Results')
        export_btn.clicked.connect(self.export_results)
        global_controls.addWidget(export_btn)
        global_controls.addStretch()
        layout.addLayout(global_controls)
        self.tabs = QTabWidget()
        test_categories = [{'name': 'Unit Tests', 'key': 'unit', 'files': [{'name': 'test_utils.py', 'path': 'unit/test_utils.py', 'description': 'Utility functions tests'}, {'name': 'test_path_utils.py', 'path': 'unit/test_path_utils.py', 'description': 'Path utility functions tests'}, {'name': 'test_managers.py', 'path': 'unit/test_managers.py', 'description': 'Manager classes tests'}, {'name': 'test_models.py', 'path': 'unit/test_models.py', 'description': 'Data models tests'}, {'name': 'test_controllers.py', 'path': 'unit/test_controllers.py', 'description': 'Controller classes tests'}, {'name': 'test_config.py', 'path': 'unit/test_config.py', 'description': 'Configuration tests'}]}, {'name': 'Integration Tests', 'key': 'integration', 'files': [{'name': 'test_mod_operations.py', 'path': 'integration/test_mod_operations.py', 'description': 'Mod installation/removal tests'}, {'name': 'test_gamebanana.py', 'path': 'integration/test_gamebanana.py', 'description': 'GameBanana integration tests'}, {'name': 'test_plugin_system.py', 'path': 'integration/test_plugin_system.py', 'description': 'Plugin system tests'}, {'name': 'test_patching_and_merging.py', 'path': 'integration/test_patching_and_merging.py', 'description': 'Patching and merging tests'}, {'name': 'test_mod_system.py', 'path': 'integration/test_mod_system.py', 'description': 'Full mod system tests (structure, installation, processing)'}, {'name': 'test_game_launch_simulation.py', 'path': 'integration/test_game_launch_simulation.py', 'description': 'Game launch simulation and path resolution tests'}, {'name': 'test_customization_colors.py', 'path': 'integration/test_customization_colors.py', 'description': 'UI color customization tests'}, {'name': 'test_refresh_updates.py', 'path': 'integration/test_refresh_updates.py', 'description': 'UI refresh functionality tests'}, {'name': 'test_localization_updates.py', 'path': 'integration/test_localization_updates.py', 'description': 'Localization and translation update tests'}]}, {'name': 'UI Tests', 'key': 'ui', 'files': [{'name': 'test_dialogs.py', 'path': 'ui/test_dialogs.py', 'description': 'Dialog components tests'}, {'name': 'test_widgets.py', 'path': 'ui/test_widgets.py', 'description': 'Widget components tests'}, {'name': 'test_main_window.py', 'path': 'ui/test_main_window.py', 'description': 'Main window tests'}]}]
        for category in test_categories:
            tab = CategoryTabWidget(category['name'], category['files'], self)
            tab.category_key = category.get('key', category['name'].lower().replace(' ', '_'))
            self.tabs.addTab(tab, category['name'])
        layout.addWidget(self.tabs)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage('Ready')

    def run_all_tests(self):
        reply = QMessageBox.question(self, 'Run All Tests', 'This will run all tests. This may take a while. Continue?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            tests_dir = Path(__file__).parent
            thread = PytestRunnerThread(str(tests_dir))
            output_dialog = QDialog(self)
            output_dialog.setWindowTitle('Running All Tests')
            output_dialog.setMinimumSize(800, 600)
            dialog_layout = QVBoxLayout(output_dialog)
            header_label = QLabel('Running all tests...\nThis may take several minutes.')
            header_label.setFont(QFont('Arial', 10, QFont.Weight.Bold))
            dialog_layout.addWidget(header_label)
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 0)
            dialog_layout.addWidget(progress_bar)
            output_text = QTextEdit()
            output_text.setReadOnly(True)
            output_text.setFont(QFont('Courier', 9))
            dialog_layout.addWidget(output_text)
            controls_layout = QHBoxLayout()
            stop_btn = QPushButton('Stop')
            stop_btn.setEnabled(True)
            controls_layout.addWidget(stop_btn)
            controls_layout.addStretch()
            results_label = QLabel('Running tests...')
            controls_layout.addWidget(results_label)
            dialog_layout.addLayout(controls_layout)
            format_normal = QTextCharFormat()
            format_error = QTextCharFormat()
            format_error.setForeground(QColor('red'))
            format_success = QTextCharFormat()
            format_success.setForeground(QColor('green'))
            format_warning = QTextCharFormat()
            format_warning.setForeground(QColor('orange'))

            def append_output(text: str):
                cursor = output_text.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                if 'FAILED' in text or 'ERROR' in text or 'FAIL' in text:
                    cursor.insertText(text + '\n', format_error)
                elif 'PASSED' in text or 'PASS' in text:
                    cursor.insertText(text + '\n', format_success)
                elif 'WARNING' in text or 'WARN' in text:
                    cursor.insertText(text + '\n', format_warning)
                else:
                    cursor.insertText(text + '\n', format_normal)
                output_text.setTextCursor(cursor)
                output_text.ensureCursorVisible()

            def on_output(text: str):
                append_output(text)

            def on_finished(passed: int, failed: int, skipped: int):
                progress_bar.setVisible(False)
                stop_btn.setEnabled(False)
                total = passed + failed + skipped
                if total > 0:
                    results_label.setText(f'Results: {passed} passed, {failed} failed, {skipped} skipped')
                    if failed > 0:
                        results_label.setStyleSheet('color: red;')
                    else:
                        results_label.setStyleSheet('color: green;')
                else:
                    results_label.setText('No tests run')
                    results_label.setStyleSheet('')
                if failed > 0:
                    QMessageBox.warning(output_dialog, 'Test Results', f'All tests completed!\n\nPassed: {passed}\nFailed: {failed}\nSkipped: {skipped}')
                else:
                    QMessageBox.information(output_dialog, 'Test Results', f'All tests completed!\n\nPassed: {passed}\nFailed: {failed}\nSkipped: {skipped}')
                if thread.isRunning():
                    thread.wait(1000)
                thread.deleteLater()

            def on_started(cmd: str):
                append_output(f'Command: {cmd}')
                append_output('=' * 60)

            def stop_tests():
                if thread.isRunning():
                    thread.cancel()
                    append_output('\n\nTest run cancelled by user')
                    if thread.isRunning():
                        thread.wait(5000)
                    on_finished(0, 0, 0)
            stop_btn.clicked.connect(stop_tests)
            thread.test_output.connect(on_output)
            thread.test_finished.connect(on_finished)
            thread.test_started.connect(on_started)
            output_dialog.show()
            thread.start()

    def export_results(self):
        file_path, _ = QFileDialog.getSaveFileName(self, 'Export Test Results', f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", 'Text Files (*.txt);;All Files (*)')
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('DELTAHUB Test Results\n')
                    f.write('=' * 60 + '\n')
                    f.write(f'Generated: {datetime.now().isoformat()}\n\n')
                    for i in range(self.tabs.count()):
                        tab = self.tabs.widget(i)
                        if isinstance(tab, CategoryTabWidget):
                            f.write(f'\n{tab.category_name}\n')
                            f.write('-' * 60 + '\n')
                            f.write(tab.output_text.toPlainText())
                            f.write('\n')
                QMessageBox.information(self, 'Export', f'Results exported to:\n{file_path}')
            except Exception as e:
                QMessageBox.critical(self, 'Export Error', f'Failed to export results:\n{str(e)}')


def main():
    app = QApplication(sys.argv)
    window = GUIWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
