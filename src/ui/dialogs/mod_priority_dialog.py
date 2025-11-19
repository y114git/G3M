from typing import List, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem, QAbstractItemView
from managers.localization_manager import tr
from ui.common.styling import get_theme_color


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
        instructions = QLabel(tr('ui.mod_priority_instructions'))
        instructions.setWordWrap(True)
        instructions.setObjectName('instructionsLabel')
        layout.addWidget(instructions)
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
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, item)
            self.list_widget.setCurrentRow(current_row - 1)

    def _move_down(self):
        current_row = self.list_widget.currentRow()
        if current_row < self.list_widget.count() - 1 and current_row >= 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, item)
            self.list_widget.setCurrentRow(current_row + 1)

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
        bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        secondary_text_color = get_theme_color(self.app_state.local_config, 'version_text', '#888888')
        self.setStyleSheet(f'\n            QDialog {{\n                background-color: {bg_color};\n                color: {text_color};\n            }}\n            QListWidget {{\n                background-color: {bg_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                padding: 5px;\n            }}\n            QListWidget::item {{\n                padding: 8px;\n                border-bottom: 1px solid {border_color};\n            }}\n            QListWidget::item:selected {{\n                background-color: {hover_color};\n            }}\n            QPushButton {{\n                background-color: {button_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                padding: 8px 15px;\n                font-weight: bold;\n            }}\n            QPushButton:hover {{\n                background-color: {hover_color};\n            }}\n            QPushButton:pressed {{\n                background-color: {hover_color};\n            }}\n            QLabel {{\n                color: {text_color};\n            }}\n        ')
        instructions = None
        layout = self.layout()
        if layout is not None:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if widget and isinstance(widget, QLabel) and (widget.objectName() == 'instructionsLabel'):
                        instructions = widget
                        break
        if instructions:
            instructions.setStyleSheet(f'color: {secondary_text_color}; font-size: 11px;')
