"""Chat and AI assistant management.

This module handles chat functionality and AI assistant interactions.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple
from config.constants import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session, check_internet_connection


class ChatManager:
    """Manages chat functionality and message handling."""
    MAX_MESSAGES = 100
    MESSAGE_MAX_LENGTH = 100

    def __init__(self):
        self.base_url = CLOUD_FUNCTIONS_BASE_URL.rstrip('/')
        if not self.base_url:
            logging.error('ChatManager: CLOUD_FUNCTIONS_BASE_URL is not configured')
        self.channel_map = {'en': 'chat_en', 'ru': 'chat_ru', 'zh': 'chat_zh', 'int': 'chat_int', 'es': 'chat_es'}

    def _check_ready(self, action: str) -> Optional[str]:
        if not self.base_url:
            logging.error(f'ChatManager: Cannot {action} - CLOUD_FUNCTIONS_BASE_URL is not configured')
            return 'config_error'
        if not check_internet_connection():
            return 'no_internet'
        return None

    def get_messages(self, channel: str) -> List[Dict[str, str]]:
        """Retrieve messages from a chat channel.

        Args:
            channel: Chat channel identifier.

        Returns:
            List[Dict[str, str]]: List of message dictionaries.
        """
        if self._check_ready('get messages'):
            return []
        try:
            url = f'{self.base_url}/getChatMessages'
            session = get_session()
            response = session.get(url, params={'channel': channel}, timeout=NETWORK_TIMEOUT_MEDIUM)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get('ok'):
                    messages = data.get('messages', [])
                    if isinstance(messages, list):
                        return messages
                return []
            else:
                error_text = response.text[:200] if hasattr(response, 'text') else 'Unknown error'
                logging.warning(f'ChatManager: Failed to get messages. Status: {response.status_code}, Response: {error_text}')
                return []
        except Exception as e:
            import requests
            if isinstance(e, requests.RequestException):
                logging.warning(f'ChatManager: Request exception when getting messages: {e}')
                return []
            else:
                logging.warning(f'ChatManager: Failed to get messages: {e}', exc_info=True)
                return []

    def _contains_url(self, text: str) -> bool:
        if re.search('https?://', text, re.IGNORECASE):
            return True
        if re.search('\\bwww\\.', text, re.IGNORECASE):
            return True
        domain_tlds = '(?:com|ru|org|net|io|co|uk|de|fr|es|it|cn|jp|info|biz|tv|me|xyz|site|online|tech|space|website|store|shop|blog|news|email|mail|domain|click|link|url|bit\\.ly|t\\.co|goo\\.gl|tinyurl|short\\.link)'
        domain_pattern = f'[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\\.{domain_tlds}'
        if re.search(f'{domain_pattern}(?:/|\\?|#)', text, re.IGNORECASE):
            return True
        url_indicator_pattern = '(?:https?://|www\\.|ftp://|mailto:|\\b@)'
        if re.search(f'{url_indicator_pattern}.*?{domain_pattern}', text, re.IGNORECASE):
            return True
        short_url_pattern = '\\b(?:bit\\.ly|t\\.co|goo\\.gl|tinyurl|short\\.link)\\b'
        if re.search(short_url_pattern, text, re.IGNORECASE):
            return True
        return False

    def send_message(self, channel: str, message: str) -> Tuple[bool, Optional[str]]:
        """Send a message to a chat channel.

        Args:
            channel: Chat channel identifier.
            message: Message text to send.

        Returns:
            Tuple[bool, Optional[str]]: (Success status, Error code if failed).
        """
        ready_error = self._check_ready('send message')
        if ready_error:
            return (False, ready_error)
        message = message.strip()
        if not message:
            return (False, 'empty_message')
        if len(message) > self.MESSAGE_MAX_LENGTH:
            return (False, 'message_too_long')
        if self._contains_url(message):
            return (False, 'contains_url')
        try:
            url = f'{self.base_url}/sendChatMessage'
            session = get_session()
            payload = {'channel': channel, 'message': message.strip()}
            response = session.post(url, json=payload, timeout=NETWORK_TIMEOUT_MEDIUM)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get('ok'):
                    return (True, None)
                else:
                    error_text = response.text[:200] if hasattr(response, 'text') else 'Unknown error'
                    logging.warning(f'ChatManager: Failed to send message. Response: {error_text}')
                    return (False, 'send_error')
            else:
                error_text = response.text[:200] if hasattr(response, 'text') else 'Unknown error'
                logging.warning(f'ChatManager: Failed to send message. Status: {response.status_code}, Response: {error_text}')
                return (False, 'send_error')
        except Exception as e:
            import requests
            if isinstance(e, requests.RequestException):
                error_msg = str(e)
                logging.warning(f'ChatManager: Request exception when sending message: {error_msg}', exc_info=True)
                return (False, 'send_error')
            else:
                logging.warning(f'ChatManager: Failed to send message: {e}', exc_info=True)
                return (False, 'send_error')
