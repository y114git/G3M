import os
import sys
import logging
import importlib.util
from typing import Any, Dict, List
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget, QTabWidget
from managers.localization_manager import localization_manager, tr


class PluginManager(QObject):
    plugins_loaded = pyqtSignal()
    plugin_error = pyqtSignal(str, str)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state

    def load_plugins(self):
        self.app_state.plugins.clear()
        if not os.path.isdir(self.app_state.plugins_dir):
            return
        for plugin_name in os.listdir(self.app_state.plugins_dir):
            plugin_path = os.path.join(self.app_state.plugins_dir, plugin_name)
            main_py_path = os.path.join(plugin_path, 'main.py')
            if os.path.isdir(plugin_path) and os.path.isfile(main_py_path):
                try:
                    spec = importlib.util.spec_from_file_location(f'plugins.{plugin_name}', main_py_path)
                    if spec and spec.loader:
                        plugin_module = importlib.util.module_from_spec(spec)
                        sys.modules[f'plugins.{plugin_name}'] = plugin_module
                        spec.loader.exec_module(plugin_module)
                        plugin_display_name_key = getattr(plugin_module, 'PLUGIN_NAME', None)
                        on_tab_open_function = getattr(plugin_module, 'on_tab_open', None)
                        page_init_function = getattr(plugin_module, 'page_init', None)
                        tab_hide = getattr(plugin_module, 'TAB_HIDE', False)
                        hooks = {'on_before_game_launch': getattr(plugin_module, 'on_before_game_launch', None), 'on_after_game_launch': getattr(plugin_module, 'on_after_game_launch', None), 'on_before_game_exit': getattr(plugin_module, 'on_before_game_exit', None), 'on_after_game_exit': getattr(plugin_module, 'on_after_game_exit', None)}
                        if hasattr(plugin_module, 'on_game_launch') and callable(getattr(plugin_module, 'on_game_launch')) and (not hooks['on_after_game_launch']):
                            hooks['on_after_game_launch'] = getattr(plugin_module, 'on_game_launch')
                        if hasattr(plugin_module, 'on_game_exit') and callable(getattr(plugin_module, 'on_game_exit')) and (not hooks['on_before_game_exit']):
                            hooks['on_before_game_exit'] = getattr(plugin_module, 'on_game_exit')
                        is_background_plugin = any((callable(h) for h in hooks.values()))
                        is_ui_plugin = not tab_hide and plugin_display_name_key and (callable(on_tab_open_function) or callable(page_init_function))
                        if not is_background_plugin and (not is_ui_plugin):
                            logging.warning(f"Plugin '{plugin_name}' is invalid. It must have at least one hook function or be a UI plugin with PLUGIN_NAME.")
                            continue
                        current_lang = localization_manager.get_current_language().upper()
                        lang_dict_name = f'LANG_{current_lang}'
                        plugin_translations = getattr(plugin_module, lang_dict_name, None)
                        if isinstance(plugin_translations, dict):
                            localization_manager.merge_translations(plugin_translations)
                        elif current_lang != 'EN':
                            en_translations = getattr(plugin_module, 'LANG_EN', None)
                            if isinstance(en_translations, dict):
                                localization_manager.merge_translations(en_translations)
                        plugin_info = {'name_key': plugin_display_name_key, 'module': plugin_module, 'on_tab_open': on_tab_open_function, 'page_init': page_init_function, 'tab_hide': tab_hide, 'path': plugin_path, **hooks}
                        self.app_state.plugins.append(plugin_info)
                        logging.info(f'Successfully loaded plugin: {plugin_name}')
                except Exception as e:
                    logging.error(f"Failed to load plugin '{plugin_name}': {e}")
                    self.plugin_error.emit(plugin_name, str(e))
        self.plugins_loaded.emit()

    def update_plugin_tabs(self, main_tab_widget: QTabWidget, num_original_tabs: int = 4) -> Dict[int, Dict[str, Any]]:
        plugin_tab_map = {}
        while main_tab_widget.count() > num_original_tabs:
            main_tab_widget.removeTab(num_original_tabs)
        for plugin_name in list(sys.modules.keys()):
            if plugin_name.startswith('plugins.'):
                del sys.modules[plugin_name]
        self.load_plugins()
        for plugin in self.app_state.plugins:
            if not plugin.get('tab_hide', False):
                plugin_tab = QWidget()
                try:
                    setattr(plugin_tab, '_plugin_info', plugin)
                    plugin_tab.setProperty('plugin_name_key', plugin.get('name_key'))
                except Exception:
                    pass
                tab_name = tr(plugin['name_key'])
                main_tab_widget.addTab(plugin_tab, tab_name)
                try:
                    tab_idx = main_tab_widget.indexOf(plugin_tab)
                    if tab_idx >= 0:
                        plugin_tab_map[tab_idx] = plugin
                except Exception:
                    pass
        return plugin_tab_map

    def execute_hooks(self, hook_name: str, app_instance):
        for plugin in self.app_state.plugins:
            hook_func = plugin.get(hook_name)
            if callable(hook_func):
                try:
                    logging.info(f"Executing {hook_name} hook for plugin: {plugin.get('name_key')}")
                    hook_func(app_instance)
                except Exception as e:
                    logging.error(f"Error executing {hook_name} hook for plugin '{plugin.get('name_key')}': {e}", exc_info=True)
                    self.plugin_error.emit(plugin.get('name_key', 'Unknown'), str(e))

    def get_ui_plugins(self) -> List[Dict[str, Any]]:
        return [p for p in self.app_state.plugins if not p.get('tab_hide', False)]

    def get_background_plugins(self) -> List[Dict[str, Any]]:
        return [p for p in self.app_state.plugins if any((callable(p.get(hook)) for hook in ['on_before_game_launch', 'on_after_game_launch', 'on_before_game_exit', 'on_after_game_exit']))]
