from __future__ import annotations
import logging
from PyQt6.QtCore import QRunnable
from PyQt6.QtGui import QImage
from workers import WorkerSignals
from utils.cache import _NET_SEM, get_from_cache, add_to_cache
from utils.network_utils import get_session, sanitize_log_message, mask_url


class ImageLoaderRunnable(QRunnable):

    def __init__(self, url: str, signals: WorkerSignals):
        super().__init__()
        self.url = url
        self.signals = signals

    def _emit_error(self, message: str) -> None:
        try:
            self.signals.error.emit(self.url, message)
        except Exception as e:
            exception_type = type(e).__name__
            safe_msg = sanitize_log_message(f'ImageLoader._emit_error: signal emit failed: {exception_type}')
            logging.debug(safe_msg)

    def run(self) -> None:
        import requests
        try:
            if not self.url or not isinstance(self.url, str):
                self._emit_error('invalid_url')
                return
            if '[INVALID_URL]' in self.url or '/[PATH]' in self.url:
                masked_url = mask_url(self.url)
                safe_msg = sanitize_log_message(f'ImageLoader.run: Invalid URL format detected: {masked_url}')
                logging.warning(safe_msg)
                self._emit_error('invalid_url')
                return
            url_lower = self.url.lower().strip()
            if not url_lower.startswith(('http://', 'https://')):
                masked_url = mask_url(self.url)
                safe_msg = sanitize_log_message(f'ImageLoader.run: URL does not start with http:// or https://: {masked_url}')
                logging.warning(safe_msg)
                self._emit_error('invalid_url')
                return
            if '..' in self.url or len(self.url) > 2048:
                masked_url = mask_url(self.url)
                safe_msg = sanitize_log_message(f'ImageLoader.run: Suspicious URL detected: {masked_url}')
                logging.warning(safe_msg)
                self._emit_error('invalid_url')
                return
            cached = get_from_cache(self.url)
            if cached is not None and (not cached.isNull()):
                try:
                    self.signals.result.emit(cached)
                    return
                except Exception as e:
                    exception_type = type(e).__name__
                    safe_msg = sanitize_log_message(f'ImageLoader.run: Error emitting cached image: {exception_type}')
                    logging.debug(safe_msg)
            if _NET_SEM:
                _NET_SEM.acquire()
            try:
                session = get_session()
                resp = session.get(self.url, timeout=10, stream=False)
            finally:
                try:
                    if _NET_SEM:
                        _NET_SEM.release()
                except Exception as e:
                    exception_type = type(e).__name__
                    safe_msg = sanitize_log_message(f'ImageLoader.run: semaphore release failed: {exception_type}')
                    logging.debug(safe_msg)
            resp.raise_for_status()
            try:
                content_type = resp.headers.get('Content-Type', '') or ''
            except Exception:
                content_type = ''
            if content_type and (not content_type.lower().startswith('image/')):
                masked_url = mask_url(self.url)
                safe_msg = sanitize_log_message(f'ImageLoader.run: Non-image content-type "{content_type}" for URL: {masked_url}')
                logging.debug(safe_msg)
                self._emit_error('non_image_content')
                return
            content = resp.content
            if not content:
                self._emit_error('empty response')
                return
            img = QImage()
            if not img.loadFromData(content):
                masked_url = mask_url(self.url)
                safe_msg = sanitize_log_message(f'ImageLoader.run: Failed to load image from data for URL: {masked_url}')
                logging.warning(safe_msg)
                self._emit_error('decode')
                return
            if img.isNull():
                masked_url = mask_url(self.url)
                safe_msg = sanitize_log_message(f'ImageLoader.run: Loaded image is null for URL: {masked_url}')
                logging.warning(safe_msg)
                self._emit_error('null image')
                return
            add_to_cache(self.url, img)
            try:
                self.signals.result.emit(img)
            except Exception as e:
                exception_type = type(e).__name__
                safe_msg = sanitize_log_message(f'ImageLoader.run: Error emitting result: {exception_type}')
                logging.debug(safe_msg)
        except requests.RequestException as e:
            masked_url = mask_url(self.url)
            exception_type = type(e).__name__
            safe_msg = sanitize_log_message(f'ImageLoader.run: Request exception ({exception_type}) for URL {masked_url}')
            logging.debug(safe_msg)
            self._emit_error(f'network:{exception_type}')
        except Exception as e:
            logging.error('ImageLoader.run: Unexpected error occurred during image loading')
            masked_url = mask_url(self.url)
            exception_type = type(e).__name__
            safe_msg = sanitize_log_message(f'ImageLoader.run: Unexpected error details - Type: {exception_type}, URL: {masked_url}')
            logging.debug(safe_msg)
            self._emit_error(exception_type)
