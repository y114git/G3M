"""Shared helper functions for mod installation workers."""
import os
import json
import logging
from typing import Optional, Dict
from utils.file_utils import sanitize_filename
from config.constants import MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME

logger = logging.getLogger(__name__)


def find_mod_config(content_path: str) -> Optional[str]:
    """Find mod config file in directory tree."""
    for config_name in (MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME):
        for root, dirs, files in os.walk(content_path):
            if config_name in files:
                return os.path.join(root, config_name)
    return None


def normalize_mod_key(config_data: dict) -> str:
    """Normalize mod key in config data."""
    key = config_data.get('key') or config_data.get('mod_key')
    if not key:
        mod_name = config_data.get('name', 'imported_mod')
        key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
        config_data['key'] = key
    if 'mod_key' in config_data:
        del config_data['mod_key']
    return key


def load_mod_config(config_path: str) -> Optional[Dict]:
    """Load and parse mod config file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f'Error reading mod config: {e}')
        return None


def save_mod_config(config_path: str, config_data: dict, indent: int = 4):
    """Save mod config to file."""
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=indent, ensure_ascii=False)
    except Exception as e:
        logger.error(f'Error writing mod config: {e}')
        raise
