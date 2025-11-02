import contextlib
import logging
import threading
from collections import OrderedDict
from PyQt6.QtGui import QImage, QPixmap
from config.constants import IMAGE_CACHE_MAX_SIZE, NETWORK_SEMAPHORE_LIMIT
try:
    _IMG_CACHE: OrderedDict[str, QImage] = OrderedDict()
    _PIX_CACHE: dict[str, QPixmap] = {}
    _IMG_CACHE_LOCK = threading.RLock()
    _NET_SEM = threading.Semaphore(NETWORK_SEMAPHORE_LIMIT)
    _CACHE_MAX_SIZE = IMAGE_CACHE_MAX_SIZE
except Exception as e:
    logging.warning(f'cache: failed to initialize cache/locks: {e}')
    _IMG_CACHE, _PIX_CACHE, _IMG_CACHE_LOCK, _NET_SEM, _CACHE_MAX_SIZE = (OrderedDict(), {}, None, None, IMAGE_CACHE_MAX_SIZE)


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


def add_to_cache(key: str, image: QImage) -> None:
    with cache_lock():
        if key in _IMG_CACHE:
            _IMG_CACHE.move_to_end(key)
        _IMG_CACHE[key] = image
        _trim_cache()


def get_from_cache(key: str) -> QImage | None:
    with cache_lock():
        if key in _IMG_CACHE:
            _IMG_CACHE.move_to_end(key)
            return _IMG_CACHE[key]
    return None
