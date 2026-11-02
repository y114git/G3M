"""GameBanana Remote Install: polls the paired member's queue and queues each mod for download."""

import logging
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from adapters.gamebanana_adapter import GameBananaAPI
from config.config import GAMEBANANA_API_BASE, NETWORK_TIMEOUT_MEDIUM
from utils.mod.utils import parse_gamebanana_download_link
from utils.network_utils import get_session

logger = logging.getLogger(__name__)

# GameBanana keeps one queue per app ID; G3M reads both of its registered IDs.
APP_IDS = ("G3M", "GameMakerModManager")
CONFIG_KEY = "gb_remote_install"
POLL_INTERVAL_MS = 60_000


class RemoteInstallService(QObject):
    mod_ready = pyqtSignal(object, dict)

    def __init__(self, app_state, settings_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.settings_service = settings_service
        self._busy = False
        self._rejected: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll)

    def pair(self, member_id: str, secret_key: str) -> None:
        credentials = {"member_id": member_id, "secret_key": secret_key}
        if self.app_state.local_config.get(CONFIG_KEY) != credentials:
            self.app_state.local_config[CONFIG_KEY] = credentials
            self._busy = False  # a poll still running for the previous account must not block the new one
        self.settings_service.write_local_config()
        self._rejected.clear()
        self.start()

    def start(self) -> None:
        if self.app_state.local_config.get(CONFIG_KEY):
            self._timer.start()
            self.poll()

    def refresh(self) -> None:
        """Poll now and restart the interval; a refresh also retries a queue that was rejected."""
        self._rejected.clear()
        self.start()

    def poll(self) -> None:
        credentials = self.app_state.local_config.get(CONFIG_KEY)
        if len(self._rejected) == len(APP_IDS) or not credentials:
            self._timer.stop()
        elif not self._busy:
            self._busy = True
            threading.Thread(target=self._fetch, args=(credentials,), daemon=True).start()

    def _fetch(self, credentials: dict) -> None:
        try:
            for app_id in APP_IDS:
                if app_id not in self._rejected and not self._fetch_queue(credentials, app_id):
                    return
        finally:
            if not self._is_stale(credentials):
                self._busy = False

    def _fetch_queue(self, credentials: dict, app_id: str) -> bool:
        """Read one app ID's queue; False once another pairing replaced these credentials."""
        url = f"{GAMEBANANA_API_BASE}/RemoteInstall/{credentials['member_id']}/{credentials['secret_key']}/{app_id}"
        try:
            response = get_session().get(url, timeout=NETWORK_TIMEOUT_MEDIUM)
            if self._is_stale(credentials):
                return False
            if 400 <= response.status_code < 500:
                self._rejected.add(app_id)  # a revoked key or unknown ID would only be retried every minute
            response.raise_for_status()
            entries = response.json()
            for entry in entries if isinstance(entries, list) else []:
                self._queue(entry)
        except Exception as error:
            # The URL carries the secret key, so never log the exception text.
            logger.warning("Remote install poll of %s failed: %s", app_id, type(error).__name__)
        return True

    def _is_stale(self, credentials: dict) -> bool:
        """True once another pairing replaced these credentials: their answer must not queue mods or reject the new key."""
        return self.app_state.local_config.get(CONFIG_KEY) is not credentials

    def _queue(self, entry: object) -> None:
        # "{downloadURL},{modType},{modID}", the same shape as a 1-click link
        link = parse_gamebanana_download_link(entry) if isinstance(entry, str) else None
        if not link or not link[1]:
            # Entries come back from a request whose URL carries the secret key, so their text stays out of the log.
            logger.warning("Remote install: ignored an entry of type %s that is not '{downloadURL},{modType},{modID}'", type(entry).__name__)
            return
        file_id, (item_type, mod_id) = link[0], link[1]
        try:
            mod = GameBananaAPI().get_installable_mod(int(mod_id), item_type)
            file = next(f for f in mod.gamebanana_supported_files if str(f["id"]) == file_id)
        except Exception as error:
            logger.warning(
                "Remote install: could not queue %s %d, file %d: %r",
                "wip" if item_type == "Wip" else "mod", int(mod_id), int(file_id), error,
            )
            return
        self.mod_ready.emit(mod, file)
