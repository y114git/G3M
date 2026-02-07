import os
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from PyQt6.QtGui import QPixmap, QColor
from services.localization_service import tr
from ui.common.styling import get_theme_color


class PluginWidget(QFrame):
    toggle_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    clicked = pyqtSignal(str)

    def __init__(self, plugin_info: dict, parent=None, parent_app=None):
        super().__init__(parent)
        self.plugin_info = plugin_info
        self.plugin_name = plugin_info.get('name', '')
        self.parent_app = parent_app
        self.is_selected = False
        self.frame_selector = 'pluginWidget'
        self.setObjectName('pluginWidget')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(120)
        self._init_ui()
        self._update_style()

    def _resolve_plugin_name(self, plugin_info: dict | None = None) -> str:
        info = plugin_info or self.plugin_info
        name_key = info.get('name_key')
        if name_key:
            name_text = tr(name_key)
            if name_text.startswith('[') and name_text.endswith(']'):
                plugin_id = info.get('plugin_id', '')
                if plugin_id and name_key.startswith(f'{plugin_id}.'):
                    plugin_name_key = name_key[len(f'{plugin_id}.'):]
                    plugin_tr = self.parent_app.lang_service.get_plugin_tr(plugin_id) if self.parent_app and hasattr(self.parent_app, 'lang_service') else None
                    if plugin_tr:
                        name_text = plugin_tr(plugin_name_key)
                        if name_text.startswith('[') and name_text.endswith(']'):
                            name_text = plugin_name_key
                    else:
                        name_text = plugin_name_key
                else:
                    name_text = name_key
        else:
            name_text = info.get('plugin_id', self.plugin_name)
        return name_text

    def _get_description_text(self, plugin_info: dict | None = None) -> str | None:
        info = plugin_info or self.plugin_info
        description = info.get('description')
        if description:
            description_text = str(description).strip()
            if description_text:
                if len(description_text) > 200:
                    return f'{description_text[:197]}...'
                return description_text
        return None

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName('pluginIcon')
        self.icon_label.setFixedSize(80, 80)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet('border: 2px solid #fff; background-color: #333;')
        self._load_icon()
        main_layout.addWidget(self.icon_label)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_layout = QHBoxLayout()
        name_text = self._resolve_plugin_name()
        self.name_label = QLabel(name_text, self)
        self.name_label.setStyleSheet('font-size: 16px; font-weight: bold;')
        title_layout.addWidget(self.name_label)
        self.version_container = QWidget(self)
        version_container_layout = QHBoxLayout(self.version_container)
        version_container_layout.setContentsMargins(0, 0, 0, 0)
        version_container_layout.setSpacing(5)
        version = self.plugin_info.get('version')
        self.version_label = None
        if version:
            self.version_label = QLabel(f'({version})', self.version_container)
            self.version_label.setObjectName('versionLabel')
            self.version_label.setStyleSheet('font-size: 16px;')
            version_container_layout.addWidget(self.version_label)
        self.status_indicator = QLabel('●', self.version_container)
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_status_indicator()
        version_container_layout.addWidget(self.status_indicator)
        title_layout.addWidget(self.version_container)
        title_layout.addStretch()
        info_layout.addLayout(title_layout)
        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(10)
        author = self.plugin_info.get('author')
        self.author_container = None
        self.author_label_value = None
        if author:
            self.author_container = QWidget(self)
            author_container_layout = QHBoxLayout(self.author_container)
            author_container_layout.setContentsMargins(0, 0, 0, 0)
            author_container_layout.setSpacing(0)
            self.author_label_title = QLabel(tr('ui.author_label'), self.author_container)
            self.author_label_title.setObjectName('primaryText')
            self.author_label_value = QLabel(f' {author}', self.author_container)
            self.author_label_value.setObjectName('secondaryText')
            author_container_layout.addWidget(self.author_label_title)
            author_container_layout.addWidget(self.author_label_value)
            metadata_layout.addWidget(self.author_container)
        installed_date = self.plugin_info.get('installed_date')
        self.installed_container = None
        self.installed_label_title = None
        if installed_date:
            self.installed_container = QWidget(self)
            installed_container_layout = QHBoxLayout(self.installed_container)
            installed_container_layout.setContentsMargins(0, 0, 0, 0)
            installed_container_layout.setSpacing(0)
            self.installed_label_title = QLabel(tr('ui.installed_label'), self.installed_container)
            self.installed_label_title.setObjectName('primaryText')
            installed_label_value = QLabel(f' {installed_date}', self.installed_container)
            installed_label_value.setObjectName('secondaryText')
            installed_container_layout.addWidget(self.installed_label_title)
            installed_container_layout.addWidget(installed_label_value)
            metadata_layout.addWidget(self.installed_container)
        metadata_layout.addStretch()
        info_layout.addLayout(metadata_layout)
        description_text = self._get_description_text()
        self.description_label = QLabel(description_text or tr('ui.no_description'), self)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName('secondaryText')
        if not description_text:
            self.description_label.setStyleSheet('font-style: italic;')
        info_layout.addWidget(self.description_label)
        error = self.plugin_info.get('error')
        if error:
            error_label = QLabel(f'Error: {error}', self)
            error_label.setStyleSheet('color: #F44336; font-size: 12px;')
            error_label.setWordWrap(True)
            info_layout.addWidget(error_label)
        info_layout.addStretch()
        main_layout.addLayout(info_layout, 1)
        self.actions_widget = QWidget(self)
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(5)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toggle_button = QPushButton(self.actions_widget)
        self._update_toggle_button()
        self.toggle_button.setObjectName('plaqueButtonInstall')
        self.toggle_button.clicked.connect(lambda: self.toggle_requested.emit(self.plugin_name))
        actions_layout.addWidget(self.toggle_button)
        self.delete_button = QPushButton(tr('buttons.delete'), self.actions_widget)
        self.delete_button.setObjectName('plaqueButton')
        text_color = get_theme_color(self.parent_app.app_state.local_config, 'text', 'white') if self.parent_app and hasattr(self.parent_app, 'app_state') else 'white'
        self.delete_button.setStyleSheet(f'\n            QPushButton#plaqueButton {{\n                background-color: #F44336;\n                color: {text_color};\n            }}\n            QPushButton#plaqueButton:hover {{\n                background-color: #da190b;\n            }}\n        ')
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.plugin_name))
        actions_layout.addWidget(self.delete_button)
        self.actions_widget.setVisible(False)
        main_layout.addWidget(self.actions_widget)
        self.main_layout = main_layout
        self.title_layout = title_layout

    _STATUS_STYLES = {'enabled': ('#4CAF50', 'plugins.status_enabled'), 'disabled': ('#FFA500', 'plugins.status_disabled')}

    def _update_status_indicator(self):
        status = self.plugin_info.get('status', 'enabled')
        color, tooltip_key = self._STATUS_STYLES.get(status, ('#F44336', 'plugins.status_broken'))
        self.status_indicator.setStyleSheet(f'color: {color}; font-size: 14px; font-weight: bold;')
        self.status_indicator.setToolTip(tr(tooltip_key))

    def _update_toggle_button(self):
        status = self.plugin_info.get('status', 'enabled')
        if status == 'enabled':
            self.toggle_button.setText(tr('plugins.disable'))
            self.toggle_button.setStyleSheet('\n                QPushButton#plaqueButtonInstall {\n                    background-color: #FF9800;\n                    font-weight: bold;\n                }\n                QPushButton#plaqueButtonInstall:hover {\n                    background-color: #F57C00;\n                }\n            ')
        else:
            self.toggle_button.setText(tr('plugins.enable'))
            self.toggle_button.setStyleSheet('\n                QPushButton#plaqueButtonInstall {\n                    background-color: #4CAF50;\n                    font-weight: bold;\n                }\n                QPushButton#plaqueButtonInstall:hover {\n                    background-color: #5cb85c;\n                }\n            ')

    def _update_style(self):
        from ui.common.styling import update_mod_widget_style
        update_mod_widget_style(self, self.frame_selector, self.parent_app)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()
        self._update_actions_visibility()

    def _update_actions_visibility(self):
        if hasattr(self, 'actions_widget'):
            self.actions_widget.setVisible(self.is_selected)

    def update_plugin_info(self, plugin_info: dict):
        self.plugin_info = plugin_info
        self._update_status_indicator()
        self._update_toggle_button()
        if hasattr(self, 'name_label'):
            self.name_label.setText(self._resolve_plugin_name())
        version = self.plugin_info.get('version')
        if hasattr(self, 'version_label') and self.version_label:
            if version:
                self.version_label.setText(f'({version})')
                self.version_label.setVisible(True)
            else:
                self.version_label.setVisible(False)
        elif version and hasattr(self, 'version_container'):
            version_container_layout = self.version_container.layout()
            if version_container_layout and isinstance(version_container_layout, QHBoxLayout):
                self.version_label = QLabel(f'({version})')
                self.version_label.setObjectName('versionLabel')
                self.version_label.setStyleSheet('font-size: 16px;')
                version_container_layout.insertWidget(0, self.version_label)
        author = self.plugin_info.get('author')
        if hasattr(self, 'author_container') and self.author_container:
            if author:
                self.author_container.setVisible(True)
                if hasattr(self, 'author_label_value') and self.author_label_value:
                    self.author_label_value.setText(f' {author}')
            else:
                self.author_container.setVisible(False)
        elif author:
            layout = self.layout()
            if layout is not None:
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item and item.layout():
                        metadata_layout = item.layout()
                        if isinstance(metadata_layout, QHBoxLayout):
                            self.author_container = QWidget()
                            author_container_layout = QHBoxLayout(self.author_container)
                            author_container_layout.setContentsMargins(0, 0, 0, 0)
                            author_container_layout.setSpacing(0)
                            self.author_label_title = QLabel(tr('ui.author_label'))
                            self.author_label_title.setObjectName('primaryText')
                            self.author_label_value = QLabel(f' {author}')
                            self.author_label_value.setObjectName('secondaryText')
                            author_container_layout.addWidget(self.author_label_title)
                            author_container_layout.addWidget(self.author_label_value)
                            if hasattr(self, 'installed_container') and self.installed_container:
                                metadata_layout.insertWidget(metadata_layout.indexOf(self.installed_container), self.author_container)
                            else:
                                metadata_layout.insertWidget(0, self.author_container)
                            break
        if hasattr(self, 'description_label'):
            description_text = self._get_description_text()
            if description_text:
                self.description_label.setText(description_text)
                self.description_label.setStyleSheet('')
                self.description_label.setVisible(True)
            else:
                self.description_label.setText(tr('ui.no_description'))
                self.description_label.setStyleSheet('font-style: italic;')
                self.description_label.setVisible(True)
            self._update_style()
        self._load_icon()

    def relocalize_texts(self):
        if hasattr(self, 'name_label'):
            self.name_label.setText(self._resolve_plugin_name())
        if hasattr(self, 'author_label_title') and self.author_label_title:
            self.author_label_title.setText(tr('ui.author_label'))
        if hasattr(self, 'installed_label_title') and self.installed_label_title:
            self.installed_label_title.setText(tr('ui.installed_label'))
        if hasattr(self, 'delete_button'):
            self.delete_button.setText(tr('buttons.delete'))
        self._update_toggle_button()
        self._update_status_indicator()
        if hasattr(self, 'description_label'):
            if not self._get_description_text():
                self.description_label.setText(tr('ui.no_description'))

    def _load_icon(self):
        if hasattr(self, 'icon_label'):
            self.icon_label.clear()
            self.icon_label.setText('')
        plugin_path = self.plugin_info.get('path', '')
        icon_path = None
        if plugin_path and os.path.isdir(plugin_path):
            icon_extensions = ['.png', '.jpg', '.jpeg', '.ico', '.bmp', '.gif', '.svg']
            for prefix in ('_icon', 'icon'):
                for ext in icon_extensions:
                    potential_icon = os.path.join(plugin_path, f'{prefix}{ext}')
                    if os.path.isfile(potential_icon):
                        icon_path = potential_icon
                        break
                if icon_path:
                    break
        if icon_path and os.path.exists(icon_path):
            try:
                pixmap = QPixmap()
                if pixmap.load(icon_path):
                    if not pixmap.isNull():
                        icon_size = min(pixmap.width(), pixmap.height())
                        if icon_size > 0:
                            cropped = pixmap.copy((pixmap.width() - icon_size) // 2, (pixmap.height() - icon_size) // 2, icon_size, icon_size)
                            scaled_pixmap = cropped.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        else:
                            scaled_pixmap = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.icon_label.setPixmap(scaled_pixmap)
                        self.icon_label.setText('')
                        return
            except Exception as e:
                import logging
                logging.debug(f'PluginWidget: Error loading icon from {icon_path}: {e}')
        try:
            default_pixmap = QPixmap(80, 80)
            default_pixmap.fill(QColor('#333'))
            self.icon_label.setPixmap(default_pixmap)
            self.icon_label.setText('🔌')
            self.icon_label.setStyleSheet('font-size: 48px; border: 2px solid #fff; background-color: #333;')
        except Exception:
            self.icon_label.setText('🔌')
            self.icon_label.setStyleSheet('font-size: 48px; border: 2px solid #fff; background-color: #333;')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.plugin_name)
        super().mousePressEvent(event)
