import os
import json
import shutil
import logging
import tempfile
from typing import Optional, Dict
from PyQt6.QtCore import pyqtSignal
from managers.localization_manager import tr
from utils.network_utils import get_session
from utils.file_utils import sanitize_filename, has_deltamod_info_file
from config.constants import UI_COLORS, MOD_CONFIG_FILENAME, LEGACY_MOD_CONFIG_FILENAME
from workers.base_install_worker import BaseInstallWorker


class ModInstallWorker(BaseInstallWorker):
    manual_install_required = pyqtSignal(str, str, str)

    def __init__(self, archive_path: str, mods_dir: str, mod_manager=None, gamebanana_metadata: Optional[Dict] = None, parent=None, is_pizza_tower_selected: bool = False):
        super().__init__(parent)
        self.archive_path = archive_path
        self.mods_dir = mods_dir
        self.mod_manager = mod_manager
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.is_pizza_tower_selected = is_pizza_tower_selected

    def _download_archive(self, url: str, target_path: str) -> bool:
        try:
            from utils.file_utils import download_file_with_progress
            from utils.ui_utils import format_size_mb
            from config.constants import NETWORK_TIMEOUT_HEAD
            self.status.emit(tr('mods.downloading_mod'), UI_COLORS['status_warning'])
            temp_dir = tempfile.mkdtemp(prefix='dh-mod-import-')
            archive_path = os.path.join(temp_dir, os.path.basename(target_path))
            try:
                session = get_session()
                self._session = session
                downloaded_ref = [0]
                total_size = 0
                try:
                    head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
                    total_size = int(head_response.headers.get('content-length', 0))
                except Exception:
                    pass

                def progress_callback(progress):
                    if not self._cancelled:
                        self.progress.emit(progress)
                        if total_size > 0:
                            downloaded_mb = format_size_mb(downloaded_ref[0])
                            total_mb = format_size_mb(total_size)
                            self.status.emit(f"{tr('mods.downloading_mod')} ({downloaded_mb} / {total_mb})", UI_COLORS['status_warning'])

                def on_response(r):
                    self._active_response = r
                success = download_file_with_progress(url, archive_path, progress_callback=progress_callback, session=session, cancel_check=lambda: self._cancelled, on_response=on_response, downloaded_ref=downloaded_ref)
                if not success:
                    raise RuntimeError('download_failed')
                if archive_path and os.path.exists(archive_path):
                    target_dir = os.path.dirname(target_path)
                    os.makedirs(target_dir, exist_ok=True)
                    shutil.move(archive_path, target_path)
                    return True
                return False
            except RuntimeError as e:
                if str(e) == 'download_cancelled' or self._cancelled:
                    self._cleanup_temp_files(archive_path, temp_dir)
                    return False
                raise
            finally:
                try:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
        except RuntimeError as e:
            if str(e) == 'download_cancelled':
                return False
            logging.error(f'ModInstallWorker: Download failed: {e}', exc_info=True)
            return False
        except Exception as e:
            logging.error(f'ModInstallWorker: Download failed: {e}', exc_info=True)
            return False

    def _install_mod_from_path(self, content_path: str) -> bool:
        try:
            files_in_root = os.listdir(content_path)
            if has_deltamod_info_file(files_in_root):
                self.status.emit(tr('status.deltamod_archive_detected_url'), UI_COLORS['status_warning'])
                from utils.deltamod_converter import DeltamodConverter
                converter = DeltamodConverter(content_path, self.mods_dir)
                new_mod_path = converter.convert()
                if new_mod_path:
                    return True
                else:
                    logging.error('ModInstallWorker: Deltamod conversion failed')
                    return False
            mod_config_path = None
            for root, dirs, files in os.walk(content_path):
                if MOD_CONFIG_FILENAME in files:
                    mod_config_path = os.path.join(root, MOD_CONFIG_FILENAME)
                    break
            if not mod_config_path:
                for root, dirs, files in os.walk(content_path):
                    if LEGACY_MOD_CONFIG_FILENAME in files:
                        mod_config_path = os.path.join(root, LEGACY_MOD_CONFIG_FILENAME)
                        break
            if not mod_config_path:
                logging.error('ModInstallWorker: config file not found in mod archive')
                return False
            try:
                with open(mod_config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                logging.error(f'ModInstallWorker: Error reading mod config: {e}')
                return False
            key = config_data.get('key') or config_data.get('mod_key')
            if not key:
                mod_name = config_data.get('name', 'imported_mod')
                key = f"local_{sanitize_filename(mod_name).lower().replace(' ', '_')}"
                config_data['key'] = key
                if 'mod_key' in config_data:
                    del config_data['mod_key']
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
            target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
            config_updated = False
            if self.gamebanana_metadata:
                config_data['is_local_mod'] = False
                if 'mod_id' in self.gamebanana_metadata:
                    mod_id = self.gamebanana_metadata['mod_id']
                    expected_mod_key = f'gb_{mod_id}'
                    old_key = config_data.get('key') or config_data.get('mod_key')
                    config_data['key'] = expected_mod_key
                    if 'mod_key' in config_data:
                        del config_data['mod_key']
                    if old_key != expected_mod_key:
                        config_updated = True
                    logging.info(f'ModInstallWorker: Set GameBanana mod key to {expected_mod_key} for mod_id {mod_id}')
                if 'profile_url' in self.gamebanana_metadata and (not config_data.get('external_url')):
                    config_data['external_url'] = self.gamebanana_metadata['profile_url']
                if 'icon_url' in self.gamebanana_metadata:
                    config_data['icon_url'] = self.gamebanana_metadata['icon_url']
                tags = []
                if 'tags' in self.gamebanana_metadata and self.gamebanana_metadata['tags']:
                    tags = self.gamebanana_metadata['tags']
                    if not isinstance(tags, list):
                        tags = [tags] if tags else []
                elif 'category' in self.gamebanana_metadata and self.gamebanana_metadata['category']:
                    from utils.gamebanana_api import GameBananaAPI
                    category_tag = GameBananaAPI.category_to_tag(self.gamebanana_metadata['category'])
                    if category_tag:
                        tags = [category_tag]
                if tags:
                    existing_tags = config_data.get('tags', [])
                    if not isinstance(existing_tags, list):
                        existing_tags = [existing_tags] if existing_tags else []
                    for tag in tags:
                        if tag and tag not in existing_tags:
                            existing_tags.append(tag)
                    config_data['tags'] = existing_tags
            else:
                config_data['is_local_mod'] = True
            game = config_data.get('game') or config_data.get('modgame', 'deltarune')
            if 'files' in config_data:
                for chapter_key, chapter_data in config_data['files'].items():
                    if chapter_key == 'demo':
                        chapter_folder = os.path.join(target_mod_dir, 'demo')
                    elif chapter_key == 'undertale':
                        chapter_folder = os.path.join(target_mod_dir, 'undertale')
                    elif chapter_key in ['0', '1', '2', '3', '4']:
                        chapter_id = int(chapter_key)
                        from utils.file_utils import get_chapter_folder_name
                        folder_name = get_chapter_folder_name(chapter_id, game=game)
                        chapter_folder = os.path.join(target_mod_dir, folder_name)
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
            icon_path = os.path.join(target_mod_dir, '_icon.png')
            if not os.path.exists(icon_path):
                icon_path = os.path.join(target_mod_dir, 'icon.png')
            if os.path.exists(icon_path) and (not config_data.get('icon_url')):
                config_data['icon_url'] = '_icon.png' if os.path.basename(icon_path) == '_icon.png' else 'icon.png'
                config_updated = True
            final_config_path = target_config_path if os.path.exists(target_config_path) else os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
            if config_updated or not os.path.exists(final_config_path):
                from utils.file_utils import atomic_write_json
                atomic_write_json(final_config_path, config_data, indent=2)
            return True
        except Exception as e:
            logging.error(f'ModInstallWorker: Error installing mod from path: {e}', exc_info=True)
            return False

    def _extract_and_install_archive(self, archive_path: str) -> None:
        self.status.emit(tr('mods.extracting_mod'), UI_COLORS['status_warning'])
        with tempfile.TemporaryDirectory(prefix='dh-mod-extract-') as extract_dir:
            try:
                from utils.archive_utils import extract_with_unrar_retry, extract_archive
                extract_with_unrar_retry(archive_path, extract_dir, self, extract_archive)
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

    def run(self):
        try:
            archive_is_url = self.archive_path.startswith('http://') or self.archive_path.startswith('https://')
            if archive_is_url:
                url = self.archive_path
                with tempfile.TemporaryDirectory(prefix='dh-mod-import-') as temp_dir:
                    from utils.archive_utils import get_file_extension_from_url
                    file_ext = get_file_extension_from_url(url)
                    temp_archive_name = f'temp_mod_{os.getpid()}{file_ext}'
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
                    self._extract_and_install_archive(temp_archive_path)
            else:
                if not os.path.exists(self.archive_path):
                    self.finished.emit(False, tr('mods.archive_not_found'))
                    return
                self._extract_and_install_archive(self.archive_path)
        except Exception as e:
            logging.error(f'ModInstallWorker: Installation failed: {e}', exc_info=True)
            self.finished.emit(False, tr('mods.installation_error', error=str(e)))
