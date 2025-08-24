from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from .base_mod_widget import BaseModWidget
from localization.manager import tr

class InstalledModWidget(BaseModWidget):
    remove_requested = pyqtSignal(object)
    use_requested = pyqtSignal(object)

    def __init__(self, mod_data, is_local=False, is_available=True, has_update=False, parent=None):
        super().__init__(mod_data, parent)
        self.use_button = None
        self.is_local = is_local
        self.is_available = is_available
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
        self._update_style()
        self._update_button_from_status()

    def _init_ui(self):
        super()._init_ui()
        self.title_layout.takeAt(self.title_layout.count() - 1)
        indicator = QLabel('●')
        indicator.setFixedSize(16, 16)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style = 'font-size: 14px; font-weight: bold; margin-left: 5px;'
        if self.is_local:
            indicator.setStyleSheet(f'color: #FFD700; {style}')
            indicator.setToolTip(tr('tooltips.local_mod'))
        elif self.is_available and self.has_update:
            indicator.setStyleSheet(f'color: #FFA500; {style}')
            indicator.setToolTip(tr('tooltips.public_mod_update_available'))
        elif self.is_available:
            indicator.setStyleSheet(f'color: #4CAF50; {style}')
            indicator.setToolTip(tr('tooltips.public_mod_available'))
        else:
            indicator.setStyleSheet(f'color: #F44336; {style}')
            indicator.setToolTip(tr('tooltips.public_mod_unavailable'))
        self.title_layout.addWidget(indicator)
        self.title_layout.addStretch()
        installed_date_text = 'N/A'
        try:
            if self.parent_app and hasattr(self.parent_app, '_get_mod_config_by_key'):
                cfg = self.parent_app._get_mod_config_by_key(self.mod_data.key)
                if isinstance(cfg, dict):
                    installed_date_text = cfg.get('installed_date') or cfg.get('created_date') or 'N/A'
        except Exception:
            installed_date_text = 'N/A'
        date_label_text = tr('ui.created_label') if self.is_local else tr('ui.installed_label')
        installed_container = QWidget()
        installed_container_layout = QHBoxLayout(installed_container)
        installed_container_layout.setContentsMargins(0, 0, 0, 0)
        installed_container_layout.setSpacing(0)
        installed_label_title = QLabel(date_label_text)
        installed_label_title.setObjectName('primaryText')
        installed_label_value = QLabel(f' {installed_date_text}')
        installed_label_value.setObjectName('secondaryText')
        installed_container_layout.addWidget(installed_label_title)
        installed_container_layout.addWidget(installed_label_value)
        containers = [self.author_container, self.game_version_container, installed_container]
        for i, container in enumerate(containers):
            self.metadata_layout.addWidget(container)
            if i < len(containers) - 1:
                separator = QLabel('|')
                separator.setObjectName('secondaryText')
                self.metadata_layout.addWidget(separator)
        self.metadata_layout.addStretch()
        self.actions_widget = QWidget()
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.use_button = QPushButton(tr('ui.use_button'))
        self.use_button.setObjectName('plaqueButtonInstall')
        self.use_button.clicked.connect(lambda: self.use_requested.emit(self.mod_data))
        actions_layout.addWidget(self.use_button)
        self.remove_button = QPushButton(tr('ui.delete_button'))
        self.remove_button.setObjectName('plaqueButton')
        self.remove_button.setStyleSheet('\n            QPushButton#plaqueButton {\n                background-color: #F44336;\n                color: white;\n            }\n            QPushButton#plaqueButton:hover {\n                background-color: #da190b;\n            }\n        ')
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.mod_data))
        actions_layout.addWidget(self.remove_button)
        self.actions_widget.setVisible(False)
        self.main_layout.addWidget(self.actions_widget)

    def _mod_needs_update(self):
        if not self.parent_app or self.is_local:
            return False
        needs_update = any((self.parent_app._mod_has_files_for_chapter(self.mod_data, i) and self.parent_app._get_mod_status_for_chapter(self.mod_data, i) == 'update' for i in range(5)))
        return needs_update

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

    def update_status(self):
        if self.is_in_slot:
            self.status = 'in_slot'
        elif self._mod_needs_update():
            self.status = 'needs_update'
        else:
            self.status = 'ready'
        self._update_button_from_status()