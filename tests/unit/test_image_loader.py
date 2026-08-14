from unittest.mock import Mock

from config.config import NETWORK_SEMAPHORE_LIMIT
from ui.utils.image_loader import ImageLoaderRunnable, get_image_loader_pool


def test_image_loader_pool_is_bounded():
    assert get_image_loader_pool().maxThreadCount() == NETWORK_SEMAPHORE_LIMIT


def test_duplicate_image_load_times_out_without_waiting_indefinitely(monkeypatch):
    url = "https://example.com/icon.png"
    signals = Mock()
    event = Mock()
    event.wait.return_value = False
    monkeypatch.setattr("ui.utils.image_loader.get_from_cache", lambda _url: None)
    with ImageLoaderRunnable._in_flight_lock:
        ImageLoaderRunnable._in_flight = {url}
        ImageLoaderRunnable._in_flight_events = {url: event}
        ImageLoaderRunnable._in_flight_results = {}
        ImageLoaderRunnable._in_flight_waiters = {}
    try:
        ImageLoaderRunnable(url, signals).run()

        event.wait.assert_called_once_with(15)
        signals.error.emit.assert_called_once_with(url, "network:Timeout")
    finally:
        with ImageLoaderRunnable._in_flight_lock:
            ImageLoaderRunnable._in_flight.clear()
            ImageLoaderRunnable._in_flight_events.clear()
            ImageLoaderRunnable._in_flight_results.clear()
            ImageLoaderRunnable._in_flight_waiters.clear()
