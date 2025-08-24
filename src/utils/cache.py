import threading
from PyQt6.QtGui import QImage, QPixmap
try:
    _IMG_CACHE: dict[str, QImage] = {}
    _PIX_CACHE: dict[str, QPixmap] = {}
    _IMG_CACHE_LOCK = threading.Lock()
    _NET_SEM = threading.Semaphore(6)
except Exception:
    _IMG_CACHE, _PIX_CACHE, _IMG_CACHE_LOCK, _NET_SEM = ({}, {}, None, None)