import logging
from typing import List, Dict, Optional, Tuple
from PyQt6.QtCore import QThread, pyqtSignal
from managers.chat_manager import ChatManager
from config.constants import NETWORK_TIMEOUT_MEDIUM


class ChatRequestThread(QThread):
    messages_received = pyqtSignal(str, list)
    message_sent = pyqtSignal(str, bool, str)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_manager = ChatManager()
        self._request_type = None
        self._channel = None
        self._message = None
        self._cancelled = False

    def request_messages(self, channel: str):
        if self.isRunning():
            logging.warning('ChatRequestThread: Already running, ignoring request')
            return
        self._request_type = 'get_messages'
        self._channel = channel
        self._message = None
        self._cancelled = False
        self.start()

    def request_send_message(self, channel: str, message: str):
        if self.isRunning():
            logging.warning('ChatRequestThread: Already running, ignoring request')
            return
        self._request_type = 'send_message'
        self._channel = channel
        self._message = message
        self._cancelled = False
        self.start()

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        if self._cancelled or self.isInterruptionRequested():
            return
        try:
            if self._request_type == 'get_messages':
                if not self._channel:
                    return
                channel = self._channel
                messages = self.chat_manager.get_messages(channel)
                if not self._cancelled and (not self.isInterruptionRequested()):
                    self.messages_received.emit(channel, messages)
            elif self._request_type == 'send_message':
                if not self._channel or not self._message:
                    return
                channel = self._channel
                message = self._message
                success, error = self.chat_manager.send_message(channel, message)
                if not self._cancelled and (not self.isInterruptionRequested()):
                    self.message_sent.emit(channel, success, error or '')
        except Exception as e:
            logging.error(f'ChatRequestThread: Error during request: {e}', exc_info=True)
            if not self._cancelled and (not self.isInterruptionRequested()):
                self.error_occurred.emit(self._channel or '', str(e))
