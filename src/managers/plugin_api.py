import logging
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QObject


class PluginAPI(QObject):

    def __init__(self, app_state, app_window, plugin_name: str, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.app_window = app_window
        self.plugin_name = plugin_name
        self._config = {}
        self._load_config()

    def _load_config(self):
        plugin_configs = self.app_state.local_config.get('plugin_configs', {})
        self._config = plugin_configs.get(self.plugin_name, {}).copy()

    def _save_config(self):
        if 'plugin_configs' not in self.app_state.local_config:
            self.app_state.local_config['plugin_configs'] = {}
        self.app_state.local_config['plugin_configs'][self.plugin_name] = self._config.copy()
        if hasattr(self.app_window, 'settings_manager'):
            self.app_window.settings_manager.write_local_config()

    def get_mods(self) -> List[Any]:
        if hasattr(self.app_state, 'all_mods'):
            return self.app_state.all_mods.copy()
        return []

    def get_mod_by_key(self, mod_key: str) -> Optional[Any]:
        if hasattr(self.app_state, 'all_mods'):
            for mod in self.app_state.all_mods:
                if hasattr(mod, 'key') and mod.key == mod_key:
                    return mod
        return None

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any):
        self._config[key] = value
        self._save_config()

    def show_message(self, message_type: str, title: str, message: str):
        if hasattr(self.app_window, 'feedback_manager'):
            self.app_window.feedback_manager.show_message(message_type, title, message)
        else:
            logging.warning(f'Plugin {self.plugin_name}: Cannot show message - feedback_manager not available')

    def log(self, level: str, message: str):
        log_level = getattr(logging, level.upper(), logging.INFO)
        logging.log(log_level, f'[Plugin {self.plugin_name}] {message}')

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
