"""Overlay widget for displaying mod details with inline screenshot carousel."""
from PyQt6.QtCore import Qt, QThread, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor, QPainter
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QSizePolicy, QScrollArea, QFrame)
from services.localization_service import tr
from ui.common.styling import get_theme_colors, get_border_radius, install_widget_update_handler, apply_rounded_mask, get_widget_border_radius, build_scrollbar_qss, build_button_style, round_pixmap
from ui.utils.ui_utils import UIAnimator
from ui.utils.image_loader import ImageLoaderRunnable
from utils.mod_utils import get_mod_key
from adapters.gamebanana_adapter import GameBananaAPI
from workers import WorkerSignals
from PyQt6 import sip as _sip
import json
import logging
import webbrowser


class LoadDescriptionFromUrlThread(QThread):
    description_loaded = pyqtSignal(str)
    error_occurred = pyqtSignal(str, int)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            from utils.network_utils import get_session
            resp = get_session().get(self.url, timeout=10)
            if resp.ok:
                self.description_loaded.emit(resp.text)
            else:
                self.error_occurred.emit('http_error', resp.status_code)
        except Exception as e:
            self.error_occurred.emit(str(e), 0)


class LoadModDetailsThread(QThread):
    details_loaded = pyqtSignal(dict)

    def __init__(self, mod_data, cache_dir=None, parent=None):
        super().__init__(parent)
        self.mod_data = mod_data
        self.cache_dir = cache_dir

    def _get_mod_id(self):
        mod_key = get_mod_key(self.mod_data) or ''
        if not mod_key.startswith('gb_'):
            return None
        try:
            return int(mod_key.removeprefix('gb_'))
        except ValueError:
            return None

    def _load_metadata_cache(self):
        if not self.cache_dir or self.isInterruptionRequested():
            return None
        try:
            from adapters.gamebanana_cache import GameBananaMetadataCache
            return GameBananaMetadataCache(self.cache_dir)
        except Exception as e:
            logging.warning(f'LoadModDetailsThread: Error accessing cache: {e}', exc_info=True)
            return None

    def _cached_details(self, metadata_cache, mod_id_str):
        if not metadata_cache or not metadata_cache.is_valid(mod_id_str):
            return None
        external_url = getattr(self.mod_data, 'external_url', None)
        result = {
            'text': metadata_cache.get_field(mod_id_str, 'full_description'),
            'screenshots': metadata_cache.get_field(mod_id_str, 'screenshots'),
        }
        if result['screenshots']:
            result['screenshots'] = GameBananaAPI.fix_screenshot_urls(result['screenshots'], external_url=external_url)
        result = {key: value for key, value in result.items() if value}
        if result:
            logging.debug(f'LoadModDetailsThread: Using cached data for mod {mod_id_str}')
        return result or None

    @staticmethod
    def _coerce_text(text_field):
        if isinstance(text_field, list):
            text_field = text_field[0] if text_field else None
        return text_field if isinstance(text_field, str) else (str(text_field) if text_field else None)

    def _extract_screenshots(self, api, screenshots_field):
        external_url = getattr(self.mod_data, 'external_url', None)
        screenshots_data = screenshots_field[0] if isinstance(screenshots_field, list) and screenshots_field else screenshots_field
        if isinstance(screenshots_data, str):
            return api.extract_screenshots_from_api(screenshots_data, external_url=external_url)
        if isinstance(screenshots_data, dict):
            try:
                screenshots_data = json.dumps(screenshots_data)
            except (TypeError, ValueError):
                return []
            return api.extract_screenshots_from_api(screenshots_data, external_url=external_url)
        if not isinstance(screenshots_data, list):
            return []
        base_url = 'https://images.gamebanana.com/img/ss/wips' if external_url and '/wips/' in external_url else 'https://images.gamebanana.com/img/ss/mods'
        screenshots = []
        for screenshot_obj in screenshots_data:
            if self.isInterruptionRequested():
                break
            if isinstance(screenshot_obj, dict):
                file_name = screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220')
                if file_name:
                    screenshots.append(f'{base_url}/{file_name}')
        return screenshots

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            mod_id = self._get_mod_id()
            if mod_id is None:
                return
            mod_id_str = str(mod_id)
            metadata_cache = self._load_metadata_cache()
            if cached := self._cached_details(metadata_cache, mod_id_str):
                if not self.isInterruptionRequested():
                    self.details_loaded.emit(cached)
                return
            if self.isInterruptionRequested():
                return
            api = GameBananaAPI()
            external_url = getattr(self.mod_data, 'external_url', None)
            details = api.get_mod_text_and_screenshots(mod_id, external_url=external_url)
            if details and (not self.isInterruptionRequested()):
                full_description = self._coerce_text(details.get('text'))
                screenshots = self._extract_screenshots(api, details.get('screenshots'))
                result = {'screenshots': screenshots}
                if full_description:
                    result['text'] = full_description
                result['screenshots'] = screenshots
                if metadata_cache and (full_description or screenshots):
                    try:
                        if not self.isInterruptionRequested():
                            metadata_cache.set(mod_id_str, full_description=full_description, screenshots=screenshots or None)
                    except Exception as e:
                        logging.warning(f'LoadModDetailsThread: Cache save error: {e}')
                if not self.isInterruptionRequested():
                    self.details_loaded.emit(result)
        except Exception as e:
            if not self.isInterruptionRequested():
                logging.error(f'Error loading mod details: {e}', exc_info=True)


class ModDetailsOverlay(QWidget):
    """Overlay widget for displaying mod details with inline screenshot carousel."""
    HEADER_HEIGHT = 80
    FOOTER_HEIGHT = 100
    IMG_W, IMG_H = 440, 221
    LEFT_COLUMN_WIDTH = 450
    EXTERNAL_BUTTON_WIDTH = 400
    NAV_BUTTON_SIZE = (35, 25)
    LOADING_TEXT = 'Loading...'
    NO_SCREENSHOTS_TEXT = 'No screenshots'
    SCREENSHOT_LIMIT = 10

    def __init__(self, parent=None, mod_data=None, source_card=None):
        super().__init__(parent)
        self.mod_data = mod_data
        self.source_card = source_card
        self.dialog_closed = False
        self.load_thread = None
        self._ss_urls = []
        self._ss_images = []
        self._ss_loading = []
        self._ss_index = 0
        self._description_html = ''
        self._last_description_width = 0
        self._thread_pool = QThreadPool.globalInstance()
        self._original_resize_event = None
        self.hide()
        self._setup_ui()
        self.main_window = self._get_main_window()
        if self.main_window and hasattr(self.main_window, 'resizeEvent'):
            self._original_resize_event = self.main_window.resizeEvent
            self.main_window.resizeEvent = self._on_main_window_resize

    def _get_main_window(self):
        window = self.parent()
        while window and window.parent():
            window = window.parent()
        return window

    def _calculate_content_geometry(self, main_rect):
        return (0, self.HEADER_HEIGHT, main_rect.width(),
                main_rect.height() - self.HEADER_HEIGHT - self.FOOTER_HEIGHT)

    def _setup_theme(self):
        self._app_state = getattr(self.parent(), 'app_state', None)
        local_cfg = getattr(self._app_state, 'local_config', None) if self._app_state else None
        self._colors = get_theme_colors(local_cfg, text='#e8e9eb', secondary_text='#6de985', border='#039d5b', background='#282828', button='#222222', button_hover='#616b78')
        self._colors['btn_hover'] = self._colors['button_hover']
        self._border_radius = get_border_radius(local_cfg)

    @staticmethod
    def _layout(layout_cls, parent=None, margins=None, spacing=None):
        layout = layout_cls(parent) if parent is not None else layout_cls()
        if margins is not None:
            layout.setContentsMargins(*margins)
        if spacing is not None:
            layout.setSpacing(spacing)
        return layout

    @staticmethod
    def _is_alive(obj) -> bool:
        try:
            return not _sip.isdeleted(obj)
        except (RuntimeError, AttributeError):
            return False

    def _can_update(self) -> bool:
        return (not self.dialog_closed) and self._is_alive(self)

    def _radius_for(self, widget, margin: int = 0) -> int:
        return get_widget_border_radius(widget, self._border_radius, margin=margin)

    def _button_style(self, obj_name: str, *, text_color: str | None = None, bg: str | None = None, hover: str | None = None, width: int | None = 110, height: int | None = 35, font_size: int = 15, padding: str = '1px') -> str:
        return build_button_style(obj_name, bg or self._colors['button'], hover or self._colors['button_hover'], text_color or self._colors['text'], self._colors['border'], width, height, font_size, border_radius=self._border_radius, padding=padding)

    def _scrollbar_qss(self, corner_inset: int) -> str:
        return build_scrollbar_qss(self._colors['text'], self._border_radius, vertical_margin=(corner_inset, 4, corner_inset, 2), horizontal_margin=(2, corner_inset, 4, corner_inset), include_corner=True)

    def _install_scroll_clip_handlers(self, target, attr_prefix: str):
        def _apply():
            if viewport := target.viewport():
                apply_rounded_mask(viewport, max(0, self._radius_for(target) - 2))
            for scrollbar in (target.verticalScrollBar(), target.horizontalScrollBar()):
                if scrollbar:
                    apply_rounded_mask(scrollbar, self._radius_for(scrollbar, margin=1))
            try:
                target.clearMask()
            except (RuntimeError, AttributeError):
                pass

        install_widget_update_handler(target, _apply, attr_name=f'_{attr_prefix}_clip_filter')
        if viewport := target.viewport():
            install_widget_update_handler(viewport, _apply, attr_name=f'_{attr_prefix}_viewport_clip_filter')

    def _install_scroller_style(self, target, *, selector: str, attr_name: str, clip_prefix: str, content_target=None, content_padding_min: int = 24, content_padding_factor: int = 6, text_color: str | None = None, font_size: int | None = None, document_margin: bool = False):
        def _apply():
            radius = self._radius_for(target)
            content_padding = max(content_padding_min, (radius * content_padding_factor + 9) // 10)
            viewport_inset = max(2, min(10, radius // 5))
            corner_inset = max(6, min(18, radius // 2))
            rules = [
                f'{selector} {{',
                f'    background-color: {self._colors["background"]};',
                *([f'    color: {text_color};'] if text_color else []),
                f'    border: 2px solid {self._colors["border"]};',
                f'    border-radius: {radius}px;',
                *([f'    font-size: {font_size}px;'] if font_size is not None else []),
                *(['    padding: 0px;'] if document_margin else []),
                '}',
                self._scrollbar_qss(corner_inset),
            ]
            target.setStyleSheet('\n'.join(rules))
            try:
                target.setViewportMargins(viewport_inset, viewport_inset, max(viewport_inset, 6), viewport_inset)
            except Exception:
                pass
            try:
                if content_target is not None:
                    content_target.setContentsMargins(content_padding, content_padding, content_padding, content_padding)
                elif document_margin:
                    target.document().setDocumentMargin(content_padding)
            except Exception:
                pass
            if viewport := target.viewport():
                viewport.setStyleSheet(f'background-color: {self._colors["background"]}; border: none;')

        install_widget_update_handler(target, _apply, attr_name=attr_name)
        self._install_scroll_clip_handlers(target, clip_prefix)

    def _html_label(self, html: str, *, align=Qt.AlignmentFlag.AlignCenter, wrap: bool = True):
        label = QLabel(html)
        label.setWordWrap(wrap)
        label.setAlignment(align)
        return label

    def _create_button(self, text: str, *, obj_name: str, style: str, clicked=None, fixed_width: int | None = None, fixed_size: tuple[int, int] | None = None):
        button = QPushButton(text)
        button.setObjectName(obj_name)
        if clicked:
            button.clicked.connect(clicked)
        if fixed_size is not None:
            button.setFixedSize(*fixed_size)
        elif fixed_width is not None:
            button.setFixedWidth(fixed_width)
        button.setStyleSheet(style)
        return button

    def _install_image_container_style(self, container):
        def _apply(target=container, image_label=self._img_label):
            radius = self._radius_for(target)
            target.setStyleSheet(f'background-color:transparent; border:2px solid {self._colors["border"]}; border-radius: {radius}px;')
            image_label.setStyleSheet(f'border: none; background-color: transparent; border-radius: {radius}px;')

        install_widget_update_handler(container, _apply, attr_name='_overlay_image_style_filter')

    def _meta_row_html(self, key: str, value: str) -> str:
        return f'<span style="color:{self._colors["text"]};font-weight:bold;font-size:13px;">{tr(key)}</span> <span style="color:{self._colors["secondary_text"]};font-size:13px;">{value}</span>'

    def _add_meta_row(self, layout, key: str, value: str, *, wrap: bool = False):
        label = QLabel(self._meta_row_html(key, value))
        label.setWordWrap(wrap)
        layout.addWidget(label)

    def _translated_tags(self) -> str:
        tags = getattr(self.mod_data, 'tags', None)
        if not tags:
            return ''
        tag_map = {'textedit': tr('tags.textedit'), 'translation': tr('tags.textedit'), 'customization': tr('tags.customization'), 'gameplay': tr('tags.gameplay'), 'other': tr('tags.other')}
        return ', '.join(tag_map.get(tag, tag) for tag in (tags if isinstance(tags, list) else [tags]) if tag)

    def _build_carousel_layout(self):
        carousel = self._layout(QVBoxLayout, spacing=8)
        img_container = QWidget()
        img_container.setFixedSize(self.IMG_W, self.IMG_H)
        self._img_label = QLabel(img_container)
        self._img_label.setFixedSize(self.IMG_W, self.IMG_H)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._install_image_container_style(img_container)
        carousel.addWidget(img_container, 0, Qt.AlignmentFlag.AlignHCenter)
        nav = self._layout(QHBoxLayout, margins=(0, 0, 0, 0), spacing=4)
        nav.addStretch()
        for attr, text, slot in (('_prev_btn', '<', self._ss_prev), ('_next_btn', '>', self._ss_next)):
            button = self._create_button(text, obj_name='overlayNavButton', style=self._button_style('overlayNavButton', width=self.NAV_BUTTON_SIZE[0], height=self.NAV_BUTTON_SIZE[1], font_size=16, padding='0px'), clicked=slot, fixed_size=self.NAV_BUTTON_SIZE)
            setattr(self, attr, button)
            nav.addWidget(button)
        nav.addStretch()
        carousel.addLayout(nav)
        self._dots_layout = self._layout(QHBoxLayout, spacing=4)
        self._dot_labels = []
        dots_wrap = self._layout(QHBoxLayout)
        dots_wrap.addStretch()
        dots_wrap.addLayout(self._dots_layout)
        dots_wrap.addStretch()
        carousel.addLayout(dots_wrap)
        return carousel

    def _build_metadata_layout(self):
        meta = self._layout(QVBoxLayout, spacing=4)
        version = self.mod_data.version
        downloads_value = getattr(self.mod_data, 'downloads', None)
        for key, value in (
            ('ui.author_label', self.mod_data.author),
            ('ui.mod_version_label', (version.split('|')[0] if version and '|' in version else version) or 'N/A'),
            ('ui.game_version_label', self.mod_data.game_version or 'N/A'),
            ('ui.created_label', self.mod_data.created_date or 'N/A'),
            ('ui.downloads_label', 'N/A' if downloads_value is None else str(downloads_value)),
            ('ui.category_label', getattr(self.mod_data, 'gamebanana_category', None) or getattr(self.mod_data, 'category', None)),
        ):
            if value:
                self._add_meta_row(meta, key, value)
        if tags := self._translated_tags():
            self._add_meta_row(meta, 'ui.tags_label', tags, wrap=True)
        return meta

    def _build_left_column(self):
        left = self._layout(QVBoxLayout, margins=(0, 0, 0, 0), spacing=15)
        if external_url := getattr(self.mod_data, 'external_url', None):
            left.addWidget(self._create_button(tr('ui.view_on_external_site'), obj_name='cardButtonExternal', style=self._button_style('cardButtonExternal', text_color='#FFD700', width=self.EXTERNAL_BUTTON_WIDTH, font_size=15), clicked=lambda: webbrowser.open(external_url), fixed_width=self.EXTERNAL_BUTTON_WIDTH), 0, Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self._html_label(f'<h2 style="color:{self._colors["text"]};margin:8px 0;font-size:18px;">{self.mod_data.name}</h2>'))
        if self.mod_data.tagline:
            left.addWidget(self._html_label(f'<p style="color:{self._colors["secondary_text"]};margin:0 0 15px 0;font-size:14px;font-style:italic;">{self.mod_data.tagline}</p>'))
        left.addLayout(self._build_carousel_layout())
        left.addLayout(self._build_metadata_layout())
        left.addStretch()
        container = QWidget()
        container.setMinimumWidth(self.LEFT_COLUMN_WIDTH)
        container.setMaximumWidth(self.LEFT_COLUMN_WIDTH)
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        container.setLayout(left)
        return container

    def _configure_install_button(self):
        if self.source_card and hasattr(self.source_card, 'install_button'):
            self._sync_button_from_card()
            self.install_button.clicked.connect(lambda: self.source_card.install_button.click())
            try:
                self._sync_timer = QTimer()
                self._sync_timer.timeout.connect(self._sync_button_from_card)
                self._sync_timer.start(100)
            except Exception as e:
                logging.debug(f'QTimer setup failed for _sync_timer: {e}', exc_info=True)
            return
        self.install_button.setText(tr('buttons.install'))
        self.install_button.setObjectName('cardButtonInstall')
        self._set_install_button_style(self._colors['border'])
        if parent_app := self.parent():
            if hasattr(parent_app, 'install_mod'):
                self.install_button.clicked.connect(lambda: parent_app.install_mod(self.mod_data))

    def _build_action_buttons(self):
        buttons = self._layout(QHBoxLayout)
        buttons.addStretch()
        self.compat_status_label = QLabel(self)
        self.compat_status_label.setObjectName('gbStatusLabel')
        self.compat_status_label.setVisible(False)
        buttons.addWidget(self.compat_status_label)
        self.install_button = QPushButton()
        self._configure_install_button()
        buttons.addWidget(self.install_button)
        buttons.addWidget(self._create_button(tr('buttons.close'), obj_name='cardButtonClose', style=self._button_style('cardButtonClose'), clicked=self.close_overlay))
        return buttons

    def _build_right_column(self):
        right = self._layout(QVBoxLayout, spacing=15)
        right.addWidget(self._html_label(f"<b style='color:{self._colors['text']};'>{tr('ui.full_description_label')}</b>"))
        self.desc_text = QTextBrowser()
        self.desc_text.setMinimumHeight(400)
        self.desc_text.setOpenExternalLinks(True)
        self.desc_text.setFrameShape(QFrame.Shape.NoFrame)
        self._install_scroller_style(self.desc_text, selector='QTextBrowser', attr_name='_overlay_description_style_filter', clip_prefix='overlay_description', content_padding_min=14, content_padding_factor=4, text_color=self._colors['text'], font_size=16, document_margin=True)
        self._desc_default_color = self._colors['text']
        right.addWidget(self.desc_text)
        right.addLayout(self._build_action_buttons())
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        container.setLayout(right)
        return container

    def _show_loading_description(self):
        self._set_description_message(tr('status.loading_description'))

    def _set_description_message(self, text: str):
        self._description_html = ''
        self.desc_text.setPlainText(text)

    def _start_thread(self, attr_name: str, thread, signal_pairs=()):
        setattr(self, attr_name, thread)
        for signal_name, handler in signal_pairs:
            getattr(thread, signal_name).connect(handler)
        thread.start()

    def _stop_timer(self, attr_name: str):
        if timer := getattr(self, attr_name, None):
            try:
                timer.stop()
                timer.deleteLater()
            except Exception as e:
                logging.debug(f'cleanup_thread: failed to stop/delete {attr_name}: {e}', exc_info=True)
            setattr(self, attr_name, None)

    def _transfer_label_state(self, source_label, target_label):
        visible = bool(source_label and source_label.isVisible())
        if visible:
            target_label.setText(source_label.text())
            target_label.setStyleSheet(source_label.styleSheet())
            target_label.setToolTip(source_label.toolTip())
        target_label.setVisible(visible)

    def _sync_install_button_style(self, src_btn, border: str):
        style_args = {
            'cardButtonUninstall': ('cardButtonUninstall', '#F44336', '#d32f2f'),
        }.get(src_btn.objectName())
        if style_args:
            self._set_install_button_style(border, *style_args)
            return
        if src_btn.toolTip() == tr('ui.gamebanana_status_manual_tooltip'):
            self._set_install_button_style(border, 'cardButtonInstall', '#FFC107', '#FFB300')
            return
        self._set_install_button_style(border)

    def _setup_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._setup_theme()
        self.setStyleSheet(f"QWidget {{ background-color: {self._colors['background']}; }}")
        root = self._layout(QVBoxLayout, self, margins=(0, 0, 0, 0), spacing=0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = self._layout(QVBoxLayout, content, margins=(20, 20, 20, 20), spacing=15)
        self._install_scroller_style(scroll, selector='QScrollArea', attr_name='_overlay_scroll_style_filter', clip_prefix='overlay_scroll', content_target=content_layout)
        columns = self._layout(QHBoxLayout, margins=(0, 0, 0, 0), spacing=5)
        columns.addWidget(self._build_left_column(), 0)
        columns.addWidget(self._build_right_column(), 1)
        cw = QWidget()
        cw.setLayout(columns)
        content_layout.addWidget(cw)
        scroll.setWidget(content)
        wrap = self._layout(QHBoxLayout, margins=(max(10, self._border_radius // 3), max(4, self._border_radius // 6), max(10, self._border_radius // 3), max(4, self._border_radius // 6)))
        wrap.addWidget(scroll)
        root.addLayout(wrap)

        self._update_ss_nav()
        self._load_description()

    def _set_install_button_style(self, border, obj_name='cardButtonInstall', bg='#4CAF50', hover='#5cb85c'):
        """Set install button stylesheet."""
        self.install_button.setStyleSheet(build_button_style(obj_name, bg, hover, '#e8e9eb', border, border_radius=self._border_radius))

    def _sync_button_from_card(self):
        """Synchronizes the Install button with the button from the mod card."""
        if not (src_btn := getattr(self.source_card, 'install_button', None)):
            return
        self.install_button.setText(src_btn.text())
        self.install_button.setObjectName(src_btn.objectName())
        self.install_button.setToolTip(src_btn.toolTip())
        self.install_button.setEnabled(src_btn.isEnabled())
        self._sync_install_button_style(src_btn, self._colors.get('border', '#039d5b'))
        self._transfer_label_state(getattr(self.source_card, 'gb_status_label', None), self.compat_status_label)

    def update_screenshots(self, urls):
        urls = [u for u in urls if isinstance(u, str) and u.startswith(('http://', 'https://'))][:self.SCREENSHOT_LIMIT]
        self._ss_urls = urls
        self._ss_images = [None] * len(urls)
        self._ss_loading = [False] * len(urls)
        self._ss_index = 0
        self._rebuild_dots()
        if urls:
            self._ss_show_current()
            self._ss_preload_neighbors()
        self._update_ss_nav()

    def _ss_prev(self):
        self._ss_shift(-1)

    def _ss_next(self):
        self._ss_shift(1)

    def _ss_shift(self, step):
        if not self._ss_urls:
            return
        self._ss_index = (self._ss_index + step) % len(self._ss_urls)
        self._ss_show_current()
        self._ss_preload_neighbors()
        self._ss_unload_distant()

    def _ss_show_current(self):
        if not self._ss_urls:
            self._set_screenshot_text(self.NO_SCREENSHOTS_TEXT)
            self._update_ss_nav()
            return

        if current_image := self._ss_images[self._ss_index]:
            self._ss_fade_to(current_image)
        else:
            self._ss_load_image(self._ss_index) if not self._ss_loading[self._ss_index] else self._set_screenshot_text(self.LOADING_TEXT)

        self._rebuild_dots()
        self._update_ss_nav()

    def _set_screenshot_text(self, text: str):
        self._img_label.clear()
        self._img_label.setText(text)

    def _ss_load_image(self, idx):
        self._set_screenshot_text(self.LOADING_TEXT)
        self._queue_screenshot_load(idx, self._ss_on_loaded)

    def _queue_screenshot_load(self, idx, on_loaded):
        if not (0 <= idx < len(self._ss_urls)) or self._ss_loading[idx]:
            return
        self._ss_loading[idx] = True
        signals = WorkerSignals()
        signals.result.connect(lambda qimg, i=idx: on_loaded(i, qimg))
        signals.error.connect(lambda url, msg, i=idx: self._ss_on_error(i, msg))
        self._thread_pool.start(ImageLoaderRunnable(self._ss_urls[idx], signals))

    def _ss_fade_to(self, qimg):
        self._ss_set_pixmap(qimg)
        UIAnimator.fade_in(self._img_label, duration=250, app_state=self._app_state)

    def _ss_set_pixmap(self, qimg):
        if not self._is_alive(self._img_label):
            return
        lw, lh = self._img_label.width(), self._img_label.height()
        pm = QPixmap.fromImage(qimg)
        scaled = pm.scaled(lw - 4, lh - 4, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        canvas = QPixmap(lw, lh)
        canvas.fill(QColor('transparent'))
        p = QPainter(canvas)
        p.drawPixmap((lw - scaled.width()) // 2, (lh - scaled.height()) // 2, scaled)
        p.end()
        self._img_label.setPixmap(round_pixmap(canvas, self._border_radius) if self._border_radius > 0 else canvas)

    def _ss_store_image(self, idx, qimg):
        if idx < len(self._ss_images):
            self._ss_images[idx] = qimg
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False

    def _ss_on_loaded(self, idx, qimg):
        self._ss_store_image(idx, qimg)
        if idx == self._ss_index:
            self._ss_fade_to(qimg)
            self._ss_unload_distant()

    def _ss_on_error(self, idx, msg):
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False
        if idx == self._ss_index:
            self._set_screenshot_text(tr('errors.file_not_available'))

    def _ss_preload_neighbors(self):
        for offset in (-1, 1):
            i = self._ss_index + offset
            if 0 <= i < len(self._ss_urls) and self._ss_images[i] is None:
                self._queue_screenshot_load(i, self._ss_on_preloaded)

    def _ss_on_preloaded(self, idx, qimg):
        self._ss_store_image(idx, qimg)

    def _ss_unload_distant(self):
        n = len(self._ss_urls)
        for i in range(len(self._ss_images)):
            d = min(abs(i - self._ss_index), abs(i - self._ss_index + n), abs(i - self._ss_index - n))
            if d > 1 and self._ss_images[i] is not None:
                self._ss_images[i] = None

    def _update_ss_nav(self):
        show = len(self._ss_urls) > 1
        self._prev_btn.setVisible(show)
        self._next_btn.setVisible(show)
        for lbl in self._dot_labels:
            lbl.setVisible(show)

    def _rebuild_dots(self):
        while self._dots_layout.count():
            item = self._dots_layout.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)
        self._dot_labels = []
        tc = self.palette().color(self.foregroundRole()).name()
        for i in range(len(self._ss_urls)):
            lbl = QLabel('●' if i == self._ss_index else '○')
            lbl.setStyleSheet(f'color:{tc};font-size:14px;background-color:transparent;border:none;padding:2px;')
            self._dot_labels.append(lbl)
            self._dots_layout.addWidget(lbl)

    def show_overlay(self):
        """Show the overlay with fade-in animation."""
        self.show()
        self.raise_()
        self.activateWindow()
        UIAnimator.fade_in(self, duration=300, app_state=self._app_state)

    def close_overlay(self):
        """Close the overlay with fade-out animation."""
        self._restore_main_window_resize()

        def cleanup():
            self.hide()
            self.deleteLater()

        if hasattr(self, '_fade_anim') and self._fade_anim:
            try:
                self._fade_anim.finished.disconnect()
            except (TypeError, RuntimeError):
                pass

        fade = UIAnimator.fade_out(self, duration=300, app_state=self._app_state)
        if fade:
            fade.finished.connect(cleanup)
        else:
            cleanup()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if not self.childAt(event.pos()):
            self.close_overlay()
        super().mousePressEvent(event)

    def _on_main_window_resize(self, event):
        try:
            if self._is_alive(self) and self.isVisible():
                self.setGeometry(*self._calculate_content_geometry(self.main_window.rect()))
        except (RuntimeError, AttributeError):
            pass
        if self._original_resize_event:
            try:
                self._original_resize_event(event)
            except (RuntimeError, AttributeError):
                pass

    def resizeEvent(self, event):
        if self.main_window:
            self.setGeometry(*self._calculate_content_geometry(self.main_window.rect()))
        super().resizeEvent(event)
        self._refresh_description_html()

    def _load_description(self):
        if hasattr(self.mod_data, 'full_description') and self.mod_data.full_description:
            self._set_description_html(self.mod_data.full_description)
        elif hasattr(self.mod_data, 'description_url') and self.mod_data.description_url:
            self._load_description_from_url()
        elif self.mod_data.is_gamebanana_mod() and self.mod_data.get_gamebanana_mod_id():
            self._load_gamebanana_description()
        else:
            self._set_description_message(tr('ui.no_description'))

    def _refresh_description_html(self, force=False):
        if not self._description_html:
            return
        try:
            viewport_width = self.desc_text.viewport().width() if self.desc_text.viewport() else self.desc_text.width()
        except Exception:
            viewport_width = 0
        if not force and viewport_width and abs(viewport_width - self._last_description_width) < 24:
            return
        self._last_description_width = viewport_width
        try:
            from ui.common.rich_html import set_rich_html
            set_rich_html(self.desc_text, self._description_html, default_color=self._desc_default_color)
        except Exception as e:
            logging.warning(f'Error setting description HTML: {e}')
            self.desc_text.setPlainText(self._description_html)

    def _set_description_html(self, content):
        """Set description HTML with error handling."""
        self._description_html = content if isinstance(content, str) else str(content)
        self._refresh_description_html(force=True)

    def _load_description_from_url(self):
        """Load description from URL."""
        self._show_loading_description()
        self._start_thread('url_load_thread', LoadDescriptionFromUrlThread(self.mod_data.description_url, parent=None), (
            ('description_loaded', self._on_url_description_loaded),
            ('error_occurred', self._on_url_description_error),
        ))

    def _on_url_description_loaded(self, html_content):
        """Handle successful URL description load."""
        try:
            if not self._can_update():
                return
            self._set_description_html(html_content)
        except Exception as e:
            logging.error(f'Error in _on_url_description_loaded: {e}', exc_info=True)

    def _on_url_description_error(self, error_msg, status_code):
        """Handle URL description load error."""
        try:
            if not self._can_update():
                return
            if error_msg == 'http_error':
                self._set_description_message(tr('errors.description_http_error_code', code=status_code))
            else:
                self._set_description_message(tr('errors.description_load_error_details', error=error_msg))
        except Exception as e:
            logging.error(f'Error in _on_url_description_error: {e}', exc_info=True)

    def _load_gamebanana_description(self):
        """Load GameBanana mod description."""
        self._show_loading_description()
        cache_dir = self._app_state.cache_dir if self._app_state and hasattr(self._app_state, 'cache_dir') else None
        self._start_thread('load_thread', LoadModDetailsThread(self.mod_data, cache_dir=cache_dir, parent=None), (('details_loaded', self._on_details_loaded),))

    def _on_details_loaded(self, details):
        try:
            if not self._can_update():
                return
            if details.get('text'):
                self._set_description_html(details['text'])
            ss = details.get('screenshots', [])
            if ss and isinstance(ss, list) and any(isinstance(u, str) and u.strip() for u in ss):
                self.update_screenshots(ss)
        except Exception as e:
            logging.error(f'Error in _on_details_loaded: {e}', exc_info=True)

    def _restore_main_window_resize(self):
        """Restores the original resizeEvent of the main window."""
        if self.main_window and self._original_resize_event:
            try:
                self.main_window.resizeEvent = self._original_resize_event
                self._original_resize_event = None
            except (RuntimeError, AttributeError):
                pass

    def _stop_thread(self, thread):
        """Stop and clean up a QThread safely."""
        try:
            thread.blockSignals(True)
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(5000):
                    logging.debug(f'{thread.__class__.__name__}: Thread did not stop within 5s, terminating')
                    thread.terminate()
                    thread.wait(50)
            if thread.isFinished():
                thread.deleteLater()
            else:
                thread.finished.connect(lambda: thread.deleteLater() if thread.isFinished() else None)
        except (RuntimeError, AttributeError) as e:
            logging.debug(f'{thread.__class__.__name__}: cleanup error: {e}')

    def _stop_thread_attr(self, attr_name: str):
        if thread := getattr(self, attr_name, None):
            setattr(self, attr_name, None)
            self._stop_thread(thread)

    def cleanup_thread(self):
        self._stop_timer('_sync_timer')
        self._stop_thread_attr('load_thread')
        self._stop_thread_attr('url_load_thread')

    def closeEvent(self, event):
        self._restore_main_window_resize()
        self.cleanup_thread()
        self.dialog_closed = True
        event.accept()


def show_mod_details_overlay(parent, mod_data, source_card=None):
    """Show mod details overlay."""
    overlay = ModDetailsOverlay(parent, mod_data, source_card=source_card)
    main_window = overlay._get_main_window()
    overlay.setGeometry(*overlay._calculate_content_geometry(main_window.rect()))
    overlay.setParent(main_window)
    overlay.show_overlay()
    return overlay
