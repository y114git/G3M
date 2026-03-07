import logging
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from services.localization_service import tr
from ui.common.styling import get_theme_color, get_border_radius, load_mod_icon_universal
from utils.mod_utils import get_mod_key
from .mod_card_widget import ModCardWidget


class SearchModCardWidget(ModCardWidget):
    BASE_CARD_WIDTH = 342
    BASE_MEDIA_WIDTH = 311
    BASE_MEDIA_HEIGHT = 185
    BASE_SPACING = 22
    BASE_SIDE_PADDING = 14

    @classmethod
    def layout_scale_for_config(cls, config) -> float:
        raw_scale = 1.0
        try:
            if config and hasattr(config, 'get'):
                raw_scale = float(config.get('ui_scale', 1.0) or 1.0)
        except Exception:
            raw_scale = 1.0
        return max(0.82, min(1.35, 1.0 + (raw_scale - 1.0) * 0.55))

    @classmethod
    def card_width_for_config(cls, config) -> int:
        return max(300, int(cls.BASE_CARD_WIDTH * cls.layout_scale_for_config(config)))

    @classmethod
    def media_size_for_config(cls, config) -> tuple[int, int]:
        scale = cls.layout_scale_for_config(config)
        return max(280, int(cls.BASE_MEDIA_WIDTH * scale)), max(156, int(cls.BASE_MEDIA_HEIGHT * scale))

    @classmethod
    def grid_spacing_for_config(cls, config) -> int:
        return max(16, int(cls.BASE_SPACING * cls.layout_scale_for_config(config)))

    @classmethod
    def side_padding_for_config(cls, config) -> int:
        return max(8, int(cls.BASE_SIDE_PADDING * cls.layout_scale_for_config(config)))

    def __init__(self, mod_data, parent=None, parent_app=None):
        self._last_visual_source = None
        self._full_name_text = getattr(mod_data, 'name', '') or ''
        config = self._resolve_layout_config(parent, parent_app)
        self._card_width = self.card_width_for_config(config)
        self._media_width, self._media_height = self.media_size_for_config(config)
        super().__init__(mod_data, parent=parent, parent_app=parent_app)
        self.setMinimumWidth(self._card_width)
        self.setMaximumWidth(self._card_width)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.MinimumExpanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._last_visual_source = self._get_visual_source_key()
        self._apply_metrics()
        self._update_name_text()
        self._update_tagline_text()
        self._update_updated_label()
        self._update_actions_visibility()

    @staticmethod
    def _resolve_layout_config(parent, parent_app):
        for source in (parent_app, parent):
            if source is None:
                continue
            if hasattr(source, 'local_config'):
                return source.local_config
            app_state = getattr(source, 'app_state', None)
            if app_state and hasattr(app_state, 'local_config'):
                return app_state.local_config
        return None

    def _apply_metrics(self):
        config = self._resolve_theme_config()
        scale = self.layout_scale_for_config(config)
        self._card_width = self.card_width_for_config(config)
        self._media_width, self._media_height = self.media_size_for_config(config)
        side_padding = max(10, int(round(14 * scale)))
        layout_spacing = max(8, int(round(10 * scale)))
        metadata_spacing = max(8, int(round(10 * scale)))
        expanded_top_margin = max(4, int(round(6 * scale)))
        expanded_spacing = max(6, int(round(8 * scale)))
        content_width = max(80, self._card_width - side_padding * 2 - 4)
        if hasattr(self, 'icon_label'):
            self.icon_label.setFixedSize(self._media_width, self._media_height)
        if hasattr(self, 'main_layout'):
            self.main_layout.setContentsMargins(side_padding, side_padding, side_padding, side_padding)
            self.main_layout.setSpacing(layout_spacing)
        if hasattr(self, 'metadata_layout'):
            self.metadata_layout.setSpacing(metadata_spacing)
        if hasattr(self, 'expanded_widget') and self.expanded_widget.layout():
            self.expanded_widget.layout().setContentsMargins(0, expanded_top_margin, 0, 0)
            self.expanded_widget.layout().setSpacing(expanded_spacing)
        if hasattr(self, 'actions_widget') and self.actions_widget.layout():
            self.actions_widget.layout().setSpacing(metadata_spacing)
        if hasattr(self, 'name_label'):
            self.name_label.setMaximumWidth(content_width)
        if hasattr(self, 'metadata_widget'):
            self.metadata_widget.setMaximumWidth(content_width)
        if hasattr(self, 'expanded_widget'):
            self.expanded_widget.setMaximumWidth(content_width)
        if hasattr(self, 'tagline_label'):
            self.tagline_label.setMaximumWidth(content_width)
        self.setMinimumWidth(self._card_width)
        self.setMaximumWidth(self._card_width)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._refresh_card_geometry()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(14, 14, 14, 14)
        self.main_layout.setSpacing(10)
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName('modIcon')
        self.icon_label.setFixedSize(self._media_width, self._media_height)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_icon()
        self.main_layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.name_label = QLabel(self)
        self.name_label.setObjectName('primaryText')
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet('font-size: 18px; font-weight: bold;')
        self.main_layout.addWidget(self.name_label)
        metadata_widget = QWidget(self)
        metadata_layout = QHBoxLayout(metadata_widget)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(10)
        metadata_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.metadata_layout = metadata_layout
        self.downloads_label = QLabel(self)
        self.downloads_label.setObjectName('secondaryText')
        self.downloads_label.setToolTip(tr('ui.downloads_tooltip'))
        self.updated_label = QLabel(self)
        self.updated_label.setObjectName('secondaryText')
        self.updated_label.setToolTip(tr('ui.updated_label'))
        separator = QLabel('|', metadata_widget)
        separator.setObjectName('secondaryText')
        metadata_layout.addWidget(self.downloads_label)
        metadata_layout.addWidget(separator)
        metadata_layout.addWidget(self.updated_label)
        self.metadata_widget = metadata_widget
        self.main_layout.addWidget(metadata_widget)
        self.expanded_widget = QWidget(self)
        self.expanded_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        expanded_layout = QVBoxLayout(self.expanded_widget)
        expanded_layout.setContentsMargins(0, 6, 0, 0)
        expanded_layout.setSpacing(8)
        expanded_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.expanded_layout = expanded_layout
        self.tagline_label = QLabel(self.expanded_widget)
        self.tagline_label.setObjectName('secondaryText')
        self.tagline_label.setWordWrap(True)
        self.tagline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        expanded_layout.addWidget(self.tagline_label)
        self.actions_widget = QWidget(self.expanded_widget)
        self.actions_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        actions_layout = QHBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 2, 0, 0)
        actions_layout.setSpacing(10)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.actions_layout = actions_layout
        self.details_button = QPushButton(tr('ui.details_button'), self.actions_widget)
        self.details_button.setObjectName('cardButton')
        self.details_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.details_button.clicked.connect(lambda: self.details_requested.emit(self.mod_data))
        self.install_button = QPushButton(tr('buttons.install'), self.actions_widget)
        self.install_button.setObjectName('cardButtonInstall')
        self.install_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.install_button.clicked.connect(self._on_install_button_clicked)
        actions_layout.addWidget(self.details_button)
        actions_layout.addWidget(self.install_button)
        expanded_layout.addWidget(self.actions_widget, 0, Qt.AlignmentFlag.AlignHCenter)
        self.main_layout.addWidget(self.expanded_widget)
        self.expanded_widget.setVisible(False)
        self.downloads_label.setText(self._get_downloads_text())
        self._update_tagline_text()
        self._update_updated_label()
        self._update_name_text()

    def _get_visual_source_key(self):
        screenshots = getattr(self.mod_data, 'screenshots_url', None) or []
        primary_screenshot = next((url for url in screenshots if isinstance(url, str) and url.strip()), '')
        return primary_screenshot or getattr(self.mod_data, 'icon_url', None) or getattr(self.mod_data, 'icon_path', None)

    def _get_tagline_text(self):
        tagline = getattr(self.mod_data, 'tagline', '') or tr('ui.no_description')
        key = get_mod_key(self.mod_data)
        if key and key.startswith('gb_') and not getattr(self.mod_data, 'has_full_metadata', True):
            tagline = tr('ui.loading_placeholder')
        if len(tagline) > 180:
            tagline = tagline[:177] + '...'
        return tagline

    def _load_icon(self):
        config = self._resolve_theme_config()
        br = get_border_radius(config)
        bc = get_theme_color(config, 'border', '#039d5b') if config else None
        bw = 2 if bc else 0
        self.icon_label.setStyleSheet('border: none; background: transparent;')
        load_mod_icon_universal(
            self.icon_label,
            self.mod_data,
            size=(self._media_width, self._media_height),
            local_fallback=self._resolve_local_icon_fallback(),
            border_radius=br,
            border_width=bw,
            border_color=bc,
            prefer_screenshot=True,
        )

    def _set_multiline_elided_text(self, label, text: str, max_lines: int, reserve_lines: int | None = None):
        cleaned_text = (text or '').replace('\n', ' ')
        words = cleaned_text.split()
        metrics = label.fontMetrics()
        margins = self.main_layout.contentsMargins()
        label_width = 0
        try:
            label_width = label.contentsRect().width() or label.width()
        except Exception:
            label_width = label.width() if hasattr(label, 'width') else 0
        available_width = max(80, label_width or self._card_width - margins.left() - margins.right() - 4)
        if not words:
            label.setText('')
            line_count = 1
        else:
            lines = []
            word_index = 0
            for line_number in range(max_lines):
                if word_index >= len(words):
                    break
                current = words[word_index]
                word_index += 1
                if metrics.horizontalAdvance(current) > available_width:
                    current = metrics.elidedText(current, Qt.TextElideMode.ElideRight, available_width)
                else:
                    while word_index < len(words):
                        candidate = f'{current} {words[word_index]}'
                        if metrics.horizontalAdvance(candidate) > available_width:
                            break
                        current = candidate
                        word_index += 1
                if line_number == max_lines - 1 and word_index < len(words):
                    remaining_text = ' '.join(words[word_index:])
                    current = metrics.elidedText(f'{current} {remaining_text}', Qt.TextElideMode.ElideRight, available_width)
                lines.append(current)
            label.setText('\n'.join(lines))
            line_count = max(len(lines), 1)
        reserved = max(line_count, reserve_lines or max_lines)
        max_height = metrics.lineSpacing() * reserved + 6
        label.setMinimumHeight(0)
        label.setMaximumHeight(max_height)

    def _refresh_card_geometry(self):
        if hasattr(self, 'main_layout') and self.main_layout:
            self.main_layout.activate()
        if hasattr(self, 'expanded_widget') and self.expanded_widget:
            self.expanded_widget.adjustSize()
        self.adjustSize()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent and parent.layout():
            parent.layout().invalidate()
            parent.updateGeometry()

    def _update_name_text(self):
        if not hasattr(self, 'name_label'):
            return
        text = self._full_name_text or getattr(self.mod_data, 'name', '') or ''
        self._set_multiline_elided_text(self.name_label, text, 2, reserve_lines=2)
        self.updateGeometry()

    def _update_tagline_text(self):
        if hasattr(self, 'tagline_label'):
            self._set_multiline_elided_text(self.tagline_label, self._get_tagline_text(), 4)

    def _update_updated_label(self):
        if hasattr(self, 'updated_label'):
            self.updated_label.setText(f'↻ {getattr(self.mod_data, "last_updated", None) or "N/A"}')

    def _update_style(self):
        super()._update_style()
        config = self._resolve_theme_config()
        scale = self.layout_scale_for_config(config)
        text_color = get_theme_color(config, 'text', '#e8e9eb') if config else '#e8e9eb'
        secondary = get_theme_color(config, 'secondary_text', '#6de985') if config else '#6de985'
        if hasattr(self, 'name_label'):
            self.name_label.setStyleSheet(f'font-size: {max(15, int(round(18 * scale)))}px; font-weight: bold; color: {text_color};')
        for label in ('downloads_label', 'updated_label'):
            widget = getattr(self, label, None)
            if widget:
                widget.setStyleSheet(f'color: {secondary}; font-size: {max(12, int(round(14 * scale)))}px;')
        if hasattr(self, 'tagline_label'):
            self.tagline_label.setStyleSheet(f'color: {secondary}; font-size: {max(12, int(round(14 * scale)))}px;')
        self._apply_metrics()
        self._update_name_text()
        self._update_tagline_text()
        self._refresh_card_geometry()

    def _update_actions_visibility(self):
        if hasattr(self, 'expanded_widget'):
            self.expanded_widget.setVisible(self.is_selected)
        self._refresh_card_geometry()

    def update_mod_data(self):
        try:
            self._apply_metrics()
            visual_source = self._get_visual_source_key()
            if visual_source != self._last_visual_source:
                self._last_visual_source = visual_source
                self._load_icon()
            self._full_name_text = getattr(self.mod_data, 'name', '') or ''
            self._update_name_text()
            if hasattr(self, 'downloads_label'):
                self.downloads_label.setText(self._get_downloads_text())
            if hasattr(self, 'updated_label'):
                self._update_updated_label()
            self._update_tagline_text()
            key = get_mod_key(self.mod_data)
            if key and key.startswith('gb_'):
                if not getattr(self.mod_data, 'gamebanana_compatibility_checked', False):
                    if not (self._compatibility_thread and self._compatibility_thread.isRunning()):
                        if not (hasattr(self, '_compatibility_check_timer') and self._compatibility_check_timer.isActive()):
                            self._start_compatibility_check()
            if not self.is_installed:
                self._apply_gamebanana_install_styles()
            self._refresh_card_geometry()
        except Exception as e:
            logging.warning(f'SearchModCardWidget: Error updating mod data: {e}', exc_info=True)

    def update_labels_text(self):
        if hasattr(self, 'details_button'):
            self.details_button.setText(tr('ui.details_button'))
        if hasattr(self, 'install_button'):
            if self.is_installed:
                self.install_button.setText(tr('buttons.delete'))
            else:
                self.install_button.setText(tr('buttons.install'))
                self._apply_gamebanana_install_styles()
        if hasattr(self, 'downloads_label'):
            self.downloads_label.setToolTip(tr('ui.downloads_tooltip'))
        if hasattr(self, 'updated_label'):
            self.updated_label.setToolTip(tr('ui.updated_label'))
        self.update_mod_data()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QTimer.singleShot(0, self._clear_selection_if_focus_is_outside)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_name_text()
        self._update_tagline_text()

    def _clear_selection_if_focus_is_outside(self):
        focus_widget = QApplication.focusWidget()
        if focus_widget is self or (focus_widget and self.isAncestorOf(focus_widget)):
            return
        if self.is_selected:
            self.set_selected(False)
