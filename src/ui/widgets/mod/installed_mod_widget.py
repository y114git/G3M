from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from .base_mod_widget import BaseModWidget
from managers.localization_manager import tr
from ui.common.styling import get_theme_color


class InstalledModWidget(BaseModWidget):
    remove_requested = pyqtSignal(object)
    use_requested = pyqtSignal(object)

    def __init__(self, mod_data, is_local=False, is_available=True, has_update=False, parent=None, installed_date=None):
        super().__init__(mod_data, parent)
        self.hide()
        self.use_button = None
        self.is_local = is_local
        self.is_available = is_available
        self.installed_date = installed_date
        self.has_update = has_update
        self.is_in_slot = False
        self.status = 'ready'
        if has_update:
            self.status = 'needs_update'
        self.frame_selector = 'installedMod'
        self.setObjectName('installedMod')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(120)
        self._init_ui()
        self._update_button_from_status()

    def _init_ui(self):
        super()._init_ui()
        self.title_layout.takeAt(self.title_layout.count() - 1)
        self.status_indicator = QLabel('●', self)
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_indicator()
        self.title_layout.addWidget(self.status_indicator)
        self.title_layout.addStretch()
        installed_date_text = self.installed_date or self.mod_data.created_date or 'N/A'
        date_label_text = tr('ui.created_label') if self.is_local else tr('ui.installed_label')
        installed_container = QWidget(self)
        installed_container_layout = QHBoxLayout(installed_container)
        installed_container_layout.setContentsMargins(0, 0, 0, 0)
        installed_container_layout.setSpacing(0)
        installed_label_title = QLabel(date_label_text, installed_container)
        installed_label_title.setObjectName('primaryText')
        installed_label_value = QLabel(f' {installed_date_text}', installed_container)
        installed_label_value.setObjectName('secondaryText')
        installed_container_layout.addWidget(installed_label_title)
        installed_container_layout.addWidget(installed_label_value)
        containers = [self.author_container, self.game_version_container, installed_container]
        for i, container in enumerate(containers):
            self.metadata_layout.addWidget(container)
            if i < len(containers) - 1:
                separator = QLabel('|', self)
                separator.setObjectName('secondaryText')
                self.metadata_layout.addWidget(separator)
        self.metadata_layout.addStretch()
        self.checkmark_label = QLabel('✓', self)
        self.checkmark_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.checkmark_label.setStyleSheet('font-size: 18px; font-weight: bold; color: #4CAF50;')
        self.checkmark_label.setFixedWidth(40)
        self.checkmark_label.setVisible(False)
        self.main_layout.addWidget(self.checkmark_label)
        self.actions_widget = QWidget(self)
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.use_button = QPushButton(tr('ui.use_button'), self.actions_widget)
        self.use_button.setObjectName('plaqueButtonInstall')
        self.use_button.clicked.connect(lambda: self.use_requested.emit(self.mod_data))
        actions_layout.addWidget(self.use_button)
        self.remove_button = QPushButton(tr('buttons.delete'), self.actions_widget)
        self.remove_button.setObjectName('plaqueButton')
        config = None
        if self.parent_app:
            if hasattr(self.parent_app, 'local_config'):
                config = self.parent_app.local_config
            elif hasattr(self.parent_app, 'app_state') and hasattr(self.parent_app.app_state, 'local_config'):
                config = self.parent_app.app_state.local_config
        text_color = get_theme_color(config, 'text', 'white') if config else 'white'
        self.remove_button.setStyleSheet(f'\n            QPushButton#plaqueButton {{\n                background-color: #F44336;\n                color: {text_color};\n            }}\n            QPushButton#plaqueButton:hover {{\n                background-color: #da190b;\n            }}\n        ')
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.mod_data))
        actions_layout.addWidget(self.remove_button)
        self.actions_widget.setVisible(False)
        self.main_layout.addWidget(self.actions_widget)
        self._update_style()

    def _update_indicator(self):
        style = 'font-size: 14px; font-weight: bold; margin-left: 5px;'
        if self.is_local:
            self.status_indicator.setStyleSheet(f'color: #FFD700; {style}')
            self.status_indicator.setToolTip(tr('defaults.local_mod'))
            return
        has_update_now = False
        try:
            has_update_now = self.has_update or self._mod_needs_update()
        except Exception:
            has_update_now = self.has_update
        if self.is_available and has_update_now:
            self.status_indicator.setStyleSheet(f'color: #FFA500; {style}')
            self.status_indicator.setToolTip(tr('tooltips.public_mod_update_available'))
        elif self.is_available:
            self.status_indicator.setStyleSheet(f'color: #4CAF50; {style}')
            self.status_indicator.setToolTip(tr('tooltips.public_mod_available'))
        else:
            self.status_indicator.setStyleSheet(f'color: #F44336; {style}')
            self.status_indicator.setToolTip(tr('tooltips.public_mod_unavailable'))

    def _mod_needs_update(self):
        if not self.parent_app or self.is_local:
            return False
        return self.parent_app.mod_manager.mod_has_update_available(self.mod_data)

    def _update_button_from_status(self):
        if not self.use_button:
            return
        if self.status == 'in_slot':
            self.use_button.setText(tr('ui.remove_button'))
            self.use_button.setStyleSheet('\n                QPushButton#plaqueButtonInstall {\n                    background-color: #FF9800;\n                    font-weight: bold;\n                }\n                QPushButton#plaqueButtonInstall:hover {\n                    background-color: #F57C00;\n                }\n            ')
        elif self.status == 'needs_update':
            self.use_button.setText(tr('ui.update_button'))
            self.use_button.setStyleSheet('\n                QPushButton#plaqueButtonInstall {\n                    background-color: #FF9800;\n                    font-weight: bold;\n                }\n                QPushButton#plaqueButtonInstall:hover {\n                    background-color: #F57C00;\n                }\n            ')
        else:
            self.use_button.setText(tr('ui.use_button'))
            self.use_button.setStyleSheet('\n                QPushButton#plaqueButtonInstall {\n                    background-color: #4CAF50;\n                    font-weight: bold;\n                }\n                QPushButton#plaqueButtonInstall:hover {\n                    background-color: #5cb85c;\n                }\n            ')

    def set_in_slot(self, in_slot):
        self.is_in_slot = in_slot
        if self.is_in_slot:
            self.status = 'in_slot'
        elif self._mod_needs_update():
            self.status = 'needs_update'
        else:
            self.status = 'ready'
        self._update_button_from_status()
        self._update_indicator()
        self._update_actions_visibility()

    def _update_actions_visibility(self):
        if not hasattr(self, 'actions_widget') or not hasattr(self, 'checkmark_label'):
            return
        if self.is_selected:
            self.actions_widget.setVisible(True)
            self.checkmark_label.setVisible(False)
        elif self.is_in_slot:
            self.actions_widget.setVisible(False)
            self.checkmark_label.setVisible(True)
        else:
            self.actions_widget.setVisible(False)
            self.checkmark_label.setVisible(False)

    def set_selected(self, selected):
        super().set_selected(selected)
        self._update_actions_visibility()

    def update_status(self):
        if self.is_in_slot:
            self.status = 'in_slot'
        elif self._mod_needs_update():
            self.status = 'needs_update'
        else:
            self.status = 'ready'
        self._update_button_from_status()
        self._update_indicator()
        self._update_actions_visibility()
