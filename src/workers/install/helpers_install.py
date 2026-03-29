"""Shared helper functions for mod installation workers."""

import logging
import os

from config.config import MOD_CONFIG_FILENAME
from utils.file_utils import load_json, sanitize_filename, save_json
from utils.mod_config_parser import (
    MOD_FIELD_LIMITS,
    build_mod_config_data,
    normalize_mod_config_data,
)

logger = logging.getLogger(__name__)


def find_mod_config(content_path: str) -> str | None:
    """Find mod config file in directory tree."""
    for root, _dirs, files in os.walk(content_path):
        if MOD_CONFIG_FILENAME in files:
            return os.path.join(root, MOD_CONFIG_FILENAME)
    return None


def normalize_mod_id(config_data: dict) -> str:
    """Normalize mod id in config data."""
    mod_id = config_data.get("id")
    if not mod_id:
        mod_name = config_data.get("name", "imported_mod")
        mod_id = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
    config_data["id"] = str(mod_id).strip()[: MOD_FIELD_LIMITS["id"]]
    config_data.pop("key", None)
    config_data.pop("mod_key", None)
    return mod_id


def load_mod_config(config_path: str) -> dict | None:
    """Load and parse mod config file."""
    try:
        config_data = load_json(config_path)
        if isinstance(config_data, dict):
            normalize_mod_config_data(
                config_data, mod_root_path=os.path.dirname(config_path)
            )
        return config_data
    except Exception as e:
        logger.error(f"Error reading mod config: {e}")
        return None


def save_mod_config(config_path: str, config_data: dict, indent: int = 4):
    """Save mod config to file."""
    try:
        save_json(config_path, build_mod_config_data(config_data), indent=indent)
    except Exception as e:
        logger.error(f"Error writing mod config: {e}")
        raise
