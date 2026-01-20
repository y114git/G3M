from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget
from ui.common.styling import load_mod_icon_universal, update_mod_widget_style, get_theme_color
from managers.localization_manager import tr


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
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName('modIcon')
        self.icon_label.setFixedSize(80, 80)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_icon()
        main_layout.addWidget(self.icon_label)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_layout = QHBoxLayout()
        self.name_label = QLabel(self.mod_data.name, self)
        self.name_label.setObjectName('primaryText')
        self.name_label.setStyleSheet('font-size: 16px; font-weight: bold;')
        title_layout.addWidget(self.name_label)
        mod_version = self.mod_data.version
        if mod_version and '|' in mod_version:
            mod_version = mod_version.split('|', 1)[0]
        version_text = mod_version or 'N/A'
        version_label = QLabel(f'({version_text})', self)
        version_label.setObjectName('versionLabel')
        version_label.setStyleSheet('font-size: 16px;')
        title_layout.addWidget(version_label)
        title_layout.addStretch()
        self.title_layout = title_layout
        info_layout.addLayout(title_layout)
        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(10)
        author_text = self.mod_data.author or tr('defaults.unknown')
        author_container = QWidget(self)
        author_container_layout = QHBoxLayout(author_container)
        author_container_layout.setContentsMargins(0, 0, 0, 0)
        author_container_layout.setSpacing(0)
        self.author_label_title = QLabel(tr('ui.author_label'), author_container)
        self.author_label_title.setObjectName('primaryText')
        author_label_value = QLabel(f' {author_text}', author_container)
        author_label_value.setObjectName('secondaryText')
        author_container_layout.addWidget(self.author_label_title)
        author_container_layout.addWidget(author_label_value)
        game_version_text = self.mod_data.game_version or 'N/A'
        game_version_container = QWidget(self)
        game_version_container_layout = QHBoxLayout(game_version_container)
        game_version_container_layout.setContentsMargins(0, 0, 0, 0)
        game_version_container_layout.setSpacing(0)
        self.game_version_label_title = QLabel(tr('ui.game_version_label'), game_version_container)
        self.game_version_label_title.setObjectName('primaryText')
        game_version_label_value = QLabel(f' {game_version_text}', game_version_container)
        game_version_label_value.setObjectName('secondaryText')
        game_version_container_layout.addWidget(self.game_version_label_title)
        game_version_container_layout.addWidget(game_version_label_value)
        self.author_container = author_container
        self.game_version_container = game_version_container
        self.metadata_layout = metadata_layout
        info_layout.addLayout(metadata_layout)
        tagline_text = self.mod_data.tagline or tr('ui.no_description')
        try:
            mod_key = getattr(self.mod_data, 'key', None) or getattr(self.mod_data, 'mod_key', None)
            if mod_key and mod_key.startswith('gb_'):
                has_full = getattr(self.mod_data, 'has_full_metadata', True)
                if not has_full:
                    placeholder = tr('ui.loading_placeholder')
                    tagline_text = placeholder
        except Exception:
            pass
        if len(tagline_text) > 200:
            tagline_text = tagline_text[:197] + '...'
        self.tagline_label = QLabel(tagline_text, self)
        self.tagline_label.setWordWrap(True)
        self.tagline_label.setObjectName('secondaryText')
        info_layout.addWidget(self.tagline_label)
        self._create_tags_layout_if_needed(info_layout)
        info_layout.addStretch()
        main_layout.addLayout(info_layout, 1)
        self.main_layout = main_layout

    def _create_tags_layout_if_needed(self, info_layout):
        pass

    def _load_icon(self):
        load_mod_icon_universal(self.icon_label, self.mod_data, 80)

    def _resolve_theme_config(self):
        if self.parent_app:
            if hasattr(self.parent_app, 'local_config'):
                return self.parent_app.local_config
            if hasattr(self.parent_app, 'app_state') and hasattr(self.parent_app.app_state, 'local_config'):
                return self.parent_app.app_state.local_config
        return None

    def _update_style(self):
        if self.frame_selector:
            update_mod_widget_style(self, self.frame_selector, self.parent_app)
        config = self._resolve_theme_config()
        if config:
            text_color = get_theme_color(config, 'text', 'white')
            if hasattr(self, 'name_label') and self.name_label:
                self.name_label.setStyleSheet(f'font-size: 16px; font-weight: bold; color: {text_color};')
            if hasattr(self, 'author_label_title') and self.author_label_title:
                self.author_label_title.setStyleSheet(f'color: {text_color};')
            if hasattr(self, 'game_version_label_title') and self.game_version_label_title:
                self.game_version_label_title.setStyleSheet(f'color: {text_color};')

    def update_labels_text(self):
        if hasattr(self, 'author_label_title') and self.author_label_title:
            self.author_label_title.setText(tr('ui.author_label'))
        if hasattr(self, 'game_version_label_title') and self.game_version_label_title:
            self.game_version_label_title.setText(tr('ui.game_version_label'))

    def set_selected(self, selected):
        self.is_selected = selected
        if hasattr(self, '_update_actions_visibility'):
            self._update_actions_visibility()
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
