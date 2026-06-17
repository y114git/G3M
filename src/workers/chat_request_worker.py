"""Chat request worker thread."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from services.chat_service import ChatManager

logger = logging.getLogger(__name__)


def _safe_emit(owner: str, signal, *args) -> None:
    try:
        signal.emit(*args)
    except Exception as e:
        logger.warning("%s: failed to emit signal: %s", owner, e, exc_info=True)


class ChatRequestThread(QThread):
    messages_received = pyqtSignal(str, list)
    message_sent = pyqtSignal(str, bool, str)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.chat_service = ChatManager()
        self._request_type = self._channel = self._message = None
        self._force_refresh = False
        self._cancelled = False

    def _is_cancelled(self):
        return self._cancelled or self.isInterruptionRequested()

    def _start_request(
        self, request_type: str, channel: str, message: str | None = None
    ):
        if self.isRunning():
            return
        self._request_type, self._channel, self._message, self._cancelled = (
            request_type,
            channel,
            message,
            False,
        )
        self.start()

    def request_messages(self, channel: str, force_refresh: bool = False):
        self._force_refresh = force_refresh
        self._start_request("get_messages", channel, None)

    def request_send_message(self, channel: str, message: str):
        self._start_request("send_message", channel, message)

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        if self._is_cancelled():
            return
        try:
            if self._request_type == "get_messages" and self._channel:
                msgs = self.chat_service.get_messages(
                    self._channel, force_refresh=self._force_refresh
                )
                if not self._is_cancelled():
                    _safe_emit(
                        self.__class__.__name__,
                        self.messages_received,
                        self._channel,
                        msgs,
                    )
            elif (
                self._request_type == "send_message" and self._channel and self._message
            ):
                success, error = self.chat_service.send_message(
                    self._channel, self._message
                )
                if not self._is_cancelled():
                    _safe_emit(
                        self.__class__.__name__,
                        self.message_sent,
                        self._channel,
                        success,
                        error or "",
                    )
        except Exception as e:
            logger.error(f"ChatRequestThread: Error: {e}", exc_info=True)
            if not self._is_cancelled():
                _safe_emit(
                    self.__class__.__name__,
                    self.error_occurred,
                    self._channel or "",
                    str(e),
                )
