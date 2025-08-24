from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from .base_mod_widget import BaseModWidget
from localization.manager import tr

class ModPlaqueWidget(BaseModWidget):
    install_requested = pyqtSignal(object)
    uninstall_requested = pyqtSignal(object)
    details_requested = pyqtSignal(object)

    def __init__(self, mod_data, parent=None):
        super().__init__(mod_data, parent)
        self.is_installed = False
        self.frame_selector = 'modPlaque'
        self.setObjectName('modPlaque')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(120)
        self._init_ui()
        self._update_style()
        self._check_installation_status()

    def _create_tags_layout_if_needed(self, info_layout):
        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 5, 0, 0)
        tags_layout.setSpacing(10)
        modtype = getattr(self.mod_data, 'modtype', 'deltarune')
        modtype_text = ''
        modtype_style = ''
        if modtype == 'deltarune':
            modtype_text = 'DELTARUNE'
            modtype_style = 'background-color: black; color: white; border: 1px solid white;'
        elif modtype == 'deltarunedemo':
            modtype_text = 'DELTARUNE DEMO'
            modtype_style = 'background-color: black; color: white; border: 1px solid lightgreen;'
        elif modtype == 'undertale':
            modtype_text = 'UNDERTALE'
            modtype_style = 'background-color: red; color: white; border: 1px solid red;'
        if modtype_text:
            modtype_label = QLabel(modtype_text)
            style_sheet = f'font-weight: bold; padding: 2px 5px; border-radius: 3px; {modtype_style}'
            modtype_label.setStyleSheet(style_sheet)
            tags_layout.addWidget(modtype_label)
        is_piracy_protected = getattr(self.mod_data, 'is_piracy_protected', False)
        is_patch = getattr(self.mod_data, 'is_xdelta', is_piracy_protected)
        if is_patch:
            patching_label = QLabel(tr('ui.patching_label'))
            patching_label.setStyleSheet('color: #2196F3; font-size: 14px;')
            tags_layout.addWidget(patching_label)
        else:
            replacement_label = QLabel(tr('ui.file_replacement_label'))
            replacement_label.setStyleSheet('color: #FF9800; font-size: 14px;')
            tags_layout.addWidget(replacement_label)
        if self.mod_data.is_verified:
            verified_label = QLabel(tr('ui.verified_label'))
            verified_label.setStyleSheet('color: #4CAF50; font-size: 14px;')
            tags_layout.addWidget(verified_label)
        tags_layout.addStretch()
        info_layout.addLayout(tags_layout)

    def _init_ui(self):
        super()._init_ui()
        downloads_label = QLabel(f'⤓ {self.mod_data.downloads}')
        downloads_label.setObjectName('secondaryText')
        downloads_label.setToolTip(tr('ui.downloads_tooltip'))
        downloads_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.title_layout.addWidget(downloads_label)
        created_date_text = self.mod_data.created_date or 'N/A'
        created_container = QWidget()
        created_container_layout = QHBoxLayout(created_container)
        created_container_layout.setContentsMargins(0, 0, 0, 0)
        created_container_layout.setSpacing(0)
        created_label_title = QLabel(tr('ui.created_label'))
        created_label_title.setObjectName('primaryText')
        created_label_value = QLabel(f' {created_date_text}')
        created_label_value.setObjectName('secondaryText')
        created_container_layout.addWidget(created_label_title)
        created_container_layout.addWidget(created_label_value)
        updated_date_text = self.mod_data.last_updated or 'N/A'
        updated_container = QWidget()
        updated_container_layout = QHBoxLayout(updated_container)
        updated_container_layout.setContentsMargins(0, 0, 0, 0)
        updated_container_layout.setSpacing(0)
        updated_label_title = QLabel(tr('ui.updated_label'))
        updated_label_title.setObjectName('primaryText')
        updated_label_value = QLabel(f' {updated_date_text}')
        updated_label_value.setObjectName('secondaryText')
        updated_container_layout.addWidget(updated_label_title)
        updated_container_layout.addWidget(updated_label_value)
        containers = [self.author_container, self.game_version_container, updated_container, created_container]
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
        self.details_button = QPushButton(tr('ui.details_button'))
        self.details_button.setObjectName('plaqueButton')
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self.mod_data))
        self.install_button = QPushButton(tr('ui.install_button'))
        self.install_button.setObjectName('plaqueButtonInstall')
        self.install_button.clicked.connect(self._on_install_button_clicked)
        actions_layout.addWidget(self.details_button)
        actions_layout.addWidget(self.install_button)
        self.actions_widget.setVisible(False)
        self.main_layout.addWidget(self.actions_widget)

    def _check_installation_status(self):
        if self.parent_app and hasattr(self.parent_app, '_is_mod_installed'):
            self.is_installed = self.parent_app._is_mod_installed(self.mod_data.key)
            self._update_install_button()

    def _update_install_button(self):
        if self.is_installed:
            self.install_button.setText(tr('ui.uninstall_button'))
            self.install_button.setObjectName('plaqueButtonUninstall')
            self.install_button.setStyleSheet('\n                QPushButton#plaqueButtonUninstall {\n                    background-color: #F44336;\n                    color: white;\n                    font-weight: bold;\n                    min-width: 110px;\n                    max-width: 110px;\n                    min-height: 35px;\n                    max-height: 35px;\n                    font-size: 15px;\n                    padding: 1px;\n                }\n                QPushButton#plaqueButtonUninstall:hover {\n                    background-color: #d32f2f;\n                }\n            ')
        else:
            self.install_button.setText(tr('ui.install_button'))
            self.install_button.setObjectName('plaqueButtonInstall')
            self.install_button.setStyleSheet('')

    def _on_install_button_clicked(self):
        if self.is_installed:
            self.uninstall_requested.emit(self.mod_data)
        else:
            self.install_requested.emit(self.mod_data)

    def update_installation_status(self):
        self._check_installation_status()