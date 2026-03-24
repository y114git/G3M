"""Shared helper functions for mod installation workers."""

import json
import logging
import os

from config.config import LEGACY_MOD_CONFIG_FILENAME, MOD_CONFIG_FILENAME
from utils.file_utils import sanitize_filename

logger = logging.getLogger(__name__)


def find_mod_config(content_path: str) -> str | None:
    """Find mod config file in directory tree."""
    for config_name in (MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME):
        for root, _dirs, files in os.walk(content_path):
            if config_name in files:
                return os.path.join(root, config_name)
    return None


def normalize_mod_key(config_data: dict) -> str:
    """Normalize mod key in config data."""
    key = config_data.get("key") or config_data.get("mod_key")
    if not key:
        mod_name = config_data.get("name", "imported_mod")
        key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
        config_data["key"] = key
    config_data.pop("mod_key", None)
    return key


def load_mod_config(config_path: str) -> dict | None:
    """Load and parse mod config file."""
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading mod config: {e}")
        return None


def save_mod_config(config_path: str, config_data: dict, indent: int = 4):
    """Save mod config to file."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=indent, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error writing mod config: {e}")
        raise
