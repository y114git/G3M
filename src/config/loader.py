"""Configuration loader for environment variables and secrets.

This module provides a centralized configuration loading system that reads
from multiple sources including .env files, config.env, and embedded secrets.
"""
import os
import sys
from typing import Dict, Any, Optional
from dotenv import load_dotenv
_CONFIG_KEYS = ('DATA_FIREBASE_URL', 'CLOUD_FUNCTIONS_BASE_URL', 'INTERNAL_SALT')


class ConfigLoader:
    """Manages loading and caching of configuration values from multiple sources."""

    def __init__(self):
        """Initialize the configuration loader with an empty cache."""
        self._config_cache: Optional[Dict[str, Any]] = None

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from all available sources and cache the result.

        Returns:
            Dict[str, Any]: Dictionary containing all configuration key-value pairs.
        """
        if self._config_cache is not None:
            return self._config_cache
        self._load_env_files()
        self._load_config_env()
        self._load_secrets_embed()
        self._config_cache = {key: os.getenv(key, '') for key in _CONFIG_KEYS}
        return self._config_cache

    def _load_env_files(self) -> None:
        """Load environment variables from .env file in the project root."""
        root_env = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        if os.path.exists(root_env):
            load_dotenv(root_env)
        else:
            load_dotenv()

    def _load_config_env(self) -> None:
        """Load environment variables from config.env file in the executable directory."""
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath('.')
            cfg_path = os.path.join(exe_dir, 'config.env')
            if os.path.exists(cfg_path):
                load_dotenv(cfg_path)
        except Exception:
            pass

    def _load_secrets_embed(self) -> None:
        """Load embedded secrets from the secrets_embed module if available."""
        try:
            import importlib
            _se = importlib.import_module('secrets_embed')
            for key in _CONFIG_KEYS:
                if not os.getenv(key, '') and hasattr(_se, key):
                    os.environ[key] = getattr(_se, key)
        except Exception:
            pass

    def get(self, key: str, default: str = '') -> str:
        """Retrieve a configuration value by key.

        Args:
            key: The configuration key to retrieve.
            default: Default value to return if key is not found.

        Returns:
            str: The configuration value or default if not found.
        """
        config = self.load_config()
        return config.get(key, default)


_config_loader = ConfigLoader()


def get_config_value(key: str, default: str = '') -> str:
    """Retrieve a configuration value using the global config loader.

    Args:
        key: The configuration key to retrieve.
        default: Default value to return if key is not found.

    Returns:
        str: The configuration value or default if not found.
    """
    return _config_loader.get(key, default)


_config_loader.load_config()
