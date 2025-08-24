from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from localization.manager import tr

class ScreenshotsCarousel(QWidget):

    def __init__(self, urls: list[str], parent=None):
        super().__init__(parent)
        self.urls = [u for u in urls if isinstance(u, str) and u.startswith(('http://', 'https://'))][:10]
        self.index = 0
        self._images = [None] * len(self.urls)
        self._workers = {}
        self._loading = [False] * len(self.urls)
        try:
            self.destroyed.connect(self._stop_all_workers)
        except Exception:
            pass
        self._init_ui()
        if self.urls:
            self._show_current()
        else:
            self._update_nav_state()

    def _stop_all_workers(self):
        try:
            for k, w in list(getattr(self, '_workers', {}).items()):
                try:
                    if w.isRunning():
                        w.requestInterruption()
                        w.quit()
                        w.wait(1000)
                except Exception:
                    pass
            if hasattr(self, '_workers'):
                self._workers.clear()
        except Exception:
            pass

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.image_label = QLabel()
        fixed_w, fixed_h = (500, 280)
        self.setMaximumWidth(fixed_w)
        self.image_label.setFixedSize(fixed_w, fixed_h)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet('background-color: black; border: 1px solid #444;')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton('⮜')
        self.next_btn = QPushButton('⮞')
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
        for i in range(len(self.urls)):
            lbl = QLabel('●' if i == self.index else '○')
            lbl.setStyleSheet('color: white; font-size: 14px;')
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
                from PyQt6.QtCore import QThread, pyqtSignal
                from utils.cache import _IMG_CACHE, _IMG_CACHE_LOCK, _NET_SEM

                class _ImgLoader(QThread):
                    loaded = pyqtSignal(int, object)
                    failed = pyqtSignal(int)

                    def __init__(self, idx, url):
                        super().__init__()
                        self.idx, self.url = (idx, url)

                    def run(self):
                        try:
                            if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                                with _IMG_CACHE_LOCK:
                                    if self.url in _IMG_CACHE:
                                        self.loaded.emit(self.idx, _IMG_CACHE[self.url])
                                        return
                            import requests
                            if _NET_SEM:
                                _NET_SEM.acquire()
                            try:
                                r = requests.get(self.url, timeout=10)
                            finally:
                                try:
                                    if _NET_SEM:
                                        _NET_SEM.release()
                                except Exception:
                                    pass
                            if not r.ok:
                                self.failed.emit(self.idx)
                                return
                            q = QImage()
                            if not q.loadFromData(r.content):
                                self.failed.emit(self.idx)
                                return
                            if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                                try:
                                    with _IMG_CACHE_LOCK:
                                        _IMG_CACHE[self.url] = q
                                except Exception:
                                    pass
                            self.loaded.emit(self.idx, q)
                        except Exception:
                            self.failed.emit(self.idx)
                worker = _ImgLoader(self.index, url)

                def on_loaded(i, qimg):
                    if i < len(self._images):
                        self._images[i] = qimg
                        self._loading[i] = False
                    try:
                        from PyQt6 import sip as _sip
                        if not hasattr(self, 'image_label') or _sip.isdeleted(self.image_label):
                            return
                    except Exception:
                        pass
                    if i == self.index:
                        self._set_pixmap(qimg)

                def on_failed(i):
                    if i < len(self._loading):
                        self._loading[i] = False
                    try:
                        from PyQt6 import sip as _sip
                        if not hasattr(self, 'image_label') or _sip.isdeleted(self.image_label):
                            return
                    except Exception:
                        pass
                    if i == self.index:
                        try:
                            from PyQt6 import sip as _sip
                            if hasattr(self, 'image_label') and (not _sip.isdeleted(self.image_label)):
                                self.image_label.setText(tr('errors.file_not_available'))
                        except Exception:
                            pass
                worker.loaded.connect(on_loaded)
                worker.failed.connect(on_failed)
                if not hasattr(self, '_workers'):
                    self._workers = {}
                self._workers[self.index] = worker
                worker.start()
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
        if not hasattr(self, '_workers'):
            self._workers = {}
        from utils.cache import _IMG_CACHE, _IMG_CACHE_LOCK, _NET_SEM

        class _Preloader(QThread):
            loaded = pyqtSignal(int, object)
            failed = pyqtSignal(int)

            def __init__(self, i, url):
                super().__init__()
                self.i, self.url = (i, url)

            def run(self):
                try:
                    if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                        with _IMG_CACHE_LOCK:
                            if self.url in _IMG_CACHE:
                                self.loaded.emit(self.i, _IMG_CACHE[self.url])
                                return
                    import requests
                    if _NET_SEM:
                        _NET_SEM.acquire()
                    try:
                        r = requests.get(self.url, timeout=10)
                    finally:
                        try:
                            if _NET_SEM:
                                _NET_SEM.release()
                        except Exception:
                            pass
                    if not r.ok:
                        self.failed.emit(self.i)
                        return
                    q = QImage()
                    if not q.loadFromData(r.content):
                        self.failed.emit(self.i)
                        return
                    if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                        try:
                            with _IMG_CACHE_LOCK:
                                _IMG_CACHE[self.url] = q
                        except Exception:
                            pass
                    self.loaded.emit(self.i, q)
                except Exception:
                    self.failed.emit(self.i)
        w = _Preloader(idx, self.urls[idx])

        def on_loaded(i, qimg):
            if i < len(self._images):
                self._images[i] = qimg
            if hasattr(self, '_loading') and i < len(self._loading):
                self._loading[i] = False
            if hasattr(self, '_workers'):
                self._workers.pop(i, None)

        def on_failed(i):
            if hasattr(self, '_loading') and i < len(self._loading):
                self._loading[i] = False
            if hasattr(self, '_workers'):
                self._workers.pop(i, None)
        w.loaded.connect(on_loaded)
        w.failed.connect(on_failed)
        self._workers[idx] = w
        w.start()

    def _set_pixmap(self, qimg: QImage):
        try:
            from PyQt6 import sip as _sip
            if not hasattr(self, 'image_label') or _sip.isdeleted(self.image_label):
                return
        except Exception:
            pass
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