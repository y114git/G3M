"""Configuration loader for environment variables and secrets."""
import os
import sys
from dotenv import load_dotenv

_CONFIG_KEYS = ('DATA_FIREBASE_URL', 'CLOUD_FUNCTIONS_BASE_URL', 'INTERNAL_SALT')


class ConfigLoader:
    """Manages loading and caching of configuration values from multiple sources."""

    def __init__(self):
        self._cache = None

    def load_config(self):
        if self._cache is not None:
            return self._cache
        root_env = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        load_dotenv(root_env) if os.path.exists(root_env) else load_dotenv()
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath('.')
            cfg_path = os.path.join(exe_dir, 'config.env')
            if os.path.exists(cfg_path):
                load_dotenv(cfg_path)
        except Exception:
            pass
        try:
            import importlib
            _se = importlib.import_module('secrets_embed')
            for key in _CONFIG_KEYS:
                if not os.getenv(key, '') and hasattr(_se, key):
                    os.environ[key] = getattr(_se, key)
        except Exception:
            pass
        self._cache = {key: os.getenv(key, '') for key in _CONFIG_KEYS}
        return self._cache

    def get(self, key, default=''):
        return self.load_config().get(key, default)


_config_loader = ConfigLoader()


def get_config_value(key, default=''):
    return _config_loader.get(key, default)


_config_loader.load_config()
