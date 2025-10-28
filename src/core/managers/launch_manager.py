import os
import sys
import platform
import shutil
import tempfile
import hashlib
import subprocess
import webbrowser
import rarfile
import tarfile
import lzma
import py7zr
import zipfile
from typing import Dict, Optional, Any
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from localization.manager import tr
from models.game_modes import DemoGameMode, UndertaleGameMode
from utils.file_utils import ensure_writable, sanitize_filename
from utils.game_utils import is_game_running
from utils.path_utils import get_xdelta_path
from threads.game_monitor import GameMonitorThread
from config.constants import UI_COLORS

class GameLauncher(QObject):
    status_changed = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    game_launch_started = pyqtSignal()
    game_launch_finished = pyqtSignal()

    def __init__(self, app_state, feedback_manager, mod_manager, save_manager=None, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.save_manager = save_manager
        self.monitor_thread = None
        self._backup_temp_dir = None
        self._backup_files = {}
        self._mod_files_to_cleanup = []
        self._mod_dirs_to_cleanup = []
        self._direct_launch_cleanup_info = None
        self._collection_backup_info = {}
        self._ensure_backup_attributes()

    def _ensure_backup_attributes(self):
        if not hasattr(self, '_mod_files_to_cleanup'):
            self._mod_files_to_cleanup = []
        if not hasattr(self, '_backup_files'):
            self._backup_files = {}
        if not hasattr(self, '_mod_dirs_to_cleanup'):
            self._mod_dirs_to_cleanup = []

    def launch_game_with_all_mods(self, execute_plugin_hooks=None, restore_window_callback=None):
        if self.save_manager:
            collection_idx = self.save_manager.prompt_for_save_collection_on_launch()
            if collection_idx is None:
                if restore_window_callback:
                    restore_window_callback()
                return
            if collection_idx != -1:
                self._collection_backup_info = self.save_manager.apply_collection_saves_for_launch(collection_idx)
        selections = self._get_slot_selections()
        self._launch_game_with_selections(selections, execute_plugin_hooks, restore_window_callback)

    def _get_slot_selections(self) -> Dict[int, str]:
        selections = {}
        if not hasattr(self.app_state, 'slots'):
            return selections
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
        if is_demo_mode:
            demo_slot = self.app_state.slots.get(-10)
            if demo_slot and demo_slot.assigned_mod:
                selections[-1] = demo_slot.assigned_mod.key
            else:
                selections[-1] = 'no_change'
        elif is_undertale_mode:
            undertale_slot = self.app_state.slots.get(-20)
            if undertale_slot and undertale_slot.assigned_mod:
                selections[-1] = undertale_slot.assigned_mod.key
            else:
                selections[-1] = 'no_change'
        elif self.app_state.current_mode == 'normal':
            universal_slot = self.app_state.slots.get(-1)
            if universal_slot and universal_slot.assigned_mod:
                mod = universal_slot.assigned_mod
                for chapter_id in range(5):
                    if mod.get_chapter_data(chapter_id):
                        selections[chapter_id] = mod.key
                    else:
                        selections[chapter_id] = 'no_change'
            else:
                for chapter_id in range(5):
                    selections[chapter_id] = 'no_change'
        elif self.app_state.current_mode == 'chapter':
            for chapter_id in range(5):
                slot = self.app_state.slots.get(chapter_id)
                if slot and slot.assigned_mod:
                    selections[chapter_id] = slot.assigned_mod.key
                else:
                    selections[chapter_id] = 'no_change'
        return selections

    def _launch_game_with_selections(self, selections: Dict[int, str], execute_plugin_hooks=None, restore_window_callback=None):
        self.execute_plugin_hooks = execute_plugin_hooks
        self.restore_window_callback = restore_window_callback
        if execute_plugin_hooks:
            execute_plugin_hooks('on_before_game_launch')
        self.game_launch_started.emit()
        self.status_changed.emit(tr('status.launching_game'), UI_COLORS['status_success'])
        self._ensure_backup_attributes()
        if not self._find_and_validate_game_path(selections):
            self._handle_launch_failure()
            return
        if not self._prepare_game_files(selections):
            self._handle_launch_failure()
            return
        launch_config = self._determine_launch_config(selections)
        if not launch_config:
            self._handle_launch_failure()
            return
        self._execute_game(launch_config)
        if execute_plugin_hooks:
            execute_plugin_hooks('on_after_game_launch')

    def _handle_launch_failure(self):
        if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
            self.restore_window_callback()

    def _execute_game(self, launch_config: Dict[str, Any], vanilla_mode: bool=False):
        target_path = launch_config.get('target')
        working_directory = launch_config.get('cwd')
        launch_type = launch_config.get('type')
        if not target_path:
            self.status_changed.emit(tr('errors.launch_target_not_defined'), 'red')
            if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                self.restore_window_callback()
            return
        try:
            if self.monitor_thread:
                try:
                    if self.monitor_thread.isRunning():
                        self.monitor_thread.requestInterruption()
                        self.monitor_thread.quit()
                        self.monitor_thread.wait(1000)
                    self.monitor_thread.deleteLater()
                except Exception:
                    pass
                self.monitor_thread = None
            if launch_type == 'webbrowser':
                self.monitor_thread = GameMonitorThread(None, vanilla_mode, self)
                self.monitor_thread.finished.connect(self._on_game_process_finished)
                self.monitor_thread.start()
                webbrowser.open(target_path)
                self.status_changed.emit(tr('status.launching_via_steam'), UI_COLORS['status_steam'])
                return
            if not working_directory or not os.path.isdir(working_directory):
                msg = tr('errors.working_directory_not_found', path=working_directory)
                self.status_changed.emit(msg, 'red')
                if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                    self.restore_window_callback()
                return
            system = platform.system()
            if system == 'Darwin':
                use_custom_exe = self.app_state.local_config.get('use_custom_executable', False)
                if use_custom_exe:
                    subprocess.Popen(['open', target_path])
                    self.status_changed.emit(tr('status.macos_file_opened'), UI_COLORS['status_steam'])
                    if getattr(self, 'is_shortcut_launch', False):
                        sys.exit(0)
                    elif hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                        QTimer.singleShot(2000, self.restore_window_callback)
                    return
                if target_path.endswith('.app'):
                    process = subprocess.Popen(['open', '-W', target_path])
            else:
                command = [target_path]
                if system == 'Linux' and target_path.lower().endswith('.exe'):
                    is_steam_launch = self.app_state.local_config.get('launch_via_steam', False)
                    if not is_steam_launch:
                        command.insert(0, 'wine')
                creationflags = 0
                if system == 'Windows':
                    creationflags = 8
                process = subprocess.Popen(command, cwd=working_directory, creationflags=creationflags)
            self.status_changed.emit(tr('status.game_launched_waiting_for_exit'), UI_COLORS['status_steam'])
            self.monitor_thread = GameMonitorThread(process, vanilla_mode, self)
            self.monitor_thread.finished.connect(self._on_game_process_finished)
            self.monitor_thread.start()
        except Exception as e:
            self.status_changed.emit(tr('errors.game_launch_error', error=str(e)), 'red')
            if hasattr(self, 'restore_window_callback') and self.restore_window_callback:
                self.restore_window_callback()

    def _on_game_process_finished(self, vanilla_mode: bool):
        if hasattr(self, 'execute_plugin_hooks') and self.execute_plugin_hooks:
            self.execute_plugin_hooks('on_before_game_exit')
        if getattr(self, 'is_shortcut_launch', False):
            sys.exit(0)
        else:
            self._check_game_running(vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        if is_game_running():
            QTimer.singleShot(2000, lambda: self._check_game_running(vanilla_mode))
        else:
            self.status_changed.emit(tr('status.game_closed_restoring_files'), UI_COLORS['status_info'])
            self._cleanup_direct_launch_files()
            if self.save_manager and self._collection_backup_info:
                self.save_manager.restore_original_saves_after_launch(self._collection_backup_info)
                self._collection_backup_info = {}
            self.game_launch_finished.emit()
            if self.monitor_thread:
                try:
                    self.monitor_thread.wait(1000)
                    self.monitor_thread.deleteLater()
                except Exception:
                    pass
                self.monitor_thread = None

    def _determine_launch_config(self, selections: Dict[int, str]) -> Optional[Dict[str, Any]]:
        use_steam = self.app_state.local_config.get('launch_via_steam', False)
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', -1)
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        direct_launch = direct_launch_slot_id >= 0 and is_chapter_mode and self.app_state.game_mode.direct_launch_allowed and (platform.system() != 'Darwin')
        if use_steam:
            return {'target': f'steam://rungameid/{self.app_state.game_mode.steam_id}', 'cwd': None, 'type': 'webbrowser'}
        if direct_launch:
            return self._handle_direct_launch(direct_launch_slot_id)
        launch_target = self._get_executable_path()
        if not launch_target:
            self.status_changed.emit(tr('errors.executable_not_found'), UI_COLORS['status_error'])
            return None
        return {'target': launch_target, 'cwd': self._get_current_game_path(), 'type': 'subprocess'}

    def _handle_direct_launch(self, selected_tab_index: int) -> Optional[Dict[str, Any]]:
        chapter_folder = self._get_target_dir(self.app_state.game_mode.get_chapter_id(selected_tab_index))
        source_exe = self._get_source_executable_path()
        use_custom_exe = self.app_state.local_config.get('use_custom_executable', False)
        if not chapter_folder or not source_exe:
            self.status_changed.emit(tr('errors.direct_launch_error'), UI_COLORS['status_error'])
            return None
        try:
            if not ensure_writable(chapter_folder):
                raise PermissionError(tr('errors.no_write_permission_for', path=chapter_folder))
            if use_custom_exe:
                target_exe = os.path.join(chapter_folder, os.path.basename(source_exe))
            else:
                exe_name = 'UNDERTALE.exe' if isinstance(self.app_state.game_mode, UndertaleGameMode) else 'DELTARUNE.exe'
                target_exe = os.path.join(chapter_folder, exe_name)
            shutil.copy2(source_exe, target_exe)
            self._direct_launch_cleanup_info = {'target_exe': target_exe, 'source_exe': source_exe, 'chapter_folder': chapter_folder, 'use_custom_exe': use_custom_exe}
            self._update_session_manifest(direct_launch=self._direct_launch_cleanup_info)
            return {'target': target_exe, 'cwd': chapter_folder, 'type': 'subprocess'}
        except PermissionError:
            self.status_changed.emit(tr('errors.permission_denied'), UI_COLORS['status_error'])
            return None

    def _get_executable_path(self):
        use_custom_exe = self.app_state.local_config.get('use_custom_executable', False)
        if use_custom_exe:
            custom_path = self.app_state.local_config.get(self.app_state.game_mode.get_custom_exec_config_key(), '')
            if custom_path and os.path.isfile(custom_path):
                return custom_path
        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None
        system = platform.system()
        is_undertale = isinstance(self.app_state.game_mode, UndertaleGameMode)
        base_exe_name = 'UNDERTALE' if is_undertale else 'DELTARUNE'
        if system == 'Windows':
            exe_path = os.path.join(current_game_path, f'{base_exe_name}.exe')
            if os.path.isfile(exe_path):
                return exe_path
        elif system == 'Linux':
            native_path = os.path.join(current_game_path, base_exe_name)
            if os.path.isfile(native_path) and os.access(native_path, os.X_OK):
                return native_path
            exe_path = os.path.join(current_game_path, f'{base_exe_name}.exe')
            if os.path.isfile(exe_path):
                return exe_path
        elif system == 'Darwin':
            if current_game_path.endswith('.app') and os.path.isdir(current_game_path):
                app_path = current_game_path
            else:
                app_path = None
                if is_undertale:
                    app_names = ['UNDERTALE.app']
                else:
                    app_names = ['DELTARUNE.app', 'DELTARUNEdemo.app']
                for name in app_names:
                    candidate = os.path.join(current_game_path, name)
                    if os.path.isdir(candidate):
                        app_path = candidate
                        break
            if app_path:
                return app_path
        self.status_changed.emit(tr('errors.executable_not_found_deltarune'), UI_COLORS['status_error'])
        return None

    def _get_source_executable_path(self):
        if self.app_state.local_config.get('use_custom_executable', False):
            cfg_key = self.app_state.game_mode.get_custom_exec_config_key()
            return self.app_state.local_config.get(cfg_key, '')
        return self._get_executable_path()

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ''

    def _get_target_dir(self, chapter_id):
        target_base = self._get_current_game_path()
        if not target_base:
            return None
        if platform.system() == 'Darwin':
            if not target_base.endswith('.app'):
                for app_name in ('DELTARUNE.app', 'DELTARUNEdemo.app'):
                    candidate = os.path.join(target_base, app_name)
                    if os.path.isdir(candidate):
                        target_base = candidate
                        break
            target_base = os.path.join(target_base, 'Contents', 'Resources')
            if not os.path.isdir(target_base):
                return None
        if chapter_id == -1:
            return target_base
        if chapter_id == 0:
            return target_base
        chapter_prefix = f'chapter{chapter_id}_'
        try:
            for entry in os.listdir(target_base):
                if os.path.isdir(os.path.join(target_base, entry)) and entry.startswith(chapter_prefix):
                    return os.path.join(target_base, entry)
            return None
        except Exception as e:
            self.status_changed.emit(tr('errors.chapter_folder_search_error', error=str(e)), UI_COLORS['status_error'])
            return None

    def _prepare_game_files(self, selections: Dict[int, str]) -> bool:
        try:
            applied_chapters = set()
            for ui_index, mod_key in selections.items():
                if mod_key == 'no_change':
                    continue
                chapter_id = self.app_state.game_mode.get_chapter_id(ui_index)
                mod = next((m for m in self.app_state.all_mods if m.key == mod_key), None)
                if not mod:
                    continue
                is_local = getattr(mod, 'is_local_mod', False)
                if is_local:
                    mod_folder_path = self.mod_manager.get_mod_folder_path(mod_key)
                    if mod_folder_path:
                        source_dir = mod_folder_path
                    else:
                        folder_name = sanitize_filename(mod.name)
                        source_dir = os.path.join(self.app_state.mods_dir, folder_name)
                else:
                    folder_name = sanitize_filename(mod.name)
                    source_dir = os.path.join(self.app_state.mods_dir, folder_name)
                if not os.path.isdir(source_dir):
                    self.status_changed.emit(tr('errors.mod_folder_not_found', mod_name=mod.name, path=source_dir), UI_COLORS['status_warning'])
                    continue
                mod_type_str = tr('ui.mod_type_local') if is_local else tr('ui.mod_type_public')
                self.status_changed.emit(tr('status.applying_mod', mod_name=mod.name, mod_type=mod_type_str), UI_COLORS['status_warning'])
                if chapter_id in applied_chapters:
                    continue
                is_xdelta_mod = self._is_xdelta_mod(mod, source_dir, chapter_id)
                if not is_xdelta_mod and (not mod.get_chapter_data(chapter_id)) and (not is_local):
                    continue
                target_dir = self._get_target_dir(chapter_id)
                if not target_dir:
                    continue
                if not ensure_writable(target_dir):
                    raise PermissionError(tr('errors.no_write_permission_for', path=target_dir))
                if not self._create_backup_and_copy_mod_files(source_dir, target_dir, chapter_id, mod):
                    return False
                applied_chapters.add(chapter_id)
            return True
        except PermissionError as e:
            path = e.filename or (e.args[0] if e.args else tr('errors.unknown_path'))
            self.status_changed.emit(tr('errors.permission_error', path=path), UI_COLORS['status_error'])
            return False
        except Exception as e:
            self.status_changed.emit(tr('errors.file_prep_error', error=str(e)), UI_COLORS['status_error'])
            return False

    def _is_xdelta_mod(self, mod_info, source_dir: str, chapter_id: Optional[int]=None) -> bool:
        if mod_info and getattr(mod_info, 'is_xdelta', False):
            return True
        if chapter_id is not None:
            search_dir = None
            if chapter_id == -1:
                demo_dir = os.path.join(source_dir, 'demo')
                if os.path.isdir(demo_dir):
                    search_dir = demo_dir
                else:
                    search_dir = source_dir
            elif chapter_id == 0:
                chapter0_dir = os.path.join(source_dir, 'chapter_0')
                menu_dir_alt = os.path.join(source_dir, 'menu')
                if os.path.isdir(chapter0_dir):
                    search_dir = chapter0_dir
                elif os.path.isdir(menu_dir_alt):
                    search_dir = menu_dir_alt
                else:
                    search_dir = source_dir
            else:
                chapter_dir = os.path.join(source_dir, f'chapter_{chapter_id}')
                if os.path.isdir(chapter_dir):
                    search_dir = chapter_dir
            if not search_dir:
                return False
        else:
            search_dir = source_dir
        if os.path.exists(search_dir):
            for root, _, files in os.walk(search_dir):
                for file in files:
                    if file.lower().endswith('.xdelta'):
                        return True
        return False

    def _create_backup_and_copy_mod_files(self, source_dir: str, target_dir: str, chapter_id: Optional[int]=None, mod_info=None):
        if not os.path.isdir(source_dir):
            self.status_changed.emit(tr('errors.mod_folder_not_found_simple', path=source_dir), UI_COLORS['status_error'])
            return False
        self._ensure_backup_attributes()
        self._ensure_session_manifest()
        is_xdelta_mod = self._is_xdelta_mod(mod_info, source_dir, chapter_id)
        applied_xdelta_for_this_chapter = False
        files_copied = 0
        if chapter_id is not None:
            chapter_folder_name = {-1: 'demo', 0: 'chapter_0'}.get(chapter_id, f'chapter_{chapter_id}')
            mod_source_dir = os.path.join(source_dir, chapter_folder_name)
            if not os.path.isdir(mod_source_dir):
                if chapter_id == 0:
                    alt_menu_dir = os.path.join(source_dir, 'menu')
                    if os.path.isdir(alt_menu_dir):
                        mod_source_dir = alt_menu_dir
                    else:
                        mod_source_dir = source_dir
                elif chapter_id == -1:
                    mod_source_dir = source_dir
                else:
                    mod_source_dir = None
        else:
            mod_source_dir = source_dir
        if not mod_source_dir or not os.path.isdir(mod_source_dir):
            self.status_changed.emit(tr('status.no_files_to_copy'), UI_COLORS['status_warning'])
            return True
        if not self._backup_temp_dir:
            self._backup_temp_dir = tempfile.mkdtemp(prefix='deltahub_backup_')
            self._update_session_manifest(backup_temp_dir=self._backup_temp_dir)
        for root, _, files in os.walk(mod_source_dir):
            for file in files:
                if file.lower() == 'config.json' or file.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico')):
                    continue
                cache_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(cache_file_path, mod_source_dir)
                file_lower = file.lower()
                target_rel_path = rel_path
                is_core_data_file = file_lower in ('data.win', 'data.ios', 'game.ios') or (file_lower.endswith('.win') and 'data' in file_lower) or (file_lower.endswith('.ios') and 'game' in file_lower) or (is_xdelta_mod and file_lower.endswith('.xdelta'))
                if platform.system() == 'Darwin':
                    if is_core_data_file:
                        target_rel_path = os.path.join(os.path.dirname(rel_path), 'game.ios')
                    elif file_lower.endswith('.win'):
                        name_without_ext = os.path.splitext(file)[0]
                        target_rel_path = os.path.join(os.path.dirname(rel_path), name_without_ext + '.ios')
                elif is_core_data_file:
                    target_rel_path = os.path.join(os.path.dirname(rel_path), 'data.win')
                elif file_lower.endswith('.ios'):
                    name_without_ext = os.path.splitext(file)[0]
                    target_rel_path = os.path.join(os.path.dirname(rel_path), name_without_ext + '.win')
                game_file_path = os.path.join(target_dir, target_rel_path)
                try:
                    target_dirname = os.path.dirname(game_file_path)
                    os.makedirs(target_dirname, exist_ok=True)
                    try:
                        if target_dirname not in self._mod_dirs_to_cleanup:
                            self._mod_dirs_to_cleanup.append(target_dirname)
                            self._update_session_manifest(mod_dirs=[target_dirname])
                    except Exception:
                        pass
                    if is_xdelta_mod and file_lower.endswith('.xdelta') and is_core_data_file:
                        if applied_xdelta_for_this_chapter:
                            continue
                        if not self._apply_xdelta_patch(cache_file_path, game_file_path, target_dir):
                            self.status_changed.emit(tr('errors.xdelta_apply_error', file=file), UI_COLORS['status_error'])
                            return False
                        files_copied += 1
                        applied_xdelta_for_this_chapter = True
                        continue
                    if file_lower.endswith('.xdelta'):
                        continue
                    if os.path.exists(game_file_path) and game_file_path not in self._backup_files:
                        unique_hash = hashlib.md5(game_file_path.encode('utf-8')).hexdigest()
                        backup_filename = f'{unique_hash}_{os.path.basename(game_file_path)}'
                        backup_file_path = os.path.join(self._backup_temp_dir, backup_filename)
                        os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)
                        shutil.move(game_file_path, backup_file_path)
                        self._backup_files[game_file_path] = backup_file_path
                        self._update_session_manifest(backup_files={game_file_path: backup_file_path})
                    if file_lower.endswith(('.zip', '.rar', '.7z', '.tar.gz', '.lzma')) and (not is_core_data_file):
                        extracted_files = self._extract_archive_to_target(cache_file_path, target_dir)
                        if extracted_files:
                            self._mod_files_to_cleanup.extend(extracted_files)
                            self._update_session_manifest(mod_files=extracted_files)
                        files_copied += 1
                    else:
                        shutil.copy2(cache_file_path, game_file_path)
                        files_copied += 1
                        self._mod_files_to_cleanup.append(game_file_path)
                        self._update_session_manifest(mod_files=[game_file_path])
                except Exception as e:
                    self.status_changed.emit(tr('errors.file_copy_error', file=file, error=str(e)), UI_COLORS['status_error'])
        if files_copied > 0:
            self.status_changed.emit(tr('status.files_copied_count', count=files_copied), UI_COLORS['status_info'])
        else:
            self.status_changed.emit(tr('status.no_files_to_copy'), UI_COLORS['status_warning'])
        return True

    def _apply_xdelta_patch(self, xdelta_file_path: str, target_game_file_path: str, target_dir: str) -> bool:
        xdelta_exe = get_xdelta_path()
        if not xdelta_exe:
            self.status_changed.emit(tr('errors.xdelta_not_found', path='xdelta'), UI_COLORS['status_error'])
            return False
        data_win = os.path.join(target_dir, 'data.win')
        game_ios = os.path.join(target_dir, 'game.ios')
        if platform.system() == 'Darwin':
            primary_file = game_ios
            secondary_file = data_win
        else:
            primary_file = data_win
            secondary_file = game_ios
        original_data_file = None
        if os.path.exists(primary_file):
            original_data_file = primary_file
        elif os.path.exists(secondary_file):
            original_data_file = secondary_file
        if not original_data_file:
            self.status_changed.emit(tr('errors.original_data_file_not_found', target_dir=target_dir), UI_COLORS['status_error'])
            return False
        if original_data_file not in self._backup_files:
            if not self._backup_temp_dir:
                self._backup_temp_dir = tempfile.mkdtemp(prefix='deltahub_backup_')
                self._update_session_manifest(backup_temp_dir=self._backup_temp_dir)
            unique_hash = hashlib.md5(original_data_file.encode('utf-8')).hexdigest()
            backup_filename = f'xdelta_{unique_hash}_{os.path.basename(original_data_file)}'
            backup_file_path = os.path.join(self._backup_temp_dir, backup_filename)
            shutil.copy2(original_data_file, backup_file_path)
            self._backup_files[original_data_file] = backup_file_path
            self._update_session_manifest(backup_files={original_data_file: backup_file_path})
        command = ['-d', '-f', '-s', self._backup_files[original_data_file], xdelta_file_path, original_data_file]
        try:
            command_to_run = [xdelta_exe] + command
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.run(command_to_run, capture_output=True, text=True, check=False, startupinfo=startupinfo, encoding='utf-8', errors='replace')
            if process.returncode == 0:
                self._mod_files_to_cleanup.append(original_data_file)
                self.status_changed.emit(tr('status.xdelta_patch_applied', patch_name=os.path.basename(xdelta_file_path)), UI_COLORS['status_success'])
                return True
            else:
                shutil.copy2(self._backup_files[original_data_file], original_data_file)
                error_message = process.stderr.strip() or process.stdout.strip()
                self.status_changed.emit(tr('errors.xdelta_patch_error', error=error_message), UI_COLORS['status_error'])
                return False
        except FileNotFoundError:
            self.status_changed.emit(tr('errors.xdelta_not_found', path=xdelta_exe), UI_COLORS['status_error'])
            return False
        except Exception as e:
            self.status_changed.emit(tr('errors.xdelta_patch_critical_error', error=str(e)), UI_COLORS['status_error'])
            try:
                shutil.copy2(self._backup_files[original_data_file], original_data_file)
            except Exception:
                pass
            return False

    def _extract_archive_to_target(self, archive_path: str, target_dir: str):
        file_lower = archive_path.lower()
        extracted_files = []
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub-extract-') as temp_dir:
                if file_lower.endswith('.zip'):
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        zf.extractall(temp_dir)
                elif file_lower.endswith('.rar'):
                    with rarfile.RarFile(archive_path, 'r') as rf:
                        rf.extractall(temp_dir)
                elif file_lower.endswith('.7z'):
                    with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                        zf.extractall(path=temp_dir)
                elif file_lower.endswith('.tar.gz'):
                    with tarfile.open(archive_path, 'r:gz') as tf:
                        tf.extractall(temp_dir)
                elif file_lower.endswith('.lzma'):
                    output_path = os.path.join(temp_dir, os.path.splitext(os.path.basename(archive_path))[0])
                    with lzma.open(archive_path) as f_in, open(output_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                else:
                    raise ValueError(f'Unsupported archive format for extraction: {archive_path}')
                from utils.file_utils import _cleanup_extracted_archive
                _cleanup_extracted_archive(temp_dir)
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        source_file = os.path.join(root, file)
                        rel_path = os.path.relpath(source_file, temp_dir)
                        target_file = os.path.join(target_dir, rel_path)
                        file_lower = file.lower()
                        if platform.system() == 'Darwin':
                            if file_lower.endswith('.win'):
                                name_without_ext = os.path.splitext(file)[0]
                                target_file = os.path.join(os.path.dirname(target_file), name_without_ext + '.ios')
                        elif file_lower.endswith('.ios'):
                            name_without_ext = os.path.splitext(file)[0]
                            target_file = os.path.join(os.path.dirname(target_file), name_without_ext + '.win')
                        target_dirname = os.path.dirname(target_file)
                        os.makedirs(target_dirname, exist_ok=True)
                        try:
                            if target_dirname not in self._mod_dirs_to_cleanup:
                                self._mod_dirs_to_cleanup.append(target_dirname)
                                self._update_session_manifest(mod_dirs=[target_dirname])
                        except Exception:
                            pass
                        if os.path.exists(target_file):
                            backup_rel_path = os.path.relpath(target_file, target_dir)
                            if self._backup_temp_dir:
                                backup_file_path = os.path.join(self._backup_temp_dir, backup_rel_path)
                                os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)
                                shutil.move(target_file, backup_file_path)
                                if not hasattr(self, '_backup_files'):
                                    self._backup_files = {}
                                self._backup_files[target_file] = backup_file_path
                                self._update_session_manifest(backup_files={target_file: backup_file_path})
                        shutil.copy2(source_file, target_file)
                        extracted_files.append(target_file)
        except Exception as e:
            self.status_changed.emit(tr('errors.archive_unpack_error', archive_name=os.path.basename(archive_path), error=str(e)), UI_COLORS['status_error'])
        return extracted_files

    def _cleanup_direct_launch_files(self):
        try:
            session_data = self._load_session_manifest()
            cleanup_info = session_data.get('direct_launch')
            if cleanup_info and cleanup_info.get('save_collection_swap'):
                collection_path = cleanup_info.get('collection_path')
                backup_path = cleanup_info.get('backup_path')
                current_save_path = self.app_state.save_path
                if not os.path.exists(current_save_path):
                    from utils.game_utils import get_default_save_path
                    current_save_path = self.app_state.local_config.get('save_path') or get_default_save_path()
                if collection_path and backup_path and os.path.exists(current_save_path):
                    if os.path.exists(collection_path):
                        shutil.rmtree(collection_path)
                    os.makedirs(collection_path)
                    import re
                    ignore_pattern = shutil.ignore_patterns('*_*_*')
                    shutil.copytree(current_save_path, collection_path, dirs_exist_ok=True, ignore=ignore_pattern)
                    for item in os.listdir(current_save_path):
                        item_path = os.path.join(current_save_path, item)
                        if not (os.path.isdir(item_path) and re.match('(.+?)_(\\d+)_(\\d+)$', item)):
                            if os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                            else:
                                os.remove(item_path)
                    if os.path.exists(backup_path):
                        shutil.copytree(backup_path, current_save_path, dirs_exist_ok=True)
                        shutil.rmtree(backup_path)
            backed_up_targets = set(self._backup_files.keys()) if self._backup_files else set()
            if self._backup_files:
                for original_path, backup_path in self._backup_files.items():
                    try:
                        if os.path.exists(backup_path):
                            if os.path.exists(original_path):
                                os.remove(original_path)
                            os.makedirs(os.path.dirname(original_path), exist_ok=True)
                            shutil.move(backup_path, original_path)
                    except Exception:
                        continue
                self._backup_files = {}
            if self._mod_files_to_cleanup:
                remaining_files = []
                for file_path in self._mod_files_to_cleanup:
                    if file_path in backed_up_targets:
                        continue
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        else:
                            remaining_files.append(file_path)
                    except Exception:
                        continue
                self._mod_files_to_cleanup = []
            if self._backup_temp_dir and os.path.exists(self._backup_temp_dir):
                try:
                    shutil.rmtree(self._backup_temp_dir)
                    self._backup_temp_dir = None
                except Exception:
                    pass
            try:
                dirs = []
                if self._mod_dirs_to_cleanup:
                    dirs = sorted(set(self._mod_dirs_to_cleanup), key=lambda p: len(p.split(os.sep)), reverse=True)
                else:
                    data = self._load_session_manifest() or {}
                    dirs = sorted(set(data.get('mod_dirs_to_cleanup', [])), key=lambda p: len(p.split(os.sep)), reverse=True)
                for d in dirs:
                    try:
                        if os.path.isdir(d) and (not os.listdir(d)):
                            os.rmdir(d)
                    except Exception:
                        pass
                self._mod_dirs_to_cleanup = []
            except Exception:
                pass
            if not cleanup_info:
                cleanup_info = self._direct_launch_cleanup_info
            if cleanup_info:
                if 'target_exe' in cleanup_info and os.path.exists(cleanup_info['target_exe']):
                    os.remove(cleanup_info['target_exe'])
                self._direct_launch_cleanup_info = None
            self.status_changed.emit(tr('status.files_restored'), UI_COLORS['status_success'])
            self._clear_session_manifest()
        except Exception as e:
            self.status_changed.emit(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])

    def _session_manifest_path(self):
        return os.path.join(self.app_state.config_dir, 'session.lock')

    def _load_session_manifest(self) -> dict:
        try:
            with open(self._session_manifest_path(), 'r', encoding='utf-8') as f:
                import json
                return json.load(f) or {}
        except Exception:
            return {}

    def _write_session_manifest(self, data: dict):
        try:
            with open(self._session_manifest_path(), 'w', encoding='utf-8') as f:
                import json
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _ensure_session_manifest(self) -> dict:
        data = self._load_session_manifest()
        if not data:
            data = {'backup_files': {}, 'mod_files_to_cleanup': [], 'mod_dirs_to_cleanup': [], 'backup_temp_dir': None, 'direct_launch': None}
            self._write_session_manifest(data)
        return data

    def _update_session_manifest(self, backup_files: Optional[dict]=None, mod_files: Optional[list]=None, backup_temp_dir: Optional[str]=None, direct_launch: Optional[dict]=None, mod_dirs: Optional[list]=None):
        data = self._ensure_session_manifest()
        if backup_files:
            data.setdefault('backup_files', {}).update(backup_files)
        if mod_files:
            existing = set(data.get('mod_files_to_cleanup', []))
            for p in mod_files:
                if p not in existing:
                    data.setdefault('mod_files_to_cleanup', []).append(p)
        if mod_dirs:
            existing_dirs = set(data.get('mod_dirs_to_cleanup', []))
            for d in mod_dirs:
                if d not in existing_dirs:
                    data.setdefault('mod_dirs_to_cleanup', []).append(d)
        if backup_temp_dir is not None:
            data['backup_temp_dir'] = backup_temp_dir
        if direct_launch is not None:
            data['direct_launch'] = direct_launch
        self._write_session_manifest(data)

    def _clear_session_manifest(self):
        try:
            os.remove(self._session_manifest_path())
        except Exception:
            pass

    def recover_previous_session(self):
        try:
            data = self._load_session_manifest()
            if not data:
                return
            self._backup_files = data.get('backup_files', {})
            self._mod_files_to_cleanup = data.get('mod_files_to_cleanup', [])
            self._backup_temp_dir = data.get('backup_temp_dir')
            self._direct_launch_cleanup_info = data.get('direct_launch')
            self.feedback_manager.update_status(tr('status.recovering_previous_session'), UI_COLORS['status_warning'])
            self._cleanup_direct_launch_files()
            self._clear_session_manifest()
        except Exception:
            pass

    def _find_and_validate_game_path(self, selections: Optional[Dict[int, str]]=None, is_initial: bool=False):
        from utils.game_utils import is_valid_game_path
        from utils.file_utils import autodetect_path
        path_from_config = self._get_current_game_path()
        skip_data_check = bool(selections and self._has_mods_with_data_files(selections)) if selections else False
        if isinstance(self.app_state.game_mode, DemoGameMode):
            game_type = 'deltarune'
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            game_type = 'undertale'
        else:
            game_type = 'deltarune'
        if is_valid_game_path(path_from_config, skip_data_check, game_type):
            self.status_changed.emit(tr('status.game_path', path=path_from_config), UI_COLORS['status_info'])
            return True
        self.status_changed.emit(tr('status.autodetecting_path'), UI_COLORS['status_info'])
        if isinstance(self.app_state.game_mode, DemoGameMode):
            game_name = 'DELTARUNEdemo'
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            game_name = 'UNDERTALE'
        else:
            game_name = 'DELTARUNE'
        autodetected_path = autodetect_path(game_name)
        if autodetected_path and is_valid_game_path(autodetected_path, skip_data_check, game_type):
            self.app_state.game_mode.set_game_path(self.app_state.local_config, autodetected_path)
            self.status_changed.emit(tr('status.game_folder_found', path=autodetected_path), UI_COLORS['status_success'])
            return True
        if is_initial:
            self.status_changed.emit(tr('status.no_game_path'), UI_COLORS['status_error'])
        return False

    def _has_mods_with_data_files(self, selections: Dict[int, str]) -> bool:
        for ui_index, mod_key in selections.items():
            if mod_key == 'no_change':
                continue
            mod = next((m for m in self.app_state.all_mods if m.key == mod_key), None)
            if not mod:
                continue
            chapter_id = self.app_state.game_mode.get_chapter_id(ui_index)
            if mod_key.startswith('local_'):
                mod_config = self.mod_manager.get_mod_config(mod_key)
                if mod_config:
                    chapter_files = mod_config.get('files', {}).get(str(chapter_id), {})
                    if chapter_files.get('data_file_url'):
                        return True
            else:
                chapter_data = mod.get_chapter_data(chapter_id)
                if chapter_data and hasattr(chapter_data, 'data_file_url') and chapter_data.data_file_url:
                    return True
        return False
