"""User presence tracking worker."""

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
    update_online_count = pyqtSignal(int)
    global_settings_received = pyqtSignal(dict)
    _MIN_SYNC_INTERVAL_SECONDS = 60
    _HEARTBEAT_INTERVAL_SECONDS = 30 * 60
    REQUEST_TIMEOUT_SECONDS = min(2, NETWORK_TIMEOUT_SHORT)

    def __init__(self, session_id, app_state=None) -> None:
        super().__init__()
        self.session_id = session_id
        self.app_state = app_state
        self._last_sync_at = 0.0
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
            if not self.app_state or not getattr(
                self.app_state, "has_internet", True
            ):
                return
            now = time.time()
            if now - self._last_sync_at < self._MIN_SYNC_INTERVAL_SECONDS:
                return
            heartbeat_due = (
                now - self._last_heartbeat_at >= self._HEARTBEAT_INTERVAL_SECONDS
            )
            heartbeat_accepted = heartbeat_due
            session = requests.Session()
            try:
                session.headers.update(BROWSER_HEADERS or {})
                resp = cloud_function_request(
                    "post",
                    f"{CLOUD_FUNCTIONS_BASE_URL}/getClientState",
                    session=session,
                    json={"sessionId": self.session_id} if heartbeat_due else {},
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
                if (
                    heartbeat_due
                    and resp is not None
                    and resp.status_code in {404, 429}
                ):
                    if resp.status_code == 404:
                        resp = cloud_function_request(
                            "post",
                            f"{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat",
                            session=session,
                            json={"sessionId": self.session_id},
                            timeout=self.REQUEST_TIMEOUT_SECONDS,
                        )
                    else:
                        heartbeat_accepted = False
                        resp = cloud_function_request(
                            "post",
                            f"{CLOUD_FUNCTIONS_BASE_URL}/getClientState",
                            session=session,
                            json={},
                            timeout=self.REQUEST_TIMEOUT_SECONDS,
                        )
            finally:
                session.close()
            if resp is not None and resp.status_code == 200:
                self._last_sync_at = now
                try:
                    payload = resp.json() or {}
                    if (
                        heartbeat_accepted
                        and payload.get("heartbeatAccepted", True)
                    ):
                        self._last_heartbeat_at = now
                    count = max(int(payload.get("online", 0)), 0)
                    global_settings = payload.get("globals")
                    if isinstance(global_settings, dict):
                        self._safe_emit(
                            self.global_settings_received, global_settings
                        )
                except (ValueError, TypeError):
                    count = self._last_online_count if self._last_online_count >= 0 else 0
        except requests.RequestException as e:
            logger.debug(f"Presence worker network error: {e}")
        except Exception:
            logger.exception("Presence worker unexpected error")
        finally:
            if count >= 0:
                self._last_online_count = count
            self._safe_emit(self.update_online_count, count)
