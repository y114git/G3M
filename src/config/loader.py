import os
import sys
from typing import Dict, Any, Optional
from dotenv import load_dotenv
_CONFIG_KEYS = ('DATA_FIREBASE_URL', 'CLOUD_FUNCTIONS_BASE_URL', 'INTERNAL_SALT')


class ConfigLoader:

    def __init__(self):
        self._config_cache: Optional[Dict[str, Any]] = None

    def load_config(self) -> Dict[str, Any]:
        if self._config_cache is not None:
            return self._config_cache
        self._load_env_files()
        self._load_config_env()
        self._load_secrets_embed()
        self._config_cache = {key: os.getenv(key, '') for key in _CONFIG_KEYS}
        return self._config_cache

    def _load_env_files(self) -> None:
        root_env = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        if os.path.exists(root_env):
            load_dotenv(root_env)
        else:
            load_dotenv()

    def _load_config_env(self) -> None:
        try:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath('.')
            cfg_path = os.path.join(exe_dir, 'config.env')
            if os.path.exists(cfg_path):
                load_dotenv(cfg_path)
        except Exception:
            pass

    def _load_secrets_embed(self) -> None:
        try:
            import importlib
            _se = importlib.import_module('secrets_embed')
            for key in _CONFIG_KEYS:
                if not os.getenv(key, '') and hasattr(_se, key):
                    os.environ[key] = getattr(_se, key)
        except Exception:
            pass

    def get(self, key: str, default: str = '') -> str:
        config = self.load_config()
        return config.get(key, default)


_config_loader = ConfigLoader()


def get_config_value(key: str, default: str = '') -> str:
    return _config_loader.get(key, default)


_config_loader.load_config()
