"""User presence tracking worker."""

import json
import logging
import time

import requests
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from config.config import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_SHORT
from utils.network_utils import cloud_function_request


class PresenceWorker(QObject):
    finished, update_online_count = pyqtSignal(), pyqtSignal(int)
    _MIN_HEARTBEAT_INTERVAL_SECONDS = 120

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
            resp = cloud_function_request(
                "post",
                f"{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat",
                json={"sessionId": self.session_id},
                timeout=NETWORK_TIMEOUT_SHORT,
            )
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
            logging.debug(f"Presence worker network error: {e}")
        finally:
            self._busy = False
            if count >= 0:
                self._last_online_count = count
            self._safe_emit(self.update_online_count, count)
            self._safe_emit(self.finished)
