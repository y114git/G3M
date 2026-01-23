"""Modpack creation worker thread.

This module provides a background thread for creating modpacks from merged mods.
"""
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
from managers.multi_mod_merger import MultiModMerger
from managers.localization_manager import tr
from utils.path_utils import get_xdelta_path


class CreateModpackThread(QThread):
    """Worker thread for creating modpacks from multiple chapters.

    Handles the creation of modpack files by merging mods from different
    chapters using the MultiModMerger. Provides progress updates and
    status reporting during the modpack creation process.

    Signals:
        progress_update: Emitted with (progress, message) for progress updates.
        status_update: Emitted with (message, type) for status updates.
        finished: Emitted with (success) when creation is complete.
    """
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, chapter_mods: Dict[int, List[Any]], modpack_name: str, modpack_dir: str, app_state, mod_manager, parent=None, fast_merge: bool = False, xdelta_modpack: bool = False):
        super().__init__(parent)
        self.chapter_mods = chapter_mods
        self.modpack_name = modpack_name
        self.modpack_dir = modpack_dir
        self.app_state = app_state
        self.mod_manager = mod_manager
        self.fast_merge = fast_merge
        self.xdelta_modpack = xdelta_modpack
        self.merger = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()
        if self.merger:
            self.merger._cancelled = True
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
            self.merger = MultiModMerger(self.app_state, self.mod_manager, None)
            self.merger.progress_update.connect(self.progress_update.emit)
            self.merger.status_update.connect(self.status_update.emit)
            self.merger._cancelled = False
            if self.isInterruptionRequested() or self._cancelled:
                return
            success = self.merger.process_mod_merge(self.chapter_mods, is_modpack=True, modpack_dir=self.modpack_dir, fast_merge=self.fast_merge, xdelta_modpack=self.xdelta_modpack)
            if self.isInterruptionRequested() or self._cancelled:
                self.merger._cancelled = True
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
            if self.merger:
                try:
                    try:
                        self.merger.progress_update.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        self.merger.status_update.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    self.merger.cleanup(force=True)
                except Exception as cleanup_error:
                    logging.warning(f'Error during merger cleanup: {cleanup_error}', exc_info=True)
                finally:
                    self.merger = None
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
                from utils.file_utils import get_chapter_folder_name
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                chapter_modpack_dir = os.path.join(self.modpack_dir, chapter_folder_name)
                if not os.path.exists(chapter_modpack_dir):
                    continue
                system = platform.system()
                modified_data_file = None
                original_data_file = None
                data_filename = None
                if system == 'Darwin':
                    modified_data_file = os.path.join(chapter_modpack_dir, 'game.ios')
                    data_filename = 'game.ios'
                else:
                    modified_data_file = os.path.join(chapter_modpack_dir, 'data.win')
                    data_filename = 'data.win'
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
            from utils.game_utils import get_game_type_string
            return get_game_type_string(self.app_state.game_mode)
        unique_games = list(set(detected_games))
        if len(unique_games) == 1:
            primary_game = unique_games[0]
            return primary_game
        most_common = max(set(detected_games), key=detected_games.count)
        return most_common

    def _find_original_data_file(self, chapter_id: int, game: str, data_filename: str) -> str:
        try:
            from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, FullGameMode
            from utils.path_utils import find_chapter_resource_dir
            game_mode = None
            base_game_path = None
            if game == 'deltarune_demo' or isinstance(self.app_state.game_mode, DemoGameMode):
                game_mode = DemoGameMode()
                base_game_path = self.app_state.demo_game_path
            elif game == 'undertale' or isinstance(self.app_state.game_mode, UndertaleGameMode):
                game_mode = UndertaleGameMode()
                base_game_path = game_mode.get_game_path(self.app_state.local_config)
            elif game == 'undertaleyellow' or isinstance(self.app_state.game_mode, UndertaleYellowGameMode):
                game_mode = UndertaleYellowGameMode()
                base_game_path = game_mode.get_game_path(self.app_state.local_config)
            elif game == 'pizzatower' or isinstance(self.app_state.game_mode, PizzaTowerGameMode):
                game_mode = PizzaTowerGameMode()
                base_game_path = game_mode.get_game_path(self.app_state.local_config)
            else:
                game_mode = FullGameMode()
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
                if chapter_id == -1:
                    chapter_key = 'demo'
                elif chapter_id == 0:
                    chapter_key = '0'
                else:
                    chapter_key = str(chapter_id)
                game = self._get_mod_game(mods_list)
                if game:
                    detected_games.append(game)
                from utils.file_utils import get_chapter_folder_name
                chapter_folder_name = get_chapter_folder_name(chapter_id, game=game)
                chapter_modpack_dir = os.path.join(self.modpack_dir, chapter_folder_name)
                if not os.path.exists(chapter_modpack_dir):
                    continue
                file_info = {}
                system = platform.system()
                if self.xdelta_modpack:
                    xdelta_patch = None
                    if system == 'Darwin':
                        xdelta_patch = os.path.join(chapter_modpack_dir, 'game.xdelta')
                    else:
                        xdelta_patch = os.path.join(chapter_modpack_dir, 'data.xdelta')
                    if os.path.exists(xdelta_patch):
                        file_info['data_file_url'] = os.path.basename(xdelta_patch)
                        file_info['data_file_version'] = '1.0.0'
                        files_data[chapter_key] = file_info
                        continue
                    else:
                        logging.warning(f'xdelta_modpack enabled but xdelta patch not found for chapter {chapter_id}, skipping in config')
                        continue
                if system == 'Darwin':
                    data_file = os.path.join(chapter_modpack_dir, 'game.ios')
                    if os.path.exists(data_file):
                        file_info['data_file_url'] = 'game.ios'
                else:
                    data_file = os.path.join(chapter_modpack_dir, 'data.win')
                    if os.path.exists(data_file):
                        file_info['data_file_url'] = 'data.win'
                if file_info:
                    file_info['data_file_version'] = '1.0.0'
                    files_data[chapter_key] = file_info
            key = f'local_{uuid.uuid4().hex[:12]}'
            detected_game = self._determine_primary_game_type(detected_games)
            config_data = {'is_local_mod': True, 'key': key, 'name': self.modpack_name, 'author': tr('defaults.multiple_authors'), 'version': '1.0.0', 'tagline': tr('defaults.no_short_description'), 'game_version': tr('defaults.not_specified'), 'game': detected_game, 'files': files_data, 'tags': [], 'created_date': time.strftime('%d.%m.%y %H:%M'), 'is_available_on_server': False}
            config_path = os.path.join(self.modpack_dir, 'mod_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logging.info(f'Created mod_config.json for modpack: {self.modpack_name}')
        except Exception as e:
            logging.error(f'Failed to create mod_config.json: {e}', exc_info=True)
            raise
