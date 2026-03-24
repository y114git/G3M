"""User presence tracking worker."""

import json
import logging

import requests
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from config.config import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session


class PresenceWorker(QObject):
    finished, update_online_count = pyqtSignal(), pyqtSignal(int)

    def __init__(self, session_id, app_state=None) -> None:
        super().__init__()
        self.session_id, self.app_state, self._busy = session_id, app_state, False

    def _safe_emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError as e:
            if "deleted" not in str(e):
                raise

    @pyqtSlot()
    def run(self):
        count = -1
        try:
            if (
                self._busy
                or not self.app_state
                or not getattr(self.app_state, "has_internet", True)
            ):
                return
            self._busy = True
            resp = get_session().post(
                f"{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat",
                json={"sessionId": self.session_id},
                timeout=NETWORK_TIMEOUT_MEDIUM,
            )
            if resp.status_code == 200:
                try:
                    count = max(int((resp.json() or {}).get("online", 0)), 0)
                except json.JSONDecodeError, ValueError, TypeError:
                    count = 0
        except (
            requests.Timeout,
            requests.ConnectionError,
            requests.RequestException,
        ) as e:
            logging.debug(f"Presence worker network error: {e}")
        finally:
            self._busy = False
            self._safe_emit(self.update_online_count, count)
            self._safe_emit(self.finished)
