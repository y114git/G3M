"""Plugin management and loading."""
import os
import sys
import logging
import importlib.util
import shutil
import tempfile
import zipfile
import tarfile
import time
from datetime import datetime
from typing import Any, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget, QTabWidget
from services.localization_service import localization_service, tr
from models.plugin_api import PluginAPI


class PluginManager(QObject):
    """Manages plugin loading, installation, and lifecycle."""
    plugins_loaded = pyqtSignal()
    plugin_error = pyqtSignal(str, str)

    def __init__(self, app_state, settings_service=None, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.settings_service = settings_service
        self.app_window: Optional[Any] = None
        self._plugin_errors: Dict[str, str] = {}
        self._plugin_apis: Dict[str, PluginAPI] = {}

    def _read_plugins_metadata(self) -> Dict[str, Any]:
        if not os.path.exists(self.app_state.plugins_metadata_path):
            return {}
        try:
            from utils.file_utils import load_json
            return load_json(self.app_state.plugins_metadata_path, migrate_config=False) or {}
        except Exception as e:
            logging.warning(f'_read_plugins_metadata: failed: {e}', exc_info=True)
            return {}

    def _write_plugins_metadata(self, data: Dict[str, Any]):
        try:
            from utils.file_utils import save_json
            save_json(self.app_state.plugins_metadata_path, data, indent=2)
        except Exception as e:
            logging.error(f'_write_plugins_metadata: failed: {e}', exc_info=True)

    def _default_plugin_metadata(self) -> Dict[str, Any]:
        return {'enabled': True, 'installed_date': None}

    def get_plugin_metadata(self, plugin_name: str) -> Dict[str, Any]:
        metadata = self._read_plugins_metadata()
        return metadata.get(plugin_name, self._default_plugin_metadata())

    def update_plugin_metadata(self, plugin_name: str, updates: Dict[str, Any]):
        metadata = self._read_plugins_metadata()
        if plugin_name not in metadata:
            metadata[plugin_name] = self._default_plugin_metadata()
        metadata[plugin_name].update(updates)
        self._write_plugins_metadata(metadata)

    def is_plugin_enabled(self, plugin_name: str) -> bool:
        plugin_meta = self.get_plugin_metadata(plugin_name)
        return plugin_meta.get('enabled', True)

    def enable_plugin(self, plugin_name: str):
        self.update_plugin_metadata(plugin_name, {'enabled': True})

    def disable_plugin(self, plugin_name: str):
        self.update_plugin_metadata(plugin_name, {'enabled': False})

    def _extract_plugin_info_from_file(self, plugin_init_py_path: str, plugin_info: dict):
        try:
            with open(plugin_init_py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            import re
            plugin_id_match = re.search('PLUGIN_ID\\s*=\\s*["\\\']([^"\\\']+)["\\\']', content)
            plugin_name_match = re.search('PLUGIN_NAME\\s*=\\s*["\\\']([^"\\\']+)["\\\']', content)
            if plugin_id_match:
                plugin_info['plugin_id'] = plugin_id_match.group(1)
            if plugin_name_match:
                plugin_info['name_key'] = plugin_name_match.group(1)
            version_match = re.search('VERSION\\s*=\\s*["\\\']([^"\\\']+)["\\\']', content)
            if version_match:
                plugin_info['version'] = version_match.group(1)
            author_match = re.search('AUTHOR\\s*=\\s*["\\\']([^"\\\']+)["\\\']', content)
            if author_match:
                plugin_info['author'] = author_match.group(1)
            desc_patterns = ['DESCRIPTION\\s*=\\s*["\\\']([^"\\\']+)["\\\']', 'DESCRIPTION\\s*=\\s*"""([^"]*)"""', "DESCRIPTION\\s*=\\s*'''([^']*)'''"]
            for pattern in desc_patterns:
                desc_match = re.search(pattern, content, re.DOTALL)
                if desc_match:
                    description = desc_match.group(1).strip()
                    if description:
                        plugin_info['description'] = description
                    break
        except Exception as e:
            logging.debug(f'_extract_plugin_info_from_file: Error extracting info from {plugin_init_py_path}: {e}')

    def get_plugin_status(self, plugin_name: str, plugin_path: str) -> str:
        if not os.path.isdir(plugin_path):
            return 'broken'
        plugin_init_py_path = os.path.join(plugin_path, 'plugin_init.py')
        if not os.path.isfile(plugin_init_py_path):
            return 'broken'
        if plugin_name in self._plugin_errors:
            return 'broken'
        if not self.is_plugin_enabled(plugin_name):
            return 'disabled'
        return 'enabled'

    def convert_plugin_archives(self) -> bool:
        if not os.path.exists(self.app_state.plugins_dir):
            return False
        conversion_happened = False
        try:
            for item_name in os.listdir(self.app_state.plugins_dir):
                item_path = os.path.join(self.app_state.plugins_dir, item_name)
                if os.path.isfile(item_path) and item_name.lower().endswith(('.zip', '.7z', '.rar', '.tar.gz', '.lzma')):
                    try:
                        has_plugin_init_py = False
                        item_name_lower = item_name.lower()
                        if item_name_lower.endswith('.zip'):
                            with zipfile.ZipFile(item_path, 'r') as zf:
                                for name in zf.namelist():
                                    normalized = name.replace('\\', '/').strip('/')
                                    if normalized == 'plugin_init.py' or normalized.endswith('/plugin_init.py'):
                                        has_plugin_init_py = True
                                        break
                        elif item_name_lower.endswith('.tar.gz'):
                            with tarfile.open(item_path, 'r:gz') as tf:
                                for member in tf.getmembers():
                                    name = member.name.replace('\\', '/').strip('/')
                                    if name == 'plugin_init.py' or name.endswith('/plugin_init.py'):
                                        has_plugin_init_py = True
                                        break
                        elif item_name_lower.endswith('.rar'):
                            try:
                                import rarfile
                                with rarfile.RarFile(item_path, 'r') as rf:
                                    for name in rf.namelist():
                                        normalized = name.replace('\\', '/').strip('/')
                                        if normalized == 'plugin_init.py' or normalized.endswith('/plugin_init.py'):
                                            has_plugin_init_py = True
                                            break
                            except (OSError, ImportError) as e:
                                logging.warning(f'convert_plugin_archives: failed to check rar archive {item_name}: {e}', exc_info=True)
                        elif item_name_lower.endswith('.7z'):
                            try:
                                import py7zr
                                with py7zr.SevenZipFile(item_path, mode='r') as zf:
                                    for name in zf.getnames():
                                        normalized = name.replace('\\', '/').strip('/')
                                        if normalized == 'plugin_init.py' or normalized.endswith('/plugin_init.py'):
                                            has_plugin_init_py = True
                                            break
                            except (OSError, ImportError) as e:
                                logging.warning(f'convert_plugin_archives: failed to check 7z archive {item_name}: {e}', exc_info=True)
                        if has_plugin_init_py:
                            from utils.file_utils import remove_archive_extension
                            plugin_folder_name = remove_archive_extension(item_name)
                            plugin_folder_path = os.path.join(self.app_state.plugins_dir, plugin_folder_name)
                            if os.path.exists(plugin_folder_path):
                                logging.warning(f'convert_plugin_archives: plugin folder already exists: {plugin_folder_name}')
                                try:
                                    os.remove(item_path)
                                except Exception as e:
                                    logging.warning(f'convert_plugin_archives: failed to remove archive {item_name}: {e}')
                                continue
                            try:
                                with tempfile.TemporaryDirectory() as temp_dir:
                                    from utils.archive_utils import extract_with_unrar_retry
                                    extract_with_unrar_retry(item_path, temp_dir)
                                    contents = os.listdir(temp_dir)
                                    plugin_init_py_path = os.path.join(temp_dir, 'plugin_init.py')
                                    if os.path.isfile(plugin_init_py_path):
                                        os.makedirs(plugin_folder_path, exist_ok=True)
                                        for item in os.listdir(temp_dir):
                                            shutil.move(os.path.join(temp_dir, item), plugin_folder_path)
                                    else:
                                        found_plugin_dir = None
                                        if len(contents) == 1:
                                            single_dir = os.path.join(temp_dir, contents[0])
                                            if os.path.isdir(single_dir):
                                                single_plugin_init_py = os.path.join(single_dir, 'plugin_init.py')
                                                if os.path.isfile(single_plugin_init_py):
                                                    found_plugin_dir = single_dir
                                        if not found_plugin_dir:
                                            for root, dirs, files in os.walk(temp_dir):
                                                if 'plugin_init.py' in files:
                                                    rel_path = os.path.relpath(root, temp_dir)
                                                    if rel_path != '.' and os.path.dirname(rel_path) == '.':
                                                        found_plugin_dir = root
                                                        break
                                        if found_plugin_dir:
                                            os.makedirs(plugin_folder_path, exist_ok=True)
                                            for item in os.listdir(found_plugin_dir):
                                                shutil.move(os.path.join(found_plugin_dir, item), plugin_folder_path)
                                        else:
                                            os.makedirs(plugin_folder_path, exist_ok=True)
                                            for item in os.listdir(temp_dir):
                                                shutil.move(os.path.join(temp_dir, item), plugin_folder_path)
                                installed_date = datetime.now().strftime('%d.%m.%y %H:%M')
                                self.update_plugin_metadata(plugin_folder_name, {'enabled': True, 'installed_date': installed_date})
                                os.remove(item_path)
                                conversion_happened = True
                                logging.info(f'convert_plugin_archives: extracted plugin archive {item_name} -> {plugin_folder_name}')
                            except Exception as e:
                                error_msg = f'Failed to extract plugin archive {item_name}: {e}'
                                logging.error(f'convert_plugin_archives: {error_msg}', exc_info=True)
                                try:
                                    os.remove(item_path)
                                except Exception:
                                    pass
                    except Exception as e:
                        error_msg = f'Failed to process plugin archive {item_name}: {e}'
                        logging.error(f'convert_plugin_archives: {error_msg}', exc_info=True)
            return conversion_happened
        except Exception as e:
            error_msg = f'Error during plugin archive conversion: {e}'
            logging.error(f'convert_plugin_archives: {error_msg}', exc_info=True)
            return False

    def load_plugins(self):
        self.app_state.plugins.clear()
        self._plugin_errors.clear()
        if not os.path.isdir(self.app_state.plugins_dir):
            return
        if self.convert_plugin_archives():
            logging.info('Plugin archives converted, reloading plugins')
        for plugin_name in os.listdir(self.app_state.plugins_dir):
            plugin_path = os.path.join(self.app_state.plugins_dir, plugin_name)
            plugin_init_py_path = os.path.join(plugin_path, 'plugin_init.py')
            if not os.path.isdir(plugin_path) or not os.path.isfile(plugin_init_py_path):
                continue
            if not self.is_plugin_enabled(plugin_name):
                logging.info(f'Plugin {plugin_name} is disabled, skipping')
                continue
            try:
                spec = importlib.util.spec_from_file_location(f'plugins.{plugin_name}', plugin_init_py_path)
                if spec and spec.loader:
                    plugin_module = importlib.util.module_from_spec(spec)
                    sys.modules[f'plugins.{plugin_name}'] = plugin_module
                    spec.loader.exec_module(plugin_module)
                    plugin_id = getattr(plugin_module, 'PLUGIN_ID', None)
                    plugin_name_key = getattr(plugin_module, 'PLUGIN_NAME', None)
                    if not plugin_id:
                        plugin_id = plugin_name
                    if not plugin_name_key:
                        plugin_name_key = plugin_id
                    version = getattr(plugin_module, 'VERSION', None)
                    author = getattr(plugin_module, 'AUTHOR', None)
                    description = getattr(plugin_module, 'DESCRIPTION', None)
                    on_tab_open_function = getattr(plugin_module, 'on_tab_open', None)
                    page_init_function = getattr(plugin_module, 'page_init', None)
                    tab_hide = getattr(plugin_module, 'TAB_HIDE', False)
                    hooks = {'on_before_game_launch': getattr(plugin_module, 'on_before_game_launch', None), 'on_after_game_launch': getattr(plugin_module, 'on_after_game_launch', None), 'on_before_game_exit': getattr(plugin_module, 'on_before_game_exit', None), 'on_after_game_exit': getattr(plugin_module, 'on_after_game_exit', None)}
                    is_background_plugin = any((callable(h) for h in hooks.values()))
                    is_ui_plugin = not tab_hide and plugin_name_key and (callable(on_tab_open_function) or callable(page_init_function))
                    if not is_background_plugin and (not is_ui_plugin):
                        logging.warning(f"Plugin '{plugin_name}' is invalid. It must have at least one hook function or be a UI plugin with PLUGIN_NAME.")
                        self._plugin_errors[plugin_name] = 'Invalid plugin: must have hooks or UI functions'
                        continue
                    current_lang = localization_service.get_current_language().upper()
                    lang_dict_name = f'LANG_{current_lang}'
                    plugin_translations = getattr(plugin_module, lang_dict_name, None)
                    if isinstance(plugin_translations, dict):
                        localization_service.merge_plugin_translations(plugin_id, plugin_translations)
                    elif current_lang != 'EN':
                        en_translations = getattr(plugin_module, 'LANG_EN', None)
                        if isinstance(en_translations, dict):
                            localization_service.merge_plugin_translations(plugin_id, en_translations)
                    plugin_meta = self.get_plugin_metadata(plugin_name)
                    if not plugin_meta.get('installed_date'):
                        installed_date = datetime.now().strftime('%d.%m.%y %H:%M')
                        self.update_plugin_metadata(plugin_name, {'installed_date': installed_date})
                        plugin_meta['installed_date'] = installed_date
                    if description is not None:
                        if isinstance(description, str):
                            description = description.strip()
                            if not description:
                                description = None
                        else:
                            description = str(description).strip() if str(description).strip() else None
                    plugin_api = None
                    if self.app_window:
                        plugin_api = PluginAPI(self.app_state, self.app_window, plugin_id, self)
                        self._plugin_apis[plugin_id] = plugin_api
                    prefixed_name_key = f'{plugin_id}.{plugin_name_key}' if plugin_name_key else None
                    plugin_info = {'name': plugin_name, 'plugin_id': plugin_id, 'name_key': prefixed_name_key, 'version': version, 'author': author, 'description': description, 'module': plugin_module, 'on_tab_open': on_tab_open_function, 'page_init': page_init_function, 'tab_hide': tab_hide, 'path': plugin_path, 'installed_date': plugin_meta.get('installed_date'), 'status': 'enabled', 'api': plugin_api, **hooks}
                    self.app_state.plugins.append(plugin_info)
                    localized_name = tr(prefixed_name_key) if prefixed_name_key else plugin_name
                    logging.info(f'Loaded plugin: {localized_name} (ID: {plugin_id})')
            except Exception as e:
                error_msg = str(e)
                logging.error(f"Failed to load plugin '{plugin_name}': {error_msg}", exc_info=True)
                self._plugin_errors[plugin_name] = error_msg
                localized_name = plugin_name
                try:
                    plugin_info_from_file = {}
                    self._extract_plugin_info_from_file(plugin_init_py_path, plugin_info_from_file)
                    plugin_id = plugin_info_from_file.get('plugin_id', plugin_name)
                    plugin_name_key = plugin_info_from_file.get('name_key')
                    if plugin_name_key and (not plugin_name_key.startswith(f'{plugin_id}.')):
                        prefixed_name_key = f'{plugin_id}.{plugin_name_key}'
                    elif plugin_name_key:
                        prefixed_name_key = plugin_name_key
                    else:
                        prefixed_name_key = None
                    if prefixed_name_key:
                        localized_name = tr(prefixed_name_key)
                except Exception:
                    pass
                self.plugin_error.emit(localized_name, error_msg)
        self.plugins_loaded.emit()

    def update_plugin_tabs(self, main_tab_widget: QTabWidget, num_original_tabs: int = 4) -> Dict[int, Dict[str, Any]]:
        plugin_tab_map = {}
        while main_tab_widget.count() > num_original_tabs:
            main_tab_widget.removeTab(num_original_tabs)
        for plugin_name in list(sys.modules.keys()):
            if plugin_name.startswith('plugins.'):
                del sys.modules[plugin_name]
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

    def get_all_plugins_info(self) -> list[Dict[str, Any]]:
        all_plugins = []
        if not os.path.isdir(self.app_state.plugins_dir):
            return all_plugins
        for item_name in os.listdir(self.app_state.plugins_dir):
            item_path = os.path.join(self.app_state.plugins_dir, item_name)
            if os.path.isfile(item_path) and item_name.lower().endswith(('.zip', '.7z', '.rar', '.tar.gz', '.lzma')):
                continue
            if not os.path.isdir(item_path):
                continue
            plugin_init_py_path = os.path.join(item_path, 'plugin_init.py')
            if not os.path.isfile(plugin_init_py_path):
                continue
            status = self.get_plugin_status(item_name, item_path)
            plugin_meta = self.get_plugin_metadata(item_name)
            installed_date = plugin_meta.get('installed_date')
            if not installed_date:
                try:
                    if os.path.exists(plugin_init_py_path):
                        mtime = os.path.getmtime(plugin_init_py_path)
                        installed_date = datetime.fromtimestamp(mtime).strftime('%d.%m.%y %H:%M')
                        self.update_plugin_metadata(item_name, {'installed_date': installed_date})
                except Exception:
                    pass
            plugin_info = {'name': item_name, 'path': item_path, 'status': status, 'installed_date': installed_date, 'error': self._plugin_errors.get(item_name)}
            self._extract_plugin_info_from_file(plugin_init_py_path, plugin_info)
            if 'plugin_id' not in plugin_info:
                plugin_info['plugin_id'] = item_name
            plugin_id = plugin_info.get('plugin_id', item_name)
            plugin_name_key = plugin_info.get('name_key')
            if plugin_name_key and (not plugin_name_key.startswith(f'{plugin_id}.')):
                plugin_info['name_key'] = f'{plugin_id}.{plugin_name_key}'
            elif not plugin_name_key:
                plugin_info['name_key'] = None
            if status == 'enabled':
                loaded_plugin = next((p for p in self.app_state.plugins if p.get('name') == item_name), None)
                if loaded_plugin:
                    if not plugin_info.get('plugin_id') and loaded_plugin.get('plugin_id'):
                        plugin_info['plugin_id'] = loaded_plugin.get('plugin_id')
                    if not plugin_info.get('name_key') and loaded_plugin.get('name_key'):
                        plugin_info['name_key'] = loaded_plugin.get('name_key')
                    if not plugin_info.get('version') and loaded_plugin.get('version'):
                        plugin_info['version'] = loaded_plugin.get('version')
                    if not plugin_info.get('author') and loaded_plugin.get('author'):
                        plugin_info['author'] = loaded_plugin.get('author')
                    if not plugin_info.get('description') and loaded_plugin.get('description'):
                        plugin_info['description'] = loaded_plugin.get('description')
                    plugin_info['tab_hide'] = loaded_plugin.get('tab_hide', False)
            all_plugins.append(plugin_info)
        return all_plugins

    def get_plugin_api(self, plugin_id: str) -> Optional[PluginAPI]:
        return self._plugin_apis.get(plugin_id)

    def reload_plugin(self, plugin_name: str):
        plugin_to_reload = next((p for p in self.app_state.plugins if p.get('name') == plugin_name), None)
        plugin_id = plugin_to_reload.get('plugin_id') if plugin_to_reload else None
        self.app_state.plugins = [p for p in self.app_state.plugins if p.get('name') != plugin_name]
        module_name = f'plugins.{plugin_name}'
        if module_name in sys.modules:
            del sys.modules[module_name]
        if plugin_id and plugin_id in self._plugin_apis:
            del self._plugin_apis[plugin_id]
        if plugin_name in self._plugin_errors:
            del self._plugin_errors[plugin_name]
        self.load_plugins()

    def execute_hooks(self, hook_name: str, app_instance):
        result = None
        for plugin in self.app_state.plugins:
            hook_func = plugin.get(hook_name)
            if callable(hook_func):
                try:
                    start_time = time.time()
                    name_key = plugin.get('name_key')
                    localized_name = tr(name_key) if name_key else plugin.get('name', 'Unknown')
                    logging.info(f'Executing {hook_name} hook for plugin: {localized_name}')
                    hook_result = hook_func(app_instance)
                    elapsed = time.time() - start_time
                    if elapsed > 1.0:
                        logging.warning(f"Plugin '{localized_name}' hook {hook_name} took {elapsed:.2f}s")
                    if hook_name == 'on_before_game_launch' and hook_result is not None:
                        result = hook_result
                except Exception as e:
                    error_msg = str(e)
                    name_key = plugin.get('name_key')
                    localized_name = tr(name_key) if name_key else plugin.get('name', 'Unknown')
                    logging.error(f"Error executing {hook_name} hook for plugin '{localized_name}': {error_msg}", exc_info=True)
                    plugin_name = plugin.get('name', 'Unknown')
                    self._plugin_errors[plugin_name] = error_msg
                    self.plugin_error.emit(localized_name, error_msg)
        return result
