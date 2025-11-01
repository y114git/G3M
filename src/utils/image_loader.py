from __future__ import annotations
import io
import logging
from typing import Optional
import requests
from PIL import Image
from PyQt6.QtCore import QRunnable
from PyQt6.QtGui import QImage
from workers import WorkerSignals
from utils.cache import _IMG_CACHE, _IMG_CACHE_LOCK, _NET_SEM, cache_lock, _trim_cache
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
            logging.debug(f'ImageLoader._emit_error: signal emit failed for {self.url}: {e}')

    def run(self) -> None:
        try:
            if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                with cache_lock():
                    cached: Optional[QImage] = _IMG_CACHE.get(self.url)
                    if cached is not None and (not cached.isNull()):
                        try:
                            self.signals.result.emit(cached)
                        finally:
                            pass
                        return
            if _NET_SEM:
                _NET_SEM.acquire()
            try:
                session = get_session()
                resp = session.get(self.url, timeout=8)
            finally:
                try:
                    if _NET_SEM:
                        _NET_SEM.release()
                except Exception as e:
                    logging.debug(f'ImageLoader.run: semaphore release failed: {e}')
            resp.raise_for_status()
            try:
                image_data = io.BytesIO(resp.content)
                pil_img = Image.open(image_data)
                if 'icc_profile' in pil_img.info:
                    del pil_img.info['icc_profile']
                buffer = io.BytesIO()
                pil_img.save(buffer, format='PNG')
                processed_content = buffer.getvalue()
            except Exception as e:
                logging.debug(f'ImageLoader.run: PIL processing failed for {self.url}, using raw content: {e}')
                processed_content = resp.content
            img = QImage()
            if not img.loadFromData(processed_content):
                self._emit_error('decode')
                return
            if _IMG_CACHE is not None:
                with cache_lock():
                    _IMG_CACHE[self.url] = img
                    _trim_cache()
            try:
                self.signals.result.emit(img)
            finally:
                pass
        except requests.RequestException as e:
            self._emit_error(f'network:{e}')
        except (OSError, ValueError, RuntimeError) as e:
            self._emit_error(str(e))
