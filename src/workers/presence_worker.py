"""User presence tracking worker."""

import json
import logging
import time

import requests
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from config.config import (
    BROWSER_HEADERS,
    CLOUD_FUNCTIONS_BASE_URL,
    NETWORK_TIMEOUT_SHORT,
)
from utils.network_utils import cloud_function_request

logger = logging.getLogger(__name__)


class PresenceWorker(QObject):
    finished, update_online_count = pyqtSignal(), pyqtSignal(int)
    _MIN_HEARTBEAT_INTERVAL_SECONDS = 120
    _REQUEST_TIMEOUT_SECONDS = min(2, NETWORK_TIMEOUT_SHORT)

    def __init__(self, session_id, app_state=None) -> None:
        super().__init__()
        self.session_id, self.app_state, self._busy = session_id, app_state, False
        self._last_heartbeat_at = 0.0
        self._last_online_count = -1

    def _safe_emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError as e:
            if "deleted" not in str(e):
                raise

    @pyqtSlot()
    def run(self):
        count = self._last_online_count
        try:
            if (
                self._busy
                or not self.app_state
                or not getattr(self.app_state, "has_internet", True)
            ):
                return
            now = time.time()
            if now - self._last_heartbeat_at < self._MIN_HEARTBEAT_INTERVAL_SECONDS:
                return
            self._busy = True
            session = requests.Session()
            try:
                session.headers.update(BROWSER_HEADERS or {})
                resp = cloud_function_request(
                    "post",
                    f"{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat",
                    session=session,
                    json={"sessionId": self.session_id},
                    timeout=self._REQUEST_TIMEOUT_SECONDS,
                )
            finally:
                session.close()
            self._last_heartbeat_at = now
            if resp is not None and resp.status_code == 200:
                try:
                    count = max(int((resp.json() or {}).get("online", 0)), 0)
                except (json.JSONDecodeError, ValueError, TypeError):
                    count = self._last_online_count if self._last_online_count >= 0 else 0
        except (
            requests.Timeout,
            requests.ConnectionError,
            requests.RequestException,
        ) as e:
            logger.debug(f"Presence worker network error: {e}")
        except Exception:
            logger.exception("Presence worker unexpected error")
        finally:
            self._busy = False
            if count >= 0:
                self._last_online_count = count
            self._safe_emit(self.update_online_count, count)
            self._safe_emit(self.finished)
