"""Image and data caching utilities."""

import contextlib
import logging
import threading
from collections import OrderedDict

from PyQt6.QtGui import QImage

from config.config import IMAGE_CACHE_MAX_SIZE, NETWORK_SEMAPHORE_LIMIT

logger = logging.getLogger(__name__)

try:
    _IMG_CACHE: OrderedDict[str, QImage] = OrderedDict()
    _IMG_CACHE_LOCK, _NET_SEM = (
        threading.RLock(),
        threading.Semaphore(NETWORK_SEMAPHORE_LIMIT),
    )
except (ValueError, RuntimeError) as e:
    logger.warning(f"cache: failed to initialize cache/locks: {e}")
    _IMG_CACHE, _IMG_CACHE_LOCK, _NET_SEM = OrderedDict(), None, None


@contextlib.contextmanager
def cache_lock():
    """Thread-safe cache access context manager."""
    acquired = _IMG_CACHE_LOCK is not None
    if acquired:
        _IMG_CACHE_LOCK.acquire()
    try:
        yield
    finally:
        if acquired:
            _IMG_CACHE_LOCK.release()


def add_to_cache(key: str, image: QImage) -> None:
    """Add image to cache with LRU eviction."""
    with cache_lock():
        if key in _IMG_CACHE:
            _IMG_CACHE.move_to_end(key)
        _IMG_CACHE[key] = image
        while len(_IMG_CACHE) > IMAGE_CACHE_MAX_SIZE:
            _IMG_CACHE.popitem(last=False)


def get_from_cache(key: str) -> QImage | None:
    """Retrieve image from cache."""
    with cache_lock():
        if key in _IMG_CACHE:
            _IMG_CACHE.move_to_end(key)
            return _IMG_CACHE[key]
    return None
