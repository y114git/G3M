"""Mod installation worker."""
import os
import shutil
import logging
import tempfile
from typing import Optional, Dict
from PyQt6.QtCore import pyqtSignal
from services.localization_service import tr
from utils.file_utils import has_deltamod_info_file
from config.constants import UI_COLORS, MOD_CONFIG_FILENAME
from workers.base_install_worker import BaseInstallWorker
from workers.install.helpers_install import find_mod_config, normalize_mod_key, load_mod_config, save_mod_config


class ModInstallWorker(BaseInstallWorker):
    """Worker for installing mods from archive files or URLs."""
    manual_install_required = pyqtSignal(str, str, str)

    def __init__(self, archive_path: str, mods_dir: str, mod_service=None, gamebanana_metadata: Optional[Dict] = None, parent=None, is_pizza_tower_selected: bool = False):
        super().__init__(parent)
        self.archive_path = archive_path
        self.mods_dir = mods_dir
        self.mod_service = mod_service
        self.gamebanana_metadata = gamebanana_metadata or {}
        self.is_pizza_tower_selected = is_pizza_tower_selected

    def _download_archive(self, url: str, target_path: str) -> bool:
        temp_dir = tempfile.mkdtemp(prefix='dh-mod-import-')
        archive_path = os.path.join(temp_dir, os.path.basename(target_path))
        try:
            if not self._download_archive_base(url, archive_path, tr('mods.downloading_mod')):
                self._cleanup_temp_files(archive_path, temp_dir)
                return False
            if archive_path and os.path.exists(archive_path):
                target_dir = os.path.dirname(target_path)
                os.makedirs(target_dir, exist_ok=True)
                shutil.move(archive_path, target_path)
                return True
            return False
        finally:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _install_mod_from_path(self, content_path: str) -> bool:
        try:
            files_in_root = os.listdir(content_path)
            if has_deltamod_info_file(files_in_root):
                self.status.emit(tr('status.deltamod_archive_detected_url'), UI_COLORS['status_warning'])
                from adapters.deltamod_adapter import DeltamodConverter
                converter = DeltamodConverter(content_path, self.mods_dir, self.gamebanana_metadata)
                new_mod_path = converter.convert()
                if not new_mod_path:
                    logging.error('ModInstallWorker: Deltamod conversion failed')
                return bool(new_mod_path)
            mod_config_path = find_mod_config(content_path)
            if not mod_config_path:
                logging.error('ModInstallWorker: config file not found in mod archive')
                return False
            config_data = load_mod_config(mod_config_path)
            if not config_data:
                return False
            normalize_mod_key(config_data)
            mod_name = config_data.get('name', 'imported_mod')
            target_mod_dir = self._create_unique_mod_dir(self.mods_dir, mod_name)
            self._copy_directory_contents(content_path, target_mod_dir)
            target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
            config_updated = False
            if self.gamebanana_metadata:
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
                    from adapters.gamebanana_adapter import GameBananaAPI
                    category_tag = GameBananaAPI.category_to_tag(self.gamebanana_metadata['category'])
                    if category_tag:
                        tags = [category_tag]
                if tags:
                    self._merge_tags(config_data, tags)
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
                save_mod_config(final_config_path, config_data, indent=2)
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
