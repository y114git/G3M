from typing import List, Tuple
import os
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QListWidget, QListWidgetItem, QCheckBox, QProgressBar, QMessageBox, QFileDialog
from managers.localization_manager import tr


class ReportBugDialog(QDialog):

    def __init__(self, parent, app_state):
        super().__init__(parent)
        self.app_state = app_state
        self.attached_files: List[str] = []
        self.max_text_length = 5000
        self.max_total_size = 10 * 1024 * 1024
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(tr('dialogs.report_bug_title'))
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        description_label = QLabel(tr('dialogs.report_bug_description'))
        description_label.setWordWrap(True)
        layout.addWidget(description_label)
        self.text_edit = QTextEdit()
        self.text_edit.setMaximumHeight(150)
        self.text_edit.setPlaceholderText(tr('dialogs.report_bug_description'))
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)
        self.char_count_label = QLabel(f'0 / {self.max_text_length}')
        self.char_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.char_count_label)
        files_label = QLabel(tr('dialogs.report_bug_attach_files'))
        files_label.setWordWrap(True)
        layout.addWidget(files_label)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(120)
        layout.addWidget(self.file_list)
        file_buttons_layout = QHBoxLayout()
        add_file_button = QPushButton(tr('dialogs.report_bug_add_file'))
        add_file_button.clicked.connect(self._add_file)
        remove_file_button = QPushButton(tr('dialogs.report_bug_remove_file'))
        remove_file_button.clicked.connect(self._remove_selected_file)
        file_buttons_layout.addWidget(add_file_button)
        file_buttons_layout.addWidget(remove_file_button)
        file_buttons_layout.addStretch()
        self.file_size_label = QLabel(tr('dialogs.report_bug_file_size', size='0 MB'))
        self.file_size_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        file_buttons_layout.addWidget(self.file_size_label)
        layout.addLayout(file_buttons_layout)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        buttons_layout = QHBoxLayout()
        self.attach_logs_checkbox = QCheckBox(tr('dialogs.report_bug_attach_logs'))
        self.attach_logs_checkbox.setChecked(True)
        buttons_layout.addWidget(self.attach_logs_checkbox)
        buttons_layout.addStretch()
        self.send_button = QPushButton(tr('dialogs.report_bug_send'))
        self.send_button.clicked.connect(self._send_report)
        cancel_button = QPushButton(tr('dialogs.report_bug_cancel'))
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.send_button)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)
        self._update_file_size()

    def _on_text_changed(self):
        text = self.text_edit.toPlainText()
        char_count = len(text)
        self.char_count_label.setText(f'{char_count} / {self.max_text_length}')
        if char_count > self.max_text_length:
            cursor = self.text_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.text_edit.setText(text[:self.max_text_length])
            cursor.movePosition(cursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)
            self.char_count_label.setText(f'{self.max_text_length} / {self.max_text_length}')

    def _add_file(self):
        file_filter = 'Images (*.png *.jpg *.jpeg);;Videos (*.mp4);;All Files (*)'
        file_path, _ = QFileDialog.getOpenFileName(self, tr('dialogs.report_bug_add_file'), '', file_filter)
        if not file_path:
            return
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.mp4']:
            QMessageBox.warning(self, tr('dialogs.report_bug_title'), tr('dialogs.report_bug_invalid_file'))
            return
        if file_path in self.attached_files:
            return
        file_size = os.path.getsize(file_path)
        current_total = sum((os.path.getsize(f) for f in self.attached_files))
        if current_total + file_size > self.max_total_size:
            QMessageBox.warning(self, tr('dialogs.report_bug_title'), tr('dialogs.report_bug_file_too_large'))
            return
        self.attached_files.append(file_path)
        item = QListWidgetItem(os.path.basename(file_path))
        item.setData(Qt.ItemDataRole.UserRole, file_path)
        self.file_list.addItem(item)
        self._update_file_size()

    def _remove_selected_file(self):
        current_item = self.file_list.currentItem()
        if not current_item:
            return
        file_path = current_item.data(Qt.ItemDataRole.UserRole)
        if file_path in self.attached_files:
            self.attached_files.remove(file_path)
        self.file_list.takeItem(self.file_list.row(current_item))
        self._update_file_size()

    def _update_file_size(self):
        total_size = sum((os.path.getsize(f) for f in self.attached_files))
        size_mb = total_size / (1024 * 1024)
        max_mb = self.max_total_size / (1024 * 1024)
        self.file_size_label.setText(tr('dialogs.report_bug_file_size', size=f'{size_mb:.2f} MB'))
        if size_mb > max_mb * 0.9:
            self.file_size_label.setStyleSheet('color: red;')
        elif size_mb > max_mb * 0.7:
            self.file_size_label.setStyleSheet('color: orange;')
        else:
            self.file_size_label.setStyleSheet('')

    def _validate_input(self) -> Tuple[bool, str]:
        text = self.text_edit.toPlainText().strip()
        if not text:
            return (False, tr('dialogs.report_bug_text_required'))
        if len(text) > self.max_text_length:
            return (False, tr('dialogs.report_bug_text_too_long'))
        total_size = sum((os.path.getsize(f) for f in self.attached_files))
        if total_size > self.max_total_size:
            return (False, tr('dialogs.report_bug_file_too_large'))
        return (True, '')

    def _send_report(self):
        is_valid, error_msg = self._validate_input()
        if not is_valid:
            QMessageBox.warning(self, tr('dialogs.report_bug_title'), error_msg)
            return
        self.send_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        from workers.report_bug_worker import ReportBugWorker
        from PyQt6.QtCore import QThread
        self.worker_thread = QThread(self)
        self.worker = ReportBugWorker(self.text_edit.toPlainText().strip(), self.attached_files, self.attach_logs_checkbox.isChecked(), self.app_state)
        self.worker.moveToThread(self.worker_thread)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

    def _on_progress(self, value: int):
        if value >= 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
        else:
            self.progress_bar.setRange(0, 0)

    def _on_worker_finished(self, success: bool, message: str):
        self.worker_thread.quit()
        self.worker_thread.wait()
        self.progress_bar.setVisible(False)
        self.send_button.setEnabled(True)
        if success:
            QMessageBox.information(self, tr('dialogs.report_bug_title'), tr('dialogs.report_bug_success'))
            self.accept()
        else:
            QMessageBox.critical(self, tr('dialogs.report_bug_title'), tr('dialogs.report_bug_error', error=message))

    def _on_worker_error(self, error: str):
        self._on_worker_finished(False, error)
