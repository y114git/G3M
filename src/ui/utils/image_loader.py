"""Asynchronous image loading.

This module provides utilities for loading images asynchronously with caching.
"""
from PyQt6.QtCore import QRunnable
from PyQt6.QtGui import QImage
from workers import WorkerSignals
from utils.cache_utils import _NET_SEM, get_from_cache, add_to_cache
from utils.network_utils import get_session


class ImageLoaderRunnable(QRunnable):

    def __init__(self, url: str, signals: WorkerSignals):
        super().__init__()
        self.url = url
        self.signals = signals

    def _emit_error(self, message: str) -> None:
        try:
            self.signals.error.emit(self.url, message)
        except Exception:
            pass

    def run(self) -> None:
        import requests
        try:
            if not self.url or not isinstance(self.url, str):
                self._emit_error('invalid_url')
                return
            if '[INVALID_URL]' in self.url or '/[PATH]' in self.url:
                self._emit_error('invalid_url')
                return
            url_lower = self.url.lower().strip()
            if not url_lower.startswith(('http://', 'https://')):
                self._emit_error('invalid_url')
                return
            if '..' in self.url or len(self.url) > 2048:
                self._emit_error('invalid_url')
                return
            cached = get_from_cache(self.url)
            if cached is not None and (not cached.isNull()):
                try:
                    self.signals.result.emit(cached)
                    return
                except Exception:
                    pass
            if _NET_SEM:
                _NET_SEM.acquire()
            try:
                session = get_session()
                resp = session.get(self.url, timeout=10, stream=False)
            finally:
                try:
                    if _NET_SEM:
                        _NET_SEM.release()
                except Exception:
                    pass
            resp.raise_for_status()
            try:
                content_type = resp.headers.get('Content-Type', '') or ''
            except Exception:
                content_type = ''
            if content_type and (not content_type.lower().startswith('image/')):
                self._emit_error('non_image_content')
                return
            content = resp.content
            if not content:
                self._emit_error('empty response')
                return
            img = QImage()
            if not img.loadFromData(content):
                self._emit_error('decode')
                return
            if img.isNull():
                self._emit_error('null image')
                return
            add_to_cache(self.url, img)
            try:
                self.signals.result.emit(img)
            except Exception:
                pass
        except requests.RequestException as e:
            exception_type = type(e).__name__
            self._emit_error(f'network:{exception_type}')
        except Exception as e:
            exception_type = type(e).__name__
            self._emit_error(exception_type)
