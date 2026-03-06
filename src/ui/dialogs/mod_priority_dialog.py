from typing import List, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem, QAbstractItemView
from services.localization_service import tr
from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values


class ModPriorityDialog(QDialog):

    def __init__(self, mods_list: List[Any], chapter_id: int, app_state, parent=None):
        super().__init__(parent)
        self.mods_list = mods_list.copy()
        self.chapter_id = chapter_id
        self.app_state = app_state
        self.result_list = None
        self.setWindowTitle(tr('ui.mod_priority_title'))
        self.setMinimumSize(400, 500)
        self.setup_ui()
        self._apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        info_label = QLabel(tr('ui.mod_priority_info'))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        self.instructions_label = QLabel(tr('ui.mod_priority_instructions'))
        self.instructions_label.setWordWrap(True)
        self.instructions_label.setObjectName('instructionsLabel')
        layout.addWidget(self.instructions_label)
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for mod in self.mods_list:
            mod_name = getattr(mod, 'name', 'Unknown Mod')
            item = QListWidgetItem(mod_name)
            item.setData(Qt.ItemDataRole.UserRole, mod)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)
        buttons_layout = QHBoxLayout()
        up_button = QPushButton(tr('ui.move_up'))
        up_button.clicked.connect(self._move_up)
        buttons_layout.addWidget(up_button)
        down_button = QPushButton(tr('ui.move_down'))
        down_button.clicked.connect(self._move_down)
        buttons_layout.addWidget(down_button)
        buttons_layout.addStretch()
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        ok_button = QPushButton(tr('ui.ok'))
        ok_button.clicked.connect(self._accept_dialog)
        ok_button.setDefault(True)
        buttons_layout.addWidget(ok_button)
        layout.addLayout(buttons_layout)

    def _move_up(self):
        self._move_item(-1)

    def _move_down(self):
        self._move_item(1)

    def _move_item(self, offset: int) -> None:
        current_row = self.list_widget.currentRow()
        target_row = current_row + offset
        if current_row < 0 or target_row < 0 or target_row >= self.list_widget.count():
            return
        item = self.list_widget.takeItem(current_row)
        self.list_widget.insertItem(target_row, item)
        self.list_widget.setCurrentRow(target_row)

    def _accept_dialog(self):
        self.result_list = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                mod = item.data(Qt.ItemDataRole.UserRole)
                if mod:
                    self.result_list.append(mod)
        self.accept()

    def get_result(self) -> List[Any]:
        return self.result_list if self.result_list is not None else self.mods_list

    def _apply_theme(self):
        apply_dialog_theme(self, self.app_state)
        self.instructions_label.setStyleSheet(f'color: {get_dialog_theme_values(self.app_state)["secondary_text"]}; font-size: 11px;')
