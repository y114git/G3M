from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget
from ui.common.styling import load_mod_icon_universal, update_mod_widget_style, get_theme_color, get_border_radius
from services.localization_service import tr
from utils.mod_utils import get_mod_key


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
        category_text = getattr(self.mod_data, 'gamebanana_category', None) or 'N/A'
        category_container = QWidget(self)
        category_container_layout = QHBoxLayout(category_container)
        category_container_layout.setContentsMargins(0, 0, 0, 0)
        category_container_layout.setSpacing(0)
        self.category_label_title = QLabel(tr('ui.category_label'), category_container)
        self.category_label_title.setObjectName('primaryText')
        category_label_value = QLabel(f' {category_text}', category_container)
        category_label_value.setObjectName('secondaryText')
        category_container_layout.addWidget(self.category_label_title)
        category_container_layout.addWidget(category_label_value)
        self.author_container = author_container
        self.category_container = category_container
        self.metadata_layout = metadata_layout
        info_layout.addLayout(metadata_layout)
        tagline_text = self.mod_data.tagline or tr('ui.no_description')
        try:
            mod_key = get_mod_key(self.mod_data)
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

    def _resolve_local_icon_fallback(self):
        key = get_mod_key(self.mod_data)
        if not key or not key.startswith('gb_'):
            return None
        app = self.parent_app
        if not app or not hasattr(app, 'mod_service'):
            return None
        try:
            folder = app.mod_service.get_mod_folder_path(key)
            if not folder:
                return None
            config = app.mod_service.get_mod_config(key)
            if not config:
                return None
            from utils.mod_utils import resolve_mod_icon
            return resolve_mod_icon(config, folder)
        except Exception:
            return None

    def _load_icon(self):
        config = self._resolve_theme_config()
        br = get_border_radius(config)
        bc = get_theme_color(config, 'border', '#039d5b') if config else None
        bw = 2 if bc else 0
        self.icon_label.setStyleSheet('border: none; background: transparent;')
        load_mod_icon_universal(self.icon_label, self.mod_data, 80, local_fallback=self._resolve_local_icon_fallback(), border_radius=br, border_width=bw, border_color=bc)

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
        if hasattr(self, 'icon_label'):
            self._load_icon()
        config = self._resolve_theme_config()
        if config:
            text_color = get_theme_color(config, 'text', '#e8e9eb')
            if hasattr(self, 'name_label') and self.name_label:
                try:
                    self.name_label.setStyleSheet(f'font-size: 16px; font-weight: bold; color: {text_color};')
                except RuntimeError:
                    pass
            if hasattr(self, 'author_label_title') and self.author_label_title:
                try:
                    self.author_label_title.setStyleSheet(f'color: {text_color};')
                except RuntimeError:
                    pass
            if hasattr(self, 'category_label_title') and self.category_label_title:
                try:
                    self.category_label_title.setStyleSheet(f'color: {text_color};')
                except RuntimeError:
                    pass

    def update_labels_text(self):
        if hasattr(self, 'author_label_title') and self.author_label_title:
            try:
                self.author_label_title.setText(tr('ui.author_label'))
            except RuntimeError:
                pass
        if hasattr(self, 'category_label_title') and self.category_label_title:
            try:
                self.category_label_title.setText(tr('ui.category_label'))
            except RuntimeError:
                pass

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
