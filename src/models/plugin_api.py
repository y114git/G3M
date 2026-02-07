"""Plugin API for extending DELTAHUB functionality."""
import logging
from typing import Any, List, Optional
from PyQt6.QtCore import QObject
from utils.mod_utils import get_mod_key


class PluginAPI(QObject):
    def __init__(self, app_state, app_window, plugin_id: str, parent=None):
        super().__init__(parent)
        self.app_state, self.app_window, self.plugin_id = app_state, app_window, plugin_id
        self._config = {}
        self._load_config()

    def _get_settings_service(self):
        return getattr(self.app_state, 'settings_service', None) or getattr(self.app_window, 'settings_service', None)

    def _get_feedback_service(self):
        return getattr(self.app_state, 'feedback_service', None) or getattr(self.app_window, 'feedback_service', None)

    def _load_config(self):
        prefixed_config = self.app_state.local_config.get('plugin_configs', {}).get(self.plugin_id, {})
        self._config = {(key[len(f'{self.plugin_id}.'):] if key.startswith(f'{self.plugin_id}.') else key): value for key, value in prefixed_config.items()}

    def _save_config(self):
        self.app_state.local_config.setdefault('plugin_configs', {})[self.plugin_id] = {f'{self.plugin_id}.{k}': v for k, v in self._config.items()}
        settings_service = self._get_settings_service()
        if settings_service:
            settings_service.write_local_config()

    def get_mods(self) -> List[Any]:
        if hasattr(self.app_state, 'get_all_mods'):
            return self.app_state.get_all_mods()
        return list(self.app_state.all_mods) if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods else []

    def get_mod_by_key(self, key: str) -> Optional[Any]:
        return next((m for m in self.get_mods() if get_mod_key(m) == key), None)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any):
        self._config[key] = value
        self._save_config()

    def show_message(self, message_type: str, title: str, message: str):
        feedback = self._get_feedback_service()
        if feedback:
            feedback.show_message(message_type, title, message)
        else:
            logging.warning(f'Plugin {self.plugin_id}: Cannot show message - feedback_service not available')

    def log(self, level: str, message: str):
        logging.log(getattr(logging, level.upper(), logging.INFO), f'[Plugin {self.plugin_id}] {message}')

    def get_app_state(self) -> Any:
        return self.app_state

    def get_game_mode(self) -> Optional[str]:
        game_mode = getattr(self.app_state, 'game_mode', None)
        return game_mode.__class__.__name__ if game_mode and hasattr(game_mode, '__class__') else None

    def is_game_running(self) -> bool:
        return getattr(self.app_state, 'game_is_running', False)
