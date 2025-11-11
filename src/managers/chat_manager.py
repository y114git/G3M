import logging
import re
from typing import Dict, List, Optional, Tuple
import requests
from config.constants import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_MEDIUM
from utils.network_utils import get_session, check_internet_connection


class ChatManager:
    MAX_MESSAGES = 100
    MESSAGE_MAX_LENGTH = 100

    def __init__(self):
        self.base_url = CLOUD_FUNCTIONS_BASE_URL.rstrip('/')
        if not self.base_url:
            logging.error('ChatManager: CLOUD_FUNCTIONS_BASE_URL is not configured')
        self.channel_map = {'en': 'chat_en', 'ru': 'chat_ru', 'zh': 'chat_zh', 'int': 'chat_int', 'es': 'chat_es'}

    def get_messages(self, channel: str) -> List[Dict[str, str]]:
        if not self.base_url:
            logging.error('ChatManager: Cannot get messages - CLOUD_FUNCTIONS_BASE_URL is not configured')
            return []
        if not check_internet_connection():
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
        except requests.RequestException as e:
            logging.warning(f'ChatManager: Request exception when getting messages: {e}')
            return []
        except Exception as e:
            logging.warning(f'ChatManager: Failed to get messages: {e}', exc_info=True)
            return []

    def _contains_url(self, text: str) -> bool:
        # Check for http/https URLs (most common and reliable case)
        if re.search(r'https?://', text, re.IGNORECASE):
            return True
        # Check for www. prefix (must be at word boundary)
        if re.search(r'\bwww\.', text, re.IGNORECASE):
            return True
        # Check for domain patterns that are clearly URLs:
        # 1. Domains followed by URL path indicators (/, ?, #) - these are definitely URLs
        # 2. Domains preceded by URL indicators (http://, https://, www., @, mailto:)
        # This prevents false positives like "communication.com" in normal text
        # where the domain appears without URL context
        domain_tlds = r'(?:com|ru|org|net|io|co|uk|de|fr|es|it|cn|jp|info|biz|tv|me|xyz|site|online|tech|space|website|store|shop|blog|news|email|mail|domain|click|link|url|bit\.ly|t\.co|goo\.gl|tinyurl|short\.link)'
        domain_pattern = rf'[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.{domain_tlds}'
        # Match domain followed by URL path indicators (/, ?, #) - definitely a URL
        if re.search(rf'{domain_pattern}(?:/|\?|#)', text, re.IGNORECASE):
            return True
        # Match domain preceded by URL indicators - definitely a URL
        url_indicator_pattern = r'(?:https?://|www\.|ftp://|mailto:|\b@)'
        if re.search(rf'{url_indicator_pattern}.*?{domain_pattern}', text, re.IGNORECASE):
            return True
        # Match common URL shorteners (bit.ly, t.co, etc.) even without path
        # These are known to be URL shorteners, so they're always URLs
        short_url_pattern = r'\b(?:bit\.ly|t\.co|goo\.gl|tinyurl|short\.link)\b'
        if re.search(short_url_pattern, text, re.IGNORECASE):
            return True
        # Don't match standalone domains like "communication.com" in normal text
        # as they are not necessarily URLs
        return False

    def send_message(self, channel: str, message: str) -> Tuple[bool, Optional[str]]:
        if not self.base_url:
            logging.error('ChatManager: Cannot send message - CLOUD_FUNCTIONS_BASE_URL is not configured')
            return (False, 'config_error')
        if not check_internet_connection():
            return (False, 'no_internet')
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
        except requests.RequestException as e:
            error_msg = str(e)
            logging.warning(f'ChatManager: Request exception when sending message: {error_msg}', exc_info=True)
            return (False, 'send_error')
        except Exception as e:
            logging.warning(f'ChatManager: Failed to send message: {e}', exc_info=True)
            return (False, 'send_error')
