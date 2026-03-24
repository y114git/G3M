"""Configuration loader for environment variables and secrets."""

import logging
import os
import sys

from dotenv import load_dotenv

_CONFIG_KEYS = ("DATA_FIREBASE_URL", "CLOUD_FUNCTIONS_BASE_URL")


logger = logging.getLogger(__name__)


class ConfigLoader:
    """Manages loading and caching of configuration values from multiple sources."""

    def __init__(self) -> None:
        self._cache = None

    def load_config(self):
        if self._cache is not None:
            return self._cache
        root_env = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        load_dotenv(root_env) if os.path.exists(root_env) else load_dotenv()
        try:
            exe_dir = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.abspath(".")
            )
            cfg_path = os.path.join(exe_dir, "config.env")
            if os.path.exists(cfg_path):
                load_dotenv(cfg_path)
        except Exception as e:
            logger.debug(
                f"ConfigLoader: failed to load config.env from executable directory: {e}",
                exc_info=True,
            )
        try:
            import importlib

            secrets_embed = importlib.import_module("secrets_embed")
            for key in _CONFIG_KEYS:
                if not os.getenv(key, "") and hasattr(secrets_embed, key):
                    os.environ[key] = getattr(secrets_embed, key)
        except Exception as e:
            logger.debug(
                f"ConfigLoader: failed to import embedded secrets: {e}", exc_info=True
            )
        self._cache = {key: os.getenv(key, "") for key in _CONFIG_KEYS}
        return self._cache

    def get(self, key, default=""):
        return self.load_config().get(key, default)


_config_loader = ConfigLoader()


def get_config_value(key, default=""):
    return _config_loader.get(key, default)


def validate_config() -> None:
    missing = tuple(
        name
        for name in ("DATA_FIREBASE_URL", "CLOUD_FUNCTIONS_BASE_URL")
        if not str(get_config_value(name, "")).strip()
    )
    if missing:
        raise RuntimeError("Missing required config " + ", ".join(missing))


_config_loader.load_config()
