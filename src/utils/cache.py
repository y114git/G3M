import contextlib
import logging
import threading
from collections import OrderedDict
from PyQt6.QtGui import QImage, QPixmap
try:
    _IMG_CACHE: OrderedDict[str, QImage] = OrderedDict()
    _PIX_CACHE: dict[str, QPixmap] = {}
    _IMG_CACHE_LOCK = threading.RLock()
    _NET_SEM = threading.Semaphore(4)
    _CACHE_MAX_SIZE = 100
except Exception as e:
    logging.warning(f'cache: failed to initialize cache/locks: {e}')
    _IMG_CACHE, _PIX_CACHE, _IMG_CACHE_LOCK, _NET_SEM, _CACHE_MAX_SIZE = (OrderedDict(), {}, None, None, 100)


@contextlib.contextmanager
def cache_lock():
    if _IMG_CACHE_LOCK is not None:
        _IMG_CACHE_LOCK.acquire()
    try:
        yield
    finally:
        if _IMG_CACHE_LOCK is not None:
            _IMG_CACHE_LOCK.release()


def _trim_cache():
    if _IMG_CACHE is not None:
        while len(_IMG_CACHE) > _CACHE_MAX_SIZE:
            _IMG_CACHE.popitem(last=False)
