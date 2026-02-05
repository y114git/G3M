"""Chat and AI assistant management."""
import logging
import re
import requests
from config.constants import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session, check_internet_connection


class ChatManager:
    """Manages chat functionality and message handling."""
    MAX_MESSAGES, MESSAGE_MAX_LENGTH = 100, 100
    _URL_PATTERNS = [r'https?://', r'\bwww\.', r'\b(?:bit\.ly|t\.co|goo\.gl|tinyurl|short\.link)\b']
    _TLDS = r'(?:com|ru|org|net|io|co|uk|de|fr|es|it|cn|jp|info|biz|tv|me|xyz|site|online|tech|space|website|store|shop|blog|news|email|mail|domain|click|link|url)'

    def __init__(self):
        self.base_url = CLOUD_FUNCTIONS_BASE_URL.rstrip('/')
        if not self.base_url:
            logging.error('ChatManager: CLOUD_FUNCTIONS_BASE_URL is not configured')
        self.channel_map = {'en': 'chat_en', 'ru': 'chat_ru', 'zh': 'chat_zh', 'int': 'chat_int', 'es': 'chat_es'}

    def _check_ready(self, action: str):
        return 'config_error' if not self.base_url else ('no_internet' if not check_internet_connection() else None)

    def _safe_request(self, method: str, endpoint: str, action: str, **kwargs):
        try:
            return getattr(get_session(), method)(f'{self.base_url}/{endpoint}', timeout=NETWORK_TIMEOUT_MEDIUM, **kwargs)
        except requests.RequestException as e:
            logging.warning(f'ChatManager: Request exception when {action}: {e}')
            return None

    def get_messages(self, channel: str):
        if self._check_ready('get messages'):
            return []
        resp = self._safe_request('get', 'getChatMessages', 'getting messages', params={'channel': channel})
        if resp and resp.status_code == 200 and isinstance((data := resp.json()), dict) and data.get('ok') and isinstance(data.get('messages'), list):
            return data['messages']
        return []

    def _contains_url(self, text: str) -> bool:
        if any(re.search(p, text, re.IGNORECASE) for p in self._URL_PATTERNS):
            return True
        domain = rf'[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.{self._TLDS}'
        return bool(re.search(rf'{domain}(?:/|\?|#)', text, re.IGNORECASE) or re.search(rf'(?:https?://|www\.|ftp://|mailto:|\b@).*?{domain}', text, re.IGNORECASE))

    def send_message(self, channel: str, message: str):
        if (err := self._check_ready('send message')):
            return (False, err)
        if not (message := message.strip()):
            return (False, 'empty_message')
        if len(message) > self.MESSAGE_MAX_LENGTH:
            return (False, 'message_too_long')
        if self._contains_url(message):
            return (False, 'contains_url')
        resp = self._safe_request('post', 'sendChatMessage', 'sending message', json={'channel': channel, 'message': message})
        if resp and resp.status_code == 200 and isinstance((data := resp.json()), dict) and data.get('ok'):
            return (True, None)
        return (False, 'send_error')
