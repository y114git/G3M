"""Plugin API for extending DELTAHUB functionality.

This module provides the API interface for plugins to interact with the application.
"""
import logging
from typing import Any, List, Optional
from PyQt6.QtCore import QObject


class PluginAPI(QObject):

    def __init__(self, app_state, app_window, plugin_id: str, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.app_window = app_window
        self.plugin_id = plugin_id
        self._config = {}
        self._load_config()

    def _get_settings_manager(self):
        if hasattr(self.app_state, 'settings_manager') and self.app_state.settings_manager:
            return self.app_state.settings_manager
        if hasattr(self.app_window, 'settings_manager'):
            return self.app_window.settings_manager
        return None

    def _get_feedback_manager(self):
        if hasattr(self.app_state, 'feedback_manager') and self.app_state.feedback_manager:
            return self.app_state.feedback_manager
        if hasattr(self.app_window, 'feedback_manager'):
            return self.app_window.feedback_manager
        return None

    def _load_config(self):
        plugin_configs = self.app_state.local_config.get('plugin_configs', {})
        prefixed_config = plugin_configs.get(self.plugin_id, {})
        self._config = {}
        for key, value in prefixed_config.items():
            if key.startswith(f'{self.plugin_id}.'):
                self._config[key[len(f'{self.plugin_id}.'):]] = value
            else:
                self._config[key] = value

    def _save_config(self):
        if 'plugin_configs' not in self.app_state.local_config:
            self.app_state.local_config['plugin_configs'] = {}
        prefixed_config = {}
        for key, value in self._config.items():
            prefixed_key = f'{self.plugin_id}.{key}'
            prefixed_config[prefixed_key] = value
        self.app_state.local_config['plugin_configs'][self.plugin_id] = prefixed_config
        settings_manager = self._get_settings_manager()
        if settings_manager:
            settings_manager.write_local_config()

    def get_mods(self) -> List[Any]:
        if hasattr(self.app_state, 'get_all_mods'):
            return self.app_state.get_all_mods()
        elif hasattr(self.app_state, 'all_mods'):
            return list(self.app_state.all_mods) if self.app_state.all_mods else []
        return []

    def get_mod_by_key(self, key: str) -> Optional[Any]:
        mods = self.get_mods()
        for mod in mods:
            mod_key_attr = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
            if mod_key_attr == key:
                return mod
        return None

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any):
        self._config[key] = value
        self._save_config()

    def show_message(self, message_type: str, title: str, message: str):
        feedback_manager = self._get_feedback_manager()
        if feedback_manager:
            feedback_manager.show_message(message_type, title, message)
        else:
            logging.warning(f'Plugin {self.plugin_id}: Cannot show message - feedback_manager not available')

    def log(self, level: str, message: str):
        log_level = getattr(logging, level.upper(), logging.INFO)
        logging.log(log_level, f'[Plugin {self.plugin_id}] {message}')

    def get_app_state(self) -> Any:
        return self.app_state

    def get_game_mode(self) -> Optional[str]:
        if hasattr(self.app_state, 'game_mode'):
            game_mode = self.app_state.game_mode
            if hasattr(game_mode, '__class__'):
                return game_mode.__class__.__name__
        return None

    def is_game_running(self) -> bool:
        return getattr(self.app_state, 'game_is_running', False)
