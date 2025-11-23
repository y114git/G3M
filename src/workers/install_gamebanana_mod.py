import os
import tempfile
import shutil
import logging
from typing import Optional, Dict
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from config.constants import UI_COLORS, NETWORK_TIMEOUT_HEAD
from managers.localization_manager import tr
from utils.gamebanana_api import GameBananaAPI
from utils.gamebanana_converter import GameBananaConverter
from utils.file_utils import normalize_mod_package
from utils.network_utils import get_session, download_file
from workers.base_install_worker import BaseInstallWorker
logger = logging.getLogger(__name__)


class InstallGameBananaModThread(BaseInstallWorker):
    file_selection_required = pyqtSignal(list, str)

    def __init__(self, main_window, mod_info, selected_file=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.mod_info = mod_info
        self.api = GameBananaAPI()
        self._selected_file_index = None
        self._file_selection_event = None
        self.selected_file = selected_file

    def set_selected_file(self, file_index: int):
        self._selected_file_index = file_index
        if self._file_selection_event:
            self._file_selection_event.set()

    def run(self):
        archive_path = None
        archive_dir = None
        try:
            mod_id = self.mod_info.gamebanana_mod_id
            if not mod_id:
                raise ValueError(tr('errors.invalid_gamebanana_mod_id'))
            if self._cancelled:
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            self.status.emit(tr('status.preparing_download'), UI_COLORS['status_info'])
            file_choice = self._resolve_selected_file(int(mod_id))
            if not file_choice:
                mod_url = self.mod_info.external_url or f'https://gamebanana.com/mods/{mod_id}'
                error_msg = f'MOD_NOT_COMPATIBLE:{mod_url}'
                logger.warning(f'Mod {mod_id} does not have a compatible file assigned for auto install')
                self.status.emit(tr('status.installation_failed'), UI_COLORS['status_error'])
                self.finished.emit(False, error_msg)
                return
            if self._cancelled:
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            download_url = file_choice.get('download_url') or file_choice.get('_sDownloadUrl')
            if not download_url:
                raise ValueError(tr('errors.no_download_url'))
            self.status.emit(tr('status.downloading_mod'), UI_COLORS['status_warning'])
            file_name = file_choice.get('name') or file_choice.get('_sFile') or file_choice.get('_sName') or f'mod_{mod_id}.zip'
            try:
                archive_path = self._download_file(download_url, file_name)
                archive_dir = os.path.dirname(archive_path) if archive_path else None
            except RuntimeError as e:
                if str(e) == 'download_cancelled' or self._cancelled:
                    self._cleanup_temp_files(archive_path, archive_dir)
                    self.finished.emit(False, tr('status.operation_cancelled'))
                    return
                else:
                    raise
            if self._cancelled:
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            file_format = file_choice.get('compatibility', 'deltahub')
            if self._cancelled:
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, tr('status.operation_cancelled'))
                return
            if file_format == 'deltahub':
                self.status.emit(tr('status.installing_mod'), UI_COLORS['status_info'])
                try:
                    from workers.mod_install_worker import ModInstallWorker
                    gb_metadata = {'mod_id': mod_id, 'mod_type': self.mod_info.gamebanana_mod_type or 'Mod', 'last_update_timestamp': self.mod_info.gamebanana_last_update_timestamp, 'profile_url': self.mod_info.external_url, 'icon_url': self.mod_info.icon_url, 'tags': self.mod_info.tags if hasattr(self.mod_info, 'tags') and self.mod_info.tags else [], 'category': self.mod_info.gamebanana_category if hasattr(self.mod_info, 'gamebanana_category') else None}
                    installer = ModInstallWorker(archive_path=archive_path, mods_dir=self.main_window.app_state.mods_dir, mod_manager=None, gamebanana_metadata=gb_metadata, parent=self.parent())
                    installer.run()
                    self._cleanup_temp_files(archive_path, archive_dir)
                    mod_dir = self._find_installed_mod_dir(mod_id)
                    if not mod_dir:
                        raise ValueError(tr('errors.gamebanana_installation_failed'))
                    mod_name = os.path.basename(mod_dir)
                    self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                except Exception as e:
                    self._cleanup_temp_files(archive_path, archive_dir)
                    logger.error(f'Error installing DELTAHUB mod from GameBanana: {e}', exc_info=True)
                    raise ValueError(tr('errors.gamebanana_installation_failed'))
                return
            self.status.emit(tr('status.converting_mod'), UI_COLORS['status_info'])
            gb_metadata = {'mod_id': mod_id, 'mod_type': self.mod_info.gamebanana_mod_type or 'Mod', 'last_update_timestamp': self.mod_info.gamebanana_last_update_timestamp, 'profile_url': self.mod_info.external_url, 'icon_url': self.mod_info.icon_url, 'tags': self.mod_info.tags if hasattr(self.mod_info, 'tags') and self.mod_info.tags else [], 'category': self.mod_info.gamebanana_category if hasattr(self.mod_info, 'gamebanana_category') else None}
            converter = GameBananaConverter(archive_path, self.main_window.app_state.mods_dir, gb_metadata)
            mod_dir = converter.convert()
            self._cleanup_temp_files(archive_path, archive_dir)
            if not mod_dir:
                raise ValueError(tr('errors.gamebanana_conversion_failed'))
            mod_name = os.path.basename(mod_dir)
            self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
        except RuntimeError as e:
            if str(e) == 'download_cancelled' or self._cancelled:
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, tr('status.operation_cancelled'))
            else:
                logger.error(f'Error installing GameBanana mod (RuntimeError): {e}', exc_info=True)
                self._cleanup_temp_files(archive_path, archive_dir)
                self.finished.emit(False, str(e))
        except Exception as e:
            logger.error(f'Error installing GameBanana mod: {e}', exc_info=True)
            self._cleanup_temp_files(archive_path, archive_dir)
            self.finished.emit(False, str(e))

    def _install_deltahub_mod(self, archive_path: str, mod_id: int) -> Optional[str]:
        import tempfile
        import json
        from utils.archive_utils import ArchiveExtractor
        from utils.file_utils import sanitize_filename
        fname_lower = os.path.basename(archive_path).lower()
        with tempfile.TemporaryDirectory(prefix='gb_install_dh_') as temp_dir:
            try:
                ArchiveExtractor.extract(archive_path, temp_dir)
            except Exception as e:
                logger.error(f'Error extracting DELTAHUB mod archive: {e}')
                raise
            try:
                normalize_info = normalize_mod_package(temp_dir, require_mod_config=True)
            except Exception as e:
                logger.error(f'Error normalizing DELTAHUB archive: {e}')
                raise
            mod_config_path = normalize_info.get('mod_config_path')
            if not mod_config_path:
                logger.error('mod_config.json not found in DELTAHUB mod archive')
                raise ValueError('mod_config.json not found in archive')
            try:
                with open(mod_config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                logger.error(f'Error reading mod_config.json: {e}')
                raise
            content_root = os.path.dirname(mod_config_path)
            files_in_archive = []
            for root, dirs, files in os.walk(content_root):
                for file in files:
                    if file != 'mod_config.json':
                        files_in_archive.append(file)
            if len(files_in_archive) == 0:
                external_url = config_data.get('external_url') or config_data.get('download_url')
                if external_url:
                    logger.info(f'DELTAHUB mod {mod_id} appears to be a redirect to {external_url}')
                    self.status.emit(tr('status.downloading_from_external'), UI_COLORS['status_info'])
                    try:
                        redirect_archive_path = self._download_file(external_url, 'redirect_mod.zip')
                        return self._install_deltahub_mod(redirect_archive_path, mod_id)
                    except Exception as e:
                        logger.error(f'Error downloading redirect mod: {e}')
                        raise ValueError(f'Failed to download redirect mod: {e}')
            mod_key = config_data.get('mod_key')
            if not mod_key:
                mod_key = f'gb_{mod_id}'
                config_data['mod_key'] = mod_key
            mod_name = config_data.get('name', f'mod_{mod_id}')
            folder_name = sanitize_filename(mod_name)
            target_mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name)
            counter = 1
            while os.path.exists(target_mod_dir):
                folder_name_with_counter = f'{folder_name}_{counter}'
                target_mod_dir = os.path.join(self.main_window.app_state.mods_dir, folder_name_with_counter)
                counter += 1
            os.makedirs(target_mod_dir, exist_ok=True)
            for item in os.listdir(content_root):
                src_path = os.path.join(content_root, item)
                dst_path = os.path.join(target_mod_dir, item)
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)
            config_data['is_gamebanana_mod'] = True
            config_data['is_local_mod'] = False
            config_data['gamebanana_mod_id'] = str(mod_id)
            if self.mod_info.gamebanana_mod_type:
                config_data['gamebanana_mod_type'] = self.mod_info.gamebanana_mod_type
            if self.mod_info.gamebanana_last_update_timestamp:
                config_data['gamebanana_last_update_timestamp'] = self.mod_info.gamebanana_last_update_timestamp
            if not config_data.get('external_url') and self.mod_info.external_url:
                config_data['external_url'] = self.mod_info.external_url
            if self.mod_info.icon_url:
                config_data['icon_url'] = self.mod_info.icon_url
            tags = []
            if hasattr(self.mod_info, 'tags') and self.mod_info.tags:
                tags = self.mod_info.tags if isinstance(self.mod_info.tags, list) else [self.mod_info.tags]
            elif hasattr(self.mod_info, 'gamebanana_category') and self.mod_info.gamebanana_category:
                from utils.gamebanana_api import GameBananaAPI
                category_tag = GameBananaAPI.category_to_tag(self.mod_info.gamebanana_category)
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
            expected_mod_key = f'gb_{mod_id}'
            config_data['mod_key'] = expected_mod_key
            target_config_path = os.path.join(target_mod_dir, 'mod_config.json')
            try:
                from utils.file_utils import atomic_write_json
                atomic_write_json(target_config_path, config_data, indent=4)
                logger.info(f'Installed DELTAHUB mod: {target_mod_dir}, mod_key={expected_mod_key}')
            except Exception as e:
                logger.error(f'Error writing mod_config.json: {e}')
                raise
            return target_mod_dir

    def _find_installed_mod_dir(self, mod_id: int) -> Optional[str]:
        try:
            import json
            mods_dir = self.main_window.app_state.mods_dir
            if not os.path.exists(mods_dir):
                return None
            mod_id_str = str(mod_id)
            for item_name in os.listdir(mods_dir):
                item_path = os.path.join(mods_dir, item_name)
                if not os.path.isdir(item_path):
                    continue
                config_path = os.path.join(item_path, 'mod_config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if config_data.get('gamebanana_mod_id') == mod_id_str:
                        return item_path
                except Exception:
                    continue
            return None
        except Exception as e:
            logger.error(f'Error finding installed mod directory: {e}', exc_info=True)
            return None

    def _check_file_compatibility(self, download_url: str, file_info: Dict) -> Optional[Dict]:
        try:
            filename = file_info.get('_sFile', 'check.zip')
            if filename.lower().endswith(('.zip', '.7z', '.rar')):
                return {'download_url': download_url, 'filename': filename, 'file_info': file_info}
        except Exception as e:
            logger.debug(f'Error checking file compatibility: {e}')
        return None

    def _download_file(self, url: str, filename: str) -> str:
        return super()._download_file(url, filename, temp_dir_prefix='gb_download_')

    def _resolve_selected_file(self, mod_id: int) -> Optional[Dict]:
        from managers.mod_manager import ModManager
        file_choice = ModManager.resolve_gamebanana_file(self.mod_info, self.api, self.selected_file)
        if file_choice:
            self.selected_file = file_choice
            self._notify_search_refresh()
        return file_choice

    def _notify_search_refresh(self):
        try:
            if hasattr(self.main_window, 'search_display'):
                QTimer.singleShot(0, self.main_window.search_display.update_search_plaques)
        except Exception as e:
            logger.debug(f'InstallGameBananaModThread: Error notifying search refresh: {e}')
