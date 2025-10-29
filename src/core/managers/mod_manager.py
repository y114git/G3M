import os
import json
import logging
import threading
import zipfile
import shutil
import tempfile
from typing import Dict
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from core.managers.localization_manager import tr
from models.mod_models import ModInfo, ModChapterData
from threads.background_workers import InstallModsThread, UrlInstallThread
from utils.file_utils import sanitize_filename
from config.constants import UI_COLORS


class ModManager(QObject):
    progress_updated = pyqtSignal(int)
    status_changed = pyqtSignal(str, str)
    mod_list_updated = pyqtSignal()
    installation_finished = pyqtSignal(bool, str)
    url_prompt_required = pyqtSignal(str, str)

    def __init__(self, app_state, feedback_manager, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self._mods_metadata_lock = threading.Lock()
        self.current_install_thread = None
        self.url_install_thread = None

    def load_local_mods(self, _skip_conversion=False):
        if not os.path.exists(self.app_state.mods_dir):
            os.makedirs(self.app_state.mods_dir, exist_ok=True)
            return False
        installed_mods = {}
        conversion_happened = False
        try:
            for item_name in os.listdir(self.app_state.mods_dir):
                item_path = os.path.join(self.app_state.mods_dir, item_name)
                if not _skip_conversion and os.path.isfile(item_path) and item_name.lower().endswith(('.zip', '.7z', '.rar', '.tar.gz', '.lzma')):
                    try:
                        is_deltamod_archive = False
                        item_name_lower = item_name.lower()
                        if item_name_lower.endswith('.zip'):
                            with zipfile.ZipFile(item_path, 'r') as zf:
                                if '_deltamodInfo.json' in zf.namelist():
                                    is_deltamod_archive = True
                        elif item_name_lower.endswith('.tar.gz'):
                            import tarfile
                            with tarfile.open(item_path, 'r:gz') as tf:
                                if '_deltamodInfo.json' in tf.getnames():
                                    is_deltamod_archive = True
                        elif item_name_lower.endswith('.rar'):
                            try:
                                import rarfile
                                with rarfile.RarFile(item_path, 'r') as rf:
                                    if '_deltamodInfo.json' in rf.namelist():
                                        is_deltamod_archive = True
                            except Exception:
                                pass
                        elif item_name_lower.endswith('.7z'):
                            import py7zr
                            try:
                                with py7zr.SevenZipFile(item_path, mode='r') as zf:
                                    if '_deltamodInfo.json' in zf.getnames():
                                        is_deltamod_archive = True
                            except Exception:
                                pass
                        if is_deltamod_archive:
                            self.status_changed.emit(tr('status.deltamod_archive_detected', name=item_name), UI_COLORS['status_info'])
                            QApplication.processEvents()
                            with tempfile.TemporaryDirectory() as temp_dir:
                                shutil.unpack_archive(item_path, temp_dir)
                                content_path = temp_dir
                                contents = os.listdir(temp_dir)
                                if len(contents) == 1 and os.path.isdir(os.path.join(temp_dir, contents[0])):
                                    content_path = os.path.join(temp_dir, contents[0])
                                from utils.deltamod_converter import DeltamodConverter
                                converter = DeltamodConverter(content_path, self.app_state.mods_dir)
                                new_mod_path = converter.convert()
                                if new_mod_path:
                                    self.status_changed.emit(tr('status.deltamod_converted', name=os.path.basename(new_mod_path)), UI_COLORS['status_success'])
                                    os.remove(item_path)
                                    conversion_happened = True
                                else:
                                    self.status_changed.emit(tr('errors.deltamod_conversion_failed', name=item_name), UI_COLORS['status_error'])
                            continue
                    except Exception as e:
                        logging.error(f'Failed to process Deltamod archive {item_name}: {e}')
                if not os.path.isdir(item_path):
                    continue
                if not _skip_conversion and '_deltamodInfo.json' in os.listdir(item_path) and ('config.json' not in os.listdir(item_path)):
                    self.status_changed.emit(tr('status.deltamod_detected', name=item_name), UI_COLORS['status_info'])
                    QApplication.processEvents()
                    from utils.deltamod_converter import DeltamodConverter
                    converter = DeltamodConverter(item_path, self.app_state.mods_dir)
                    if converter.convert():
                        shutil.rmtree(item_path)
                        conversion_happened = True
                    continue
                config_path = os.path.join(item_path, 'config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if not config_data:
                        continue
                    mod_key = config_data.get('mod_key')
                    if mod_key:
                        installed_mods[mod_key] = config_data
                except Exception:
                    pass
            for mod in list(self.app_state.all_mods):
                if mod.key in installed_mods:
                    config_data = installed_mods[mod.key]
                    mod_folder_path = self.get_mod_folder_path(mod.key)
                    if mod_folder_path:
                        for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                            potential_icon = os.path.join(mod_folder_path, f'_icon{ext}')
                            if os.path.exists(potential_icon):
                                mod.icon_url = potential_icon
                                break
            self.app_state.all_mods = [mod for mod in self.app_state.all_mods if not hasattr(mod, 'tags') or 'local' not in mod.tags]
            for mod_key, config_data in list(installed_mods.items()):
                if config_data.get('is_local_mod'):
                    try:
                        mod_folder_for_icon = self.get_mod_folder_path(mod_key)
                        icon_path = ''
                        if mod_folder_for_icon:
                            for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                                potential_icon = os.path.join(mod_folder_for_icon, f'_icon{ext}')
                                if os.path.exists(potential_icon):
                                    icon_path = potential_icon
                                    break
                        safe_mod_info = {'key': mod_key, 'name': config_data.get('name', tr('defaults.local_mod')), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'modgame': config_data.get('modgame', 'deltarune'), 'is_verified': False, 'icon_url': icon_path, 'tags': ['local'], 'hide_mod': False, 'is_xdelta': config_data.get('is_xdelta', False), 'is_local_mod': config_data.get('is_local_mod', True), 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A'), 'external_url': config_data.get('external_url')}
                        mod = ModInfo(**safe_mod_info)
                        files_data = config_data.get('files', {})
                        mod_folder_path = None
                        for folder_name in os.listdir(self.app_state.mods_dir):
                            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
                            test_config_path = os.path.join(folder_path, 'config.json')
                            if os.path.isfile(test_config_path):
                                try:
                                    with open(test_config_path, 'r', encoding='utf-8') as f:
                                        test_config = json.load(f)
                                    if test_config.get('mod_key') == mod_key:
                                        mod_folder_path = folder_path
                                        break
                                except Exception as e:
                                    logging.warning(f'Failed reading config {test_config_path}: {e}')
                                    continue
                        for file_key, ch_info in list(files_data.items()):
                            chapter_files = ch_info
                            if mod_folder_path:
                                if file_key == 'demo':
                                    chapter_folder = os.path.join(mod_folder_path, 'demo')
                                elif file_key == 'undertale':
                                    chapter_folder = os.path.join(mod_folder_path, 'undertale')
                                elif file_key in ['0', '1', '2', '3', '4']:
                                    if file_key == '0':
                                        chapter_folder = os.path.join(mod_folder_path, 'chapter_0')
                                    else:
                                        chapter_folder = os.path.join(mod_folder_path, f'chapter_{file_key}')
                                else:
                                    try:
                                        ch_id = int(file_key)
                                        if ch_id == -1:
                                            chapter_folder = os.path.join(mod_folder_path, 'demo')
                                        elif ch_id == 0:
                                            chapter_folder = os.path.join(mod_folder_path, 'chapter_0')
                                        else:
                                            chapter_folder = os.path.join(mod_folder_path, f'chapter_{ch_id}')
                                    except ValueError:
                                        continue
                            data_file_url = ''
                            if chapter_files.get('data_file_url') and mod_folder_path:
                                data_file_url = os.path.join(chapter_folder, chapter_files['data_file_url'])
                            from models.mod_models import ModExtraFile
                            extra_files = []
                            if chapter_files.get('extra_files') and mod_folder_path:
                                for group_key, filenames in list(chapter_files['extra_files'].items()):
                                    for filename in filenames:
                                        file_path = os.path.join(chapter_folder, filename)
                                        extra_files.append(ModExtraFile(key=group_key, url=file_path, version='1.0.0'))
                            mod_chapter = ModChapterData(description=config_data.get('tagline', ''), data_file_url=data_file_url, data_file_version=chapter_files.get('data_file_version', (ch_info.get('versions', {}) or {}).get('data', '1.0.0')), extra_files=extra_files)
                            mod.files[file_key] = mod_chapter
                        if mod.files:
                            self.app_state.all_mods.append(mod)
                    except Exception as e:
                        logging.warning(f'Failed to build local ModInfo: {e}')
                        continue
            metadata = self._read_metadata()
            cleanup_files = metadata.get('mod_files_to_cleanup', [])
            cleanup_dirs = metadata.get('mod_dirs_to_cleanup', [])
            for p in cleanup_files:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            for d in cleanup_dirs:
                if os.path.exists(d):
                    try:
                        shutil.rmtree(d)
                    except Exception:
                        pass
            self._write_metadata({'mod_files_to_cleanup': [], 'mod_dirs_to_cleanup': []})
            if conversion_happened and (not _skip_conversion):
                return self.load_local_mods(_skip_conversion=True)
            return True
        except Exception as e:
            logging.error(f'_load_local_mods_from_folders failed: {e}')
            return False

    def get_mod_config(self, mod_key: str) -> dict:
        if not os.path.exists(self.app_state.mods_dir):
            return {}
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                if config_data.get('mod_key') == mod_key:
                    return config_data
            except Exception:
                continue
        return {}

    def get_mod_folder_path(self, mod_key: str) -> str:
        if not os.path.exists(self.app_state.mods_dir):
            return ''
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if not os.path.exists(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                if config_data.get('mod_key') == mod_key:
                    return folder_path
            except Exception:
                continue
        return ''

    def install_mod(self, mod, force=False, is_update=False):
        try:
            if self.app_state.is_installing and (not force):
                return
            available_chapters = []
            if mod.modgame == 'undertale':
                available_chapters = [1]
            elif mod.modgame == 'deltarune':
                available_chapters = [1, 2, 3, 4]
            if not available_chapters:
                self.feedback_manager.show_error('errors.no_chapters_available')
                return
            was_installed = self.is_mod_installed(mod)
            self.app_state.is_installing = True
            parent = self.parent()
            if parent:
                set_buttons_method = getattr(parent, '_set_install_buttons_enabled', None)
                if callable(set_buttons_method):
                    set_buttons_method(False)
            self.status_changed.emit(tr('status.installing_mod'), 'status_info')
            install_tasks = []
            for chapter_id in available_chapters:
                install_tasks.append((mod, chapter_id))
            self.current_install_thread = InstallModsThread(self.parent(), install_tasks, was_installed or is_update)
            self.current_install_thread.progress.connect(self.progress_updated.emit)
            self.current_install_thread.status.connect(self.status_changed.emit)
            self.current_install_thread.finished.connect(self._on_single_mod_install_finished)
            self.current_install_thread.start()
        except Exception as e:
            self.app_state.is_installing = False
            self.feedback_manager.show_error('errors.installation_failed', str(e))

    def install_from_url(self, url: str):
        if self.app_state.is_installing:
            return
        self.app_state.is_installing = True
        self.status_changed.emit(tr('status.downloading_mod'), 'status_info')
        self.url_install_thread = UrlInstallThread(self.parent(), url)
        self.url_install_thread.progress.connect(self.progress_updated.emit)
        self.url_install_thread.status.connect(self.status_changed.emit)
        self.url_install_thread.finished.connect(self._on_url_install_finished)
        self.url_install_thread.prompt_required.connect(self.url_prompt_required.emit)
        self.url_install_thread.start()

    def uninstall_mod(self, mod):
        try:
            self.delete_mod_files(mod)
            self.app_state.is_installing = False
            self.mod_list_updated.emit()
            self.status_changed.emit(tr('status.mod_uninstalled'), 'status_success')
        except Exception as e:
            self.feedback_manager.show_error('errors.uninstall_failed', str(e))

    def update_mod(self, mod_data):
        if self.app_state.is_installing:
            return
        self.install_mod(mod_data, force=True, is_update=True)

    def delete_mod_files(self, mod_data):
        try:
            if not os.path.exists(self.app_state.mods_dir):
                return
            mod_folder_found = None
            mod_key = mod_data.get('key', '') if isinstance(mod_data, dict) else mod_data.key
            for folder_name in os.listdir(self.app_state.mods_dir):
                folder_path = os.path.join(self.app_state.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if config_data.get('mod_key') == mod_key:
                        mod_folder_found = folder_path
                        break
                except Exception:
                    continue
            if mod_folder_found and os.path.exists(mod_folder_found):
                import shutil
                shutil.rmtree(mod_folder_found)
        except Exception:
            pass

    def get_mod_status(self, mod: ModInfo, chapter_id: int) -> str:
        if mod.is_local_mod:
            return 'ready'
        if not os.path.exists(self.app_state.mods_dir):
            return 'install'

        def _collect_remote_versions(m: ModInfo, ch_id: int) -> dict:
            if ch_id == -1:
                return {'demo': m.demo_version} if m.is_valid_for_demo() and m.demo_version else {}
            ch = m.get_chapter_data(ch_id)
            if not ch:
                return {}
            d = {}
            if ch.data_file_version:
                d['data'] = ch.data_file_version
            for ef in ch.extra_files:
                d[ef.key] = ef.version
            return d
        remote_versions = _collect_remote_versions(mod, chapter_id)
        if not remote_versions:
            return 'n/a'
        for mod_folder in os.listdir(self.app_state.mods_dir):
            mod_cache_dir = os.path.join(self.app_state.mods_dir, mod_folder)
            config_path = os.path.join(mod_cache_dir, 'config.json')
            if not os.path.isfile(config_path):
                continue
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                if config_data.get('mod_key') == mod.key:
                    if chapter_id == -1:
                        file_key = 'demo'
                    elif chapter_id == 0:
                        file_key = '0'
                    elif chapter_id > 0:
                        file_key = str(chapter_id)
                    else:
                        file_key = str(chapter_id)
                    local_versions = {}
                    files_data = config_data.get('files', {})
                    if file_key in files_data:
                        file_info = files_data[file_key]
                        if file_info.get('data_file_version'):
                            local_versions['data'] = file_info['data_file_version']
                        versions_data = file_info.get('versions', {})
                        for key, version in versions_data.items():
                            local_versions[key] = version
                    if not local_versions:
                        return 'install'
                    for k in local_versions.keys():
                        if k not in remote_versions:
                            return 'update'
                    from utils.file_utils import version_sort_key
                    for k, rv in remote_versions.items():
                        lv = local_versions.get(k)
                        if version_sort_key(rv) > version_sort_key(lv or '0.0.0'):
                            return 'update'
                    return 'ready'
            except Exception as e:
                logging.warning(f'Failed to parse local config {config_path}: {e}')
                continue
        return 'install'

    def is_mod_installed(self, mod_key: str) -> bool:
        if not os.path.exists(self.app_state.mods_dir):
            return False
        for mod_folder in os.listdir(self.app_state.mods_dir):
            config_path = os.path.join(self.app_state.mods_dir, mod_folder, 'config.json')
            if os.path.isfile(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if config_data.get('mod_key') == mod_key:
                        return True
                except Exception:
                    continue
        return False

    def check_mod_exists(self, mod_info):
        folder_name = mod_info.get('folder_name', '')
        if folder_name:
            mod_folder = os.path.join(self.app_state.mods_dir, folder_name)
            if os.path.exists(mod_folder):
                return True
        mod_key = mod_info.get('mod_key', '')
        if mod_key:
            mod_folder_by_key = os.path.join(self.app_state.mods_dir, mod_key)
            if os.path.exists(mod_folder_by_key):
                return True
        mod_name = mod_info.get('name', '')
        if mod_name:
            safe_name = sanitize_filename(mod_name)
            mod_folder_by_name = os.path.join(self.app_state.mods_dir, safe_name)
            if os.path.exists(mod_folder_by_name):
                return True
        return False

    def mod_has_files_for_chapter(self, mod_data, chapter_id):
        try:
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
            if not mod_key:
                return True
            is_local = getattr(mod_data, 'is_local_mod', False)
            if is_local:
                mod_folder = self.get_mod_folder_path(mod_key)
                if not mod_folder:
                    return False
            else:
                mod_folder = os.path.join(self.app_state.mods_dir, mod_key)
                if not os.path.exists(mod_folder):
                    mod_folder_by_name = os.path.join(self.app_state.mods_dir, mod_data.name)
                    if os.path.exists(mod_folder_by_name):
                        mod_folder = mod_folder_by_name
                    else:
                        return False
            config_path = os.path.join(mod_folder, 'config.json')
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    files_data = config_data.get('files', {})
                    if files_data:
                        if chapter_id == -1:
                            file_key = 'demo'
                        elif chapter_id == 0:
                            file_key = '0'
                        elif chapter_id > 0:
                            file_key = str(chapter_id)
                        else:
                            return False
                        if chapter_id == -1:
                            return 'demo' in files_data or 'undertale' in files_data
                        return file_key in files_data
                except Exception:
                    pass
            chapter_folders = {-1: 'universal', 0: 'menu', 1: 'chapter1', 2: 'chapter2', 3: 'chapter3', 4: 'chapter4'}
            folder_name = chapter_folders.get(chapter_id, 'universal')
            chapter_folder = os.path.join(mod_folder, folder_name)
            if os.path.exists(chapter_folder):
                return len(os.listdir(chapter_folder)) > 0
            universal_folder = os.path.join(mod_folder, 'universal')
            if os.path.exists(universal_folder):
                return len(os.listdir(universal_folder)) > 0
            return True
        except Exception:
            return True

    def _read_metadata(self) -> Dict:
        with self._mods_metadata_lock:
            if not os.path.exists(self.app_state.mods_metadata_path):
                return {}
            try:
                with open(self.app_state.mods_metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f) or {}
            except Exception:
                return {}

    def _write_metadata(self, data: Dict):
        with self._mods_metadata_lock:
            try:
                with open(self.app_state.mods_metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def _on_single_mod_install_finished(self, success):
        was_installed_before = False
        if self.current_install_thread:
            was_installed_before = getattr(self.current_install_thread, 'was_installed_before', False)
        self.progress_updated.emit(0)
        self.app_state.is_installing = False
        if success:
            if was_installed_before:
                self.status_changed.emit(tr('status.mod_updated'), 'status_success')
            else:
                self.status_changed.emit(tr('status.mod_installed'), 'status_success')
        else:
            self.status_changed.emit(tr('status.installation_failed'), 'status_error')
        self.mod_list_updated.emit()
        self.installation_finished.emit(success, '')

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.mod_list_updated.emit()
        if success:
            self.status_changed.emit(tr('status.mod_installed'), 'status_success')
        else:
            self.status_changed.emit(tr('status.installation_failed'), 'status_error')
        self.installation_finished.emit(success, message)

    def handle_url_prompt_response(self, response: bool):
        if self.url_install_thread:
            self.url_install_thread.prompt_result = response
            self.url_install_thread.prompt_event.set()
