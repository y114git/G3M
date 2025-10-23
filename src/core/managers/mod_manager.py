import os
import json
import threading
from typing import Dict
from PyQt6.QtCore import QObject, pyqtSignal
from localization.manager import tr
from models.mod_models import ModInfo
from threads.background_workers import InstallModsThread, UrlInstallThread
from utils.file_utils import sanitize_filename


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

    def load_local_mods(self):
        if not os.path.exists(self.app_state.mods_dir):
            os.makedirs(self.app_state.mods_dir, exist_ok=True)
            return False

        installed_mods = {}
        try:
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

                    mod_key = config_data.get('mod_key', folder_name)
                    if not mod_key:
                        mod_key = folder_name

                    icon_path = os.path.join(folder_path, 'icon.png')
                    if not os.path.exists(icon_path):
                        icon_path = None

                    safe_mod_info = {
                        'key': mod_key,
                        'name': config_data.get('name', tr('defaults.local_mod')),
                        'version': config_data.get('version', '1.0.0'),
                        'author': config_data.get('author', tr('defaults.unknown')),
                        'tagline': config_data.get('tagline', tr('defaults.no_description')),
                        'game_version': config_data.get('game_version', tr('defaults.not_specified')),
                        'description_url': '',
                        'downloads': 0,
                        'modgame': config_data.get('modgame', 'deltarune'),
                        'is_verified': False,
                        'icon_url': icon_path,
                        'tags': ['local'],
                        'hide_mod': False,
                        'is_xdelta': config_data.get('is_xdelta', False),
                        'ban_status': False,
                        'demo_url': None,
                        'demo_version': '1.0.0',
                        'created_date': config_data.get('created_date', 'N/A'),
                        'last_updated': config_data.get('created_date', 'N/A'),
                        'external_url': config_data.get('external_url')
                    }

                    installed_mods[mod_key] = safe_mod_info

                except Exception as e:
                    print(f"Error reading config for {folder_name}: {e}")
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
                        import shutil
                        shutil.rmtree(d)
                    except Exception:
                        pass

            self._write_metadata({'mod_files_to_cleanup': [], 'mod_dirs_to_cleanup': []})

            return True

        except Exception as e:
            print(f"Error loading local mods: {e}")
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

    def install_mod(self, mod, force=False):
        try:
            if self.app_state.is_installing and not force:
                return

            available_chapters = []
            if mod.modgame == 'undertale':
                available_chapters = [1]
            elif mod.modgame == 'deltarune':
                available_chapters = [1, 2, 3, 4]

            if not available_chapters:
                self.feedback_manager.show_error("errors.no_chapters_available")
                return

            self.app_state.is_installing = True
            self.status_changed.emit(tr("status.installing_mod"), "status_info")

            self.current_install_thread = InstallModsThread(
                self.parent(),
                [mod],
                False
            )

            self.current_install_thread.progress.connect(self.progress_updated.emit)
            self.current_install_thread.status.connect(self.status_changed.emit)
            self.current_install_thread.finished.connect(self._on_single_mod_install_finished)

            self.current_install_thread.start()

        except Exception as e:
            self.app_state.is_installing = False
            self.feedback_manager.show_error("errors.installation_failed", str(e))

    def install_from_url(self, url: str):
        if self.app_state.is_installing:
            return

        self.app_state.is_installing = True
        self.status_changed.emit(tr("status.downloading_mod"), "status_info")

        self.url_install_thread = UrlInstallThread(
            self.parent(),
            url
        )

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
            self.status_changed.emit(tr("status.mod_uninstalled"), "status_success")
        except Exception as e:
            self.feedback_manager.show_error("errors.uninstall_failed", str(e))

    def update_mod(self, mod_data):
        if self.app_state.is_installing:
            return
        self.install_mod(mod_data)

    def delete_mod_files(self, mod_data):
        try:
            if not os.path.exists(self.app_state.mods_dir):
                print('Mods directory not found')
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

        except Exception as e:
            print(f"Error deleting mod files: {e}")

    def get_mod_status(self, mod: ModInfo, chapter_id: int) -> str:
        if mod.key.startswith('local_'):
            return 'ready'

        if not os.path.exists(self.app_state.mods_dir):
            return 'install'

        mod_folder_path = self.get_mod_folder_path(mod.key)
        if not mod_folder_path:
            return 'install'

        chapter_folder = os.path.join(mod_folder_path, f'chapter_{chapter_id}')
        if os.path.exists(chapter_folder):
            return 'ready'

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
        mod_key = mod_info.get('mod_key', '')
        mod_name = mod_info.get('name', '')

        if mod_key:
            mod_folder_by_key = os.path.join(self.app_state.mods_dir, mod_key)
            if os.path.exists(mod_folder_by_key):
                return True

        if mod_name:
            safe_name = sanitize_filename(mod_name)
            mod_folder_by_name = os.path.join(self.app_state.mods_dir, safe_name)
            if os.path.exists(mod_folder_by_name):
                return True

        return False

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
            except Exception as e:
                print(f"Error writing metadata: {e}")

    def _on_single_mod_install_finished(self, success):
        was_installed_before = False
        if self.current_install_thread:
            was_installed_before = getattr(self.current_install_thread, 'was_installed_before', False)

        self.progress_updated.emit(0)
        self.app_state.is_installing = False

        if success:
            if was_installed_before:
                self.status_changed.emit(tr("status.mod_updated"), "status_success")
            else:
                self.status_changed.emit(tr("status.mod_installed"), "status_success")
        else:
            self.status_changed.emit(tr("status.installation_failed"), "status_error")

        self.mod_list_updated.emit()
        self.installation_finished.emit(success, "")

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.mod_list_updated.emit()

        if success:
            self.status_changed.emit(tr("status.mod_installed"), "status_success")
        else:
            self.status_changed.emit(tr("status.installation_failed"), "status_error")

        self.installation_finished.emit(success, message)

    def handle_url_prompt_response(self, response: bool):
        if self.url_install_thread:
            self.url_install_thread.prompt_result = response
            self.url_install_thread.prompt_event.set()
