from __future__ import annotations
import io
from typing import Optional
import requests
from PIL import Image
from PyQt6.QtCore import QRunnable
from PyQt6.QtGui import QImage
from ui.widgets.common.worker_signals import WorkerSignals
from utils.cache import _IMG_CACHE, _IMG_CACHE_LOCK, _NET_SEM


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
        try:
            if _IMG_CACHE is not None and _IMG_CACHE_LOCK is not None:
                with _IMG_CACHE_LOCK:
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
                resp = requests.get(self.url, timeout=8)
            finally:
                try:
                    if _NET_SEM:
                        _NET_SEM.release()
                except Exception:
                    pass
            resp.raise_for_status()
            try:
                image_data = io.BytesIO(resp.content)
                pil_img = Image.open(image_data)
                if 'icc_profile' in pil_img.info:
                    del pil_img.info['icc_profile']
                buffer = io.BytesIO()
                pil_img.save(buffer, format='PNG')
                processed_content = buffer.getvalue()
            except Exception:
                processed_content = resp.content
            img = QImage()
            if not img.loadFromData(processed_content):
                self._emit_error('decode')
                return
            if _IMG_CACHE is not None:
                try:
                    if _IMG_CACHE_LOCK is not None:
                        _IMG_CACHE_LOCK.acquire()
                    _IMG_CACHE[self.url] = img
                except Exception:
                    pass
                finally:
                    try:
                        if _IMG_CACHE_LOCK is not None:
                            _IMG_CACHE_LOCK.release()
                    except Exception:
                        pass
            try:
                self.signals.result.emit(img)
            finally:
                pass
        except requests.RequestException as e:
            self._emit_error(f'network:{e}')
        except Exception as e:
            self._emit_error(str(e))
