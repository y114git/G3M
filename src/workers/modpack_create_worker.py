"""Modpack creation worker thread."""
import logging
import os
import json
import uuid
import time
import platform
import shutil
import subprocess
from typing import Dict, List, Any
from PyQt6.QtCore import QThread, pyqtSignal
from services.mod_patching_service import ModPatcher
from services.localization_service import tr
from utils.path_utils import get_xdelta_path
from utils.file_utils import get_chapter_folder_name


class CreateModpackThread(QThread):
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, chapter_mods: Dict[int, List[Any]], modpack_name: str, modpack_dir: str, app_state, mod_service, parent=None, fast_patch: bool = False, xdelta_modpack: bool = False):
        super().__init__(parent)
        self.chapter_mods = chapter_mods
        self.modpack_name = modpack_name
        self.modpack_dir = modpack_dir
        self.app_state = app_state
        self.mod_service = mod_service
        self.fast_patch = fast_patch
        self.xdelta_modpack = xdelta_modpack
        self.patcher = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self.patcher:
            self.patcher._cancelled = True
        self.status_update.emit('Operation cancelled', 'error')

    def _get_mod_game(self, mods_list: List[Any]):
        game = None
        if mods_list:
            first_mod = mods_list[0]
            game = getattr(first_mod, 'game', None) or getattr(first_mod, 'modgame', None)
            if not game and hasattr(first_mod, 'config_data'):
                config = getattr(first_mod, 'config_data')
                if isinstance(config, dict):
                    game = config.get('game') or config.get('modgame')
        return game

    def run(self):
        success = False
        try:
            if self.isInterruptionRequested() or self._cancelled:
                return
            self.patcher = ModPatcher(self.app_state, self.mod_service, None)
            self.patcher.progress_update.connect(self.progress_update.emit)
            self.patcher.status_update.connect(self.status_update.emit)
            self.patcher._cancelled = False
            if self.isInterruptionRequested() or self._cancelled:
                return
            success = self.patcher.process_mod_patch(self.chapter_mods, is_modpack=True, modpack_dir=self.modpack_dir, fast_patch=self.fast_patch, xdelta_modpack=self.xdelta_modpack)
            if self.isInterruptionRequested() or self._cancelled:
                self.patcher._cancelled = True
                success = False
                if os.path.exists(self.modpack_dir):
                    try:
                        shutil.rmtree(self.modpack_dir, ignore_errors=True)
                        logging.info(f'Cancelled modpack creation, removed directory: {self.modpack_dir}')
                    except Exception as e:
                        logging.error(f'Failed to remove cancelled modpack directory: {e}')
            if success and (not (self.isInterruptionRequested() or self._cancelled)):
                if self.xdelta_modpack:
                    self._create_xdelta_patches()
                self._create_config_json()
        except Exception as e:
            logging.error(f'CreateModpackThread failed: {e}', exc_info=True)
            self.status_update.emit(f'Modpack creation failed: {str(e)}', 'error')
            success = False
        finally:
            if self.patcher:
                try:
                    for sig in (self.patcher.progress_update, self.patcher.status_update):
                        try:
                            sig.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                    self.patcher.cleanup(force=True)
                except Exception as cleanup_error:
                    logging.warning(f'Error during patcher cleanup: {cleanup_error}', exc_info=True)
                finally:
                    self.patcher = None
            self.finished.emit(success)

    def _create_xdelta_patches(self):
        try:
            xdelta_path = get_xdelta_path()
            if not xdelta_path or not os.path.exists(xdelta_path):
                logging.error('xdelta executable not found, cannot create xdelta patches')
                self.status_update.emit(tr('errors.xdelta_not_found', path=''), 'error')
                return
            for chapter_id, mods_list in self.chapter_mods.items():
                if self.isInterruptionRequested() or self._cancelled:
                    return
                game = self._get_mod_game(mods_list)
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                chapter_modpack_dir = os.path.join(self.modpack_dir, chapter_folder_name)
                if not os.path.exists(chapter_modpack_dir):
                    continue
                system = platform.system()
                data_filename = 'game.ios' if system == 'Darwin' else 'data.win'
                modified_data_file = os.path.join(chapter_modpack_dir, data_filename)
                if not os.path.exists(modified_data_file):
                    continue
                original_data_file = self._find_original_data_file(chapter_id, game, data_filename)
                if not original_data_file or not os.path.exists(original_data_file):
                    logging.warning(f'Original data file not found for chapter {chapter_id}, skipping xdelta creation')
                    continue
                patch_filename = f'{os.path.splitext(data_filename)[0]}.xdelta'
                patch_path = os.path.join(chapter_modpack_dir, patch_filename)
                self.status_update.emit(tr('status.creating_xdelta_patch', chapter=chapter_id), 'info')
                cmd = [xdelta_path, '-e', '-s', original_data_file, modified_data_file, patch_path]
                startupinfo = None
                creationflags = 0
                if platform.system() == 'Windows':
                    import subprocess as sp
                    startupinfo = sp.STARTUPINFO()
                    startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = sp.SW_HIDE
                    creationflags = sp.CREATE_NO_WINDOW
                try:
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL, startupinfo=startupinfo, creationflags=creationflags)
                    stdout, stderr = process.communicate(timeout=300)
                    if process.returncode != 0:
                        logging.error(f'Failed to create xdelta patch for chapter {chapter_id}: {stderr}')
                        self.status_update.emit(tr('errors.xdelta_patch_creation_failed', chapter=chapter_id), 'error')
                        continue
                    if os.path.exists(patch_path):
                        try:
                            os.remove(modified_data_file)
                            logging.info(f'Removed data file: {modified_data_file}')
                            for file in os.listdir(chapter_modpack_dir):
                                if file.endswith('.xdelta') and file != patch_filename:
                                    old_patch_path = os.path.join(chapter_modpack_dir, file)
                                    try:
                                        os.remove(old_patch_path)
                                        logging.info(f'Removed old xdelta patch: {old_patch_path}')
                                    except Exception as e:
                                        logging.warning(f'Failed to remove old xdelta patch {old_patch_path}: {e}')
                            logging.info(f'Created xdelta patch for chapter {chapter_id}: {patch_path}')
                        except Exception as e:
                            logging.warning(f'Failed to remove data file after creating xdelta patch: {e}')
                except subprocess.TimeoutExpired:
                    logging.error(f'xdelta patch creation timed out for chapter {chapter_id}')
                    process.kill()
                    self.status_update.emit(tr('errors.xdelta_patch_timeout', chapter=chapter_id), 'error')
                except Exception as e:
                    logging.error(f'Error creating xdelta patch for chapter {chapter_id}: {e}', exc_info=True)
                    self.status_update.emit(tr('errors.xdelta_patch_creation_failed', chapter=chapter_id), 'error')
        except Exception as e:
            logging.error(f'Failed to create xdelta patches: {e}', exc_info=True)
            self.status_update.emit(tr('errors.xdelta_patch_creation_failed_general'), 'error')

    def _determine_primary_game_type(self, detected_games: List[str]) -> str:
        if not detected_games:
            from services.game_detection_service import get_game_type_string
            return get_game_type_string(self.app_state.game_mode)
        unique_games = set(detected_games)
        if len(unique_games) == 1:
            return unique_games.pop()
        return max(unique_games, key=detected_games.count)

    def _find_original_data_file(self, chapter_id: int, game: str, data_filename: str) -> str:
        try:
            from models.game_modes import get_game, DeltaruneGame
            from utils.path_utils import find_chapter_resource_dir
            game_mode = None
            base_game_path = None
            if game == 'deltarune_demo' or self.app_state.game_mode.game_id == 'deltarunedemo':
                game_mode = get_game('deltarunedemo')
                base_game_path = self.app_state.demo_game_path
            elif game == 'undertale' or self.app_state.game_mode.game_id == 'undertale':
                game_mode = get_game('undertale')
                base_game_path = game_mode.get_game_path(self.app_state.local_config)
            elif game == 'undertaleyellow' or self.app_state.game_mode.game_id == 'undertaleyellow':
                game_mode = get_game('undertaleyellow')
                base_game_path = game_mode.get_game_path(self.app_state.local_config)
            elif game == 'pizzatower' or self.app_state.game_mode.game_id == 'pizzatower':
                game_mode = get_game('pizzatower')
                base_game_path = game_mode.get_game_path(self.app_state.local_config)
            else:
                game_mode = get_game('deltarune') or DeltaruneGame()
                base_game_path = self.app_state.game_path
            if not base_game_path or not os.path.exists(base_game_path):
                logging.warning(f'Base game path not found: {base_game_path}')
                return None
            chapter_dir = find_chapter_resource_dir(base_game_path, chapter_id)
            if not chapter_dir or not os.path.exists(chapter_dir):
                logging.warning(f'Chapter directory not found for chapter {chapter_id} in {base_game_path}')
                return None
            original_data_file = os.path.join(chapter_dir, data_filename)
            if os.path.exists(original_data_file):
                logging.info(f'Found original data file: {original_data_file}')
                return original_data_file
            logging.warning(f'Original data file not found: {original_data_file}')
            return None
        except Exception as e:
            logging.error(f'Error finding original data file: {e}', exc_info=True)
            return None

    def _create_config_json(self):
        try:
            files_data = {}
            detected_games = []
            for chapter_id, mods_list in self.chapter_mods.items():
                chapter_key = 'demo' if chapter_id == -1 else str(chapter_id)
                game = self._get_mod_game(mods_list)
                if game:
                    detected_games.append(game)
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                chapter_modpack_dir = os.path.join(self.modpack_dir, chapter_folder_name)
                if not os.path.exists(chapter_modpack_dir):
                    continue
                file_info = {}
                system = platform.system()
                if self.xdelta_modpack:
                    xdelta_patch = os.path.join(chapter_modpack_dir, 'game.xdelta' if system == 'Darwin' else 'data.xdelta')
                    if os.path.exists(xdelta_patch):
                        file_info['data_file_url'] = os.path.basename(xdelta_patch)
                        file_info['data_file_version'] = '1.0.0'
                        files_data[chapter_key] = file_info
                        continue
                    logging.warning(f'xdelta_modpack enabled but xdelta patch not found for chapter {chapter_id}, skipping in config')
                    continue
                data_name = 'game.ios' if system == 'Darwin' else 'data.win'
                if os.path.exists(os.path.join(chapter_modpack_dir, data_name)):
                    file_info['data_file_url'] = data_name
                if file_info:
                    file_info['data_file_version'] = '1.0.0'
                    files_data[chapter_key] = file_info
            key = f'local_{uuid.uuid4().hex[:12]}'
            detected_game = self._determine_primary_game_type(detected_games)
            config_data = {'key': key, 'name': self.modpack_name, 'author': tr('defaults.multiple_authors'), 'version': '1.0.0', 'tagline': tr('defaults.no_short_description'), 'game_version': tr('defaults.not_specified'), 'game': detected_game, 'files': files_data, 'tags': [], 'created_date': time.strftime('%d.%m.%y %H:%M')}
            config_path = os.path.join(self.modpack_dir, 'mod_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logging.info(f'Created mod_config.json for modpack: {self.modpack_name}')
        except Exception as e:
            logging.error(f'Failed to create mod_config.json: {e}', exc_info=True)
            raise
