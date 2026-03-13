"""Worker thread for installing mods from GameBanana."""
import os
import tempfile
import logging
from typing import Optional, Dict
from PyQt6.QtCore import pyqtSignal
from config.constants import UI_COLORS, MOD_CONFIG_FILENAME
from services.localization_service import tr
from models.exceptions import AppError
from adapters.gamebanana_adapter import GameBananaAPI
from adapters.gamebanana_converter import GameBananaConverter
from utils.file_utils import normalize_mod_package
from utils.network_utils import get_session
from utils.mod_utils import get_mod_key
from workers.base_install_worker import BaseInstallWorker
logger = logging.getLogger(__name__)


class InstallGameBananaModThread(BaseInstallWorker):
    """Background thread for installing mods from GameBanana."""
    file_selection_required = pyqtSignal(list, str)

    def __init__(self, main_window, mod_info, selected_file=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.mod_info = mod_info
        self.api = GameBananaAPI()
        self._selected_file_index = None
        self._file_selection_event = None
        self.selected_file = selected_file

    def _build_gb_metadata(self, mod_id: int) -> Dict:
        return {'mod_id': mod_id, 'profile_url': self.mod_info.external_url, 'icon_url': self.mod_info.icon_url, 'tags': getattr(self.mod_info, 'tags', None) or [], 'category': getattr(self.mod_info, 'gamebanana_category', None), 'game': getattr(self.mod_info, 'game', 'deltarune')}

    def _emit_cancelled(self, archive_path=None, archive_dir=None):
        self._cleanup_temp_files(archive_path, archive_dir)
        self.finished.emit(False, tr('status.operation_cancelled'))

    def run(self):
        archive_path = None
        archive_dir = None
        try:
            mod_key = get_mod_key(self.mod_info)
            mod_id_str = self.mod_info.get_gamebanana_mod_id() if hasattr(self.mod_info, 'get_gamebanana_mod_id') else mod_key.replace('gb_', '', 1) if mod_key and mod_key.startswith('gb_') else None
            if not mod_id_str:
                raise AppError('errors.invalid_gamebanana_mod_id')
            mod_id = int(mod_id_str)
            if self._cancelled:
                return self._emit_cancelled()
            self.status.emit(tr('status.preparing_download'), UI_COLORS['status_info'])
            file_choice = self._resolve_selected_file(int(mod_id))
            if not file_choice:
                mod_url = self.mod_info.external_url or f'https://gamebanana.com/mods/{mod_id}'
                self.status.emit(tr('status.installation_failed'), UI_COLORS['status_error'])
                self.finished.emit(False, f'MOD_NOT_COMPATIBLE:{mod_url}')
                return
            if self._cancelled:
                return self._emit_cancelled()
            download_url = file_choice.get('download_url') or file_choice.get('_sDownloadUrl')
            if not download_url:
                raise AppError('errors.no_download_url')
            self.status.emit(tr('status.downloading_mod'), UI_COLORS['status_warning'])
            file_name = file_choice.get('name') or file_choice.get('_sFile') or file_choice.get('_sName') or f'mod_{mod_id}.zip'
            temp_dir = tempfile.mkdtemp(prefix='gb_download_')
            archive_path = os.path.join(temp_dir, file_name)
            archive_dir = temp_dir
            try:
                if not self._download_archive_base(download_url, archive_path, tr('status.downloading_mod')):
                    raise RuntimeError('download_failed')
            except RuntimeError as e:
                if str(e) == 'download_cancelled' or self._cancelled:
                    return self._emit_cancelled(archive_path, archive_dir)
                raise
            if self._cancelled:
                return self._emit_cancelled(archive_path, archive_dir)
            file_format = file_choice.get('compatibility', 'deltahub')
            if file_format == 'deltahub':
                self.status.emit(tr('status.installing_mod'), UI_COLORS['status_info'])
                try:
                    from workers.install.mod_install_worker import ModInstallWorker
                    gb_metadata = self._build_gb_metadata(mod_id)
                    installer = ModInstallWorker(archive_path=archive_path, mods_dir=self.main_window.app_state.mods_dir, mod_service=None, gamebanana_metadata=gb_metadata, parent=self.parent())
                    installer.run()
                    self._cleanup_temp_files(archive_path, archive_dir)
                    mod_dir = self._find_installed_mod_dir(mod_id)
                    if not mod_dir:
                        raise AppError('errors.gamebanana_installation_failed')
                    mod_name = os.path.basename(mod_dir)
                    self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
                except Exception as e:
                    self._cleanup_temp_files(archive_path, archive_dir)
                    logger.error(f'Error installing DELTAHUB mod from GameBanana (mod {mod_id}): {e}', exc_info=True)
                    raise AppError('errors.gamebanana_installation_failed')
                return
            self.status.emit(tr('status.converting_mod'), UI_COLORS['status_info'])
            gb_metadata = self._build_gb_metadata(mod_id)
            converter = GameBananaConverter(archive_path, self.main_window.app_state.mods_dir, gb_metadata)
            mod_dir = converter.convert()
            self._cleanup_temp_files(archive_path, archive_dir)
            if not mod_dir:
                raise AppError('errors.gamebanana_conversion_failed')
            mod_name = os.path.basename(mod_dir)
            self.finished.emit(True, tr('status.install_complete_success', mod_name=mod_name))
        except RuntimeError as e:
            self._cleanup_temp_files(archive_path, archive_dir)
            if str(e) == 'download_cancelled' or self._cancelled:
                self.finished.emit(False, tr('status.operation_cancelled'))
            else:
                logger.error(f'Error installing GameBanana mod: {e}', exc_info=True)
                self.finished.emit(False, str(e))
        except Exception as e:
            logger.error(f'Error installing GameBanana mod: {e}', exc_info=True)
            self._cleanup_temp_files(archive_path, archive_dir)
            self.finished.emit(False, str(e))

    def _install_deltahub_mod(self, archive_path: str, mod_id: int) -> Optional[str]:
        import json
        from utils.archive_utils import extract_any_archive
        with tempfile.TemporaryDirectory(prefix='gb_install_dh_') as temp_dir:
            try:
                extract_any_archive(archive_path, temp_dir)
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
                    if file != MOD_CONFIG_FILENAME:
                        files_in_archive.append(file)
            if len(files_in_archive) == 0:
                external_url = config_data.get('external_url') or config_data.get('download_url')
                if external_url:
                    logger.info(f'DELTAHUB mod {mod_id} appears to be a redirect to {external_url}')
                    self.status.emit(tr('status.downloading_from_external'), UI_COLORS['status_info'])
                    try:
                        from utils.file_utils import download_file_with_progress
                        from utils.archive_utils import get_file_extension_from_url
                        temp_dir = tempfile.mkdtemp(prefix='gb_redirect_')
                        file_ext = get_file_extension_from_url(external_url)
                        redirect_archive_path = os.path.join(temp_dir, f'redirect_mod{file_ext}')
                        session = get_session()
                        self._session = session
                        downloaded_ref = [0]
                        success = download_file_with_progress(external_url, redirect_archive_path, session=session, cancel_check=lambda: self._cancelled, downloaded_ref=downloaded_ref)
                        if not success:
                            raise RuntimeError('download_failed')
                        return self._install_deltahub_mod(redirect_archive_path, mod_id)
                    except Exception as e:
                        logger.error(f'Error downloading redirect mod: {e}')
                        raise ValueError(f'Failed to download redirect mod: {e}')
            mod_name = config_data.get('name', f'mod_{mod_id}')
            target_mod_dir = self._create_unique_mod_dir(self.main_window.app_state.mods_dir, mod_name)
            self._copy_directory_contents(content_root, target_mod_dir)
            if not config_data.get('external_url') and self.mod_info.external_url:
                config_data['external_url'] = self.mod_info.external_url
            if self.mod_info.icon_url:
                config_data['icon_url'] = self.mod_info.icon_url
            tags = []
            if hasattr(self.mod_info, 'tags') and self.mod_info.tags:
                tags = self.mod_info.tags if isinstance(self.mod_info.tags, list) else [self.mod_info.tags]
            elif hasattr(self.mod_info, 'gamebanana_category') and self.mod_info.gamebanana_category:
                category_tag = GameBananaAPI.category_to_tag(self.mod_info.gamebanana_category)
                if category_tag:
                    tags = [category_tag]
            if tags:
                self._merge_tags(config_data, tags)
            expected_mod_key = f'gb_{mod_id}'
            config_data['key'] = expected_mod_key
            if 'mod_key' in config_data:
                del config_data['mod_key']
            target_config_path = os.path.join(target_mod_dir, MOD_CONFIG_FILENAME)
            try:
                from utils.file_utils import save_json
                save_json(target_config_path, config_data, indent=4)
                logger.info(f'Installed DELTAHUB mod: {target_mod_dir}, key = {expected_mod_key}')
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
            expected_mod_key = f'gb_{mod_id}'
            for item_name in os.listdir(mods_dir):
                item_path = os.path.join(mods_dir, item_name)
                if not os.path.isdir(item_path):
                    continue
                config_path = os.path.join(item_path, MOD_CONFIG_FILENAME)
                if not os.path.exists(config_path):
                    continue
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    if (config_data.get('key') or config_data.get('mod_key')) == expected_mod_key:
                        return item_path
                except Exception:
                    continue
            return None
        except Exception as e:
            logger.error(f'Error finding installed mod directory: {e}', exc_info=True)
            return None

    def _resolve_selected_file(self, mod_id: int) -> Optional[Dict]:
        from services.mod_service import ModManager
        file_choice = ModManager.resolve_gamebanana_file(self.mod_info, self.api, self.selected_file)
        if file_choice:
            self.selected_file = file_choice
            self._notify_search_refresh()
        return file_choice

    def _notify_search_refresh(self):
        try:
            if hasattr(self.main_window, 'search_display'):
                self.main_window.search_display.update_search_cards()
        except Exception as e:
            logger.debug(f'InstallGameBananaModThread: Error notifying search refresh: {e}')
