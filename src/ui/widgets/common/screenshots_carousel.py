from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from managers.localization_manager import tr
from utils.image_loader import ImageLoaderRunnable
import logging
from workers import WorkerSignals


class ScreenshotsCarousel(QWidget):

    def __init__(self, urls: list[str], parent=None, app_state=None):
        super().__init__(parent)
        self.app_state = app_state
        self.urls = [u for u in urls if isinstance(u, str) and u.startswith(('http://', 'https://'))][:10]
        self.index = 0
        self._images = [None] * len(self.urls)
        self._loading = [False] * len(self.urls)
        self._thread_pool = QThreadPool.globalInstance()
        self._thread_pool.setMaxThreadCount(min(4, self._thread_pool.maxThreadCount()))
        try:
            self.destroyed.connect(self._cleanup)
        except Exception:
            pass
        self._init_ui()
        if self.urls:
            self._show_current()
        else:
            self._update_nav_state()

    def _cleanup(self):
        pass

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.image_label = QLabel(self)
        fixed_w, fixed_h = (500, 280)
        self.setMaximumWidth(fixed_w)
        self.image_label.setFixedSize(fixed_w, fixed_h)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet('background-color: black; border: 1px solid #444;')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton('⮜', self)
        self.next_btn = QPushButton('⮞', self)
        self.prev_btn.setObjectName('carouselPrevButton')
        self.next_btn.setObjectName('carouselNextButton')
        self.setStyleSheet('\n            QPushButton#carouselPrevButton, QPushButton#carouselNextButton {\n                min-width: 34px; max-width: 34px;\n                min-height: 28px; max-height: 28px;\n                padding: 0px; margin: 0px;\n                font-size: 12px;\n            }\n            ')
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn.clicked.connect(self._next)
        nav_layout.addStretch()
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addSpacing(8)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addStretch()
        self.dots_layout = QHBoxLayout()
        self.dots_layout.setSpacing(4)
        self._dot_labels = []
        layout.addWidget(self.image_label)
        layout.addLayout(nav_layout)
        dots_container = QHBoxLayout()
        dots_container.addStretch()
        dots_container.addLayout(self.dots_layout)
        dots_container.addStretch()
        layout.addLayout(dots_container)
        self._nav_container = nav_layout
        self._root_layout = layout

    def _ensure_dots(self):
        while self.dots_layout.count():
            item = self.dots_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setParent(None)
        self._dot_labels = []
        from ui.common.styling import get_theme_color
        text_color = 'white'
        if self.app_state and hasattr(self.app_state, 'local_config'):
            text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        for i in range(len(self.urls)):
            lbl = QLabel('●' if i == self.index else '○', self)
            lbl.setStyleSheet(f'color: {text_color}; font-size: 14px;')
            self._dot_labels.append(lbl)
            self.dots_layout.addWidget(lbl)

    def _prev(self):
        if not self.urls:
            return
        self.index = (self.index - 1) % len(self.urls)
        self._show_current()

    def _next(self):
        if not self.urls:
            return
        self.index = (self.index + 1) % len(self.urls)
        self._show_current()

    def _update_nav_state(self):
        count = len(self.urls)
        enable_nav = count > 1
        self.prev_btn.setEnabled(enable_nav)
        self.next_btn.setEnabled(enable_nav)
        for i in range(self.dots_layout.count()):
            item = self.dots_layout.itemAt(i)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setVisible(enable_nav)
        self.prev_btn.setVisible(enable_nav)
        self.next_btn.setVisible(enable_nav)

    def _show_current(self):
        self._ensure_dots()
        self._update_nav_state()
        if not self.urls:
            self.image_label.setText(tr('ui.empty'))
            return
        url = self.urls[self.index]
        img = self._images[self.index]
        if img is None:
            if not hasattr(self, '_loading'):
                self._loading = [False] * len(self.urls)
                self._current_worker = None
            if not self._loading[self.index]:
                self._loading[self.index] = True
                signals = WorkerSignals()
                idx = self.index

                def on_loaded(qimg):
                    if idx < len(self._images):
                        self._images[idx] = qimg
                        self._loading[idx] = False
                    try:
                        from PyQt6 import sip as _sip
                        if not hasattr(self, 'image_label') or _sip.isdeleted(self.image_label):
                            return
                    except Exception:
                        pass
                    if idx == self.index:
                        self._set_pixmap(qimg)

                def on_error(url, error_msg):
                    if idx < len(self._loading):
                        self._loading[idx] = False
                    try:
                        from PyQt6 import sip as _sip
                        if not hasattr(self, 'image_label') or _sip.isdeleted(self.image_label):
                            return
                    except Exception:
                        pass
                    if idx == self.index:
                        try:
                            from PyQt6 import sip as _sip
                            if hasattr(self, 'image_label') and (not _sip.isdeleted(self.image_label)):
                                self.image_label.setText(tr('errors.file_not_available'))
                        except Exception:
                            pass
                signals.result.connect(on_loaded)
                signals.error.connect(on_error)
                loader = ImageLoaderRunnable(url, signals)
                if self.app_state and hasattr(self.app_state, 'network_session'):
                    pass
                self._thread_pool.start(loader)
            return
        self._set_pixmap(img)
        self._preload_neighbor(self.index - 1)
        self._preload_neighbor(self.index + 1)

    def _preload_neighbor(self, idx: int):
        if not self.urls:
            return
        if idx < 0 or idx >= len(self.urls):
            return
        if self._images[idx] is not None or (hasattr(self, '_loading') and idx < len(self._loading) and self._loading[idx]):
            return
        if not hasattr(self, '_loading'):
            self._loading = [False] * len(self.urls)
        self._loading[idx] = True
        signals = WorkerSignals()
        preload_idx = idx

        def on_preload_loaded(qimg):
            if preload_idx < len(self._images):
                self._images[preload_idx] = qimg
            if hasattr(self, '_loading') and preload_idx < len(self._loading):
                self._loading[preload_idx] = False

        def on_preload_error(url, error_msg):
            if hasattr(self, '_loading') and preload_idx < len(self._loading):
                self._loading[preload_idx] = False
        signals.result.connect(on_preload_loaded)
        signals.error.connect(on_preload_error)
        loader = ImageLoaderRunnable(self.urls[idx], signals)
        self._thread_pool.start(loader)

    def _set_pixmap(self, qimg: QImage):
        try:
            from PyQt6 import sip as _sip
            if not hasattr(self, 'image_label'):
                return
            try:
                if _sip.isdeleted(self.image_label):
                    return
            except (RuntimeError, AttributeError):
                return
            try:
                if not hasattr(self.image_label, 'parent'):
                    return
            except (RuntimeError, AttributeError):
                return
        except Exception as e:
            logging.debug(f'ScreenshotsCarousel._set_pixmap: Error checking widget validity: {e}')
            return
        try:
            label_w = self.image_label.width() or 760
            label_h = self.image_label.height() or 220
            pm = QPixmap.fromImage(qimg)
            scaled = pm.scaled(label_w, label_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            canvas = QPixmap(label_w, label_h)
            canvas.fill(QColor('black'))
            painter = QPainter(canvas)
            x = (label_w - scaled.width()) // 2
            y = (label_h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
            self.image_label.setPixmap(canvas)
        except (RuntimeError, AttributeError) as e:
            logging.debug(f'ScreenshotsCarousel._set_pixmap: Widget deleted during pixmap set: {e}')
        except Exception as e:
            logging.debug(f'ScreenshotsCarousel._set_pixmap: Error setting pixmap: {e}')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.urls and 0 <= self.index < len(self._images):
            current = self._images[self.index]
            if current is not None:
                try:
                    from PyQt6 import sip as _sip
                    if hasattr(self, 'image_label') and (not _sip.isdeleted(self.image_label)):
                        self._set_pixmap(current)
                except Exception:
                    pass
