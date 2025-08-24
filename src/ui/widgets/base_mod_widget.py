from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget
from ui.styling import load_mod_icon_universal, update_mod_widget_style
from localization.manager import tr

class BaseModWidget(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, mod_data, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data
        self.is_selected = False
        self.parent_app = parent
        self.frame_selector = ''

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        self.icon_label = QLabel()
        self.icon_label.setObjectName('modIcon')
        self.icon_label.setFixedSize(80, 80)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_icon()
        main_layout.addWidget(self.icon_label)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_layout = QHBoxLayout()
        name_label = QLabel(self.mod_data.name)
        name_label.setStyleSheet('font-size: 16px; font-weight: bold;')
        title_layout.addWidget(name_label)
        if self.mod_data.version and '|' in self.mod_data.version:
            mod_version = self.mod_data.version.split('|')[0]
        else:
            mod_version = self.mod_data.version
        version_text = mod_version or 'N/A'
        version_label = QLabel(f'({version_text})')
        version_label.setObjectName('versionLabel')
        version_label.setStyleSheet('font-size: 16px;')
        title_layout.addWidget(version_label)
        title_layout.addStretch()
        self.title_layout = title_layout
        info_layout.addLayout(title_layout)
        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(10)
        author_text = self.mod_data.author or tr('ui.unknown_author')
        author_container = QWidget()
        author_container_layout = QHBoxLayout(author_container)
        author_container_layout.setContentsMargins(0, 0, 0, 0)
        author_container_layout.setSpacing(0)
        author_label_title = QLabel(tr('ui.author_label'))
        author_label_title.setObjectName('primaryText')
        author_label_value = QLabel(f' {author_text}')
        author_label_value.setObjectName('secondaryText')
        author_container_layout.addWidget(author_label_title)
        author_container_layout.addWidget(author_label_value)
        game_version_text = self.mod_data.game_version or 'N/A'
        game_version_container = QWidget()
        game_version_container_layout = QHBoxLayout(game_version_container)
        game_version_container_layout.setContentsMargins(0, 0, 0, 0)
        game_version_container_layout.setSpacing(0)
        game_version_label_title = QLabel(tr('ui.game_version_label'))
        game_version_label_title.setObjectName('primaryText')
        game_version_label_value = QLabel(f' {game_version_text}')
        game_version_label_value.setObjectName('secondaryText')
        game_version_container_layout.addWidget(game_version_label_title)
        game_version_container_layout.addWidget(game_version_label_value)
        self.author_container = author_container
        self.game_version_container = game_version_container
        self.metadata_layout = metadata_layout
        info_layout.addLayout(metadata_layout)
        tagline_text = self.mod_data.tagline or tr('ui.no_description')
        if len(tagline_text) > 200:
            tagline_text = tagline_text[:197] + '...'
        tagline_label = QLabel(tagline_text)
        tagline_label.setWordWrap(True)
        tagline_label.setObjectName('secondaryText')
        info_layout.addWidget(tagline_label)
        self._create_tags_layout_if_needed(info_layout)
        info_layout.addStretch()
        main_layout.addLayout(info_layout, 1)
        self.main_layout = main_layout

    def _create_tags_layout_if_needed(self, info_layout):
        pass

    def _load_icon(self):
        load_mod_icon_universal(self.icon_label, self.mod_data, 80)

    def _update_style(self):
        if self.frame_selector:
            update_mod_widget_style(self, self.frame_selector, self.parent_app)

    def set_selected(self, selected):
        self.is_selected = selected
        actions_widget = getattr(self, 'actions_widget', None)
        if actions_widget:
            actions_widget.setVisible(selected)
        self._update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mod_data)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            details_requested = getattr(self, 'details_requested', None)
            if details_requested:
                details_requested.emit(self.mod_data)
        super().mouseDoubleClickEvent(event)