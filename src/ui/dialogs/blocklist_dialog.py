from typing import List
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox, QLineEdit, QGroupBox, QSplitter, QWidget, QMessageBox, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from services.localization_service import tr
from services.blocklist_service import BlocklistManager
from ui.common.styling import get_theme_color, get_border_radius


class BlocklistDialog(QDialog):
    blocklist_changed = pyqtSignal()

    def __init__(self, blocklist_service: BlocklistManager, current_game: str, available_games: List[str], parent=None):
        super().__init__(parent)
        self.blocklist_service = blocklist_service
        self.current_game = current_game
        self.available_games = available_games
        self.setup_ui()
        self.load_blocklist()
        self.relocalize_ui()

    def setup_ui(self):
        self.setWindowTitle(tr('blocklist.title'))
        self.setMinimumSize(600, 500)
        self.setModal(True)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        game_selector_layout = QHBoxLayout()
        game_selector_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.game_label = QLabel(tr('blocklist.select_game'))
        self.game_label.setFont(QFont('', 10, QFont.Weight.Bold))
        game_selector_layout.addWidget(self.game_label)
        self.game_combo = QComboBox()
        self.game_combo.setMinimumWidth(150)
        self.game_combo.currentIndexChanged.connect(self.on_game_changed)
        game_selector_layout.addWidget(self.game_combo)
        main_layout.addLayout(game_selector_layout)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)
        self.add_group = QGroupBox(tr('blocklist.add_entry'))
        add_layout = QVBoxLayout(self.add_group)
        prefix_layout = QVBoxLayout()
        prefix_layout.setSpacing(4)
        self.prefix_label = QLabel(tr('blocklist.prefix'))
        prefix_layout.addWidget(self.prefix_label)
        self.prefix_combo = QComboBox()
        self._populate_prefix_combo()
        prefix_layout.addWidget(self.prefix_combo)
        add_layout.addLayout(prefix_layout)
        value_layout = QVBoxLayout()
        value_layout.setSpacing(4)
        self.value_label = QLabel(tr('blocklist.value'))
        value_layout.addWidget(self.value_label)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText(tr('blocklist.value_placeholder'))
        self.value_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        value_layout.addWidget(self.value_edit)
        add_layout.addLayout(value_layout)
        add_layout.addSpacing(6)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.add_button = QPushButton(tr('blocklist.add'))
        self.add_button.clicked.connect(self.add_entry)
        button_layout.addWidget(self.add_button)
        button_layout.addStretch()
        add_layout.addLayout(button_layout)
        left_layout.addWidget(self.add_group)
        left_layout.addStretch()
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)
        self.list_group = QGroupBox(tr('blocklist.current_entries'))
        list_layout = QVBoxLayout(self.list_group)
        self.blocklist_list = QListWidget()
        self.blocklist_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        list_layout.addWidget(self.blocklist_list)
        list_buttons_layout = QHBoxLayout()
        self.remove_button = QPushButton(tr('blocklist.remove'))
        self.remove_button.clicked.connect(self.remove_entry)
        self.remove_button.setEnabled(False)
        list_buttons_layout.addWidget(self.remove_button)
        list_buttons_layout.addStretch()
        list_layout.addLayout(list_buttons_layout)
        right_layout.addWidget(self.list_group)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([250, 350])
        main_layout.addWidget(splitter)
        close_button = QPushButton(tr('common.close'))
        close_button.clicked.connect(self.accept)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        main_layout.addLayout(button_layout)
        self.blocklist_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.apply_theme()

    def apply_theme(self):
        if hasattr(self.parent(), 'app_state') and self.parent().app_state:
            app_state = self.parent().app_state
            bg_color = get_theme_color(app_state.local_config, 'background', '#282828')
            text_color = get_theme_color(app_state.local_config, 'text', '#e8e9eb')
            hover_color = get_theme_color(app_state.local_config, 'button_hover', '#616b78')
            br = get_border_radius(app_state.local_config)
            self.setStyleSheet(f'\n                QDialog {{\n                    background-color: {bg_color};\n                    color: {text_color};\n                    border-radius: {br}px;\n                }}\n                QGroupBox {{\n                    color: {text_color};\n                    border: 2px solid {text_color};\n                    border-radius: {br}px;\n                    margin-top: 10px;\n                    padding-top: 10px;\n                    background-color: {bg_color};\n                }}\n                QGroupBox::title {{\n                    subcontrol-origin: margin;\n                    left: 10px;\n                    padding: 0 5px 0 5px;\n                    color: {text_color};\n                }}\n                QPushButton {{\n                    background-color: {bg_color};\n                    color: {text_color};\n                    border: 2px solid {text_color};\n                    border-radius: {br}px;\n                    padding: 5px 15px;\n                    font-size: 12px;\n                }}\n                QPushButton:hover {{\n                    background-color: {hover_color};\n                    color: {text_color};\n                }}\n                QPushButton:disabled {{\n                    background-color: {bg_color};\n                    color: {text_color};\n                    opacity: 0.5;\n                }}\n                QLineEdit, QComboBox, QListWidget {{\n                    background-color: {bg_color};\n                    color: {text_color};\n                    border: 2px solid {text_color};\n                    border-radius: {br}px;\n                    padding: 3px;\n                }}\n                QListWidget::item:selected {{\n                    background-color: {text_color};\n                    color: {bg_color};\n                }}\n                QLabel {{\n                    color: {text_color};\n                }}\n            ')

    def load_blocklist(self):
        self.game_combo.clear()
        game_names = {'deltarune': tr('ui.deltarune'), 'deltarunedemo': tr('ui.deltarunedemo'), 'undertale': tr('ui.undertale'), 'undertaleyellow': tr('ui.undertaleyellow'), 'pizzatower': tr('ui.pizzatower'), 'sugaryspire': tr('ui.sugaryspire'), 'global': tr('blocklist.global')}
        for game in self.available_games:
            display_name = game_names.get(game, game)
            self.game_combo.addItem(display_name, game)
        current_index = self.game_combo.findData(self.current_game)
        if current_index >= 0:
            self.game_combo.setCurrentIndex(current_index)
        self.update_blocklist_display()

    def update_blocklist_display(self):
        self.blocklist_list.clear()
        current_game = self.game_combo.currentData()
        if not current_game:
            return
        entries = self.blocklist_service.get_blocklist_for_game(current_game)
        for entry in entries:
            prefix_type = entry['prefix_type']
            value = entry['value']
            prefix_display = self.blocklist_service.get_prefix_type_display_name(prefix_type)
            item_text = f'[{prefix_display}] {value}'
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.blocklist_list.addItem(item)

    def on_game_changed(self):
        self.update_blocklist_display()

    def on_selection_changed(self):
        has_selection = bool(self.blocklist_list.selectedItems())
        self.remove_button.setEnabled(has_selection)

    def add_entry(self):
        prefix_type = self.prefix_combo.currentData()
        value = self.value_edit.text().strip()
        if not value:
            QMessageBox.warning(self, tr('common.warning'), tr('blocklist.empty_value'))
            return
        current_game = self.game_combo.currentData()
        if current_game:
            self.blocklist_service.add_blocklist_entry(current_game, prefix_type, value)
            self.value_edit.clear()
            self.update_blocklist_display()
            self.blocklist_changed.emit()

    def remove_entry(self):
        selected_items = self.blocklist_list.selectedItems()
        if not selected_items:
            return
        current_game = self.game_combo.currentData()
        if not current_game:
            return
        item = selected_items[0]
        entry = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, tr('blocklist.confirm_remove'), tr('blocklist.confirm_remove_text'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success = self.blocklist_service.remove_blocklist_entry(current_game, entry['prefix_type'], entry['value'])
            if success:
                self.update_blocklist_display()
                self.blocklist_changed.emit()

    def relocalize_ui(self):
        self.setWindowTitle(tr('blocklist.title'))
        if hasattr(self, 'game_combo'):
            self.load_blocklist()
        if hasattr(self, 'add_button'):
            self.add_button.setText(tr('blocklist.add'))
        if hasattr(self, 'remove_button'):
            self.remove_button.setText(tr('blocklist.remove'))
        if hasattr(self, 'value_edit'):
            self.value_edit.setPlaceholderText(tr('blocklist.value_placeholder'))
        if hasattr(self, 'prefix_label'):
            self.prefix_label.setText(tr('blocklist.prefix'))
        if hasattr(self, 'value_label'):
            self.value_label.setText(tr('blocklist.value'))
        if hasattr(self, 'game_label'):
            self.game_label.setText(tr('blocklist.select_game'))
        if hasattr(self, 'add_group'):
            self.add_group.setTitle(tr('blocklist.add_entry'))
        if hasattr(self, 'list_group'):
            self.list_group.setTitle(tr('blocklist.current_entries'))
        if hasattr(self, 'prefix_combo'):
            current_data = self.prefix_combo.currentData()
            self._populate_prefix_combo(current_data)

    def _populate_prefix_combo(self, current_data: str | None = None) -> None:
        if not hasattr(self, 'prefix_combo'):
            return
        prefix_combo_items = [(tr('blocklist.prefix_type_id'), BlocklistManager.PREFIX_TYPE_ID), (tr('blocklist.prefix_type_name'), BlocklistManager.PREFIX_TYPE_NAME), (tr('blocklist.prefix_type_category'), BlocklistManager.PREFIX_TYPE_CATEGORY)]
        self.prefix_combo.clear()
        for text, data in prefix_combo_items:
            self.prefix_combo.addItem(text, data)
        if current_data:
            index = self.prefix_combo.findData(current_data)
            if index >= 0:
                self.prefix_combo.setCurrentIndex(index)
