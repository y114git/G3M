import os
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame, QWidget
from PyQt6.QtGui import QPixmap, QColor
from config.constants import PLUGIN_STATUS_STYLES
from services.localization_service import tr
from ui.common.styling import get_theme_color, build_button_style, round_pixmap, get_border_radius, get_card_layout_scale, get_card_button_metrics, apply_stylesheet_if_changed, update_mod_widget_style
from ui.utils.ui_utils import UIAnimator


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
        self._metrics_cache_key = None
        self._last_icon_render_key = None
        self.setObjectName('pluginWidget')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(self._card_height())
        self.hide()
        self._init_ui()
        self._update_style()
        UIAnimator.fade_in(self, 200, getattr(self.parent_app, 'app_state', None) if getattr(self, 'parent_app', None) else None)

    def _resolve_theme_config(self):
        app_state = getattr(self.parent_app, 'app_state', None)
        return app_state.local_config if app_state and hasattr(app_state, 'local_config') else None

    def _layout_scale(self) -> float:
        return get_card_layout_scale(self._resolve_theme_config())

    def _icon_size(self) -> int:
        return max(64, int(round(80 * self._layout_scale())))

    def _card_height(self) -> int:
        return max(120, int(round(120 * self._layout_scale())))

    def _title_font_size(self) -> int:
        return max(14, int(round(16 * self._layout_scale())))

    def _apply_metrics(self):
        scale = self._layout_scale()
        margin = max(8, int(round(10 * scale)))
        spacing = max(10, int(round(15 * scale)))
        title_spacing = max(6, int(round(8 * scale)))
        metadata_spacing = max(8, int(round(10 * scale)))
        icon_size = self._icon_size() if hasattr(self, 'icon_label') and self.icon_label else None
        indicator_size = max(14, int(round(16 * scale))) if hasattr(self, 'status_indicator') and self.status_indicator else None
        version_spacing = max(4, int(round(5 * scale))) if hasattr(self, 'version_container') and self.version_container and self.version_container.layout() else None
        card_height = self._card_height()
        metrics_key = (margin, spacing, title_spacing, metadata_spacing, icon_size, indicator_size, version_spacing, card_height)
        if self._metrics_cache_key == metrics_key:
            return False
        if hasattr(self, 'main_layout') and self.main_layout:
            self.main_layout.setContentsMargins(margin, margin, margin, margin)
            self.main_layout.setSpacing(spacing)
        if hasattr(self, 'title_layout') and self.title_layout:
            self.title_layout.setSpacing(title_spacing)
        if hasattr(self, 'metadata_layout') and self.metadata_layout:
            self.metadata_layout.setSpacing(metadata_spacing)
        if hasattr(self, 'icon_label') and self.icon_label:
            self.icon_label.setFixedSize(icon_size, icon_size)
        if hasattr(self, 'status_indicator') and self.status_indicator:
            self.status_indicator.setFixedSize(indicator_size, indicator_size)
        if hasattr(self, 'version_container') and self.version_container and self.version_container.layout():
            self.version_container.layout().setSpacing(version_spacing)
        self.setFixedHeight(card_height)
        self._metrics_cache_key = metrics_key
        return True

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
        self.icon_label.setStyleSheet('border: none; background: transparent;')
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
        self.metadata_layout = metadata_layout
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
        self.toggle_button.setObjectName('cardButtonInstall')
        self.toggle_button.clicked.connect(lambda: self.toggle_requested.emit(self.plugin_name))
        actions_layout.addWidget(self.toggle_button)
        self.delete_button = QPushButton(tr('buttons.delete'), self.actions_widget)
        self.delete_button.setObjectName('cardButton')
        app_state = getattr(self.parent_app, 'app_state', None)
        config = app_state.local_config if app_state and hasattr(app_state, 'local_config') else None
        text_color = get_theme_color(config, 'text', '#e8e9eb')
        border = get_theme_color(config, 'border', '#039d5b')
        br = get_border_radius(config)
        self.delete_button.setStyleSheet(build_button_style('cardButton', '#F44336', '#da190b', text_color, border, border_radius=br))
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.plugin_name))
        actions_layout.addWidget(self.delete_button)
        self.actions_widget.setVisible(False)
        main_layout.addWidget(self.actions_widget)
        self.main_layout = main_layout
        self.title_layout = title_layout

    def _update_status_indicator(self):
        status = self.plugin_info.get('status', 'enabled')
        color, tooltip_key = PLUGIN_STATUS_STYLES.get(status, ('#F44336', 'plugins.status_broken'))
        font_size = max(12, int(round(14 * self._layout_scale())))
        apply_stylesheet_if_changed(self.status_indicator, f'color: {color}; font-size: {font_size}px; font-weight: bold;', cache_attr='_status_indicator_stylesheet_cache')
        self.status_indicator.setToolTip(tr(tooltip_key))

    def _update_toggle_button(self):
        status = self.plugin_info.get('status', 'enabled')
        app_state = getattr(self.parent_app, 'app_state', None)
        config = app_state.local_config if app_state and hasattr(app_state, 'local_config') else None
        border = get_theme_color(config, 'border', '#039d5b')
        br = get_border_radius(config)
        button_width, button_height, button_font_size = get_card_button_metrics(config)
        if status == 'enabled':
            self.toggle_button.setText(tr('plugins.disable'))
            apply_stylesheet_if_changed(self.toggle_button, build_button_style('cardButtonInstall', '#FF9800', '#F57C00', '#e8e9eb', border, width=button_width, height=button_height, font_size=button_font_size, border_radius=br), cache_attr='_toggle_button_stylesheet_cache')
        else:
            self.toggle_button.setText(tr('plugins.enable'))
            apply_stylesheet_if_changed(self.toggle_button, build_button_style('cardButtonInstall', '#4CAF50', '#5cb85c', '#e8e9eb', border, width=button_width, height=button_height, font_size=button_font_size, border_radius=br), cache_attr='_toggle_button_stylesheet_cache')

    def _update_style(self):
        self._apply_metrics()
        update_mod_widget_style(self, self.frame_selector, self.parent_app)
        if hasattr(self, 'icon_label'):
            apply_stylesheet_if_changed(self.icon_label, 'border: none; background: transparent;', cache_attr='_plugin_icon_label_stylesheet_cache')
            self._load_icon()
        config = self._resolve_theme_config()
        text_color = get_theme_color(config, 'text', '#e8e9eb')
        secondary_text_color = get_theme_color(config, 'secondary_text', '#6de985')
        title_font_size = self._title_font_size()
        if hasattr(self, 'name_label') and self.name_label:
            apply_stylesheet_if_changed(self.name_label, f'font-size: {title_font_size}px; font-weight: bold; color: {text_color};', cache_attr='_plugin_name_stylesheet_cache')
        if hasattr(self, 'version_label') and self.version_label:
            apply_stylesheet_if_changed(self.version_label, f'font-size: {title_font_size}px; color: {secondary_text_color};', cache_attr='_plugin_version_stylesheet_cache')
        if hasattr(self, 'delete_button') and self.delete_button:
            border = get_theme_color(config, 'border', '#039d5b')
            br = get_border_radius(config)
            button_width, button_height, button_font_size = get_card_button_metrics(config)
            apply_stylesheet_if_changed(self.delete_button, build_button_style('cardButton', '#F44336', '#da190b', text_color, border, width=button_width, height=button_height, font_size=button_font_size, border_radius=br), cache_attr='_delete_button_stylesheet_cache')
        self._update_toggle_button()
        self._update_status_indicator()

    def set_selected(self, selected: bool):
        if self.is_selected == selected:
            return
        self.is_selected = selected
        self._update_style()
        self._update_actions_visibility()

    def _update_actions_visibility(self):
        if hasattr(self, 'actions_widget'):
            should_show = bool(self.is_selected)
            if self.actions_widget.isVisible() != should_show:
                self.actions_widget.setVisible(should_show)

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
                self.version_label = QLabel(f'({version})', self.version_container)
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
        app_state = getattr(self.parent_app, 'app_state', None)
        config = app_state.local_config if app_state and hasattr(app_state, 'local_config') else None
        border_color = get_theme_color(config, 'border', '#039d5b')
        bg_color = get_theme_color(config, 'background', '#333')
        br = get_border_radius(config)
        bw = 2 if border_color else 0
        target_size = max(1, self.icon_label.width() or self._icon_size())
        icon_stat = None
        if icon_path and os.path.exists(icon_path):
            try:
                stat_result = os.stat(icon_path)
                icon_stat = (stat_result.st_mtime_ns, stat_result.st_size)
            except OSError:
                icon_stat = None
        icon_key = (icon_path, icon_stat, target_size, br, bw, border_color, bg_color)
        if self._last_icon_render_key == icon_key:
            return
        if hasattr(self, 'icon_label'):
            self.icon_label.clear()
            self.icon_label.setText('')
        if icon_path and os.path.exists(icon_path):
            try:
                pixmap = QPixmap()
                if pixmap.load(icon_path):
                    if not pixmap.isNull():
                        icon_size = min(pixmap.width(), pixmap.height())
                        if icon_size > 0:
                            cropped = pixmap.copy((pixmap.width() - icon_size) // 2, (pixmap.height() - icon_size) // 2, icon_size, icon_size)
                            scaled_pixmap = cropped.scaled(target_size, target_size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        else:
                            scaled_pixmap = pixmap.scaled(target_size, target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.icon_label.setPixmap(round_pixmap(scaled_pixmap, br, bw, border_color) if (br > 0 or bw > 0) else scaled_pixmap)
                        self.icon_label.setText('')
                        self._last_icon_render_key = icon_key
                        return
            except Exception as e:
                import logging
                logging.debug(f'PluginWidget: Error loading icon from {icon_path}: {e}')
        try:
            default_pixmap = QPixmap(target_size, target_size)
            default_pixmap.fill(QColor(bg_color))
            self.icon_label.setPixmap(round_pixmap(default_pixmap, br, bw, border_color) if (br > 0 or bw > 0) else default_pixmap)
            self.icon_label.setText('🔌')
            apply_stylesheet_if_changed(self.icon_label, f'font-size: {max(36, int(round(48 * self._layout_scale())))}px; border: none; background: transparent;', cache_attr='_plugin_icon_label_stylesheet_cache')
        except Exception:
            self.icon_label.setText('🔌')
            apply_stylesheet_if_changed(self.icon_label, f'font-size: {max(36, int(round(48 * self._layout_scale())))}px; border: none; background: transparent;', cache_attr='_plugin_icon_label_stylesheet_cache')
        self._last_icon_render_key = icon_key

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.plugin_name)
        super().mousePressEvent(event)
