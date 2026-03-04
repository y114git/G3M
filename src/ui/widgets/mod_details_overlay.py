"""Overlay widget for displaying mod details with inline screenshot carousel."""
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QThreadPool
from PyQt6.QtGui import QPixmap, QColor, QPainter
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QSizePolicy, QScrollArea)
from services.localization_service import tr
from ui.common.styling import get_theme_color
from ui.utils.ui_utils import UIAnimator
from ui.utils.image_loader import ImageLoaderRunnable
from utils.mod_utils import get_mod_key
from adapters.gamebanana_adapter import GameBananaAPI
from workers import WorkerSignals
from PyQt6 import sip as _sip
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

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            mod_key = get_mod_key(self.mod_data)
            if not mod_key or not mod_key.startswith('gb_'):
                return
            mod_id_str = mod_key.replace('gb_', '', 1)
            if not mod_id_str:
                return
            mod_id = int(mod_id_str)
            mod_id_str = str(mod_id)
            metadata_cache = None
            cached_text = None
            cached_screenshots = None
            if self.cache_dir:
                try:
                    if self.isInterruptionRequested():
                        return
                    from adapters.gamebanana_cache import GameBananaMetadataCache
                    metadata_cache = GameBananaMetadataCache(self.cache_dir)
                    if metadata_cache.is_valid(mod_id_str):
                        cached_text = metadata_cache.get_field(mod_id_str, 'full_description')
                        cached_screenshots = metadata_cache.get_field(mod_id_str, 'screenshots')
                        if cached_text or cached_screenshots:
                            logging.debug(f'LoadModDetailsThread: Using cached data for mod {mod_id_str}')
                            result = {}
                            if cached_text:
                                result['text'] = cached_text
                            if cached_screenshots:
                                result['screenshots'] = GameBananaAPI.fix_screenshot_urls(cached_screenshots, external_url=getattr(self.mod_data, 'external_url', None))
                            if result and not self.isInterruptionRequested():
                                self.details_loaded.emit(result)
                                return
                except Exception as e:
                    logging.warning(f'LoadModDetailsThread: Error accessing cache: {e}', exc_info=True)
            if self.isInterruptionRequested():
                return
            api = GameBananaAPI()
            external_url = getattr(self.mod_data, 'external_url', None)
            details = api.get_mod_text_and_screenshots(mod_id, external_url=external_url)
            if details and (not self.isInterruptionRequested()):
                result = {}
                text_field = details.get('text')
                full_description = None
                if text_field:
                    full_description = text_field[0] if isinstance(text_field, list) and text_field else (text_field if isinstance(text_field, str) else str(text_field))
                    result['text'] = full_description
                screenshots_field = details.get('screenshots')
                screenshots = []
                if screenshots_field:
                    external_url = getattr(self.mod_data, 'external_url', None)
                    is_wip = external_url and '/wips/' in external_url
                    screenshots_data = None
                    if isinstance(screenshots_field, list) and len(screenshots_field) > 0:
                        screenshots_data = screenshots_field[0]
                    elif not isinstance(screenshots_field, list):
                        screenshots_data = screenshots_field
                    if isinstance(screenshots_data, str):
                        screenshots = api.extract_screenshots_from_api(screenshots_data, external_url=external_url)
                    elif isinstance(screenshots_data, list):
                        base_url = 'https://images.gamebanana.com/img/ss/wips' if is_wip else 'https://images.gamebanana.com/img/ss/mods'
                        for screenshot_obj in screenshots_data:
                            if self.isInterruptionRequested():
                                break
                            if isinstance(screenshot_obj, dict):
                                file_name = screenshot_obj.get('_sFile') or screenshot_obj.get('_sFile800') or screenshot_obj.get('_sFile530') or screenshot_obj.get('_sFile220')
                                if file_name:
                                    screenshot_url = f'{base_url}/{file_name}'
                                    screenshots.append(screenshot_url)
                    elif isinstance(screenshots_data, dict):
                        import json
                        try:
                            screenshots_str = json.dumps(screenshots_data)
                            screenshots = api.extract_screenshots_from_api(screenshots_str, external_url=external_url)
                        except (TypeError, ValueError):
                            screenshots = []
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

    def _setup_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._app_state = getattr(self.parent(), 'app_state', None)
        local_cfg = getattr(self._app_state, 'local_config', None) if self._app_state else None

        self._colors = {
            'text': get_theme_color(local_cfg, 'text', 'white'),
            'secondary': get_theme_color(local_cfg, 'version_text', 'rgba(255,255,255,178)'),
            'border': get_theme_color(local_cfg, 'border', '#fff'),
            'bg': get_theme_color(local_cfg, 'background', '#000'),
            'btn_bg': get_theme_color(local_cfg, 'button', '#000000'),
            'btn_hover': get_theme_color(local_cfg, 'hover', '#333333')
        }
        text_color, secondary_text, border, bg = self._colors['text'], self._colors['secondary'], self._colors['border'], self._colors['bg']
        btn_bg, btn_hover = self._colors['btn_bg'], self._colors['btn_hover']

        self.setStyleSheet(f"QWidget {{ background-color: {bg}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background-color: {bg}; border: 2px solid {border}; }}
            QScrollArea > QWidget > QWidget {{ background-color: {bg}; }}
        """)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(15)

        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(5)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(15)

        if hasattr(self.mod_data, 'external_url') and self.mod_data.external_url:
            from ui.common.styling import build_button_style
            eb = QPushButton(tr('ui.view_on_external_source'))
            eb.setObjectName('cardButtonExternal')
            eb.clicked.connect(lambda: webbrowser.open(self.mod_data.external_url))
            eb.setFixedWidth(400)
            eb.setStyleSheet(build_button_style('cardButtonExternal', btn_bg, btn_hover, '#FFD700', border, 400, 35, 15))
            left.addWidget(eb, 0, Qt.AlignmentFlag.AlignCenter)

        title = QLabel(f'<h2 style="color:{text_color};margin:8px 0;font-size:18px;">{self.mod_data.name}</h2>')
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(title)

        if self.mod_data.tagline:
            tl = QLabel(f'<p style="color:{secondary_text};margin:0 0 15px 0;font-size:14px;font-style:italic;">{self.mod_data.tagline}</p>')
            tl.setWordWrap(True)
            tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            left.addWidget(tl)

        car = QVBoxLayout()
        car.setSpacing(8)
        img_container = QWidget()
        img_container.setFixedSize(self.IMG_W, self.IMG_H)
        img_container.setStyleSheet(f'background-color:transparent; border:2px solid {border};')

        self._img_label = QLabel(img_container)
        self._img_label.setFixedSize(self.IMG_W, self.IMG_H)
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet('border: none; background-color: transparent;')

        car.addWidget(img_container, 0, Qt.AlignmentFlag.AlignHCenter)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        nav_style = f"""QPushButton {{ font-size:16px; color:{text_color}; background-color:{btn_bg};
                   border:2px solid {border}; padding:0; }}
                   QPushButton:hover {{ background-color:{btn_hover}; }}"""
        self._prev_btn = QPushButton('<')
        self._prev_btn.setFixedSize(35, 25)
        self._prev_btn.setStyleSheet(nav_style)
        self._prev_btn.clicked.connect(self._ss_prev)
        self._next_btn = QPushButton('>')
        self._next_btn.setFixedSize(35, 25)
        self._next_btn.setStyleSheet(nav_style)
        self._next_btn.clicked.connect(self._ss_next)
        nav.addStretch()
        nav.addWidget(self._prev_btn)
        nav.addSpacing(4)
        nav.addWidget(self._next_btn)
        nav.addStretch()
        car.addLayout(nav)

        self._dots_layout = QHBoxLayout()
        self._dots_layout.setSpacing(4)
        self._dot_labels = []
        dots_wrap = QHBoxLayout()
        dots_wrap.addStretch()
        dots_wrap.addLayout(self._dots_layout)
        dots_wrap.addStretch()
        car.addLayout(dots_wrap)

        left.addLayout(car)

        meta = QVBoxLayout()
        meta.setSpacing(4)

        def _row(key, val):
            meta.addWidget(QLabel(
                f'<span style="color:{text_color};font-weight:bold;font-size:13px;">{tr(key)}</span>'
                f' <span style="color:{secondary_text};font-size:13px;">{val}</span>'))

        if self.mod_data.author:
            _row('ui.author_label', self.mod_data.author)
        v = self.mod_data.version
        _row('ui.mod_version_label', (v.split('|')[0] if v and '|' in v else v) or 'N/A')
        _row('ui.game_version_label', self.mod_data.game_version or 'N/A')
        _row('ui.created_label', self.mod_data.created_date or 'N/A')
        _row('ui.downloads_label', str(self.mod_data.downloads) if self.mod_data.downloads else 'N/A')
        cat = getattr(self.mod_data, 'gamebanana_category', None) or getattr(self.mod_data, 'category', None)
        if cat:
            _row('ui.category_label', cat)

        if hasattr(self.mod_data, 'tags') and self.mod_data.tags:
            tag_map = {'textedit': tr('tags.textedit'), 'translation': tr('tags.textedit'),
                       'customization': tr('tags.customization'), 'gameplay': tr('tags.gameplay'),
                       'other': tr('tags.other')}
            tags_list = self.mod_data.tags if isinstance(self.mod_data.tags, list) else [self.mod_data.tags]

            translated_tags = [tag_map.get(tg, tg) for tg in tags_list if tg]
            tags_string = ", ".join(translated_tags)
            if tags_string:
                tags_label = QLabel(
                    f'<span style="color:{text_color};font-weight:bold;font-size:13px;">{tr("ui.tags_label")}</span> '
                    f'<span style="color:{secondary_text};font-size:13px;">{tags_string}</span>'
                )
                tags_label.setWordWrap(True)
                meta.addWidget(tags_label)

        left.addLayout(meta)
        left.addStretch()

        lc = QWidget()
        lc.setMinimumWidth(450)
        lc.setMaximumWidth(450)
        lc.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        lc.setLayout(left)

        right = QVBoxLayout()
        right.setSpacing(15)

        dt = QLabel(f"<b style='color:{text_color};'>{tr('ui.full_description_label')}</b>")
        dt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(dt)

        self.desc_text = QTextBrowser()
        self.desc_text.setMinimumHeight(400)
        self.desc_text.setOpenExternalLinks(True)
        self.desc_text.setFrameShape(QTextBrowser.Shape.Box)
        self.desc_text.setLineWidth(2)
        self.desc_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {bg};
                color: {text_color};
                border: 2px solid {border};
                padding: 15px;
                font-size: 16px;
            }}
        """)
        self._desc_default_color = text_color
        right.addWidget(self.desc_text)

        btns = QHBoxLayout()
        btns.addStretch()
        self.compat_status_label = QLabel(self)
        self.compat_status_label.setObjectName('gbStatusLabel')
        self.compat_status_label.setVisible(False)
        btns.addWidget(self.compat_status_label)
        self.install_button = QPushButton()
        if self.source_card and hasattr(self.source_card, 'install_button'):
            self._sync_button_from_card()
            self.install_button.clicked.connect(lambda: self.source_card.install_button.click())
            try:
                from PyQt6.QtCore import QTimer
                self._sync_timer = QTimer()
                self._sync_timer.timeout.connect(self._sync_button_from_card)
                self._sync_timer.start(100)
            except Exception:
                pass
        else:
            self.install_button.setText(tr('buttons.install'))
            self.install_button.setObjectName('cardButtonInstall')
            self._set_install_button_style(border)
            parent_app = self.parent()
            if parent_app and hasattr(parent_app, 'install_mod'):
                self.install_button.clicked.connect(lambda: parent_app.install_mod(self.mod_data))
        btns.addWidget(self.install_button)
        from ui.common.styling import build_button_style
        cb = QPushButton(tr('buttons.close'))
        cb.clicked.connect(self.close_overlay)
        cb.setObjectName('cardButtonClose')
        cb.setStyleSheet(build_button_style('cardButtonClose', btn_bg, btn_hover, text_color, border))
        btns.addWidget(cb)
        right.addLayout(btns)

        rc = QWidget()
        rc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        rc.setLayout(right)

        cols.addWidget(lc, 0)
        cols.addWidget(rc, 1)
        cw = QWidget()
        cw.setLayout(cols)
        cl.addWidget(cw)
        scroll.setWidget(content)

        wrap = QHBoxLayout()
        wrap.setContentsMargins(10, 0, 10, 0)
        wrap.addWidget(scroll)
        root.addLayout(wrap)

        self._update_ss_nav()
        self._load_description()

    def _set_install_button_style(self, border, obj_name='cardButtonInstall', bg='#4CAF50', hover='#5cb85c'):
        """Set install button stylesheet."""
        from ui.common.styling import build_button_style
        self.install_button.setStyleSheet(build_button_style(obj_name, bg, hover, 'white', border))

    def _sync_button_from_card(self):
        """Synchronizes the Install button with the button from the mod card."""
        if not self.source_card or not hasattr(self.source_card, 'install_button'):
            return

        src_btn = self.source_card.install_button
        border = self._colors.get('border', '#fff')
        obj_name = src_btn.objectName()

        self.install_button.setText(src_btn.text())
        self.install_button.setObjectName(obj_name)
        self.install_button.setToolTip(src_btn.toolTip())
        self.install_button.setEnabled(src_btn.isEnabled())

        if obj_name == 'cardButtonUninstall':
            self._set_install_button_style(border, 'cardButtonUninstall', '#F44336', '#d32f2f')
        elif src_btn.toolTip() == tr('ui.gamebanana_status_manual_tooltip'):
            self._set_install_button_style(border, 'cardButtonInstall', '#FFC107', '#FFB300')
        else:
            self._set_install_button_style(border)

        if hasattr(self.source_card, 'gb_status_label') and self.source_card.gb_status_label:
            src_label = self.source_card.gb_status_label
            if src_label.isVisible():
                self.compat_status_label.setText(src_label.text())
                self.compat_status_label.setStyleSheet(src_label.styleSheet())
                self.compat_status_label.setToolTip(src_label.toolTip())
                self.compat_status_label.setVisible(True)
            else:
                self.compat_status_label.setVisible(False)
        else:
            self.compat_status_label.setVisible(False)

    def update_screenshots(self, urls):
        urls = [u for u in urls if isinstance(u, str) and u.startswith(('http://', 'https://'))][:10]
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
        if not self._ss_urls:
            return
        self._ss_index = (self._ss_index - 1) % len(self._ss_urls)
        self._ss_show_current()
        self._ss_preload_neighbors()
        self._ss_unload_distant()

    def _ss_next(self):
        if not self._ss_urls:
            return
        self._ss_index = (self._ss_index + 1) % len(self._ss_urls)
        self._ss_show_current()
        self._ss_preload_neighbors()
        self._ss_unload_distant()

    def _ss_show_current(self):
        if not self._ss_urls:
            self._img_label.clear()
            self._img_label.setText('No screenshots')
            self._update_ss_nav()
            return

        if self._ss_images[self._ss_index] is not None:
            self._ss_fade_to(self._ss_images[self._ss_index])
        else:
            self._img_label.clear()
            if not self._ss_loading[self._ss_index]:
                self._ss_load_image(self._ss_index)
            else:
                self._img_label.setText('Loading...')

        self._rebuild_dots()
        self._update_ss_nav()

    def _ss_load_image(self, idx):
        """Load screenshot at index."""
        self._ss_loading[idx] = True
        self._img_label.setText('Loading...')
        signals = WorkerSignals()
        signals.result.connect(lambda qimg, i=idx: self._ss_on_loaded(i, qimg))
        signals.error.connect(lambda url, msg, i=idx: self._ss_on_error(i, msg))
        self._thread_pool.start(ImageLoaderRunnable(self._ss_urls[idx], signals))

    def _ss_fade_to(self, qimg):
        self._ss_set_pixmap(qimg)
        UIAnimator.fade_in(self._img_label, duration=250, app_state=self._app_state)

    def _ss_set_pixmap(self, qimg):
        try:
            if _sip.isdeleted(self._img_label):
                return
        except (RuntimeError, AttributeError):
            return
        lw, lh = self._img_label.width(), self._img_label.height()
        pm = QPixmap.fromImage(qimg)
        scaled = pm.scaled(lw - 4, lh - 4, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        canvas = QPixmap(lw, lh)
        canvas.fill(QColor('transparent'))
        p = QPainter(canvas)
        p.drawPixmap((lw - scaled.width()) // 2, (lh - scaled.height()) // 2, scaled)
        p.end()
        self._img_label.setPixmap(canvas)

    def _ss_on_loaded(self, idx, qimg):
        if idx < len(self._ss_images):
            self._ss_images[idx] = qimg
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False
        if idx == self._ss_index:
            self._ss_fade_to(qimg)
            self._ss_unload_distant()

    def _ss_on_error(self, idx, msg):
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False
        if idx == self._ss_index:
            self._img_label.setText(tr('errors.file_not_available'))

    def _ss_preload_neighbors(self):
        for offset in (-1, 1):
            i = self._ss_index + offset
            if 0 <= i < len(self._ss_urls) and self._ss_images[i] is None and not self._ss_loading[i]:
                self._ss_loading[i] = True
                signals = WorkerSignals()
                signals.result.connect(lambda qimg, ii=i: self._ss_on_preloaded(ii, qimg))
                signals.error.connect(lambda url, msg, ii=i: self._ss_on_error(ii, msg))
                self._thread_pool.start(ImageLoaderRunnable(self._ss_urls[i], signals))

    def _ss_on_preloaded(self, idx, qimg):
        if idx < len(self._ss_images):
            self._ss_images[idx] = qimg
        if idx < len(self._ss_loading):
            self._ss_loading[idx] = False

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
        app_state = getattr(self.parent(), 'app_state', None) if self.parent() else None
        self.show()
        self.raise_()
        self.activateWindow()
        UIAnimator.fade_in(self, duration=300, app_state=app_state)

    def close_overlay(self):
        """Close the overlay with fade-out animation."""
        self._restore_main_window_resize()
        app_state = getattr(self.parent(), 'app_state', None) if self.parent() else None

        def cleanup():
            self.hide()
            self.deleteLater()

        if hasattr(self, '_fade_anim') and self._fade_anim:
            try:
                self._fade_anim.finished.disconnect()
            except (TypeError, RuntimeError):
                pass

        fade = UIAnimator.fade_out(self, duration=300, app_state=app_state)
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
            if not _sip.isdeleted(self) and self.isVisible():
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

    def _load_description(self):
        if hasattr(self.mod_data, 'full_description') and self.mod_data.full_description:
            self._set_description_html(self.mod_data.full_description)
        elif hasattr(self.mod_data, 'description_url') and self.mod_data.description_url:
            self._load_description_from_url()
        elif self.mod_data.is_gamebanana_mod() and self.mod_data.get_gamebanana_mod_id():
            self._load_gamebanana_description()
        else:
            self.desc_text.setPlainText(tr('ui.no_description'))

    def _set_description_html(self, content):
        """Set description HTML with error handling."""
        try:
            from ui.common.rich_html import set_rich_html
            set_rich_html(self.desc_text, content, default_color=self._desc_default_color)
        except Exception as e:
            logging.warning(f'Error setting description HTML: {e}')
            self.desc_text.setPlainText(content)

    def _load_description_from_url(self):
        """Load description from URL."""
        self.desc_text.setPlainText(tr('status.loading_description'))
        self.url_load_thread = LoadDescriptionFromUrlThread(self.mod_data.description_url, parent=None)
        self.url_load_thread.description_loaded.connect(self._on_url_description_loaded)
        self.url_load_thread.error_occurred.connect(self._on_url_description_error)
        self.url_load_thread.start()

    def _on_url_description_loaded(self, html_content):
        """Handle successful URL description load."""
        try:
            if self.dialog_closed or _sip.isdeleted(self):
                return
            self._set_description_html(html_content)
        except Exception as e:
            logging.error(f'Error in _on_url_description_loaded: {e}', exc_info=True)

    def _on_url_description_error(self, error_msg, status_code):
        """Handle URL description load error."""
        try:
            if self.dialog_closed or _sip.isdeleted(self):
                return
            if error_msg == 'http_error':
                self.desc_text.setPlainText(tr('errors.description_http_error_code', code=status_code))
            else:
                self.desc_text.setPlainText(tr('errors.description_load_error_details', error=error_msg))
        except Exception as e:
            logging.error(f'Error in _on_url_description_error: {e}', exc_info=True)

    def _load_gamebanana_description(self):
        """Load GameBanana mod description."""
        self.desc_text.setPlainText(tr('status.loading_description'))
        cache_dir = self._app_state.cache_dir if self._app_state and hasattr(self._app_state, 'cache_dir') else None
        self.load_thread = LoadModDetailsThread(self.mod_data, cache_dir=cache_dir, parent=None)
        self.load_thread.details_loaded.connect(self._on_details_loaded)
        self.load_thread.start()

    def _on_details_loaded(self, details):
        try:
            if self.dialog_closed or _sip.isdeleted(self):
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

    def cleanup_thread(self):
        if hasattr(self, '_sync_timer'):
            try:
                self._sync_timer.stop()
                self._sync_timer.deleteLater()
            except Exception:
                pass
        if self.load_thread:
            t = self.load_thread
            self.load_thread = None
            self._stop_thread(t)
        if getattr(self, 'url_load_thread', None):
            t = self.url_load_thread
            self.url_load_thread = None
            self._stop_thread(t)

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
