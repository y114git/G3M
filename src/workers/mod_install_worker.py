import os
import shutil
import logging
import tempfile
import json
from PyQt6.QtCore import QThread, pyqtSignal
from managers.localization_manager import tr
from utils.network_utils import get_session, download_file
from utils.file_utils import extract_archive, sanitize_filename
from utils.deltamod_converter import DeltamodConverter
from config.constants import NETWORK_TIMEOUT_HEAD, UI_COLORS


class ModInstallWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, archive_path: str, mods_dir: str, mod_manager, parent=None):
        super().__init__(parent)
        self.archive_path = archive_path
        self.mods_dir = mods_dir
        self.mod_manager = mod_manager
        self._cancelled = False
        self._session = None

    def cancel(self):
        self._cancelled = True
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass

    def _download_archive(self, url: str, target_path: str) -> bool:
        try:
            self.status.emit(tr('mods.downloading_mod'), UI_COLORS['status_warning'])
            session = get_session()
            self._session = session
            total_size = 0
            try:
                head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
                total_size = int(head_response.headers.get('content-length', 0))
            except Exception:
                pass
            downloaded_ref = [0]

            def progress_callback(progress):
                self.progress.emit(progress)
            download_file(session, url, target_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=lambda: self._cancelled)
            self.progress.emit(100)
            return True
        except Exception as e:
            logging.error(f'ModInstallWorker: Download failed: {e}', exc_info=True)
            return False

    def _install_mod_from_path(self, content_path: str) -> bool:
        try:
            files_in_root = os.listdir(content_path)
            if '_deltamodInfo.json' in files_in_root:
                self.status.emit(tr('status.deltamod_archive_detected_url'), UI_COLORS['status_warning'])
                converter = DeltamodConverter(content_path, self.mods_dir)
                new_mod_path = converter.convert()
                if new_mod_path:
                    return True
                else:
                    logging.error('ModInstallWorker: Deltamod conversion failed')
                    return False
            mod_config_path = None
            for root, dirs, files in os.walk(content_path):
                if 'mod_config.json' in files:
                    mod_config_path = os.path.join(root, 'mod_config.json')
                    break
            if not mod_config_path:
                for root, dirs, files in os.walk(content_path):
                    if 'config.json' in files:
                        mod_config_path = os.path.join(root, 'config.json')
                        break
            if not mod_config_path:
                logging.error('ModInstallWorker: mod_config.json or config.json not found in mod archive')
                return False
            try:
                with open(mod_config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                logging.error(f'ModInstallWorker: Error reading mod config: {e}')
                return False
            mod_key = config_data.get('mod_key')
            if not mod_key:
                mod_name = config_data.get('name', 'imported_mod')
                mod_key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                config_data['mod_key'] = mod_key
            mod_name = config_data.get('name', 'imported_mod')
            folder_name = sanitize_filename(mod_name)
            target_mod_dir = os.path.join(self.mods_dir, folder_name)
            counter = 1
            while os.path.exists(target_mod_dir):
                folder_name_with_counter = f'{folder_name}_{counter}'
                target_mod_dir = os.path.join(self.mods_dir, folder_name_with_counter)
                counter += 1
            os.makedirs(target_mod_dir, exist_ok=True)
            for item in os.listdir(content_path):
                src_path = os.path.join(content_path, item)
                dst_path = os.path.join(target_mod_dir, item)
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)
            target_old_config_path = os.path.join(target_mod_dir, 'config.json')
            target_config_path = os.path.join(target_mod_dir, 'mod_config.json')
            if os.path.exists(target_old_config_path) and (not os.path.exists(target_config_path)):
                try:
                    shutil.move(target_old_config_path, target_config_path)
                    logging.info(f'Migrated mod config.json to mod_config.json during import in {folder_name}')
                except Exception as e:
                    logging.warning(f'Failed to migrate mod config.json to mod_config.json during import in {folder_name}: {e}')
            config_data['is_local_mod'] = True
            if 'is_gamebanana_mod' not in config_data:
                config_data['is_gamebanana_mod'] = False
            config_updated = False
            if 'files' in config_data:
                for chapter_key, chapter_data in config_data['files'].items():
                    if chapter_key == 'demo':
                        chapter_folder = os.path.join(target_mod_dir, 'demo')
                    elif chapter_key == 'undertale':
                        chapter_folder = os.path.join(target_mod_dir, 'undertale')
                    elif chapter_key in ['0', '1', '2', '3', '4']:
                        if chapter_key == '0':
                            chapter_folder = os.path.join(target_mod_dir, 'chapter_0')
                        else:
                            chapter_folder = os.path.join(target_mod_dir, f'chapter_{chapter_key}')
                    else:
                        continue
                    if os.path.exists(chapter_folder):
                        if not chapter_data.get('data_file_url'):
                            from config.constants import DATA_FILE_EXTENSIONS
                            for file in os.listdir(chapter_folder):
                                if file.lower().endswith(DATA_FILE_EXTENSIONS):
                                    chapter_data['data_file_url'] = file
                                    config_updated = True
                                    break
            final_config_path = target_config_path if os.path.exists(target_config_path) else os.path.join(target_mod_dir, 'mod_config.json')
            if config_updated or not os.path.exists(final_config_path):
                with open(final_config_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logging.error(f'ModInstallWorker: Error installing mod from path: {e}', exc_info=True)
            return False

    def run(self):
        try:
            archive_is_url = self.archive_path.startswith('http://') or self.archive_path.startswith('https://')
            if archive_is_url:
                url = self.archive_path
                with tempfile.TemporaryDirectory(prefix='dh-mod-import-') as temp_dir:
                    temp_archive_name = f'temp_mod_{os.getpid()}.zip'
                    temp_archive_path = os.path.join(temp_dir, temp_archive_name)
                    try:
                        if not self._download_archive(url, temp_archive_path):
                            self.finished.emit(False, tr('mods.download_failed'))
                            return
                    except Exception as e:
                        self.finished.emit(False, tr('mods.download_error', error=str(e)))
                        return
                    if self._cancelled:
                        self.finished.emit(False, tr('status.operation_cancelled'))
                        return
                    self.status.emit(tr('mods.extracting_mod'), UI_COLORS['status_warning'])
                    with tempfile.TemporaryDirectory(prefix='dh-mod-extract-') as extract_dir:
                        try:
                            extract_archive(temp_archive_path, extract_dir)
                        except Exception as e:
                            self.finished.emit(False, tr('mods.extract_error', error=str(e)))
                            return
                        if self._cancelled:
                            self.finished.emit(False, tr('status.operation_cancelled'))
                            return
                        content_path = extract_dir
                        contents = os.listdir(extract_dir)
                        if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
                            content_path = os.path.join(extract_dir, contents[0])
                        self.status.emit(tr('mods.installing_mod'), UI_COLORS['status_warning'])
                        if self._install_mod_from_path(content_path):
                            self.status.emit(tr('mods.mod_installed'), 'success')
                            self.finished.emit(True, tr('mods.mod_installed_success'))
                        else:
                            self.finished.emit(False, tr('mods.installation_failed'))
            else:
                if not os.path.exists(self.archive_path):
                    self.finished.emit(False, tr('mods.archive_not_found'))
                    return
                self.status.emit(tr('mods.extracting_mod'), UI_COLORS['status_warning'])
                with tempfile.TemporaryDirectory(prefix='dh-mod-extract-') as extract_dir:
                    try:
                        extract_archive(self.archive_path, extract_dir)
                    except Exception as e:
                        self.finished.emit(False, tr('mods.extract_error', error=str(e)))
                        return
                    if self._cancelled:
                        self.finished.emit(False, tr('status.operation_cancelled'))
                        return
                    content_path = extract_dir
                    contents = os.listdir(extract_dir)
                    if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
                        content_path = os.path.join(extract_dir, contents[0])
                    self.status.emit(tr('mods.installing_mod'), UI_COLORS['status_warning'])
                    if self._install_mod_from_path(content_path):
                        self.status.emit(tr('mods.mod_installed'), 'success')
                        self.finished.emit(True, tr('mods.mod_installed_success'))
                    else:
                        self.finished.emit(False, tr('mods.installation_failed'))
        except Exception as e:
            logging.error(f'ModInstallWorker: Installation failed: {e}', exc_info=True)
            self.finished.emit(False, tr('mods.installation_error', error=str(e)))
