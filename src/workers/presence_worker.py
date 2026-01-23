"""User presence tracking worker.

This module provides a worker for tracking and reporting user presence.
"""
import logging
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from config.constants import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session


class PresenceWorker(QObject):
    finished, update_online_count = (pyqtSignal(), pyqtSignal(int))

    def __init__(self, session_id, app_state=None):
        super().__init__()
        self.session_id = session_id
        self.app_state = app_state
        self._busy = False

    def _safe_emit_online_count(self, value: int):
        try:
            self.update_online_count.emit(value)
        except RuntimeError as e:
            if 'deleted' in str(e):
                logging.debug('PresenceWorker: object deleted, skipping signal emit')
            else:
                raise

    def _safe_emit_finished(self):
        try:
            self.finished.emit()
        except RuntimeError as e:
            if 'deleted' in str(e):
                logging.debug('PresenceWorker: object deleted, skipping signal emit')
            else:
                raise

    @pyqtSlot()
    def run(self):
        import requests
        try:
            if self._busy:
                return
            if not self.app_state or not getattr(self.app_state, 'has_internet', True):
                self._safe_emit_online_count(-1)
                return
            self._busy = True
            url = f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat'
            data = {'sessionId': self.session_id}
            session = get_session()
            resp = session.post(url, json=data, timeout=NETWORK_TIMEOUT_MEDIUM)
            if resp.status_code == 200:
                try:
                    data = resp.json() or {}
                    online = int(data.get('online', 0))
                    self._safe_emit_online_count(max(online, 0))
                except Exception as e:
                    logging.warning(f'PresenceWorker: parse error: {e}', exc_info=True)
                    self._safe_emit_online_count(-1)
            else:
                self._safe_emit_online_count(-1)
        except requests.Timeout:
            self._safe_emit_online_count(-1)
        except requests.ConnectionError:
            self._safe_emit_online_count(-1)
        except requests.RequestException:
            self._safe_emit_online_count(-1)
        finally:
            self._busy = False
            self._safe_emit_finished()
