import os
import shutil
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
from localization.manager import tr

class SaveEditorDialog(QDialog):

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('dialogs.save_editing'))
        self.resize(600, 500)
        self.file_path = file_path
        lay = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels([tr('ui.value_label')])
        if (header := self.table.horizontalHeader()):
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        buttons = [(tr('ui.cancel_button'), self._on_cancel), (tr('ui.save'), self._on_save)]
        for text, slot in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btn_bar.addWidget(btn)
        lay.addLayout(btn_bar)
        self._load_file()
        self._original = self._current_data()

    def _load_file(self):
        with open(self.file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            for i, line in enumerate(content.splitlines()):
                self.table.insertRow(i)
                self.table.setItem(i, 0, QTableWidgetItem(line))

    def _current_data(self):
        data = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            data.append('' if item is None else item.text())
        return data

    def _on_cancel(self):
        if self._current_data() != self._original:
            reply = QMessageBox.question(self, tr('dialogs.cancel_changes'), tr('dialogs.changes_will_be_lost'))
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.reject()

    def _on_save(self):
        new = self._current_data()
        if new != self._original:
            reply = QMessageBox.question(self, tr('dialogs.save_changes'), tr('dialogs.original_save_overwrite'))
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            tmp = self.file_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8', errors='replace') as f:
                f.write('\n'.join(new))
            shutil.move(tmp, self.file_path)
            self.accept()
        except PermissionError:
            path = os.path.dirname(self.file_path)
            QMessageBox.critical(self, tr('dialogs.access_error'), tr('dialogs.no_write_permissions', path=path))
        except Exception:
            QMessageBox.critical(self, tr('dialogs.error'), tr('dialogs.save_file_error'))