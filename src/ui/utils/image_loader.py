"""Asynchronous image loading.

This module provides utilities for loading images asynchronously with caching.
"""

import contextlib
import logging
import threading

from PyQt6.QtCore import QRunnable
from PyQt6.QtGui import QImage

from utils.cache_utils import _NET_SEM, add_to_cache, get_from_cache
from utils.network_utils import get_session
from workers import WorkerSignals

logger = logging.getLogger(__name__)


class ImageLoaderRunnable(QRunnable):
    _in_flight: set[str] = set()
    _in_flight_events: dict[str, threading.Event] = {}
    _in_flight_results: dict[str, tuple[bool, QImage | str]] = {}
    _in_flight_waiters: dict[str, int] = {}
    _in_flight_lock = threading.RLock()

    def __init__(self, url: str, signals: WorkerSignals) -> None:
        super().__init__()
        self.url = url
        self.signals = signals

    def _emit_error(self, message: str) -> None:
        with contextlib.suppress(Exception):
            self.signals.error.emit(self.url, message)

    def _emit_result(self, image: QImage) -> None:
        with contextlib.suppress(Exception):
            self.signals.result.emit(image)

    def _deliver_waited_result(self) -> None:
        with self._in_flight_lock:
            outcome = self._in_flight_results.get(self.url)
            waiters = self._in_flight_waiters.get(self.url, 0)
            if waiters <= 1:
                self._in_flight_waiters.pop(self.url, None)
                self._in_flight_results.pop(self.url, None)
            else:
                self._in_flight_waiters[self.url] = waiters - 1
        if not outcome:
            self._emit_error("network:UnknownError")
            return
        success, value = outcome
        if success:
            if isinstance(value, QImage):
                self._emit_result(value)
            else:
                self._emit_error("network:InvalidImage")
        else:
            self._emit_error(str(value))

    def run(self) -> None:
        import requests

        event = None
        acquired_sem = False
        is_fetcher = False
        try:
            if not self.url or not isinstance(self.url, str):
                self._emit_error("invalid_url")
                return
            if "[INVALID_URL]" in self.url or "/[PATH]" in self.url:
                self._emit_error("invalid_url")
                return
            url_lower = self.url.lower().strip()
            if not url_lower.startswith(("http://", "https://")):
                self._emit_error("invalid_url")
                return
            if ".." in self.url or len(self.url) > 2048:
                self._emit_error("invalid_url")
                return
            cached = get_from_cache(self.url)
            if cached is not None and (not cached.isNull()):
                try:
                    self._emit_result(cached)
                    return
                except Exception as e:
                    logger.debug(
                        f"ImageLoaderRunnable: failed to emit cached image result for {self.url}: {e}",
                        exc_info=True,
                    )
            wait_event = None
            with self._in_flight_lock:
                if self.url in self._in_flight:
                    wait_event = self._in_flight_events.get(self.url)
                    self._in_flight_waiters[self.url] = (
                        self._in_flight_waiters.get(self.url, 0) + 1
                    )
                else:
                    event = threading.Event()
                    self._in_flight_events[self.url] = event
                    self._in_flight.add(self.url)
                    is_fetcher = True
            if wait_event is not None:
                wait_event.wait()
                self._deliver_waited_result()
                return
            if _NET_SEM:
                _NET_SEM.acquire()
                acquired_sem = True
            try:
                session = get_session()
                resp = session.get(self.url, timeout=10, stream=False)
                resp.raise_for_status()
                try:
                    content_type = resp.headers.get("Content-Type", "") or ""
                except Exception:
                    content_type = ""
                if content_type and (not content_type.lower().startswith("image/")):
                    raise ValueError("non_image_content")
                content = resp.content
                if not content:
                    raise ValueError("empty response")
                img = QImage()
                if not img.loadFromData(content):
                    raise ValueError("decode")
                if img.isNull():
                    raise ValueError("null image")
                add_to_cache(self.url, img)
                with self._in_flight_lock:
                    self._in_flight_results[self.url] = (True, img)
                self._emit_result(img)
            except requests.RequestException as e:
                exception_type = type(e).__name__
                with self._in_flight_lock:
                    self._in_flight_results[self.url] = (
                        False,
                        f"network:{exception_type}",
                    )
                self._emit_error(f"network:{exception_type}")
            except Exception as e:
                message = str(e)
                with self._in_flight_lock:
                    self._in_flight_results[self.url] = (False, message)
                self._emit_error(message)
        except Exception as e:
            exception_type = type(e).__name__
            self._emit_error(exception_type)
        finally:
            with self._in_flight_lock:
                if is_fetcher:
                    self._in_flight.discard(self.url)
                    event = self._in_flight_events.pop(self.url, None)
                    if self._in_flight_waiters.get(self.url, 0) <= 0:
                        self._in_flight_results.pop(self.url, None)
                else:
                    event = None
            if is_fetcher and event is not None:
                event.set()
            try:
                if is_fetcher and _NET_SEM and acquired_sem:
                    _NET_SEM.release()
            except Exception as e:
                logger.debug(
                    f"ImageLoaderRunnable: failed to release network semaphore for {self.url}: {e}",
                    exc_info=True,
                )
