from __future__ import annotations
import logging
import requests
from PyQt6.QtCore import QRunnable
from PyQt6.QtGui import QImage
from workers import WorkerSignals
from utils.cache import _NET_SEM, get_from_cache, add_to_cache
from utils.network_utils import get_session


class ImageLoaderRunnable(QRunnable):

    def __init__(self, url: str, signals: WorkerSignals):
        super().__init__()
        self.url = url
        self.signals = signals

    def _emit_error(self, message: str) -> None:
        try:
            self.signals.error.emit(self.url, message)
        except Exception as e:
            from utils.network_utils import sanitize_log_message
            safe_msg = sanitize_log_message(f'ImageLoader._emit_error: signal emit failed: {e}')
            logging.debug(safe_msg)

    def run(self) -> None:
        try:
            cached = get_from_cache(self.url)
            if cached is not None and (not cached.isNull()):
                try:
                    self.signals.result.emit(cached)
                    return
                except Exception as e:
                    logging.debug(f'ImageLoader.run: Error emitting cached image: {e}')
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
                    logging.debug(f'ImageLoader.run: semaphore release failed: {e}')
            resp.raise_for_status()
            content = resp.content
            if not content:
                self._emit_error('empty response')
                return
            img = QImage()
            if not img.loadFromData(content):
                logging.warning(f'ImageLoader.run: Failed to load image from data for URL: {self.url[:100]}')
                self._emit_error('decode')
                return
            if img.isNull():
                logging.warning(f'ImageLoader.run: Loaded image is null for URL: {self.url[:100]}')
                self._emit_error('null image')
                return
            add_to_cache(self.url, img)
            try:
                self.signals.result.emit(img)
            except Exception as e:
                logging.debug(f'ImageLoader.run: Error emitting result: {e}')
        except requests.RequestException as e:
            logging.debug(f'ImageLoader.run: Request exception for URL {self.url[:100]}: {e}')
            self._emit_error(f'network:{e}')
        except Exception as e:
            logging.error(f'ImageLoader.run: Unexpected error for URL {self.url[:100]}: {e}', exc_info=True)
            self._emit_error(str(e))
