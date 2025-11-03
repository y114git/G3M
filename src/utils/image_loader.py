from __future__ import annotations
import io
import logging
import requests
from PIL import Image
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
                from utils.network_utils import sanitize_log_message
                safe_msg = sanitize_log_message(f'ImageLoader.run: PIL processing failed, using raw content: {e}')
                logging.debug(safe_msg)
                processed_content = resp.content
            img = QImage()
            if not img.loadFromData(processed_content):
                self._emit_error('decode')
                return
            add_to_cache(self.url, img)
            try:
                self.signals.result.emit(img)
            finally:
                pass
        except requests.RequestException as e:
            self._emit_error(f'network:{e}')
        except (OSError, ValueError, RuntimeError) as e:
            self._emit_error(str(e))
