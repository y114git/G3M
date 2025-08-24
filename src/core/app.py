import base64
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
import ctypes
import subprocess
import webbrowser
import rarfile
import argparse
import hashlib
from typing import Callable, Optional, List, Dict, Any
import logging
from pathlib import Path
import requests
from PyQt6.QtCore import Qt, QEvent, QEventLoop, QThread, QTimer, QUrl, pyqtSignal, QTranslator
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QMovie, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QInputDialog, QColorDialog, QListWidget, QScrollArea
from localization.manager import get_localization_manager, tr
from models.game_modes import GameMode
from config.constants import LAUNCHER_VERSION, UI_COLORS, SOCIAL_LINKS, THEMES, SAVE_SLOT_FINISH_MAP, DEFAULT_FONT_FALLBACK_CHAIN, ARCH
from models.mod_models import ModInfo, ModChapterData
from models.game_modes import FullGameMode, DemoGameMode, UndertaleGameMode
from utils.file_utils import autodetect_path, resource_path, get_file_filter, sanitize_filename, ensure_writable, fix_macos_python_symlink
from utils.game_utils import is_game_running, get_default_save_path, is_valid_save_path, is_valid_game_path
from utils.path_utils import get_user_data_root, get_launcher_dir, get_legacy_ylauncher_path
from utils.network_utils import check_internet_connection
from threads.fetch_mods import FetchModsThread
from threads.game_monitor import GameMonitorThread
from threads.background_workers import PresenceWorker, FetchChangelogThread, BgLoader, FullInstallThread, InstallModsThread
from ui.styling import get_theme_color, clear_layout_widgets, load_mod_icon_universal, show_empty_message_in_layout
from ui.widgets.custom_controls import NoScrollComboBox, NoScrollTabWidget, ClickableLabel, SlotFrame
from ui.widgets.outlined_label import OutlinedTextLabel
from ui.components.screenshots_carousel import ScreenshotsCarousel
from ui.widgets.mod_plaque_widget import ModPlaqueWidget
from ui.widgets.installed_mod_widget import InstalledModWidget
from ui.dialogs.xdelta_dialog import XdeltaDialog
from ui.dialogs.save_editor import SaveEditorDialog
from ui.dialogs.mod_editor import ModEditorDialog
_translator = QTranslator()
_lock_file = None
_splash_start_time = None
_player, _audio_output = (None, None)
_sound_instance = None


def get_xdelta_path():
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    xdelta_exe = 'xdelta3.exe' if platform.system() == 'Windows' else 'xdelta3'
    xdelta_path = os.path.join(application_path, 'resources', 'bin', xdelta_exe)
    if not os.path.exists(xdelta_path) and platform.system() != 'Windows':
        xdelta_path_fallback = os.path.join(application_path, 'resources', 'bin', 'xdelta3.exe')
        if os.path.exists(xdelta_path_fallback):
            xdelta_path = xdelta_path_fallback
    if platform.system() != 'Windows' and os.path.exists(xdelta_path) and (not xdelta_path.lower().endswith('.exe')):
        try:
            os.chmod(xdelta_path, 493)
        except Exception as e:
            logging.warning(f'Could not set executable permission on {xdelta_path}: {e}')
    return os.path.normpath(xdelta_path)


class DeltaHubApp(QWidget):
    update_status_signal = pyqtSignal(str, str)
    set_progress_signal = pyqtSignal(int)
    show_update_prompt = pyqtSignal(dict)
    initialization_finished = pyqtSignal()
    hide_window_signal = pyqtSignal()
    quit_signal = pyqtSignal()
    restore_window_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    mods_loaded_signal = pyqtSignal()
    update_info_ready = pyqtSignal(dict)
    update_cleanup = pyqtSignal()

    def __init__(self, args: Optional[argparse.Namespace] = None, parent_for_dialogs: Optional[QWidget] = None):
        super().__init__()
        self.is_shortcut_launch = args and args.shortcut_launch
        self.dialog_parent = parent_for_dialogs or self
        self.session_id = uuid.uuid4().hex
        self._init_session()
        self.presence_thread = None
        self.presence_worker = None
        self._direct_launch_cleanup_info = None
        self._online_timer = QTimer(self)
        self._online_timer.timeout.connect(self._run_presence_tick)
        self._online_timer.start(30000)
        if self.is_shortcut_launch:
            self._shortcut_launch(args)
            return
        QTimer.singleShot(0, self._run_presence_tick)
        self.setWindowTitle('DELTAHUB')
        self._supports_volume = platform.system() == 'Windows'
        self._initial_size = None
        self.config_dir = os.path.join(get_user_data_root(), 'cache')
        self.launcher_dir = get_launcher_dir()
        from utils.path_utils import get_user_mods_dir
        self.mods_dir = get_user_mods_dir()
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.mods_dir, exist_ok=True)
        self.config_path = os.path.join(self.config_dir, 'config.json')
        self.local_config = self._read_json(self.config_path) or {}
        self._recover_previous_session()
        self._init_localization()
        self.save_path: str = ''
        self.is_save_manager_view: bool = False
        self.current_collection_idx: Dict[int, int] = {}
        self.selected_slot: Optional[tuple[int, int]] = None
        self.resize(875, 750)
        self._initial_size = self.size()
        self.background_movie = None
        self.background_pixmap: Optional[QPixmap] = None
        self.custom_font_family = None
        self.game_path = ''
        self.demo_game_path = ''
        self.translations_by_chapter = {i: [] for i in range(5)}
        self.all_mods: List[ModInfo] = []
        self.is_settings_view = False
        self.current_mode = 'normal'
        self.slots = {}
        self.update_in_progress = False
        self.is_changelog_view = False
        self.is_help_view = False
        self.monitor_thread: Optional[GameMonitorThread] = None
        self.is_full_install = False
        self.global_settings: Dict[str, Any] = {}
        self.current_settings_page: Optional[QWidget] = None
        self.settings_nav_stack: list[QWidget] = []
        self.mods_loaded = False
        self.initialization_timer = None
        self.initialization_completed = False
        self.is_shown_to_user = False
        self._bg_music_running = False
        self._bg_music_thread = None
        self.game_mode: GameMode = FullGameMode()
        self.init_ui()
        self.load_font()
        QTimer.singleShot(100, self._perform_initial_setup)
        self.update_status_signal.connect(self._update_status)
        self.hide_window_signal.connect(self._hide_window_for_game)
        self.restore_window_signal.connect(self._restore_window_after_game)
        self.set_progress_signal.connect(self.progress_bar.setValue)
        self.show_update_prompt.connect(self._prompt_for_update)
        self.error_signal.connect(lambda msg: QMessageBox.critical(self, tr('errors.error'), msg))
        self.quit_signal.connect(QApplication.quit)
        self.mods_loaded_signal.connect(self._on_mods_loaded)
        self.update_info_ready.connect(self._handle_update_info)
        self.update_cleanup.connect(self._on_update_cleanup)
        self._legacy_cleanup_done = False
        QTimer.singleShot(1000, self._maybe_run_legacy_cleanup)
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(5000)
        if (saved := self.local_config.get('window_geometry')):
            from PyQt6.QtCore import QByteArray
            try:
                self.restoreGeometry(QByteArray.fromHex(saved.encode()))
            except Exception:
                pass

    def _init_session(self):
        try:
            import requests
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat', json={'sessionId': self.session_id}, timeout=5)
        except Exception:
            pass

    def _session_manifest_path(self):
        return os.path.join(self.config_dir, 'session.lock')

    def _load_session_manifest(self) -> dict:
        try:
            with open(self._session_manifest_path(), 'r', encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _write_session_manifest(self, data: dict):
        try:
            with open(self._session_manifest_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _ensure_session_manifest(self) -> dict:
        data = self._load_session_manifest()
        if not data:
            data = {'backup_files': {}, 'mod_files_to_cleanup': [], 'mod_dirs_to_cleanup': [], 'backup_temp_dir': None, 'direct_launch': None}
            self._write_session_manifest(data)
        return data

    def _update_session_manifest(self, backup_files: Optional[dict] = None, mod_files: Optional[list] = None, backup_temp_dir: Optional[str] = None, direct_launch: Optional[dict] = None, mod_dirs: Optional[list] = None):
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

    def _recover_previous_session(self):
        try:
            data = self._load_session_manifest()
            if not data:
                return
            self._backup_files = data.get('backup_files', {})
            self._mod_files_to_cleanup = data.get('mod_files_to_cleanup', [])
            self._backup_temp_dir = data.get('backup_temp_dir')
            self._direct_launch_cleanup_info = data.get('direct_launch')
            self.update_status_signal.emit(tr('status.recovering_previous_session'), UI_COLORS['status_warning'])
            self._cleanup_direct_launch_files()
            self._clear_session_manifest()
        except Exception:
            pass

    def _shortcut_launch(self, args):
        try:
            settings_json = base64.b64decode(args.shortcut_launch).decode('utf-8')
            settings = json.loads(settings_json)
        except Exception as e:
            print(tr('startup.shortcut_settings_read_error', error=str(e)))
            sys.exit(1)
        self._load_local_data()
        self._load_local_mods_from_folders()
        try:
            if settings.get('is_undertale_mode', False):
                self.game_mode = UndertaleGameMode()
            else:
                self.game_mode = DemoGameMode() if settings.get('is_demo_mode', False) else FullGameMode()
            self.game_path = settings.get('game_path', '')
            self.demo_game_path = settings.get('demo_game_path', '')
            launch_via_steam = settings.get('launch_via_steam', False)
            use_custom_executable = settings.get('use_custom_executable', False)
            custom_exec_path = settings.get('custom_executable_path', '')
            demo_custom_exec_path = settings.get('demo_custom_executable_path', '')
            direct_launch_slot_id = settings.get('direct_launch_slot_id', -1)
            current_game_path = self._get_current_game_path()
            if not current_game_path or not os.path.exists(current_game_path):
                print(tr('errors.game_files_launch_not_found'))
                sys.exit(1)
            mods_settings = settings.get('mods', {})
            if not mods_settings:
                mods_settings = settings.get('selections', {})
            self._apply_shortcut_mods(mods_settings)
            self._launch_game_from_shortcut(launch_via_steam=launch_via_steam, use_custom_executable=use_custom_executable, custom_exec_path=custom_exec_path, demo_custom_exec_path=demo_custom_exec_path, direct_launch_slot_id=direct_launch_slot_id)
        except Exception as e:
            print(tr('startup.launch_error', error=str(e)))
            sys.exit(1)

    def _create_shortcut_flow(self):
        settings = self._gather_shortcut_settings()
        if not settings:
            QMessageBox.warning(self, tr('dialogs.cannot_create_shortcut_title'), tr('dialogs.path_not_specified'))
            return
        description_lines = [tr('dialogs.shortcut_description'), '', tr('dialogs.current_shortcut_settings'), '']
        game_name = tr('ui.undertale_label') if settings.get('is_undertale_mode', False) else tr('ui.deltarunedemo_label') if settings.get('is_demo_mode', False) else tr('ui.deltarune_label')
        description_lines.append(f"<b>{tr('ui.mod_type_label')}</b> {game_name}")
        if settings.get('is_demo_mode', False):
            mod_key = settings['mods'].get('demo')
            if mod_key:
                mod_config = self._get_mod_config_by_key(mod_key)
                mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        elif settings.get('is_undertale_mode', False):
            mod_key = settings['mods'].get('undertale')
            if mod_key:
                mod_config = self._get_mod_config_by_key(mod_key)
                mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        else:
            is_chapter_mode = settings.get('is_chapter_mode', False)
            direct_launch_slot_id = settings.get('direct_launch_slot_id', -1)
            if is_chapter_mode:
                if direct_launch_slot_id >= 0:
                    chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                    chapter_name = chapter_names.get(direct_launch_slot_id, tr('ui.chapter_tab_title', chapter_num=direct_launch_slot_id))
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {chapter_name}")
                    mod_key = settings['mods'].get(str(direct_launch_slot_id))
                    if mod_key:
                        mod_config = self._get_mod_config_by_key(mod_key)
                        mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                        description_lines.append(f"<b>{tr('status.mod_for_chapter_label', chapter_name=chapter_name)}</b> {mod_name}")
                    else:
                        description_lines.append(f"<b>{tr('status.mod_for_chapter_label', chapter_name=chapter_name)}</b> <i>{tr('status.no_mod')}</i>")
                else:
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {tr('status.disabled')}")
                    for chapter_id in [0, 1, 2, 3, 4]:
                        mod_key = settings['mods'].get(str(chapter_id))
                        if mod_key:
                            mod_config = self._get_mod_config_by_key(mod_key)
                            mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                            chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                            chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_tab_title', chapter_num=chapter_id))
                            description_lines.append(f'<b>{chapter_name}:</b> {mod_name}')
            else:
                uni_key = settings['mods'].get('universal')
                if uni_key:
                    mod_config = self._get_mod_config_by_key(uni_key)
                    mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=uni_key)) if mod_config else tr('errors.mod_not_found', mod_key=uni_key)
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
                else:
                    description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.no_mod')}</i>")
        description_lines.append('')
        if settings.get('launch_via_steam'):
            description_lines.append(f"✓ {tr('status.steam_launch')}")
        elif settings.get('use_custom_executable'):
            custom_path = settings.get('custom_executable_path', '') or settings.get('demo_custom_executable_path', '')
            exe_name = os.path.basename(custom_path) if custom_path else '?'
            description_lines.append(f"✓ {tr('status.custom_executable_launch', exe_name=exe_name)}")
        else:
            description_lines.append(f"✓ {tr('status.normal_launch')}")
        msg = QMessageBox(self)
        msg.setWindowTitle(tr('dialogs.create_shortcut_question'))
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText('<br>'.join(description_lines) + f"<br><br><p>{tr('dialogs.shortcut_create_description')}</p>")
        msg.exec()
        reply = msg.standardButton(msg.clickedButton())
        if reply == QMessageBox.StandardButton.Yes:
            self._save_shortcut(settings)

    def _load_local_mods_from_folders(self):
        if not os.path.exists(self.mods_dir):
            return False
        installed_mods = {}
        try:
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    config_data = self._read_json(config_path)
                    if not config_data:
                        continue
                    mod_key = config_data.get('mod_key')
                    if mod_key:
                        installed_mods[mod_key] = config_data
                except Exception:
                    continue
            for mod in self.all_mods:
                if mod.key in installed_mods:
                    config_data = installed_mods[mod.key]
                    config_path = None
                    for folder_name in os.listdir(self.mods_dir):
                        folder_path = os.path.join(self.mods_dir, folder_name)
                        test_config_path = os.path.join(folder_path, 'config.json')
                        if os.path.isfile(test_config_path):
                            try:
                                test_config = self._read_json(test_config_path)
                                if test_config.get('mod_key') == mod.key:
                                    config_path = test_config_path
                                    break
                            except Exception as e:
                                logging.warning(f'Failed reading config {test_config_path}: {e}')
                                continue
                    if config_path:
                        config_data.get('is_available_on_server', False)
            existing_keys = {mod.key for mod in self.all_mods}
            for mod_key, config_data in installed_mods.items():
                if mod_key not in existing_keys and config_data.get('is_local_mod'):
                    try:
                        safe_mod_info = {'key': mod_key, 'name': config_data.get('name', tr('defaults.local_mod')), 'version': config_data.get('version', '1.0.0'), 'author': config_data.get('author', tr('defaults.unknown')), 'tagline': config_data.get('tagline', tr('defaults.no_description')), 'game_version': config_data.get('game_version', tr('defaults.not_specified')), 'description_url': '', 'downloads': 0, 'modtype': config_data.get('modtype', 'deltarune'), 'is_verified': False, 'icon_url': '', 'tags': ['local'], 'hide_mod': False, 'is_xdelta': False, 'ban_status': False, 'demo_url': None, 'demo_version': '1.0.0', 'created_date': config_data.get('created_date', 'N/A'), 'last_updated': config_data.get('created_date', 'N/A')}
                        mod = ModInfo(**safe_mod_info)
                        files_data = config_data.get('files', {})
                        mod_folder_path = None
                        for folder_name in os.listdir(self.mods_dir):
                            folder_path = os.path.join(self.mods_dir, folder_name)
                            test_config_path = os.path.join(folder_path, 'config.json')
                            if os.path.isfile(test_config_path):
                                try:
                                    test_config = self._read_json(test_config_path)
                                    if test_config.get('mod_key') == mod_key:
                                        mod_folder_path = folder_path
                                        break
                                except Exception as e:
                                    logging.warning(f'Failed reading config {test_config_path}: {e}')
                                    continue
                        for file_key, ch_info in files_data.items():
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
                                for group_key, filenames in chapter_files['extra_files'].items():
                                    for filename in filenames:
                                        file_path = os.path.join(chapter_folder, filename)
                                        extra_files.append(ModExtraFile(key=group_key, url=file_path, version='1.0.0'))
                            mod_chapter = ModChapterData(description=config_data.get('tagline', ''), data_file_url=data_file_url, data_file_version=chapter_files.get('data_file_version', (ch_info.get('versions', {}) or {}).get('data', '1.0.0')), extra_files=extra_files)
                            mod.files[file_key] = mod_chapter
                        if mod.files:
                            self.all_mods.append(mod)
                    except Exception as e:
                        logging.warning(f'Failed to build local ModInfo: {e}')
                        continue
            return True
        except Exception as e:
            logging.error(f'_load_local_mods_from_folders failed: {e}')
            return False

    def _get_mod_config_by_key(self, mod_key: str) -> dict:
        if not os.path.exists(self.mods_dir):
            return {}
        for folder_name in os.listdir(self.mods_dir):
            folder_path = os.path.join(self.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if not os.path.exists(config_path):
                continue
            try:
                config_data = self._read_json(config_path)
                if config_data and config_data.get('mod_key') == mod_key:
                    return config_data
            except Exception as e:
                logging.warning(f'Failed to read mod config {config_path}: {e}')
                continue
        return {}

    def _set_install_buttons_enabled(self, enabled: bool):
        if hasattr(self, 'mod_list_layout'):
            for i in range(self.mod_list_layout.count() - 1):
                item = self.mod_list_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, ModPlaqueWidget):
                        widget.install_button.setEnabled(enabled)
        if hasattr(self, 'installed_mods_layout'):
            for i in range(self.installed_mods_layout.count() - 1):
                item = self.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget) and hasattr(widget, 'use_button') and widget.use_button:
                        widget.use_button.setEnabled(enabled)

    def _create_settings_nav_button(self, text: str, on_click: Callable, style_sheet: str = '', fixed_width: int = 400) -> QPushButton:
        button = QPushButton(text)
        button.setFixedWidth(fixed_width)
        base_style = f'width: {fixed_width}px;'
        button.setStyleSheet(f'{base_style} {style_sheet}' if style_sheet else base_style)
        if on_click:
            button.clicked.connect(on_click)
        return button

    def _handle_permission_error(self, path: str):
        detailed_message = tr('dialogs.access_denied_detailed', path=path)
        QMessageBox.critical(self, tr('errors.access_denied'), detailed_message)

    def _get_current_game_path(self) -> str:
        return self.game_mode.get_game_path(self.local_config) or ''

    def _current_tab_names(self):
        return self.game_mode.tab_names

    def init_ui(self):
        self.full_install_checkbox = QCheckBox(tr('ui.install_game_files_first'))
        self.full_install_checkbox.stateChanged.connect(self._on_toggle_full_install)
        self.full_install_checkbox.hide()
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.top_panel_widget = QFrame()
        self.top_frame = QHBoxLayout(self.top_panel_widget)
        self.settings_button = QPushButton(tr('ui.settings_title'))
        self.settings_button.clicked.connect(self._toggle_settings_view)
        self.online_label = QLabel(tr('ui.online_status'))
        self.online_label.setStyleSheet('padding-left:8px;')
        self.online_label.setToolTip(tr('tooltips.online_counter'))
        self.top_frame.addWidget(self.settings_button)
        self.top_refresh_button = QPushButton('🔄️')
        self.top_refresh_button.setObjectName('topRefreshBtn')
        self.top_refresh_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.top_refresh_button.setMinimumSize(40, 40)
        self.top_refresh_button.setMaximumSize(40, 40)
        self.top_refresh_button.setStyleSheet('min-width:40px; max-width:40px; min-height:40px; max-height:40px; padding:0; margin:0;')
        self.top_refresh_button.setToolTip(tr('ui.update_mod_list'))
        self.top_refresh_button.clicked.connect(lambda: self._refresh_mods_list(force=True))
        self.top_frame.addWidget(self.top_refresh_button)
        self.top_frame.addWidget(self.online_label)
        self.top_frame.addStretch()
        logo_placeholder = QWidget()
        logo_placeholder.setFixedWidth(225)
        self.top_frame.addWidget(logo_placeholder)
        self.top_frame.addStretch()
        self.telegram_button = QPushButton(tr('buttons.telegram'))
        self.telegram_button.clicked.connect(lambda: webbrowser.open(self.global_settings.get('telegram_url', SOCIAL_LINKS['telegram'])))
        self.telegram_button.setStyleSheet(f"color: {UI_COLORS['link']};")
        self.top_frame.addWidget(self.telegram_button)
        self.discord_button = QPushButton(tr('buttons.discord'))
        self.discord_button.clicked.connect(lambda: webbrowser.open(self.global_settings.get('discord_url', SOCIAL_LINKS['discord'])))
        self.discord_button.setStyleSheet(f"color: {UI_COLORS['social_discord']};")
        self.top_frame.addWidget(self.discord_button)
        self.main_layout.addWidget(self.top_panel_widget)
        self.launcher_icon_label = QLabel(self.top_panel_widget)
        self.launcher_icon_label.setFixedSize(225, 80)
        self.launcher_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_launcher_icon()
        self.bottom_widget = QFrame()
        self.bottom_widget.setObjectName('bottom_widget')
        self.bottom_frame = QVBoxLayout(self.bottom_widget)
        self.status_label = QLabel(tr('ui.initialization'))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.action_frame = QHBoxLayout()
        self.shortcut_button = QPushButton(tr('buttons.shortcut'))
        self.shortcut_button.clicked.connect(self._create_shortcut_flow)
        self.action_button = QPushButton(tr('status.please_wait'))
        self.action_button.setEnabled(False)
        self.action_button.setMinimumWidth(200)
        self.action_button.clicked.connect(self._on_action_button_click)
        self.is_installing = False
        self.current_install_thread = None
        self.pending_updates = []
        self.saves_button = QPushButton(tr('ui.saves_button'))
        self.saves_button.setStyleSheet('color: yellow;')
        self.saves_button.clicked.connect(self._on_configure_saves_click)
        self.action_frame.addWidget(self.shortcut_button)
        self.action_frame.addWidget(self.action_button)
        self.action_frame.addWidget(self.saves_button)
        self.bottom_frame.addWidget(self.status_label)
        self.bottom_frame.addWidget(self.progress_bar)
        self.bottom_frame.addLayout(self.action_frame)
        self.main_layout.addSpacing(20)
        self.main_tab_widget = NoScrollTabWidget()
        self.main_tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.search_mods_tab = self._create_search_mods_tab()
        self.library_tab = self._create_library_tab()
        self.manage_mods_tab = QWidget()
        self.xdelta_patch_tab = QWidget()
        self.main_tab_widget.addTab(self.search_mods_tab, tr('ui.search_tab'))
        self.main_tab_widget.addTab(self.library_tab, tr('ui.library_tab'))
        self.main_tab_widget.addTab(self.manage_mods_tab, tr('ui.mod_management'))
        self.main_tab_widget.addTab(self.xdelta_patch_tab, tr('ui.patching_tab'))
        self.previous_tab_index = 0
        self.main_tab_widget.currentChanged.connect(self._on_tab_changed)
        self.main_tab_widget.setStyleSheet('\n            QTabWidget::tab-bar {\n                alignment: center;\n            }\n            QTabBar::tab {\n                min-width: 120px;\n                padding: 8px 16px;\n            }\n        ')
        self.main_layout.addWidget(self.main_tab_widget)
        self.main_layout.addWidget(self.bottom_widget)
        self.settings_widget = QFrame()
        self.settings_widget.setObjectName('settings_widget')
        settings_layout = QVBoxLayout(self.settings_widget)
        self.settings_pages_container = QWidget()
        pages_layout = QVBoxLayout(self.settings_pages_container)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_customization_page = QWidget()
        self.settings_menu_page = QWidget()
        settings_menu_layout = QVBoxLayout(self.settings_menu_page)
        settings_menu_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_menu_layout.setSpacing(20)
        settings_title_label = QLabel(f"<h1>{tr('ui.settings_title')}</h1>")
        settings_title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        settings_menu_layout.addWidget(settings_title_label)
        settings_menu_layout.addStretch()
        settings_center_container = QVBoxLayout()
        settings_center_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_center_container.setSpacing(20)
        language_container = QWidget()
        language_layout = QHBoxLayout(language_container)
        language_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        language_layout.setSpacing(10)
        language_label = QLabel(tr('ui.language_label'))
        language_label.setStyleSheet('font-size: 20px; font-weight: bold;')
        language_layout.addWidget(language_label)
        self.language_combo = NoScrollComboBox()
        self.language_combo.setMinimumWidth(200)
        self.language_combo.setMaximumWidth(250)
        manager = get_localization_manager()
        available_languages = manager.get_available_languages()
        current_language = manager.get_current_language()
        for code, name in available_languages.items():
            self.language_combo.addItem(name, code)
            if code == current_language:
                self.language_combo.setCurrentIndex(self.language_combo.count() - 1)
        self.language_combo.currentTextChanged.connect(self._on_language_changed)
        language_layout.addWidget(self.language_combo)
        settings_center_container.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        settings_center_container.addSpacing(30)
        self.launch_via_steam_checkbox = QCheckBox(tr('ui.steam_launch'))
        self.launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>')
        self.launch_via_steam_checkbox.stateChanged.connect(self._on_toggle_steam_launch)
        settings_center_container.addWidget(self.launch_via_steam_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.use_custom_executable_checkbox = QCheckBox(tr('ui.custom_executable'))
        self.use_custom_executable_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.custom_exe') + '</body></html>')
        self.use_custom_executable_checkbox.stateChanged.connect(self._on_toggle_custom_executable)
        settings_center_container.addWidget(self.use_custom_executable_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.select_custom_executable_button = QPushButton(tr('buttons.select_file'))
        self.select_custom_executable_button.setFixedWidth(153)
        self.select_custom_executable_button.clicked.connect(self._select_custom_executable_file)
        self.custom_executable_path_label = QLabel(tr('ui.file_not_selected'))
        self.custom_executable_path_label.setFixedHeight(20)
        self.custom_exe_frame = QFrame()
        custom_exe_layout = QVBoxLayout(self.custom_exe_frame)
        custom_exe_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        custom_exe_layout.addWidget(self.select_custom_executable_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        custom_exe_layout.addWidget(self.custom_executable_path_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        settings_center_container.addWidget(self.custom_exe_frame, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.custom_exe_frame.setVisible(False)
        self.change_path_button = QPushButton()
        self.change_path_button.setFixedWidth(300)
        self.change_path_button.clicked.connect(self._prompt_for_game_path)
        settings_center_container.addWidget(self.change_path_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.change_mods_dir_button = QPushButton(tr('ui.change_mods_dir'))
        self.change_mods_dir_button.setFixedWidth(400)
        self.change_mods_dir_button.setToolTip(tr('tooltips.change_mods_dir'))
        self.change_mods_dir_button.clicked.connect(self._prompt_for_mods_dir)
        settings_center_container.addWidget(self.change_mods_dir_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        customization_button = self._create_settings_nav_button(tr('ui.launcher_customization'), lambda: self._switch_settings_page(self.settings_customization_page), fixed_width=200)
        reset_button = self._create_settings_nav_button(tr('buttons.reset_settings'), self._on_reset_settings_click, fixed_width=200)

        buttons_layout = QHBoxLayout()
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons_layout.setSpacing(10)
        buttons_layout.addWidget(customization_button)
        buttons_layout.addWidget(reset_button)

        settings_center_container.addLayout(buttons_layout)

        self.settings_customization_button = customization_button
        settings_menu_layout.addLayout(settings_center_container)
        settings_menu_layout.addStretch()
        pages_layout.addWidget(self.settings_menu_page)
        self.disable_background_checkbox = QCheckBox(tr('checkboxes.disable_background'))
        self.disable_background_checkbox.stateChanged.connect(self._on_toggle_disable_background)
        self.disable_splash_checkbox = QCheckBox(tr('checkboxes.disable_splash'))
        self.disable_splash_checkbox.stateChanged.connect(self._on_toggle_disable_splash)
        self.change_background_button = QPushButton(tr('buttons.change_background'))
        self.change_background_button.clicked.connect(self._on_background_button_click)
        settings_customization_layout = QVBoxLayout(self.settings_customization_page)
        back_button_cust = QPushButton(tr('ui.back_button'))
        back_button_cust.clicked.connect(self._go_back)
        settings_customization_layout.addWidget(back_button_cust, alignment=Qt.AlignmentFlag.AlignLeft)
        settings_customization_layout.addSpacing(15)
        self.change_background_button = QPushButton()
        self.change_background_button.setFixedWidth(400)
        self.change_background_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.change_background_button.clicked.connect(self._on_background_button_click)
        settings_customization_layout.addWidget(self.change_background_button, 0, Qt.AlignmentFlag.AlignHCenter)
        settings_customization_layout.addSpacing(8)
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)
        self.background_music_button = QPushButton(self._get_background_music_button_text())
        self.background_music_button.setFixedWidth(275)
        self.background_music_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.background_music_button.clicked.connect(self._on_background_music_button_click)
        sound_buttons_layout.addWidget(self.background_music_button)
        self.startup_sound_button = QPushButton(self._get_startup_sound_button_text())
        self.startup_sound_button.setFixedWidth(275)
        self.startup_sound_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.startup_sound_button.clicked.connect(self._on_startup_sound_button_click)
        sound_buttons_layout.addWidget(self.startup_sound_button)
        settings_customization_layout.addLayout(sound_buttons_layout)
        settings_customization_layout.addSpacing(20)
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkboxes_layout.setSpacing(20)
        checkboxes_layout.addWidget(self.disable_background_checkbox)
        checkboxes_layout.addWidget(self.disable_splash_checkbox)
        settings_customization_layout.addLayout(checkboxes_layout)
        settings_customization_layout.addSpacing(8)
        self.custom_style_frame = QFrame()
        custom_style_layout = QVBoxLayout(self.custom_style_frame)
        custom_style_layout.setContentsMargins(0, 15, 0, 0)
        custom_style_layout.setSpacing(8)

        def create_setting_row(label_text: str) -> tuple[QHBoxLayout, QLineEdit, QPushButton]:
            layout = QHBoxLayout()
            label = QLabel(label_text)
            color_display = QLineEdit()
            color_display.setFixedWidth(95)
            color_display.setReadOnly(True)
            color_btn = QPushButton(tr('ui.select_color'))
            color_btn.setFixedWidth(150)
            reset_btn = QPushButton('⭯')
            reset_btn.setStyleSheet('min-width: 35px; max-width: 35px; padding-left: 0px; padding-right: 0px;')
            reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            reset_btn.clicked.connect(lambda: (color_display.clear(), self._on_custom_style_edited()))
            layout.addWidget(label)
            layout.addStretch()
            for widget in [color_display, color_btn, reset_btn]:
                layout.addWidget(widget)
            return (layout, color_display, color_btn)
        self.color_widgets = {}
        self.color_config = {'background': tr('ui.background_color'), 'button': tr('ui.elements_color'), 'border': tr('ui.border_color'), 'button_hover': tr('ui.hover_color'), 'text': tr('ui.main_text_color'), 'version_text': tr('ui.secondary_text_color')}

        def pick_color_for_edit(target_edit):
            if (color := QColorDialog.getColor()).isValid():
                target_edit.setText(color.name())
                self._on_custom_style_edited()
        for key, label in self.color_config.items():
            layout, line_edit, btn = create_setting_row(label)
            line_edit.editingFinished.connect(self._on_custom_style_edited)
            btn.clicked.connect(lambda _, le=line_edit: pick_color_for_edit(le))
            self.color_widgets[key] = line_edit
            custom_style_layout.addLayout(layout)
        settings_customization_layout.addWidget(self.custom_style_frame)
        settings_customization_layout.addStretch()
        pages_layout.addWidget(self.settings_customization_page)
        self.settings_customization_page.setVisible(False)
        self.changelog_widget = QFrame()
        self.changelog_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        changelog_layout = QVBoxLayout(self.changelog_widget)
        self.changelog_text_edit = QTextBrowser()
        self.changelog_text_edit.setOpenExternalLinks(True)
        self.changelog_text_edit.setMinimumHeight(0)
        self.changelog_text_edit.setMaximumHeight(500)
        current_font = self.font()
        self.changelog_text_edit.setFont(current_font)
        doc = self.changelog_text_edit.document()
        if doc is not None:
            doc.setDefaultFont(current_font)
            doc.setDefaultStyleSheet('p { margin-bottom: 0.75em; } ul, ol { margin-left: 1em; } li { margin-bottom: 0.25em; }')
        self.changelog_text_edit.setOpenExternalLinks(True)
        self.changelog_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")
        changelog_layout.addWidget(self.changelog_text_edit)
        self.help_widget = QFrame()
        self.help_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        help_layout = QVBoxLayout(self.help_widget)
        self.help_text_edit = QTextBrowser()
        self.help_text_edit.setOpenExternalLinks(True)
        self.help_text_edit.setMinimumHeight(0)
        self.help_text_edit.setMaximumHeight(500)
        help_font = self.font()
        self.help_text_edit.setFont(help_font)
        help_doc = self.help_text_edit.document()
        if help_doc is not None:
            help_doc.setDefaultFont(help_font)
            help_doc.setDefaultStyleSheet('p { margin-bottom: 0.75em; } ul, ol { margin-left: 1em; } li { margin-bottom: 0.25em; }')
        self.help_text_edit.setOpenExternalLinks(True)
        self.help_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")
        help_layout.addWidget(self.help_text_edit)
        self.changelog_button = QPushButton(tr('buttons.changelog'))
        self.changelog_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.changelog_button.setStyleSheet('min-width: 220px; max-width: 220px;')
        self.changelog_button.clicked.connect(self._toggle_changelog_view)
        self.help_button = QPushButton(tr('buttons.help'))
        self.help_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.help_button.setStyleSheet('min-width: 220px; max-width: 220px;')
        self.help_button.clicked.connect(self._toggle_help_view)

        # Добавляем сброс фильтров
        self.sort_combo.setCurrentIndex(0)
        self.sort_order_btn.setText('▼')
        self.sort_ascending = False
        self.modtype_combo.setCurrentIndex(0)
        for tag_checkbox in [self.tag_translation, self.tag_customization, self.tag_gameplay, self.tag_other]:
            tag_checkbox.setChecked(False)
        self.search_text = ''
        self.search_button.setText('🔍')
        self._update_filtered_mods()
        settings_layout.addWidget(self.settings_pages_container)
        self.changelog_widget.setVisible(False)
        settings_layout.addWidget(self.changelog_widget, stretch=1)
        self.help_widget.setVisible(False)
        settings_layout.addWidget(self.help_widget, stretch=1)
        button_bar_layout = QHBoxLayout()
        button_bar_layout.setSpacing(10)
        button_bar_layout.addStretch(1)
        button_bar_layout.addWidget(self.changelog_button)
        button_bar_layout.addWidget(self.help_button)
        button_bar_layout.addStretch(1)
        settings_layout.addLayout(button_bar_layout)
        self.settings_widget.setVisible(False)
        self.main_layout.addWidget(self.settings_widget)
        self.save_manager_widget = QFrame()
        self.save_manager_widget.setObjectName('save_manager_widget')
        self._init_save_manager_ui()
        self.save_manager_widget.setVisible(False)
        self.main_layout.addWidget(self.save_manager_widget)
        self.current_settings_page = self.settings_menu_page
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.chapter_btn_widget = QWidget()
        self.chapter_btn_widget.hide()
        self.setWindowIcon(QIcon(resource_path('icons/icon.ico')))

    def _on_tab_changed(self, index):
        if index == 2:
            self._on_manage_mods_click()
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 3:
            self._on_xdelta_patch_click()
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 1:
            self._update_installed_mods_display()
            self.previous_tab_index = index
        else:
            self.previous_tab_index = index

    def _on_mods_loaded(self):
        if self.initialization_timer and self.initialization_timer.isActive():
            self.initialization_timer.stop()
        self.initialization_completed = True
        self.initialization_finished.emit()
        self._maybe_start_background_music()

    def _force_finish_initialization(self):
        if self.initialization_completed:
            return
        self.mods_loaded = True
        self.initialization_completed = True
        self.initialization_finished.emit()
        if not is_game_running():
            self._maybe_start_background_music()

    def _create_search_mods_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.current_page = 1
        self.mods_per_page = 15
        self.filtered_mods = []
        filters_widget = self._create_filters_widget()
        layout.addWidget(filters_widget)
        self.search_container = QWidget()
        self.search_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.search_container.setObjectName('search_mods_background')
        search_container_layout = QVBoxLayout(self.search_container)
        search_container_layout.setContentsMargins(10, 10, 10, 10)
        search_container_layout.setSpacing(10)
        self.search_mods_scroll = QScrollArea()
        self.search_mods_scroll.setWidgetResizable(True)
        self.search_mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.search_mods_scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        self.mod_list_widget = QWidget()
        self.mod_list_layout = QVBoxLayout(self.mod_list_widget)
        self.mod_list_layout.setSpacing(15)
        self.mod_list_layout.addStretch()
        self.search_mods_scroll.setWidget(self.mod_list_widget)
        search_container_layout.addWidget(self.search_mods_scroll)
        pagination_widget = self._create_pagination_widget()
        search_container_layout.addWidget(pagination_widget)
        search_bg_color = get_theme_color(self.local_config, 'background', '#000000')
        r, g, b = (int(search_bg_color[1:3], 16), int(search_bg_color[3:5], 16), int(search_bg_color[5:7], 16)) if search_bg_color.startswith('#') else (0, 0, 0)
        search_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        self.search_container.setStyleSheet(f'\n            QWidget#search_mods_background {{\n                background-color: {search_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        layout.addWidget(self.search_container)
        return widget

    def _create_library_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls_layout = QHBoxLayout()
        controls_layout.addStretch()
        self.game_type_combo = QComboBox()
        self.game_type_combo.addItem('DELTARUNE', 'deltarune')
        self.game_type_combo.addItem('DELTARUNE DEMO', 'deltarunedemo')
        self.game_type_combo.addItem('UNDERTALE', 'undertale')
        self.game_type_combo.currentIndexChanged.connect(self._on_game_type_changed)
        controls_layout.addWidget(self.game_type_combo)
        controls_layout.addSpacing(20)
        self.chapter_mode_checkbox = QCheckBox(tr('ui.chapter_mode'))
        self.chapter_mode_checkbox.stateChanged.connect(self._on_chapter_mode_changed)
        controls_layout.addWidget(self.chapter_mode_checkbox)
        self.full_install_checkbox = QCheckBox(tr('ui.full_install'))
        self.full_install_checkbox.stateChanged.connect(self._on_toggle_full_install)
        controls_layout.addWidget(self.full_install_checkbox)
        saved_game_type = self.local_config.get('selected_game_type', 'deltarune')
        saved_chapter_mode = self.local_config.get('chapter_mode_enabled', False)
        saved_full_install = self.local_config.get('full_install_enabled', False)
        self.game_type_combo.blockSignals(True)
        for i in range(self.game_type_combo.count()):
            if self.game_type_combo.itemData(i) == saved_game_type:
                self.game_type_combo.setCurrentIndex(i)
                break
        self.game_type_combo.blockSignals(False)
        self.chapter_mode_checkbox.blockSignals(True)
        self.chapter_mode_checkbox.setChecked(saved_chapter_mode)
        self.chapter_mode_checkbox.blockSignals(False)
        self.game_type_combo.setEnabled(not saved_chapter_mode)
        self.full_install_checkbox.blockSignals(True)
        self.full_install_checkbox.setChecked(saved_full_install)
        self.full_install_checkbox.blockSignals(False)
        if saved_game_type == 'deltarunedemo':
            self.game_mode = DemoGameMode()
        elif saved_game_type == 'undertale':
            self.game_mode = UndertaleGameMode()
        else:
            self.game_mode = FullGameMode()
        self.current_mode = 'chapter' if saved_chapter_mode else 'normal'
        self._previous_mode = self.current_mode
        self._update_checkbox_visibility()
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        self.selected_chapter_id = None
        self.slots_container = QWidget()
        self.slots_layout = QVBoxLayout(self.slots_container)
        self.active_slots_widget = QWidget()
        self.active_slots_widget.setObjectName('slots_background')
        self.active_slots_layout = QHBoxLayout(self.active_slots_widget)
        self.active_slots_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_slots_layout.setContentsMargins(20, 15, 20, 15)
        self.active_slots_layout.setSpacing(0)
        slots_bg_color = get_theme_color(self.local_config, 'background', '#000000')
        if slots_bg_color.startswith('#'):
            r = int(slots_bg_color[1:3], 16)
            g = int(slots_bg_color[3:5], 16)
            b = int(slots_bg_color[5:7], 16)
            slots_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            slots_bg_rgba = 'rgba(0, 0, 0, 128)'
        self.active_slots_widget.setStyleSheet(f'\n            QWidget#slots_background {{\n                background-color: {slots_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        self.slots_layout.addWidget(self.active_slots_widget)
        layout.addWidget(self.slots_container)
        self.installed_mods_container = QWidget()
        self.installed_mods_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.installed_mods_container.setObjectName('mods_background')
        mods_container_layout = QVBoxLayout(self.installed_mods_container)
        mods_container_layout.setContentsMargins(15, 15, 15, 15)
        mods_container_layout.setSpacing(10)
        installed_mods_label = QLabel(tr('ui.installed_mods_label'))
        installed_mods_label.setStyleSheet('font-weight: bold; font-size: 16px;')
        installed_mods_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mods_container_layout.addWidget(installed_mods_label)
        self.installed_mods_scroll = QScrollArea()
        self.installed_mods_scroll.setWidgetResizable(True)
        self.installed_mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.installed_mods_widget = QWidget()
        self.installed_mods_layout = QVBoxLayout(self.installed_mods_widget)
        self.installed_mods_layout.addStretch()
        self.installed_mods_layout.setContentsMargins(0, 0, 0, 0)
        self.installed_mods_scroll.setWidget(self.installed_mods_widget)
        mods_container_layout.addWidget(self.installed_mods_scroll)
        mods_bg_color = get_theme_color(self.local_config, 'background', '#000000')
        if mods_bg_color.startswith('#'):
            r = int(mods_bg_color[1:3], 16)
            g = int(mods_bg_color[3:5], 16)
            b = int(mods_bg_color[5:7], 16)
            mods_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            mods_bg_rgba = 'rgba(0, 0, 0, 128)'
        self.installed_mods_container.setStyleSheet(f'\n            QWidget#mods_background {{\n                background-color: {mods_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        layout.addWidget(self.installed_mods_container)
        QTimer.singleShot(500, self._update_installed_mods_display)
        QTimer.singleShot(700, self._update_mod_widgets_slot_status)
        self.slots = {}
        self._update_slots_display()
        QTimer.singleShot(400, self._load_slots_state)
        return widget

    def _create_filters_widget(self):
        filters_widget = QFrame()
        filters_widget.setObjectName('filters')
        filters_widget.setFixedHeight(55)
        filters_layout = QHBoxLayout(filters_widget)
        filters_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        self.sort_combo = NoScrollComboBox()
        self.sort_combo.addItems([tr('ui.sort_by_downloads'), tr('ui.sort_by_update_date'), tr('ui.sort_by_creation_date')])
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        filters_layout.addWidget(self.sort_combo)
        self.sort_order_btn = QPushButton('▼')
        self.sort_order_btn.setObjectName('sortOrderBtn')
        self.sort_order_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.sort_order_btn.setToolTip(tr('ui.sort_direction_tooltip'))
        self.sort_ascending = False
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        filters_layout.addWidget(self.sort_order_btn)
        filters_layout.addSpacing(20)
        self.modtype_combo = QComboBox()
        self.modtype_combo.addItem(tr('dropdowns.all_mods'), '')
        self.modtype_combo.addItem(tr('dropdowns.filter_deltarune'), 'deltarune')
        self.modtype_combo.addItem(tr('dropdowns.filter_deltarunedemo'), 'deltarunedemo')
        self.modtype_combo.addItem(tr('dropdowns.filter_undertale'), 'undertale')
        self.modtype_combo.currentIndexChanged.connect(self._on_modtype_filter_changed)
        filters_layout.addWidget(self.modtype_combo)
        filters_layout.addSpacing(20)
        filters_layout.addWidget(QLabel(tr('ui.tags_label')))
        self.tag_translation = QCheckBox(tr('tags.translation'))
        self.tag_customization = QCheckBox(tr('tags.customization'))
        self.tag_gameplay = QCheckBox(tr('tags.gameplay'))
        self.tag_other = QCheckBox(tr('tags.other'))
        tag_style = '\n            QCheckBox {\n                color: white;\n                font-size: 12px;\n                spacing: 5px;\n            }\n            QCheckBox::indicator {\n                width: 16px;\n                height: 16px;\n            }\n        '
        for tag in [self.tag_translation, self.tag_customization, self.tag_gameplay, self.tag_other]:
            tag.setStyleSheet(tag_style)
            tag.stateChanged.connect(self._on_tag_filter_changed)
            filters_layout.addWidget(tag)
        filters_layout.addStretch()
        self.search_text = ''
        self.search_button = QPushButton('🔍')
        self.search_button.setObjectName('searchBtn')
        self.search_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.search_button.setFixedSize(35, 35)
        self.search_button.setToolTip(tr('tooltips.search'))
        self.search_button.clicked.connect(self._show_search_dialog)
        filters_layout.addWidget(self.search_button)
        return filters_widget

    def _create_pagination_widget(self):
        pagination_widget = QWidget()
        pagination_layout = QHBoxLayout(pagination_widget)
        pagination_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_page_btn = QPushButton(tr('ui.prev_page'))
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.prev_page_btn.setEnabled(False)
        self.prev_page_btn.setMaximumHeight(24)
        self.prev_page_btn.setStyleSheet('font-size: 12px; padding: 3px 8px;')
        pagination_layout.addWidget(self.prev_page_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.page_label = QLabel(tr('ui.page_label', current=1, total=1))
        self.page_label.setStyleSheet('font-size: 14px; padding: 0px 10px;')
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pagination_layout.addWidget(self.page_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.next_page_btn = QPushButton(tr('ui.next_page'))
        self.next_page_btn.clicked.connect(self._next_page)
        self.next_page_btn.setEnabled(False)
        self.next_page_btn.setMaximumHeight(24)
        self.next_page_btn.setStyleSheet('font-size: 12px; padding: 3px 8px;')
        pagination_layout.addWidget(self.next_page_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        return pagination_widget

    def _toggle_sort_order(self):
        self.sort_ascending = not self.sort_ascending
        if self.sort_ascending:
            self.sort_order_btn.setText('▲')
            self.sort_order_btn.setToolTip(tr('ui.ascending'))
        else:
            self.sort_order_btn.setText('▼')
            self.sort_order_btn.setToolTip(tr('ui.descending'))
        self._update_filtered_mods()

    def _on_sort_changed(self, index):
        self._update_filtered_mods()

    def _on_tag_filter_changed(self, state):
        self.current_page = 1
        self._update_filtered_mods()

    def _on_modtype_filter_changed(self, index):
        self.current_page = 1
        self._update_filtered_mods()

    def _show_search_dialog(self):
        if self.search_text:
            self.search_text = ''
            self.search_button.setText('🔍')
            self.search_button.setToolTip(tr('ui.search_mods_placeholder'))
            self._update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self, tr('ui.search_mods'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.search_text = text.strip()
                self.search_button.setText('↻')
                self.search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.search_text))
                self._update_filtered_mods()

    def _prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._update_mod_display()

    def _next_page(self):
        total_pages = (len(self.filtered_mods) - 1) // self.mods_per_page + 1
        if self.current_page < total_pages:
            self.current_page += 1
            self._update_mod_display()

    def _init_slots_system(self):
        self.slots = {}
        self._update_slots_display()

    def _on_game_type_changed(self, index):
        game_type = self.game_type_combo.itemData(index)
        if not game_type:
            return
        self._save_slots_state()
        if game_type == 'deltarunedemo':
            self.game_mode = DemoGameMode()
        elif game_type == 'undertale':
            self.game_mode = UndertaleGameMode()
        else:
            self.game_mode = FullGameMode()
        self._update_checkbox_visibility()
        self._update_slots_display()
        self._load_slots_state()
        self._update_installed_mods_display()
        self._update_change_path_button_text()
        self.local_config['selected_game_type'] = game_type
        self._write_local_config()

    def _update_checkbox_visibility(self):
        game_type = self.game_type_combo.currentData()
        if game_type == 'deltarune':
            self.chapter_mode_checkbox.setVisible(True)
            self.full_install_checkbox.setVisible(False)
        elif game_type == 'deltarunedemo':
            self.chapter_mode_checkbox.setVisible(False)
            self.full_install_checkbox.setVisible(True)
        else:
            self.chapter_mode_checkbox.setVisible(False)
            self.full_install_checkbox.setVisible(False)

    def _clear_all_slots(self):
        for slot_frame in getattr(self, 'slots', {}).values():
            if slot_frame.assigned_mod:
                self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
            slot_frame.is_selected = False
            self._update_slot_visual_state(slot_frame)

    def _on_chapter_mode_changed(self, state):
        game_type = self.game_type_combo.currentData()
        if game_type != 'deltarune':
            return
        old_mode = getattr(self, 'current_mode', 'normal')
        self._previous_mode = old_mode
        is_chapter = bool(state)
        self.current_mode = 'chapter' if is_chapter else 'normal'
        self.game_type_combo.setEnabled(not is_chapter)
        self._save_slots_state()
        self._update_slots_display()
        self._update_mod_widgets_slot_status()
        self._update_action_button_state()
        if is_chapter:
            for slot_frame in self.slots.values():
                slot_frame.is_selected = False
                self._update_slot_visual_state(slot_frame)
            self.selected_chapter_id = None
            self._show_chapter_mode_instruction()
        else:
            self.selected_chapter_id = None
            self._update_installed_mods_display()
        self._update_change_path_button_text()
        self.local_config['chapter_mode_enabled'] = is_chapter
        self._write_local_config()

    def _show_chapter_mode_instruction(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        instruction_widget = QLabel(tr('ui.chapter_mode_instruction'))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_widget.setStyleSheet('\n            QLabel {\n                color: #CCCCCC;\n                font-size: 14px;\n                font-style: italic;\n                padding: 20px;\n                border: 2px dashed #666666;\n                background-color: rgba(255, 255, 255, 0.1);\n            }\n        ')
        instruction_widget.setWordWrap(True)
        instruction_widget.setMinimumHeight(80)
        self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, instruction_widget)

    def _update_slots_display(self):
        if hasattr(self, 'active_slots_layout'):
            clear_layout_widgets(self.active_slots_layout, keep_last_n=0)
        if not hasattr(self, 'slots'):
            self.slots = {}
        else:
            self.slots.clear()
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        if self.current_mode == 'normal':
            if is_demo_mode:
                slot = self._create_slot_widget(tr('ui.demo_slot'), -10)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.slots[-10] = slot
            elif isinstance(self.game_mode, UndertaleGameMode):
                slot = self._create_slot_widget(tr('ui.universal_slot'), -20)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.slots[-20] = slot
            else:
                slot = self._create_slot_widget(tr('ui.mod_slot'), -1)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.slots[-1] = slot
                self._create_chapter_indicators()
        else:
            slot_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
            for i, name in enumerate(slot_names):
                slot = self._create_slot_widget(name, i)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.slots[i] = slot
        self._load_slots_state()

    def _get_slots_config_key(self, game_mode_instance, is_chapter_mode):
        if isinstance(game_mode_instance, DemoGameMode):
            return 'saved_slots_deltarunedemo'
        elif isinstance(game_mode_instance, UndertaleGameMode):
            return 'saved_slots_undertale'
        else:
            return 'saved_slots_deltarune_chapter' if is_chapter_mode else 'saved_slots_deltarune'

    def _create_chapter_indicators(self):
        chapter_names = [tr('ui.menu_label'), tr('ui.chapter_1_label'), tr('ui.chapter_2_label'), tr('ui.chapter_3_label'), tr('ui.chapter_4_label')]
        self.chapter_indicators = {}
        main_text_color = get_theme_color(self.local_config, 'text', 'white')
        for i, chapter_name in enumerate(chapter_names):
            indicator_frame = QFrame()
            indicator_layout = QVBoxLayout(indicator_frame)
            indicator_layout.setContentsMargins(5, 5, 5, 5)
            indicator_layout.setSpacing(2)
            chapter_label = QLabel(chapter_name)
            chapter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chapter_label.setStyleSheet(f'color: {main_text_color}; font-size: 14px; font-weight: bold;')
            status_label = QLabel('?')
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setStyleSheet('color: #FFD700; font-size: 16px; font-weight: bold;')
            indicator_layout.addWidget(chapter_label)
            indicator_layout.addWidget(status_label)
            self.chapter_indicators[i] = {'status_label': status_label, 'chapter_label': chapter_label, 'frame': indicator_frame}
            if hasattr(self, 'active_slots_layout'):
                self.active_slots_layout.addWidget(indicator_frame)

    def _update_chapter_indicators(self, mod=None):
        if not hasattr(self, 'chapter_indicators'):
            return
        if mod is None:
            for i in range(5):
                if i in self.chapter_indicators:
                    self.chapter_indicators[i]['status_label'].setText('?')
                    self.chapter_indicators[i]['status_label'].setStyleSheet('color: #FFD700; font-size: 16px; font-weight: bold;')
        else:
            for i in range(5):
                if i in self.chapter_indicators:
                    has_files = self._mod_has_files_for_chapter(mod, i)
                    if has_files:
                        self.chapter_indicators[i]['status_label'].setText('✓')
                        self.chapter_indicators[i]['status_label'].setStyleSheet('color: #00FF00; font-size: 16px; font-weight: bold;')
                    else:
                        self.chapter_indicators[i]['status_label'].setText('✗')
                        self.chapter_indicators[i]['status_label'].setStyleSheet('color: #FF0000; font-size: 16px; font-weight: bold;')

    def _update_chapter_indicators_style(self):
        if hasattr(self, 'chapter_indicators'):
            main_text_color = get_theme_color(self.local_config, 'text', 'white')
            for indicator_data in self.chapter_indicators.values():
                if 'chapter_label' in indicator_data:
                    indicator_data['chapter_label'].setStyleSheet(f'color: {main_text_color}; font-size: 14px; font-weight: bold;')

    def _create_slot_widget(self, name, chapter_id):
        slot_frame = SlotFrame()
        if chapter_id in [-1, -10, -20]:
            slot_frame.setFixedSize(250, 100)
        else:
            slot_frame.setFixedSize(150, 100)
        slot_frame.setObjectName('mod_slot')
        slot_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(slot_frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet('font-weight: bold; border: none; background-color: transparent;')
        layout.addWidget(name_label)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon = QLabel(tr('ui.empty_slot'))
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon.setObjectName('secondaryText')
        content_layout.addWidget(mod_icon)
        layout.addWidget(content_widget)
        slot_frame.chapter_id = chapter_id
        slot_frame.assigned_mod = None
        slot_frame.content_widget = content_widget
        slot_frame.mod_icon = mod_icon
        slot_frame.is_selected = False
        slot_frame.click_handler = lambda: self._on_slot_clicked(slot_frame)
        slot_frame.double_click_handler = lambda: self._on_slot_frame_double_clicked(slot_frame)
        self._update_slot_visual_state(slot_frame)
        return slot_frame

    def _update_slot_visual_state(self, slot_frame):
        user_bg_hex = get_theme_color(self.local_config, 'background', None)
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            slot_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            slot_bg_color = 'rgba(0, 0, 0, 150)'
        slot_border_color = get_theme_color(self.local_config, 'border', 'white')
        direct_launch_slot_id = self.local_config.get('direct_launch_slot_id', -1)
        is_direct_launch_slot = direct_launch_slot_id >= 0 and slot_frame.chapter_id >= 0 and (slot_frame.chapter_id == direct_launch_slot_id)
        border_style = '3px dashed' if is_direct_launch_slot else '3px solid'
        if getattr(slot_frame, 'is_selected', False):
            border_color = slot_border_color
            bg_color = slot_bg_color.replace('0.75', '0.9').replace('150', '200')
        else:
            border_color = slot_border_color
            bg_color = slot_bg_color
        slot_frame.setStyleSheet(f"\n            QFrame#mod_slot {{\n                border: {border_style} {border_color};\n                background-color: {bg_color};\n            }}\n            QFrame#mod_slot:hover {{\n                border: {border_style} {border_color};\n                background-color: {bg_color.replace('150', '180').replace('0.75', '0.85')};\n            }}\n        ")

    def _on_slot_clicked(self, slot_frame):
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        if not is_chapter_mode:
            if slot_frame.assigned_mod:
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(tr('ui.remove_mod_from_slot'))
                msg_box.setText(tr('ui.remove_mod_question', mod_name=slot_frame.assigned_mod.name))
                msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if msg_box.exec() == QMessageBox.StandardButton.Yes:
                    self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
                    self._save_slots_state()
            else:
                self._show_mod_selection_for_slot(slot_frame)
        else:
            for other_slot in self.slots.values():
                if other_slot != slot_frame:
                    other_slot.is_selected = False
                    self._update_slot_visual_state(other_slot)
            slot_frame.is_selected = not slot_frame.is_selected
            self._update_slot_visual_state(slot_frame)
            if slot_frame.is_selected:
                selected_chapter = slot_frame.chapter_id
                self.selected_chapter_id = selected_chapter
                self._update_installed_mods_for_chapter_mode(selected_chapter)
            else:
                self.selected_chapter_id = None
                self._show_chapter_mode_instruction()

    def _on_slot_frame_double_clicked(self, slot_frame):
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        if not is_chapter_mode or slot_frame.chapter_id < 0:
            return
        current_direct_launch_slot = self.local_config.get('direct_launch_slot_id', -1)
        is_direct_launch_active = current_direct_launch_slot == slot_frame.chapter_id
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr('ui.direct_launch'))
        if is_direct_launch_active:
            msg_box.setText(tr('ui.disable_direct_launch', chapter=slot_frame.chapter_id))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                self._disable_direct_launch()
        else:
            msg_box.setText(tr('ui.enable_direct_launch', chapter=slot_frame.chapter_id))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                self._on_toggle_direct_launch_for_slot(slot_frame.chapter_id)

    def _update_installed_mods_for_chapter_mode(self, selected_chapter_id):
        if not hasattr(self, 'installed_mods_layout'):
            return
        if hasattr(self, '_updating_chapter_mods') and self._updating_chapter_mods:
            return
        self._updating_chapter_mods = True
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        installed_mods = self._get_installed_mods_list()
        is_demo_mode = hasattr(self, 'game_type_combo') and self.game_type_combo.currentData() == 'deltarunedemo'
        for mod_info in installed_mods:
            if is_demo_mode and (not mod_info.get('modtype', 'deltarune') == 'deltarunedemo'):
                continue
            elif not is_demo_mode and mod_info.get('modtype', 'deltarune') == 'deltarunedemo':
                continue
            if selected_chapter_id is not None:
                mod_data = self._create_mod_object_from_info(mod_info)
                if mod_data and (not self._mod_has_files_for_chapter(mod_data, selected_chapter_id)):
                    continue
            is_local = mod_info.get('is_local_mod', False)
            is_available = mod_info.get('is_available_on_server', True)
            mod_data = self._create_mod_object_from_info(mod_info)
            if mod_data:
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, parent=self)
                mod_widget.clicked.connect(self._on_installed_mod_clicked)
                mod_widget.remove_requested.connect(self._on_installed_mod_remove)
                if selected_chapter_id is not None:
                    mod_widget.use_requested.connect(lambda mod_data=mod_data: self._on_chapter_mode_mod_use(mod_data, selected_chapter_id))
                    is_in_slot = self._is_mod_in_specific_slot(mod_data, selected_chapter_id)
                    mod_widget.set_in_slot(is_in_slot)
                else:
                    mod_widget.use_requested.connect(self._on_installed_mod_use)
                self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)
        if self.installed_mods_layout.count() <= 1:
            if selected_chapter_id is not None:
                chapter_names = {-1: tr('ui.universal_slot'), 0: tr('ui.menu'), 1: tr('ui.chapter_1'), 2: tr('ui.chapter_2'), 3: tr('ui.chapter_3'), 4: tr('ui.chapter_4')}
                chapter_name = chapter_names.get(selected_chapter_id, tr('ui.chapter_n', chapter=str(selected_chapter_id)))
                self._show_empty_chapter_message(chapter_name)
            else:
                self._show_empty_mods_message()
        self._updating_chapter_mods = False

    def _mod_has_files_for_chapter(self, mod_data, chapter_id):
        try:
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
            if not mod_key:
                return True
            mod_folder = os.path.join(self.mods_dir, mod_key)
            if not os.path.exists(mod_folder):
                mod_folder_by_name = os.path.join(self.mods_dir, mod_data.name)
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
        except Exception as e:
            print(f'Error checking mod files for chapter {chapter_id}: {e}')
            return True

    def _on_chapter_mode_mod_use(self, mod_data, chapter_id):
        mod_widget = None
        for i in range(self.installed_mods_layout.count()):
            item = self.installed_mods_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                    widget_mod_data = getattr(widget, 'mod_data', None)
                    if widget_mod_data:
                        widget_mod_key = getattr(widget_mod_data, 'key', None) or getattr(widget_mod_data, 'mod_key', None) or getattr(widget_mod_data, 'name', None)
                        current_mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
                        if widget_mod_key == current_mod_key:
                            mod_widget = widget
                            break
        status = getattr(mod_widget, 'status', 'ready') if mod_widget else 'ready'
        if status == 'needs_update':
            self._update_mod(mod_data)
            return
        target_slot = None
        for slot_frame in self.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break
        if target_slot and target_slot.assigned_mod:
            assigned_mod_key = getattr(target_slot.assigned_mod, 'key', None) or getattr(target_slot.assigned_mod, 'mod_key', None) or getattr(target_slot.assigned_mod, 'name', None)
            mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
            if assigned_mod_key == mod_key:
                self._remove_mod_from_slot(target_slot, mod_data)
                self._update_installed_mods_for_chapter_mode(chapter_id)
                return
        target_slot = None
        for slot_frame in self.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break
        if target_slot:
            self._assign_mod_to_slot(target_slot, mod_data)
            self._update_installed_mods_for_chapter_mode(chapter_id)
        else:
            QMessageBox.warning(self, tr('errors.error'), tr('errors.target_slot_not_found'))

    def _show_mod_selection_for_slot(self, slot_frame):
        installed_mods = self._get_installed_mods_list()
        available_mods = []
        for mod_info in installed_mods:
            if mod_info:
                mod_exists = self._check_mod_exists(mod_info)
                if not mod_exists:
                    continue
                mod_modtype = mod_info.get('modtype', 'deltarune')
                slot_id = slot_frame.chapter_id
                if slot_id == -10:
                    if mod_modtype != 'deltarunedemo':
                        continue
                elif slot_id == -20:
                    if mod_modtype != 'undertale':
                        continue
                elif slot_id == -1:
                    if mod_modtype not in ['deltarune', 'deltarunedemo']:
                        continue
                elif mod_modtype != 'deltarune':
                    continue
                mod_data = self._create_mod_object_from_info(mod_info)
                if mod_data and (not self._find_mod_in_slots(mod_data)):
                    available_mods.append(mod_data)
        if not available_mods:
            QMessageBox.information(self, tr('ui.no_available_mods'), tr('ui.no_mods_to_insert'))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.select_mod'))
        dialog.setFixedSize(350, 250)
        layout = QVBoxLayout(dialog)
        label = QLabel(tr('ui.select_mod_for_slot'))
        layout.addWidget(label)
        mod_list = QListWidget()
        for mod_data in available_mods:
            mod_list.addItem(mod_data.name)
        layout.addWidget(mod_list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = mod_list.selectedItems()
            if selected_items:
                selected_index = mod_list.row(selected_items[0])
                selected_mod = available_mods[selected_index]
                self._assign_mod_to_slot(slot_frame, selected_mod)

    def _update_installed_mods_display(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            if hasattr(self, 'selected_chapter_id') and self.selected_chapter_id is not None:
                self._update_installed_mods_for_chapter_mode(self.selected_chapter_id)
                return
            else:
                self._show_chapter_mode_instruction()
                return
        self._refresh_installed_mods_async()

    def _update_installed_mods_display_from_list(self, installed_mods):
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = getattr(self, 'selected_chapter_id', None)
            if selected_id is None:
                if hasattr(self, 'installed_mods_container') and hasattr(self, 'installed_mods_layout'):
                    self.installed_mods_container.setUpdatesEnabled(False)
                    clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
                    self._show_chapter_mode_instruction()
                    self.installed_mods_container.setUpdatesEnabled(True)
                return
            else:
                self._update_installed_mods_for_chapter_mode(selected_id)
                return
        self.installed_mods_container.setUpdatesEnabled(False)
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        self._cleanup_missing_mods(installed_mods)
        current_game_type = 'deltarune'
        if hasattr(self, 'game_type_combo'):
            current_game_type = self.game_type_combo.currentData() or 'deltarune'
        for mod_info in installed_mods:
            mod_exists = self._check_mod_exists(mod_info)
            if not mod_exists:
                continue
            mod_modtype = mod_info.get('modtype', 'deltarune')
            if mod_modtype != current_game_type:
                continue
            is_local = mod_info.get('is_local_mod', False)
            is_available = mod_info.get('is_available_on_server', True)
            has_update = False
            if not is_local and is_available:
                public_mod = next((mod for mod in self.all_mods if mod.key == mod_info.get('key')), None)
                if public_mod:
                    has_update = any((self._mod_has_files_for_chapter(public_mod, i) and self._get_mod_status_for_chapter(public_mod, i) == 'update' for i in range(5)))
            mod_data = self._create_mod_object_from_info(mod_info)
            if mod_data:
                mod_widget = InstalledModWidget(mod_data, is_local, is_available, has_update, parent=self)
                mod_widget.clicked.connect(self._on_installed_mod_clicked)
                mod_widget.remove_requested.connect(self._on_installed_mod_remove)
                mod_widget.use_requested.connect(self._on_installed_mod_use)
                self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)
        if self.installed_mods_layout.count() <= 1:
            self._show_empty_mods_message()
        self._update_mod_widgets_slot_status()
        self._update_action_button_state()
        self.installed_mods_container.setUpdatesEnabled(True)

    def _refresh_installed_mods_async(self):
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        if is_chapter_mode:
            selected_id = getattr(self, 'selected_chapter_id', None)
            if selected_id is None:
                if hasattr(self, 'installed_mods_container') and hasattr(self, 'installed_mods_layout'):
                    self.installed_mods_container.setUpdatesEnabled(False)
                    clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
                    self._show_chapter_mode_instruction()
                    self.installed_mods_container.setUpdatesEnabled(True)
                return
            else:
                self._update_installed_mods_for_chapter_mode(selected_id)
                return
        from PyQt6.QtCore import QThread, pyqtSignal

        class _Scan(QThread):
            done = pyqtSignal(list)

            def __init__(self, outer):
                super().__init__(outer)
                self.outer = outer

            def run(self):
                try:
                    mods = self.outer._get_installed_mods_list()
                except Exception:
                    mods = []
                self.done.emit(mods)
        try:
            self._installed_scan_thread = _Scan(self)
            self._installed_scan_thread.done.connect(self._update_installed_mods_display_from_list)
            self._installed_scan_thread.start()
        except Exception:
            mods = self._get_installed_mods_list()
            self._update_installed_mods_display_from_list(mods)

    def _show_empty_mods_message(self):
        show_empty_message_in_layout(self.installed_mods_layout, tr('ui.empty'), self.local_config, font_size=18)

    def _show_empty_chapter_message(self, chapter_name):
        show_empty_message_in_layout(self.installed_mods_layout, tr('ui.no_mods_for_chapter', chapter_name=chapter_name), self.local_config, font_size=16)

    def _check_mod_exists(self, mod_info):
        mod_key = mod_info.get('mod_key', '')
        mod_name = mod_info.get('name', '')
        if mod_key:
            mod_folder_by_key = os.path.join(self.mods_dir, mod_key)
            if os.path.exists(mod_folder_by_key):
                return True
        if mod_name:
            mod_folder_by_name = os.path.join(self.mods_dir, mod_name)
            if os.path.exists(mod_folder_by_name):
                return True
        return False

    def _cleanup_missing_mods(self, installed_mods):
        missing_mods = []
        for mod_info in installed_mods:
            mod_key = mod_info.get('mod_key', '')
            mod_name = mod_info.get('name', '')
            mod_exists = False
            if mod_key:
                mod_folder_by_key = os.path.join(self.mods_dir, mod_key)
                if os.path.exists(mod_folder_by_key):
                    mod_exists = True
            if not mod_exists and mod_name:
                mod_folder_by_name = os.path.join(self.mods_dir, mod_name)
                if os.path.exists(mod_folder_by_name):
                    mod_exists = True
            if not mod_exists:
                missing_mods.append(mod_info)
        for missing_mod in missing_mods:
            mod_data = self._create_mod_object_from_info(missing_mod)
            if mod_data:
                self._remove_mod_from_all_slots(mod_data)
                config_keys = ['saved_slots_deltarune', 'saved_slots_deltarune_chapter', 'saved_slots_deltarunedemo', 'saved_slots_undertale']
                for config_key in config_keys:
                    slots_data = self.local_config.get(config_key, {})
                    slots_to_clear = []
                    for slot_id_str, slot_info in slots_data.items():
                        if isinstance(slot_info, dict):
                            saved_mod_key = slot_info.get('mod_key')
                            if hasattr(mod_data, 'key') and saved_mod_key == mod_data.key:
                                slots_to_clear.append(slot_id_str)
                    for slot_id_str in slots_to_clear:
                        del slots_data[slot_id_str]
                    if slots_to_clear:
                        self.local_config[config_key] = slots_data
                        self._write_local_config()

    def _get_installed_mods_list(self):
        installed_mods = []
        if not hasattr(self, 'mods_dir') or not os.path.exists(self.mods_dir):
            return installed_mods
        for folder_name in os.listdir(self.mods_dir):
            folder_path = os.path.join(self.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if os.path.exists(config_path):
                try:
                    config_data = self._read_json(config_path)
                    if config_data:
                        config_data['is_available_on_server'] = config_data.get('is_available_on_server', False)
                        config_data['is_local_mod'] = config_data.get('is_local_mod', False)
                        installed_mods.append(config_data)
                except Exception as e:
                    logging.warning(f'Failed to read config {config_path}: {e}')
                    continue
        return installed_mods

    def _create_mod_object_from_info(self, mod_info):
        mod_key = mod_info.get('mod_key', '')
        if hasattr(self, 'all_mods') and self.all_mods:
            for mod in self.all_mods:
                if hasattr(mod, 'key') and mod.key == mod_key:
                    return mod
        from models.mod_models import ModInfo
        return ModInfo(key=mod_key, name=mod_info.get('name', mod_key), tagline=mod_info.get('tagline', tr('defaults.no_description')), version=mod_info.get('version', '1.0.0'), author=mod_info.get('author', tr('defaults.unknown')), game_version=mod_info.get('game_version', '1.04'), description_url='', downloads=0, modtype=mod_info.get('modtype', 'deltarune'), is_verified=False)

    def _on_installed_mod_clicked(self, mod_data):
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget) and widget.mod_data == mod_data:
                    self._clear_all_installed_mod_selections()
                    widget.set_selected(True)
                    break

    def _clear_all_installed_mod_selections(self):
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _on_installed_mod_remove(self, mod_data):
        try:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr('dialogs.delete_confirmation'))
            msg_box.setText(tr('dialogs.delete_mod_confirmation', mod_name=mod_data.name))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                self._delete_mod_files(mod_data)
                self._remove_mod_from_all_slots(mod_data)
                self._update_installed_mods_display()
                try:
                    self._update_search_mod_plaques()
                except Exception:
                    pass
        except Exception as e:
            print(f'Error removing mod {mod_data.name}: {e}')
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_removal_failed', error=str(e)))

    def _on_installed_mod_use(self, mod_data):
        current_slot = self._find_mod_in_slots(mod_data)
        if current_slot:
            self._remove_mod_from_slot(current_slot, mod_data)
            self._save_slots_state()
        else:
            is_chapter_mode = self.chapter_mode_checkbox.isChecked()
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)
            mod_widget = None
            for i in range(self.installed_mods_layout.count()):
                item = self.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if hasattr(widget, 'mod_data') and hasattr(widget, 'use_button'):
                        widget_mod_data = getattr(widget, 'mod_data', None)
                        if widget_mod_data:
                            widget_mod_key = getattr(widget_mod_data, 'key', None) or getattr(widget_mod_data, 'mod_key', None) or getattr(widget_mod_data, 'name', None)
                            current_mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
                            if widget_mod_key == current_mod_key:
                                mod_widget = widget
                                break
            status = getattr(mod_widget, 'status', 'ready') if mod_widget else 'ready'
            if status == 'needs_update':
                self._update_mod(mod_data)
                return
            elif not is_chapter_mode or is_demo_mode:
                target_slot = None
                if is_demo_mode:
                    target_slot_id = -10
                elif hasattr(mod_data, 'modtype') and mod_data.modtype == 'undertale':
                    target_slot_id = -20
                else:
                    target_slot_id = -1
                for key, slot_frame in self.slots.items():
                    if slot_frame.chapter_id == target_slot_id:
                        target_slot = slot_frame
                        break
                if target_slot:
                    self._assign_mod_to_slot(target_slot, mod_data)
            else:
                self._show_slot_selection_dialog(mod_data)

    def _find_mod_in_slots(self, mod_data, exclude_chapter_id=None):
        if not mod_data:
            return None
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return None
        for slot_frame in self.slots.values():
            if exclude_chapter_id is not None and slot_frame.chapter_id == exclude_chapter_id:
                continue
            if slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    return slot_frame
        return None

    def _remove_mod_from_slot(self, slot_frame, mod_data):
        slot_frame.assigned_mod = None
        if slot_frame.content_widget:
            slot_frame.content_widget.setParent(None)
            slot_frame.content_widget = None
        slot_frame.mod_icon = None
        is_large_slot = slot_frame.chapter_id < 0
        title_label = None
        if slot_frame.layout():
            for i in range(slot_frame.layout().count()):
                item = slot_frame.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    title_label = item.widget()
                    break
        if is_large_slot and title_label:
            title_label.setVisible(True)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon = QLabel(tr('ui.empty_slot'))
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mod_icon.setObjectName('secondaryText')
        content_layout.addWidget(mod_icon)
        slot_frame.layout().addWidget(content_widget)
        slot_frame.content_widget = content_widget
        slot_frame.mod_icon = mod_icon
        self._update_mod_widgets_slot_status()
        if slot_frame.chapter_id == -1:
            self._update_chapter_indicators(None)
        self._update_action_button_state()

    def _show_slot_selection_dialog(self, mod_data):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.select_slot'))
        dialog.setFixedSize(300, 200)
        layout = QVBoxLayout(dialog)
        label = QLabel(tr('ui.select_slot_for_mod', mod_name=mod_data.name))
        layout.addWidget(label)
        slot_list = QListWidget()
        available_slots = []
        for key, slot_frame in self.slots.items():
            if slot_frame.assigned_mod is None:
                if slot_frame.chapter_id == -1:
                    slot_name = tr('ui.mod_slot')
                else:
                    chapter_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
                    slot_name = chapter_names[slot_frame.chapter_id]
                slot_list.addItem(slot_name)
                available_slots.append(slot_frame)
        if not available_slots:
            QMessageBox.information(self, tr('dialogs.no_free_slots'), tr('dialogs.all_slots_occupied'))
            return
        layout.addWidget(slot_list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = slot_list.selectedItems()
            if selected_items:
                selected_index = slot_list.row(selected_items[0])
                selected_slot = available_slots[selected_index]
                self._assign_mod_to_slot(selected_slot, mod_data)

    def _show_mod_details_dialog(self, mod_data):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.mod_details_title', mod_name=mod_data.name))
        dialog.setMinimumSize(700, 700)
        dialog.resize(800, 750)
        secondary_text_color = get_theme_color(self.local_config, 'version_text', 'rgba(255, 255, 255, 178)')
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        header_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        icon_label = QLabel()
        icon_label.setFixedSize(120, 120)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet('border: 2px solid #fff;')
        load_mod_icon_universal(icon_label, mod_data, 120)
        left_layout.addWidget(icon_label)
        left_container = QWidget()
        left_container.setMaximumWidth(200)
        left_container.setLayout(left_layout)
        metadata_layout = QVBoxLayout()
        metadata_layout.setSpacing(3)
        author_text = mod_data.author or tr('defaults.unknown')
        author_label = QLabel(f"""<span style="color: white;">{tr('ui.author_label')}</span> <span style="color: {secondary_text_color};">{author_text}</span>""")
        author_label.setStyleSheet('font-size: 12px;')
        metadata_layout.addWidget(author_label)
        game_version_text = mod_data.game_version or 'N/A'
        game_version_label = QLabel(f"""<span style="color: white;">{tr('ui.game_version_label')}</span> <span style="color: {secondary_text_color};">{game_version_text}</span>""")
        game_version_label.setStyleSheet('font-size: 12px;')
        metadata_layout.addWidget(game_version_label)
        created_date_text = mod_data.created_date or 'N/A'
        created_label = QLabel(f"""<span style="color: white;">{tr('ui.created_label')}</span> <span style="color: {secondary_text_color};">{created_date_text}</span>""")
        created_label.setStyleSheet('font-size: 12px;')
        metadata_layout.addWidget(created_label)
        updated_date_text = mod_data.last_updated or 'N/A'
        updated_label = QLabel(f"""<span style="color: white;">{tr('ui.updated_label')}</span> <span style="color: {secondary_text_color};">{updated_date_text}</span>""")
        updated_label.setStyleSheet('font-size: 12px;')
        metadata_layout.addWidget(updated_label)
        downloads_label = QLabel(f"""<span style="color: white;">{tr('ui.downloads_label')}</span> <span style="color: {secondary_text_color};">{mod_data.downloads}</span>""")
        downloads_label.setStyleSheet('font-size: 12px;')
        metadata_layout.addWidget(downloads_label)
        if hasattr(mod_data, 'tags') and mod_data.tags:
            metadata_layout.addSpacing(8)
            tags_header = QLabel(tr('ui.tags_label'))
            tags_header.setStyleSheet('font-size: 12px; color: white; font-weight: bold;')
            metadata_layout.addWidget(tags_header)
            tag_translations = {'translation': tr('tags.translation'), 'customization': tr('tags.customization'), 'gameplay': tr('tags.gameplay'), 'other': tr('tags.other')}
            tags_list = mod_data.tags if isinstance(mod_data.tags, list) else [mod_data.tags]
            filtered_tags = [tag for tag in tags_list if tag]
            translated_tags = [tag_translations.get(tag, tag) or tag for tag in filtered_tags]
            for tag in translated_tags:
                tag_label = QLabel(tag)
                tag_label.setStyleSheet(f'font-size: 12px; color: {secondary_text_color}; margin-left: 10px;')
                tag_label.setMaximumWidth(190)
                metadata_layout.addWidget(tag_label)
        left_layout.addLayout(metadata_layout)
        left_layout.addStretch()
        header_layout.addWidget(left_container)
        right_layout = QVBoxLayout()
        title_label = QLabel(f'<h2>{mod_data.name}</h2>')
        title_label.setWordWrap(True)
        right_layout.addWidget(title_label)
        mod_version = mod_data.version.split('|')[0] if mod_data.version and '|' in mod_data.version else mod_data.version
        version_text = mod_version or 'N/A'
        version_label = QLabel(tr('ui.mod_version_label', version_text=version_text))
        version_label.setStyleSheet(f'font-size: 14px; color: {secondary_text_color}; margin-bottom: 10px;')
        right_layout.addWidget(version_label)
        tagline_container = QWidget()
        tagline_container.setMinimumHeight(180)
        tagline_layout = QVBoxLayout(tagline_container)
        tagline_layout.setContentsMargins(0, 0, 0, 0)
        if mod_data.tagline:
            tagline_label = QLabel(mod_data.tagline)
            tagline_label.setWordWrap(True)
            tagline_label.setStyleSheet('font-size: 14px; color: #ddd;')
            tagline_label.setAlignment(Qt.AlignmentFlag.AlignTop)
            tagline_layout.addWidget(tagline_label)
        tagline_layout.addSpacing(20)
        status_layout = QVBoxLayout()
        status_layout.setSpacing(15)
        modtype_container = QVBoxLayout()
        modtype_container.setSpacing(4)
        modtype_label = OutlinedTextLabel(tr(f'ui.{mod_data.modtype}_label'))
        fill_color = 'white'
        outline_color = '#222222'
        if mod_data.modtype == 'deltarune':
            outline_color = '#222222'
        elif mod_data.modtype == 'deltarunedemo':
            outline_color = 'lightgreen'
        elif mod_data.modtype == 'undertale':
            outline_color = '#750B0B'
        f = modtype_label.font()
        f.setBold(True)
        f.setPointSize(15)
        modtype_label.setFont(f)
        modtype_label.setColors(fill_color, outline_color)
        modtype_label.setOutlineWidth(0.8)
        modtype_label.setMinimumHeight(26)
        modtype_label.setLeftMargin(0)
        modtype_container.addWidget(modtype_label)
        modtype_desc = OutlinedTextLabel(tr(f'ui.{mod_data.modtype}_desc'))
        df = modtype_desc.font()
        df.setPointSize(11)
        modtype_desc.setFont(df)
        modtype_desc.setColors(fill_color, outline_color)
        modtype_desc.setOutlineWidth(0.7)
        modtype_desc.setMinimumHeight(18)
        modtype_desc.setLeftMargin(12)
        modtype_container.addWidget(modtype_desc)
        status_layout.addLayout(modtype_container)
        tagline_layout.addLayout(status_layout)
        tagline_layout.addStretch()
        right_layout.addWidget(tagline_container)
        if getattr(mod_data, 'is_verified', False):
            verified_container = QVBoxLayout()
            verified_container.setSpacing(4)
            verified_label = QLabel(tr('ui.verified_label'))
            verified_label.setStyleSheet('color: #4CAF50; font-size: 15px;')
            verified_container.addWidget(verified_label)
            verified_desc = QLabel(tr('ui.verified_desc'))
            verified_desc.setStyleSheet('color: #4CAF50; font-size: 11px; margin-left: 12px;')
            verified_desc.setWordWrap(True)
            verified_container.addWidget(verified_desc)
            status_layout.addLayout(verified_container)
        if getattr(mod_data, 'is_xdelta', getattr(mod_data, 'is_piracy_protected', False)):
            patching_container = QVBoxLayout()
            patching_container.setSpacing(4)
            patching_label = QLabel(tr('ui.patching_label'))
            patching_label.setStyleSheet('color: #2196F3; font-size: 15px;')
            patching_container.addWidget(patching_label)
            patching_desc = QLabel(tr('ui.patching_desc'))
            patching_desc.setStyleSheet('color: #2196F3; font-size: 11px; margin-left: 12px;')
            patching_desc.setWordWrap(True)
            patching_container.addWidget(patching_desc)
            status_layout.addLayout(patching_container)
        else:
            replacement_container = QVBoxLayout()
            replacement_container.setSpacing(4)
            replacement_label = QLabel(tr('ui.file_replacement_label'))
            replacement_label.setStyleSheet('color: #FF9800; font-size: 15px;')
            replacement_container.addWidget(replacement_label)
            replacement_desc = QLabel(tr('ui.file_replacement_desc'))
            replacement_desc.setStyleSheet('color: #FF9800; font-size: 11px; margin-left: 12px;')
            replacement_desc.setWordWrap(True)
            replacement_container.addWidget(replacement_desc)
            status_layout.addLayout(replacement_container)
        if mod_data.modtype == 'deltarunedemo':
            demo_container = QVBoxLayout()
            demo_container.setSpacing(4)
            demo_label = QLabel(tr('ui.demo_label'))
            demo_label.setStyleSheet('color: #FF9800; font-weight: bold; font-size: 15px;')
            demo_container.addWidget(demo_label)
            demo_desc = QLabel(tr('ui.demo_desc'))
            demo_desc.setStyleSheet('color: #FF9800; font-size: 11px; margin-left: 12px;')
            demo_desc.setWordWrap(True)
            demo_container.addWidget(demo_desc)
            status_layout.addLayout(demo_container)
        right_layout.addStretch()
        header_layout.addLayout(right_layout)
        scroll_layout.addLayout(header_layout)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        scroll_layout.addWidget(separator)
        screenshots = getattr(mod_data, 'screenshots_url', []) or []
        if isinstance(screenshots, list) and any((isinstance(u, str) and u.strip() for u in screenshots)):
            screenshots_title = QLabel(f"<b>{tr('ui.screenshots_title')}</b>")
            screenshots_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll_layout.addWidget(screenshots_title)
            carousel = ScreenshotsCarousel(screenshots, self)
            container = QWidget()
            cont_layout = QHBoxLayout(container)
            cont_layout.setContentsMargins(0, 0, 0, 0)
            cont_layout.addStretch()
            cont_layout.addWidget(carousel)
            cont_layout.addStretch()
            scroll_layout.addWidget(container)
            scroll_layout.addSpacing(12)
        full_desc_label = QLabel(f"<b>{tr('ui.full_description_label')}</b>")
        full_desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll_layout.addWidget(full_desc_label)
        scroll_layout.addSpacing(6)
        desc_text = QTextBrowser()
        desc_text.setMinimumHeight(300)
        desc_text.setOpenExternalLinks(True)
        if hasattr(mod_data, 'description_url') and mod_data.description_url:
            self._load_description_from_url(desc_text, mod_data.description_url)
        else:
            desc_text.setPlainText(tr('ui.no_description'))
        scroll_layout.addWidget(desc_text)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        buttons_layout = QHBoxLayout()
        if hasattr(mod_data, 'url') and mod_data.url:
            open_url_btn = QPushButton(tr('ui.open_in_browser'))
            open_url_btn.clicked.connect(lambda: webbrowser.open(mod_data.url))
            buttons_layout.addWidget(open_url_btn)
        buttons_layout.addStretch()
        close_btn = QPushButton(tr('ui.close_button'))
        close_btn.clicked.connect(dialog.close)
        buttons_layout.addWidget(close_btn)
        layout.addLayout(buttons_layout)
        dialog.exec()

    def _load_description_from_url(self, text_widget, description_url):
        try:
            import requests
            text_widget.setPlainText(tr('status.loading_description'))
            response = requests.get(description_url, timeout=10)
            if response.ok:
                content = response.text
                is_markdown = description_url.lower().endswith(('.md', '.markdown')) or '# ' in content or '## ' in content or ('**' in content) or ('__' in content)
                if is_markdown:
                    text_widget.setMarkdown(content)
                else:
                    text_widget.setPlainText(content)
            else:
                text_widget.setPlainText(tr('errors.description_http_error_code', code=response.status_code))
        except Exception as e:
            text_widget.setPlainText(tr('errors.description_load_error_details', error=str(e)))

    def _assign_mod_to_slot(self, slot_frame, mod_data, save_state=True):
        slot_frame.assigned_mod = mod_data
        if slot_frame.content_widget:
            slot_frame.content_widget.setParent(None)
            slot_frame.content_widget = None
            slot_frame.mod_icon = None
        is_large_slot = slot_frame.chapter_id < 0
        title_label = None
        if slot_frame.layout():
            for i in range(slot_frame.layout().count()):
                item = slot_frame.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QLabel):
                    title_label = item.widget()
                    break
        if is_large_slot and title_label:
            title_label.setVisible(False)
        new_content_widget = QWidget()
        new_content_layout = QHBoxLayout(new_content_widget)
        new_content_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        mod_icon = QLabel()
        mod_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        border_color = self.local_config.get('custom_color_border') or 'white'
        mod_icon.setStyleSheet(f'border: 1px solid {border_color};')
        text_vbox = QVBoxLayout()
        text_vbox.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        name_label = QLabel()
        status_text, status_color = ('', 'gray')
        is_local_mod = getattr(mod_data, 'key', '').startswith('local_')
        if is_large_slot:
            new_content_layout.setContentsMargins(8, 0, 8, 0)
            new_content_layout.setSpacing(10)
            mod_icon.setFixedSize(48, 48)
            text_vbox.setSpacing(2)
            name_label.setWordWrap(True)
            name_label.setStyleSheet('font-weight: bold; font-size: 13px; border: none; background: transparent;')
            name_label.setText(mod_data.name)
            if is_local_mod:
                status_text, status_color = (tr('status.local_mod'), '#FFD700')
            else:
                needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_available'), 'orange') if needs_update else (tr('status.version_current'), 'lightgreen')
            version_label = QLabel(status_text)
            version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
        else:
            new_content_layout.setContentsMargins(8, 0, 8, 0)
            new_content_layout.setSpacing(8)
            mod_icon.setFixedSize(40, 40)
            text_vbox.setSpacing(1)
            name_label.setStyleSheet('font-weight: bold; font-size: 11px; border: none; background: transparent;')
            original_name = mod_data.name
            display_name = original_name[:7] + '...' if len(original_name) > 10 else original_name
            name_label.setText(display_name)
            name_label.setToolTip(original_name)
            if is_local_mod:
                status_text, status_color = (tr('status.local'), '#FFD700')
            else:
                needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_short'), 'orange') if needs_update else (tr('status.current_short'), 'lightgreen')
            version_label = QLabel(status_text)
            version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
        load_mod_icon_universal(mod_icon, mod_data, 32)
        new_content_layout.addWidget(mod_icon)
        text_vbox.addWidget(name_label)
        text_vbox.addWidget(version_label)
        new_content_layout.addLayout(text_vbox)
        new_content_layout.addStretch()
        slot_frame.layout().addWidget(new_content_widget)
        slot_frame.content_widget = new_content_widget
        slot_frame.mod_icon = mod_icon
        self._update_mod_widgets_slot_status()
        if slot_frame.chapter_id == -1:
            self._update_chapter_indicators(mod_data)
        self._update_action_button_state()
        if save_state:
            self._save_slots_state()

    def _calculate_optimal_font_size(self, text, max_width, max_height):
        from PyQt6.QtGui import QFontMetrics
        for font_size in range(10, 6, -1):
            font = QFont()
            font.setPointSize(font_size)
            font.setBold(True)
            metrics = QFontMetrics(font)
            text_rect = metrics.boundingRect(0, 0, max_width, max_height, Qt.TextFlag.TextWordWrap, text)
            if text_rect.width() <= max_width and text_rect.height() <= max_height:
                return font_size
        return 7

    def _update_mod_widgets_slot_status(self):
        if not hasattr(self, 'installed_mods_layout') or self.installed_mods_layout is None:
            return
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    is_in_slot = self._find_mod_in_slots(widget.mod_data) is not None
                    widget.set_in_slot(is_in_slot)

    def _refresh_all_slot_status_displays(self):
        for slot_frame in self.slots.values():
            if slot_frame.assigned_mod and slot_frame.content_widget:
                self._refresh_slot_status_display(slot_frame)
                if hasattr(slot_frame, 'mod_icon') and slot_frame.mod_icon:
                    load_mod_icon_universal(slot_frame.mod_icon, slot_frame.assigned_mod, 32)

    def _refresh_slot_status_display(self, slot_frame):
        if not slot_frame.assigned_mod or not slot_frame.content_widget:
            return
        mod_data = slot_frame.assigned_mod
        version_label = None
        content_layout = slot_frame.content_widget.layout()
        if content_layout:
            for i in range(content_layout.count()):
                item = content_layout.itemAt(i)
                if item and item.layout():
                    text_layout = item.layout()
                    if text_layout and text_layout.count() >= 2:
                        version_item = text_layout.itemAt(1)
                        if version_item and version_item.widget() and isinstance(version_item.widget(), QLabel):
                            version_label = version_item.widget()
                            break
        if version_label:
            is_large_slot = slot_frame.chapter_id < 0
            is_local_mod = getattr(mod_data, 'key', '').startswith('local_')
            if is_local_mod:
                if is_large_slot:
                    status_text, status_color = (tr('status.local_mod'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
                else:
                    status_text, status_color = (tr('status.local'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            elif is_large_slot:
                needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_available'), 'orange') if needs_update else (tr('status.version_current'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
            else:
                needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_short'), 'orange') if needs_update else (tr('status.current_short'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            version_label.setText(status_text)

    def _delete_mod_files(self, mod_data):
        try:
            if not hasattr(self, 'mods_dir') or not os.path.exists(self.mods_dir):
                print('Mods directory not found')
                return
            mod_folder_found = None
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if os.path.exists(config_path):
                    try:
                        config_data = self._read_json(config_path)
                        if config_data and config_data.get('mod_key') == mod_data.key:
                            mod_folder_found = folder_path
                            break
                    except Exception as e:
                        logging.warning(f'Failed to read installed mod config {config_path}: {e}')
                        continue
            if mod_folder_found and os.path.exists(mod_folder_found):
                shutil.rmtree(mod_folder_found)
            else:
                print(f'Mod folder not found for mod: {mod_data.name}')
        except Exception as e:
            print(f'Error deleting mod files: {e}')
            raise

    def _remove_mod_from_all_slots(self, mod_data):
        if not mod_data:
            return
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return
        for slot_frame in self.slots.values():
            if slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
        self._save_slots_state()

    def _populate_search_mods(self):
        self._update_filtered_mods()

    def _update_filtered_mods(self):
        if not hasattr(self, 'all_mods') or not self.all_mods:
            self.filtered_mods = []
            self._update_mod_display()
            return
        selected_tags = []
        if hasattr(self, 'tag_translation') and self.tag_translation.isChecked():
            selected_tags.append('translation')
        if hasattr(self, 'tag_customization') and self.tag_customization.isChecked():
            selected_tags.append('customization')
        if hasattr(self, 'tag_gameplay') and self.tag_gameplay.isChecked():
            selected_tags.append('gameplay')
        if hasattr(self, 'tag_other') and self.tag_other.isChecked():
            selected_tags.append('other')
        selected_modtype = ''
        if hasattr(self, 'modtype_combo'):
            selected_modtype = self.modtype_combo.currentData() or ''
        self.filtered_mods = []
        for mod in self.all_mods:
            if getattr(mod, 'hide_mod', False) in [True, 'true', 'True', 1]:
                continue
            if getattr(mod, 'ban_status', False) in [True, 'true', 'True', 1]:
                continue
            mod_status = getattr(mod, 'status', 'approved')
            if mod_status not in ['approved', 'pending']:
                continue
            if getattr(mod, 'key', '').startswith('local_'):
                continue
            if selected_tags:
                mod_tags = getattr(mod, 'tags', []) or []
                if not all((tag in mod_tags for tag in selected_tags)):
                    continue
            if selected_modtype:
                mod_modtype = getattr(mod, 'modtype', 'deltarune')
                if mod_modtype != selected_modtype:
                    continue
            if hasattr(self, 'search_text') and self.search_text:
                search_text_lower = self.search_text.lower()
                mod_name = getattr(mod, 'name', '').lower()
                mod_tagline = getattr(mod, 'tagline', '').lower()
                if search_text_lower not in mod_name and search_text_lower not in mod_tagline:
                    continue
            self.filtered_mods.append(mod)
        self._sort_filtered_mods()
        self.current_page = 1
        self._update_mod_display()

    def _sort_filtered_mods(self):
        if not hasattr(self, 'sort_combo') or not self.filtered_mods:
            return
        sort_type = self.sort_combo.currentIndex()
        reverse = not self.sort_ascending
        if sort_type == 0:
            self.filtered_mods.sort(key=lambda mod: getattr(mod, 'downloads', 0), reverse=reverse)
        elif sort_type == 1:
            self.filtered_mods.sort(key=lambda mod: self._parse_date(getattr(mod, 'last_updated', '')), reverse=reverse)
        elif sort_type == 2:
            self.filtered_mods.sort(key=lambda mod: self._parse_date(getattr(mod, 'created_date', '')), reverse=reverse)

    def _parse_date(self, date_str):
        if not date_str or date_str == 'N/A':
            return (0, 0, 0, 0, 0)
        try:
            parts = date_str.split(' ')
            if len(parts) >= 2:
                date_part = parts[0]
                time_part = parts[1]
                day, month, year = map(int, date_part.split('.'))
                hour, minute = map(int, time_part.split(':'))
                if year < 50:
                    year += 2000
                else:
                    year += 1900
                return (year, month, day, hour, minute)
        except Exception as e:
            logging.debug(f"_parse_date failed for '{date_str}': {e}")
            pass
        return (0, 0, 0, 0, 0)

    def _update_mod_display(self):
        clear_layout_widgets(self.mod_list_layout, keep_last_n=1)
        start_index = (self.current_page - 1) * self.mods_per_page
        end_index = start_index + self.mods_per_page
        current_page_mods = self.filtered_mods[start_index:end_index]
        self.mod_list_widget.setUpdatesEnabled(False)
        try:
            for mod in current_page_mods:
                plaque = ModPlaqueWidget(mod, parent=self)
                plaque.install_requested.connect(self._on_mod_install_requested)
                plaque.uninstall_requested.connect(self._on_mod_uninstall_requested)
                plaque.clicked.connect(self._on_mod_clicked)
                plaque.details_requested.connect(self._on_mod_details_requested)
                plaque.install_button.setEnabled(not self.is_installing)
                self.mod_list_layout.insertWidget(self.mod_list_layout.count() - 1, plaque)
        finally:
            self.mod_list_widget.setUpdatesEnabled(True)
        self._update_pagination_controls()

    def _update_pagination_controls(self):
        if not hasattr(self, 'page_label') or not hasattr(self, 'prev_page_btn') or (not hasattr(self, 'next_page_btn')):
            return
        total_mods = len(self.filtered_mods)
        total_pages = max(1, (total_mods - 1) // self.mods_per_page + 1) if total_mods > 0 else 1
        self.page_label.setText(tr('ui.page_label', current=self.current_page, total=total_pages))
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < total_pages)

    def _on_mod_install_requested(self, mod):
        if self.is_installing:
            return
        self._install_single_mod(mod)

    def _install_single_mod(self, mod):
        try:
            if self.is_installing:
                return
            available_chapters = []
            if mod.modtype == 'undertale':
                if mod.files.get('undertale'):
                    available_chapters.append(0)
            elif mod.modtype == 'deltarunedemo':
                if mod.files.get('demo'):
                    available_chapters.append(-1)
            else:
                for chapter_id in range(0, 5):
                    chapter_data = mod.get_chapter_data(chapter_id)
                    if chapter_data:
                        available_chapters.append(chapter_id)
            if not available_chapters:
                debug_info = f'Mod type: {mod.modtype}, Files keys: {list(mod.files.keys())}'
                print(f'Debug: {debug_info}')
                QMessageBox.warning(self, tr('errors.error'), tr('errors.mod_no_files', mod_name=mod.name) + f'\n\nDebug: {debug_info}')
                return
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            self.is_installing = True
            self._set_install_buttons_enabled(False)
            self.action_button.setText(tr('ui.cancel_button'))
            self._install_op_id = getattr(self, '_install_op_id', 0) + 1
            op_id = self._install_op_id
            was_installed_before = self._is_mod_installed(mod.key)
            self.current_install_thread = InstallModsThread(self, install_tasks, was_installed_before)
            self.install_thread = self.current_install_thread
            self.install_thread.progress.connect(lambda v, oid=op_id: self._on_install_progress_token(v, oid))
            self.install_thread.status.connect(lambda msg, col, oid=op_id: self._on_install_status_token(msg, col, oid))
            self.install_thread.finished.connect(lambda ok, oid=op_id: self._on_install_finished_token(ok, oid))
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            try:
                self.update_status_signal.emit(tr('status.preparing_download'), UI_COLORS['status_warning'])
            except Exception:
                pass
            self._update_action_button_state()
            self.install_thread.start()
        except Exception as e:
            print(f'Error installing mod {mod.name}: {e}')
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_install_failed', error=str(e)))

    def _on_install_progress_token(self, value: int, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.is_installing:
            self.progress_bar.setValue(value)

    def _on_install_status_token(self, message: str, color: str, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.is_installing:
            self._update_status(message, color)

    def _on_install_finished_token(self, success: bool, op_id: int):
        if getattr(self, '_install_op_id', 0) != op_id:
            return
        self._on_single_mod_install_finished(success)

    def _on_single_mod_install_finished(self, success):
        was_installed_before = False
        if hasattr(self, 'current_install_thread') and self.current_install_thread:
            was_installed_before = getattr(self.current_install_thread, 'was_installed_before', False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        if success:
            self.update_status_signal.emit(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        else:
            if getattr(self, '_operation_cancelled', False):
                try:
                    self._operation_cancelled = False
                except Exception:
                    pass
            else:
                self.update_status_signal.emit(tr('status.mod_install_error'), UI_COLORS['status_error'])
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        if success:
            self._load_local_mods_from_folders()
            self._update_search_mod_plaques()
            if hasattr(self, '_update_installed_mods_display'):
                self._update_installed_mods_display()
            QTimer.singleShot(100, self._refresh_specific_mod_widget_after_update)
            if not was_installed_before:
                QMessageBox.information(self, tr('dialogs.mod_installed_title'), tr('dialogs.mod_installed_apply_info'))
            self.update_status_signal.emit(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        self._update_action_button_state()

    def _refresh_specific_mod_widget_after_update(self):
        if not hasattr(self, 'current_install_thread') or not self.current_install_thread:
            return
        install_tasks = getattr(self.current_install_thread, 'install_tasks', [])
        if not install_tasks:
            return
        mod_data_tuple = install_tasks[0]
        mod_to_update = mod_data_tuple[0]
        mod_key_to_find = getattr(mod_to_update, 'key', None)
        if not mod_key_to_find:
            return
        if hasattr(self, 'installed_mods_layout'):
            for i in range(self.installed_mods_layout.count()):
                item = self.installed_mods_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = getattr(widget.mod_data, 'key', None)
                        if widget_mod_key == mod_key_to_find:
                            widget.update_status()
                            break

    def _on_mod_uninstall_requested(self, mod):
        if self.is_installing:
            return
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, tr('dialogs.delete_confirmation'), tr('dialogs.delete_mod_confirmation', mod_name=mod.name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._uninstall_single_mod(mod)

    def _uninstall_single_mod(self, mod):
        try:
            self._delete_mod_files(mod)
            self._remove_mod_from_all_slots(mod)
            self._update_search_mod_plaques()
            if hasattr(self, '_update_installed_mods_display'):
                self._update_installed_mods_display()
        except Exception as e:
            print(f'Error uninstalling mod {mod.name}: {e}')
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mod_delete_failed', error=str(e)))

    def _update_search_mod_plaques(self):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.update_installation_status()

    def _on_mod_clicked(self, mod):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget) and widget.mod_data == mod:
                    self._clear_all_mod_selections()
                    widget.set_selected(True)
                    break

    def _on_mod_details_requested(self, mod):
        self._show_mod_details_dialog(mod)

    def _clear_all_mod_selections(self):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.set_selected(False)

    def _update_mod(self, mod_data):
        if self.is_installing:
            return
        self._install_single_mod(mod_data)

    def _on_mod_install_finished(self, success):
        self.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        self.progress_bar.setVisible(False)
        self._update_action_button_state()
        if success:
            self.update_status_signal.emit(tr('status.mod_installed_success'), UI_COLORS['status_success'])
            self._update_installed_mods_display()
            self._update_mod_widgets_slot_status()
            self._update_action_button_state()
            self._refresh_slots_content()
            if hasattr(self, 'pending_updates') and self.pending_updates:
                next_mod = self.pending_updates.pop(0)
                self.update_status_signal.emit(tr('status.updating_mod', mod_name=next_mod.name), UI_COLORS['status_warning'])
                self._update_mod(next_mod)
        else:
            self.update_status_signal.emit(tr('status.mod_install_error'), UI_COLORS['status_error'])
            if hasattr(self, 'pending_updates'):
                self.pending_updates = []

    def _prompt_for_mods_dir(self):
        current_mods_dir = self.mods_dir
        new_parent_dir = QFileDialog.getExistingDirectory(self, tr('ui.select_new_mods_folder'), os.path.dirname(current_mods_dir))
        if not new_parent_dir or os.path.dirname(current_mods_dir) == new_parent_dir:
            return
        new_mods_dir = os.path.join(new_parent_dir, 'mods')
        if os.path.exists(new_mods_dir):
            QMessageBox.critical(self, tr('errors.error'), tr('errors.mods_folder_exists', dir=new_parent_dir))
            return
        try:
            self.update_status_signal.emit(tr('status.moving_mods_folder'), UI_COLORS['status_warning'])
            QApplication.processEvents()
            shutil.move(current_mods_dir, new_mods_dir)
            self.mods_dir = new_mods_dir
            self.local_config['mods_dir_path'] = new_parent_dir
            self._write_local_config()
            QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.mods_folder_moved', path=new_mods_dir))
            self.update_status_signal.emit(tr('status.mods_folder_location_changed'), UI_COLORS['status_success'])
        except Exception as e:
            QMessageBox.critical(self, tr('dialogs.move_error'), tr('dialogs.mods_folder_move_failed', error=str(e)))
            self.mods_dir = current_mods_dir
            self.update_status_signal.emit(tr('status.mods_folder_change_error'), UI_COLORS['status_error'])

    def _update_change_path_button_text(self):
        self.change_path_button.setText(self.game_mode.path_change_button_text)

    def _full_install_tooltip(self) -> str:
        if platform.system() == 'Darwin':
            return tr('tooltips.macos_install_unavailable')
        return tr('tooltips.full_install_instructions')

    def _on_toggle_full_install(self, state):
        self.is_full_install = bool(state)
        if platform.system() == 'Darwin' and self.is_full_install:
            QMessageBox.information(self, tr('dialogs.unavailable'), tr('dialogs.macos_install_unavailable'))
            self.full_install_checkbox.blockSignals(True)
            self.full_install_checkbox.setChecked(False)
            self.full_install_checkbox.blockSignals(False)
            return
        self._update_action_button_state()

    def _save_window_geometry(self):
        geom_ba = self.saveGeometry()
        self.local_config['window_geometry'] = geom_ba.toHex().data().decode()
        self._write_local_config()

    def load_font(self):
        self.custom_font_family = None
        self._font_families_chain = list(DEFAULT_FONT_FALLBACK_CHAIN)
        font_path = resource_path('fonts/main.ttf')
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    self.custom_font_family = families[0]
                else:
                    pass
            else:
                pass
        else:
            pass

    def apply_theme(self):
        theme = THEMES['default']
        background_path = None
        background_disabled = self.local_config.get('background_disabled', False)
        if self.background_movie is not None:
            self.background_movie.stop()
            self.background_movie.deleteLater()
            self.background_movie = None
        self.background_pixmap = None
        if not background_disabled:
            background_path = self.local_config.get('custom_background_path') or resource_path(theme.get('background', ''))
            if background_path:
                self._bg_loader = BgLoader(background_path, self.size())
                self._bg_loader.loaded.connect(self._on_bg_ready)
                self._bg_loader.start()
        user_bg_hex = self.local_config.get('custom_color_background')
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            frame_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            frame_bg_color = 'rgba(0, 0, 0, 150)'
        button_color = self.local_config.get('custom_color_button') or theme['colors']['button']
        border_color = self.local_config.get('custom_color_border') or theme['colors']['border']
        button_hover_color = self.local_config.get('custom_color_button_hover') or theme['colors']['button_hover']
        main_text_color = self.local_config.get('custom_color_text') or theme['colors']['text']
        base_family = self.custom_font_family or theme['font_family']
        families = [base_family] + [f for f in self._font_families_chain if f != base_family]
        font_family_main = families[0]
        font_size_main = theme['font_size_main']
        font_size_small = theme['font_size_small']
        status_font = QFont(font_family_main, font_size_small)
        self.status_label.setFont(status_font)
        explicit_color_widgets = [getattr(self, 'telegram_button', None), getattr(self, 'discord_button', None)]
        explicit_colors = [UI_COLORS['link'], UI_COLORS['social_discord']]
        for widget, color in zip(explicit_color_widgets, explicit_colors):
            if widget is not None:
                widget.setStyleSheet(f'color: {color};')
        qss_font_chain = '", "'.join(families)
        style_sheet = f'''\n                    QFrame#bottom_widget, QFrame#settings_widget {{ background-color: {frame_bg_color}; }}\n                    QWidget {{ font-family: "{qss_font_chain}"; outline: none; font-size: {font_size_main}pt; color: {main_text_color}; background-color: transparent; }}\n                    QDialog, QMessageBox {{ font-family: "{qss_font_chain}"; font-size: {font_size_small}pt; color: {main_text_color}; background-color: {frame_bg_color}; border: 3px solid {border_color}; }}\n                    QDialog > QLabel, QMessageBox > QLabel {{ background: transparent; font-size: {font_size_small}pt; }}\n                    QDialog QPushButton, QMessageBox QPushButton {{ font-size: {font_size_small}pt; }}\n                    QPushButton {{ background-color: {button_color}; border: 2px solid {border_color}; color: {theme['colors']['button_text']}; padding: 5px; min-height: 30px; min-width: 100px; }}\n                    QPushButton:hover {{ background-color: {button_hover_color}; }}\n                    QPushButton:disabled, QComboBox:disabled {{ background-color: #333333; color: #888888; border: 2px solid #555555; }}\n                    QPushButton#addTranslationButton {{ min-width: 33px; min-height: 33px; padding: 2px; }}\n                    QComboBox {{ background-color: {button_color}; color: {theme['colors']['button_text']}; border: 2px solid {border_color}; padding: 4px; min-height: 30px; }}\n                    QComboBox QAbstractItemView {{ background-color: {button_color}; border: 2px solid {border_color}; color: {theme['colors']['button_text']}; selection-background-color: {button_hover_color}; }}\n                    QTextEdit, QTextBrowser {{ background-color: {frame_bg_color}; border: 2px solid {border_color}; }}\n                    QFrame#filters {{\n                        background-color: {frame_bg_color};\n                        border: 2px solid {border_color};\n                        padding: 4px 8px;\n                    }}\n                    QPushButton#sortOrderBtn {{\n                        min-width: 35px;\n                        max-width: 35px;\n                        padding-left: 0px;\n                        padding-right: 0px;\n                        background-color: {button_color};\n                        border: 2px solid {border_color};\n                        color: {theme['colors']['button_text']};\n                        font-weight: bold;\n                        font-size: 12px;\n                    }}\n                    QPushButton#sortOrderBtn:hover {{\n                        background-color: {button_hover_color};\n                    }}\n                    QPushButton#searchBtn {{\n                        min-width: 35px;\n                        max-width: 35px;\n                        min-height: 30px;\n                        max-height: 30px;\n                        padding-left: 0px;\n                        padding-right: 0px;\n                        background-color: {button_color};\n                        border: 2px solid {border_color};\n                        color: {theme['colors']['button_text']};\n                        font-weight: bold;\n                        font-size: 16px;\n                    }}\n                    QPushButton#searchBtn:hover {{\n                        background-color: {button_hover_color};\n                    }}\n                    QTextEdit, QTextBrowser {{ background-color: {frame_bg_color}; color: {main_text_color}; border: 2px solid {border_color}; min-height: 100px; }}\n                    QTabBar::tab {{ background-color: {button_color}; color: {theme['colors']['button_text']}; border: 2px solid {border_color}; padding: 5px; min-height: 25px; min-width: 80px; }}\n                    QTabBar::tab:selected, QTabBar::tab:hover {{ background-color: {button_hover_color}; }}\n                    QTabBar::tab:disabled {{ background-color: #333333; color: #888888; border: 2px solid #555555; }}\n                    QTabWidget::pane {{ background: transparent; border: 0px; }}\n                    QCheckBox:disabled {{ color: #888888; }}\n                    QCheckBox::indicator {{ width: 15px; height: 15px; background-color: {button_color}; border: 2px solid {border_color}; }}\n                    QCheckBox::indicator:checked {{ background-color: {('#ffffff' if not self.color_widgets['button_hover'].text() else button_hover_color)}; }}\n                    QCheckBox::indicator:disabled {{ background-color: #333333; border: 2px solid #555555; }}\n                    QPushButton:checked {{ background-color: {button_hover_color}; border: 2px solid {main_text_color}; }}\n            '''
        scroll_handle_color = self.local_config.get('custom_color_button') or 'white'
        scroll_groove_color = 'rgba(0, 0, 0, 40)'
        scroll_bar_qss = f'\n                QScrollBar:vertical {{\n                    border: none;\n                    background: {scroll_groove_color};\n                    width: 14px;\n                    margin: 0;\n                }}\n                QScrollBar::handle:vertical {{\n                    background-color: {scroll_handle_color};\n                    min-height: 25px;\n                }}\n                QScrollBar:horizontal {{\n                    border: none;\n                    background: {scroll_groove_color};\n                    height: 14px;\n                    margin: 0;\n                }}\n                QScrollBar::handle:horizontal {{\n                    background-color: {scroll_handle_color};\n                    min-width: 25px;\n                }}\n            '
        style_sheet += scroll_bar_qss
        app_inst = QApplication.instance()
        (app_inst if isinstance(app_inst, QApplication) else self).setStyleSheet(style_sheet)
        for widget in self.findChildren(QWidget):
            style = widget.style()
            if style:
                style.unpolish(widget)
                style.polish(widget)
        self._update_mod_plaques_styles()
        self.update()

    def _configure_hidden_tab_bar(self, tab_widget: QTabWidget):
        bar = tab_widget.tabBar()
        if bar:
            bar.hide()
            bar.setEnabled(False)
            bar.setMaximumSize(0, 0)
            bar.setMinimumSize(0, 0)
            bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _init_save_manager_ui(self):
        lay = QVBoxLayout(self.save_manager_widget)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        top = QHBoxLayout()
        top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.save_back_btn = QPushButton(tr('ui.back_button'))
        self.save_back_btn.clicked.connect(self._hide_save_manager)
        self.save_back_btn.setVisible(False)
        self.change_save_path_btn = QPushButton(tr('buttons.change_save_path'))
        self.change_save_path_btn.clicked.connect(self._prompt_for_save_path)
        top.addWidget(self.change_save_path_btn)
        lay.addLayout(top)
        self.save_tabs = NoScrollTabWidget()
        self._slot_labels = {}
        for ch in range(1, 5):
            tab = QWidget()
            v = QVBoxLayout(tab)
            for s in range(3):
                lbl = QLabel(self._slot_placeholder(False))
                lbl = ClickableLabel(ch, s, self._slot_placeholder(False))
                lbl.setObjectName(f'slot_{ch}_{s}')
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setMinimumWidth(300)
                lbl.setStyleSheet('border:1px solid white; background-color: rgba(0,0,0,128); padding:4px;')
                lbl.clicked.connect(self._on_save_manager_slot_clicked)
                lbl.doubleClicked.connect(self._on_slot_double_clicked)
                v.addWidget(lbl)
                self._slot_labels[ch, s] = lbl
            v.addStretch()
            self.save_tabs.addTab(tab, tr('ui.chapter_tab_title', chapter_num=ch))
        self._configure_hidden_tab_bar(self.save_tabs)
        chapter_bar = QHBoxLayout()
        chapter_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chapter_bar.setSpacing(2)
        chapter_bar.setContentsMargins(0, 0, 0, 0)
        self._chapter_buttons = []
        for ch in range(1, 5):
            btn = QPushButton(tr('ui.chapter_button_title', chapter_num=ch))
            btn.setCheckable(True)
            btn.setMinimumWidth(80)
            if ch == 1:
                btn.setChecked(True)
            btn.clicked.connect(lambda _checked, idx=ch - 1: self.save_tabs.setCurrentIndex(idx))
            self._chapter_buttons.append(btn)
            chapter_bar.addWidget(btn)
        lay.addLayout(chapter_bar)

        def _sync_buttons(index: int):
            for i, b in enumerate(self._chapter_buttons):
                b.setChecked(i == index)
        self.save_tabs.currentChanged.connect(_sync_buttons)
        lay.addWidget(self.save_tabs)
        self.collection_name_lbl = QLabel('')
        self.collection_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collection_name_lbl.setVisible(False)
        lay.addWidget(self.collection_name_lbl)
        bottom = QHBoxLayout()
        bottom.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.left_col_btn = QPushButton('←')
        self.left_col_btn.clicked.connect(lambda: self._navigate_collection(-1))
        bottom.addWidget(self.left_col_btn)
        self.switch_collection_btn = QPushButton(tr('buttons.additional_slots'))
        self.switch_collection_btn.clicked.connect(self._toggle_collection_view)
        bottom.addWidget(self.switch_collection_btn)
        self.right_col_btn = QPushButton('→')
        self.right_col_btn.clicked.connect(lambda: self._navigate_collection(1))
        bottom.addWidget(self.right_col_btn)
        lay.addLayout(bottom)
        self.rename_collection_btn = QPushButton(tr('buttons.rename_collection'))
        self.rename_collection_btn.clicked.connect(self._rename_current_collection)
        self.delete_collection_btn = QPushButton(tr('buttons.delete_collection'))
        self.delete_collection_btn.clicked.connect(self._delete_current_collection)
        self.rename_collection_btn.setVisible(False)
        self.delete_collection_btn.setVisible(False)
        copy_bar = QHBoxLayout()
        copy_bar.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        copy_bar.addStretch()
        self.copy_from_main_btn = QPushButton(tr('buttons.copy_from_main'))
        self.copy_from_main_btn.clicked.connect(lambda: self._copy_between_storages(to_collection=True))
        copy_bar.addWidget(self.copy_from_main_btn)
        self.copy_to_main_btn = QPushButton(tr('buttons.copy_to_main'))
        self.copy_to_main_btn.clicked.connect(lambda: self._copy_between_storages(to_collection=False))
        copy_bar.addWidget(self.copy_to_main_btn)
        copy_bar.addStretch()
        lay.addLayout(copy_bar)
        self.slot_actions = QHBoxLayout()
        self.slot_actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.show_btn = QPushButton(tr('buttons.show'))
        self.erase_btn = QPushButton(tr('buttons.erase'))
        self.import_btn = QPushButton(tr('buttons.import'))
        self.export_btn = QPushButton(tr('buttons.export'))
        for b in (self.show_btn, self.erase_btn, self.import_btn, self.export_btn):
            b.setVisible(False)
            self.slot_actions.addWidget(b)
        self.show_btn.clicked.connect(self._action_show_save)
        self.erase_btn.clicked.connect(self._action_delete_save)
        self.import_btn.clicked.connect(lambda: self._action_import_export(True))
        self.export_btn.clicked.connect(lambda: self._action_import_export(False))
        lay.addLayout(self.slot_actions)
        top.addWidget(self.rename_collection_btn)
        top.addWidget(self.delete_collection_btn)
        self.save_tabs.currentChanged.connect(lambda _: self._on_chapter_tab_changed())
        self.save_manager_widget.installEventFilter(self)
        self._update_slot_highlight()

    def _hide_save_manager(self):
        self.save_manager_widget.setVisible(False)
        self.is_save_manager_view = False
        if self.is_settings_view:
            self.settings_widget.setVisible(True)
        else:
            self.main_tab_widget.setVisible(True)
            self.bottom_widget.setVisible(True)

    def _slot_placeholder(self, active: bool) -> str:
        return tr('ui.placeholder_format') if active else tr('status.empty_save_slot')

    def _clear_selected_slot(self):
        self.selected_slot = None
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def eventFilter(self, obj, ev):
        if obj is self.save_manager_widget and ev.type() == QEvent.Type.MouseButtonPress:
            click_pos = ev.pos()
            inside = any((lbl.rect().contains(lbl.mapFrom(self.save_manager_widget, click_pos)) for lbl in self._slot_labels.values()))
            if not inside:
                self._clear_selected_slot()
        return super().eventFilter(obj, ev)

    def _update_slot_action_bar(self):
        in_main = self.current_collection_idx.get(self.save_tabs.currentIndex() + 1, -1) == -1
        visible = self.selected_slot is not None
        for b in (self.show_btn, self.import_btn, self.erase_btn, self.export_btn):
            b.setVisible(visible)
        has_data = False
        if self.selected_slot:
            ch, s = self.selected_slot
            idx = self.current_collection_idx.get(ch, -1)
            base = self._get_collection_path(ch, idx)
            fp = os.path.join(base, f'filech{ch}_{s}')
            has_data = os.path.exists(fp) and os.path.getsize(fp) > 0
        self.erase_btn.setEnabled(has_data)
        self.export_btn.setEnabled(has_data)
        self.copy_from_main_btn.setEnabled(not in_main)
        self.copy_to_main_btn.setEnabled(not in_main)

    def _on_slot_double_clicked(self, chapter: int, slot: int):
        idx = self.current_collection_idx.get(chapter, -1)
        base = self._get_collection_path(chapter, idx)
        fp = os.path.join(base, f'filech{chapter}_{slot}')
        if not (os.path.exists(fp) and os.path.getsize(fp) > 0):
            return
        dlg = SaveEditorDialog(fp, self)
        if dlg.exec():
            self._refresh_save_slots()

    def _on_save_manager_slot_clicked(self, chapter: int, slot: int):
        self.selected_slot = (chapter, slot)
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _update_slot_highlight(self):
        user_bg = self.local_config.get('custom_color_background')
        if user_bg and self._is_valid_hex_color(user_bg):
            slot_bg = f"#80{user_bg.lstrip('#')}"
        else:
            slot_bg = '#80000000'
        for (ch, sl), lbl in self._slot_labels.items():
            if self.selected_slot == (ch, sl):
                lbl.setStyleSheet(f'border:2px solid white; background-color: {slot_bg}; padding:4px;')
            else:
                lbl.setStyleSheet(f'border:1px solid white; background-color: {slot_bg}; padding:4px;')

    def _collection_regex(self, chapter: int):
        return re.compile(f'(.+?)_(\\d+)_{chapter}$')

    def _list_collections(self, chapter: int) -> list[str]:
        cols = []
        rx = self._collection_regex(chapter)
        if not (self.save_path and os.path.isdir(self.save_path)):
            return cols
        for entry in os.listdir(self.save_path):
            m = rx.match(entry)
            if m and os.path.isdir(os.path.join(self.save_path, entry)):
                cols.append(entry)

        def _index(name: str) -> int:
            m = rx.match(name)
            return int(m.group(2)) if m else 10000
        cols.sort(key=_index)
        return cols

    def _get_collection_path(self, chapter: int, idx: int) -> str:
        if idx == -1:
            return self.save_path
        cols = self._list_collections(chapter)
        if 0 <= idx < len(cols):
            return os.path.join(self.save_path, cols[idx])
        return ''

    def _return_from_save_manager(self):
        self._hide_save_manager()
        self.settings_button.setText(tr('ui.settings_title'))
        try:
            self.settings_button.clicked.disconnect(self._return_from_save_manager)
        except TypeError:
            pass
        self.settings_button.clicked.connect(self._toggle_settings_view)

    def _on_configure_saves_click(self):
        if not self._find_and_validate_save_path():
            return
        self.is_save_manager_view = True
        self.main_tab_widget.setVisible(False)
        self.bottom_widget.setVisible(False)
        self.settings_widget.setVisible(False)
        self.save_manager_widget.setVisible(True)
        self.selected_slot = None
        self._refresh_save_slots()
        self.update_status_signal.emit(tr('status.save_path_info', save_path=self.save_path), UI_COLORS['status_info'])
        self.settings_button.setText(tr('ui.back_button'))
        try:
            self.settings_button.clicked.disconnect(self._toggle_settings_view)
        except TypeError:
            pass
        self.settings_button.clicked.connect(self._return_from_save_manager)

    def _refresh_save_slots(self):
        if not (self.save_path and os.path.isdir(self.save_path)):
            return
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        base_path = self._get_collection_path(chapter, idx) or self.save_path
        for s in range(3):
            fp = os.path.join(base_path, f'filech{chapter}_{s}')
            active = os.path.exists(fp) and os.path.getsize(fp) > 0
            if active:
                try:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.read().splitlines()
                    nickname = lines[0] if len(lines) > 0 else '???'
                    currency = lines[10] if len(lines) > 10 else '0'
                except Exception:
                    nickname, currency = ('???', '0')
                fin_idx = SAVE_SLOT_FINISH_MAP.get(s, -1)
                fin_fp = os.path.join(base_path, f'filech{chapter}_{fin_idx}')
                finished = os.path.exists(fin_fp) and os.path.getsize(fin_fp) > 0
                status = tr('status.completed_save') if finished else tr('status.incomplete_save')
                text = tr('ui.save_info', nickname=nickname, currency=currency, status=status)
            else:
                text = self._slot_placeholder(False)
            self._slot_labels[chapter, s].setText(text)
        self._update_collection_ui()
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _find_and_validate_save_path(self) -> bool:
        if is_valid_save_path(self.save_path):
            return True
        default_path = get_default_save_path()
        if is_valid_save_path(default_path):
            self.save_path = default_path
            self.local_config['save_path'] = self.save_path
            self._write_local_config()
            return True
        return self._prompt_for_save_path()

    def _prompt_for_save_path(self) -> bool:
        if not (path := QFileDialog.getExistingDirectory(self, tr('ui.select_deltarune_saves_folder'))):
            return False
        if not is_valid_save_path(path):
            QMessageBox.warning(self, tr('errors.empty_folder_title'), tr('errors.empty_folder_message'))
            return False
        self.save_path = path
        self.local_config['save_path'] = self.save_path
        self._write_local_config()
        return True

    def _toggle_collection_view(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            cols = self._list_collections(chapter)
            if not cols and (not self._create_new_collection(chapter)):
                return
            self.current_collection_idx[chapter] = 0
        else:
            self.current_collection_idx[chapter] = -1
        self._refresh_save_slots()

    def _navigate_collection(self, direction: int):
        chapter = self.save_tabs.currentIndex() + 1
        cols = self._list_collections(chapter)
        if not cols and direction > 0:
            if not self._create_new_collection(chapter):
                return
            cols = self._list_collections(chapter)
        if not cols:
            return
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            idx = 0
        else:
            idx += direction
        if idx < 0:
            idx = 0
        elif idx >= len(cols):
            if direction > 0 and self._create_new_collection(chapter):
                idx = len(cols)
            else:
                idx = len(cols) - 1
        self.current_collection_idx[chapter] = idx
        self.selected_slot = None
        self._refresh_save_slots()

    def _create_new_collection(self, chapter: int) -> bool:
        if (name := self._prompt_collection_name()) is None:
            return False
        idx = len(self._list_collections(chapter))
        folder = f'{name}_{idx}_{chapter}'
        try:
            os.makedirs(os.path.join(self.save_path, folder), exist_ok=False)
            return True
        except Exception as e:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.folder_creation_failed', error=str(e)))
            return False

    def _prompt_collection_name(self, default: str = 'Collection') -> Optional[str]:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('dialogs.new_collection'))
        v, e = (QVBoxLayout(dlg), QLineEdit())
        e.setMaxLength(20)
        e.setText(default)
        e.selectAll()
        v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        e.setFocus()
        return e.text().strip() or default if dlg.exec() == QDialog.DialogCode.Accepted else None

    def _update_collection_ui(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        in_col = idx != -1
        cols = self._list_collections(chapter)
        self.switch_collection_btn.setText(tr('buttons.main_slots') if in_col else tr('buttons.additional_slots'))
        self.left_col_btn.setEnabled(in_col and idx > 0)
        self.right_col_btn.setEnabled(in_col)
        self.rename_collection_btn.setVisible(in_col)
        self.delete_collection_btn.setVisible(in_col)
        self.copy_from_main_btn.setVisible(in_col)
        self.copy_to_main_btn.setVisible(in_col)
        if in_col and 0 <= idx < len(cols):
            self.collection_name_lbl.setText(cols[idx].rsplit('_', 2)[0])
            self.collection_name_lbl.setVisible(True)
        else:
            self.collection_name_lbl.setVisible(False)
        self.change_save_path_btn.setVisible(not in_col)

    def _on_chapter_tab_changed(self):
        ch = self.save_tabs.currentIndex() + 1
        if ch not in self.current_collection_idx:
            self.current_collection_idx[ch] = -1
        self.selected_slot = None
        self._refresh_save_slots()

    def _rename_current_collection(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            return
        cols = self._list_collections(chapter)
        old_folder = cols[idx]
        old_name = old_folder.rsplit('_', 2)[0]
        new_name, ok = QInputDialog.getText(self, tr('dialogs.change_collection_name'), tr('dialogs.new_name'), text=old_name)
        if not ok or not new_name.strip():
            return
        new_folder = f'{new_name.strip()}_{idx}_{chapter}'
        try:
            os.rename(os.path.join(self.save_path, old_folder), os.path.join(self.save_path, new_folder))
            self._refresh_save_slots()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.rename_failed', error=str(e)))

    def _delete_current_collection(self):
        chapter = self.save_tabs.currentIndex() + 1
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            return
        cols = self._list_collections(chapter)
        folder = cols[idx]
        if QMessageBox.question(self, tr('dialogs.delete_collection'), tr('dialogs.delete_collection_confirmation')) != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(os.path.join(self.save_path, folder))
            remaining = self._list_collections(chapter)
            for new_idx, f in enumerate(remaining):
                parts = f.rsplit('_', 2)
                cur_idx = int(parts[1])
                if cur_idx != new_idx:
                    new_folder = f'{parts[0]}_{new_idx}_{chapter}'
                    os.rename(os.path.join(self.save_path, f), os.path.join(self.save_path, new_folder))
            self.current_collection_idx[chapter] = -1
            self._refresh_save_slots()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.deletion_failed', error=str(e)))

    def _copy_between_storages(self, to_collection: bool):
        chapter = self.save_tabs.currentIndex() + 1
        if self.selected_slot is None or self.selected_slot[0] != chapter:
            slot_indices = range(3)
        else:
            slot_indices = [self.selected_slot[1]]
        idx = self.current_collection_idx.get(chapter, -1)
        if idx == -1:
            return
        src_dir = self.save_path if to_collection else self._get_collection_path(chapter, idx)
        dst_dir = self._get_collection_path(chapter, idx) if to_collection else self.save_path
        if not src_dir or not dst_dir:
            return
        prompt = (tr('dialogs.overwrite_all_3_slots_collection') if to_collection else tr('dialogs.overwrite_all_3_main_slots')) if self.selected_slot is None else tr('dialogs.overwrite_selected_slot_collection') if to_collection else tr('dialogs.overwrite_selected_main_slot')
        reply = QMessageBox.question(self, tr('dialogs.copy_confirmation'), prompt, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            for slot_idx in slot_indices:
                finish_idx = SAVE_SLOT_FINISH_MAP.get(slot_idx, -1)
                names = [f'filech{chapter}_{slot_idx}', f'filech{chapter}_{finish_idx}']
                for _name in names:
                    src = os.path.join(src_dir, _name)
                    dst = os.path.join(dst_dir, _name)
                    if os.path.exists(src):
                        shutil.copy2(src, dst)
                    elif os.path.exists(dst):
                        os.remove(dst)
            self._refresh_save_slots()
            self.update_status_signal.emit(tr('status.copying_completed'), UI_COLORS['status_success'])
        except Exception as e:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.copy_failed', error=str(e)))
            self.update_status_signal.emit(tr('status.copying_error'), UI_COLORS['status_error'])

    def _action_show_save(self):
        if not self.selected_slot:
            return
        ch, s = self.selected_slot
        idx = self.current_collection_idx.get(ch, -1)
        path = self._get_collection_path(ch, idx)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _action_delete_save(self):
        if not self.selected_slot:
            return
        ch, s = self.selected_slot
        idx = self.current_collection_idx.get(ch, -1)
        base = self._get_collection_path(ch, idx)
        fp = os.path.join(base, f'filech{ch}_{s}')
        if not os.path.exists(fp):
            return
        if QMessageBox.question(self, tr('dialogs.delete_save'), tr('dialogs.delete_save_confirmation')) != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(fp)
            self._refresh_save_slots()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.error'), str(e))

    def _action_import_export(self, is_import: bool):
        if not self.selected_slot:
            return
        ch, s = self.selected_slot
        idx = self.current_collection_idx.get(ch, -1)
        base_cur = self._get_collection_path(ch, idx)
        src_fp = os.path.join(base_cur, f'filech{ch}_{s}')
        choice, ok = QInputDialog.getItem(self, tr('dialogs.where_to') if not is_import else tr('dialogs.where_from'), tr('ui.select_storage'), [tr('dialogs.external_file') if is_import else tr('dialogs.external_folder'), tr('dialogs.additional_collection') if idx == -1 else tr('dialogs.main_slots')], 0, False)
        if not ok:
            return
        if choice in [tr('dialogs.external_file'), tr('dialogs.external_folder')]:
            if is_import:
                fp, _ = QFileDialog.getOpenFileName(self, tr('ui.select_save_file'), '', f'filech{ch}_*. (*)')
                if not fp:
                    return
                if not re.fullmatch(f'filech{ch}_[0-2]', os.path.basename(fp)):
                    QMessageBox.warning(self, tr('errors.invalid_file'), tr('errors.wrong_save_file'))
                    return
                shutil.copy2(fp, src_fp)
                fin_idx = SAVE_SLOT_FINISH_MAP.get(s, -1)
                fin_name = f'filech{ch}_{fin_idx}'
                fin_src = os.path.join(os.path.dirname(fp), fin_name)
                fin_dst = os.path.join(base_cur, fin_name)
                if os.path.exists(fin_src):
                    shutil.copy2(fin_src, fin_dst)
            else:
                dir_ = QFileDialog.getExistingDirectory(self, tr('dialogs.export_save_location'))
                if not dir_:
                    return
                if not os.path.exists(src_fp):
                    QMessageBox.warning(self, tr('errors.no_save'), tr('errors.empty_slot'))
                    return
                shutil.copy2(src_fp, dir_)
                fin_idx = SAVE_SLOT_FINISH_MAP.get(s, -1)
                fin_src = os.path.join(base_cur, f'filech{ch}_{fin_idx}')
                if os.path.exists(src_fp) and os.path.exists(fin_src):
                    shutil.copy2(fin_src, dir_)
        else:
            if idx == -1:
                cols = self._list_collections(ch)
                if not cols:
                    if QMessageBox.question(self, tr('dialogs.no_collections'), tr('dialogs.create_new_collection_question')) != QMessageBox.StandardButton.Yes:
                        return
                    if not self._create_new_collection(ch):
                        return
                    cols = self._list_collections(ch)
                sel, ok = QInputDialog.getItem(self, tr('ui.collections'), tr('ui.select'), cols, 0, False)
                if not ok:
                    return
                target_base = os.path.join(self.save_path, sel)
            else:
                target_base = self.save_path
            src_main_fp = os.path.join(base_cur, f'filech{ch}_{s}')
            target_main_fp = os.path.join(target_base, f'filech{ch}_{s}')
            fin_idx = SAVE_SLOT_FINISH_MAP.get(s, -1)
            fin_name = f'filech{ch}_{fin_idx}'
            src_fin_fp = os.path.join(base_cur, fin_name)
            target_fin_fp = os.path.join(target_base, fin_name)
            if is_import:
                if not os.path.exists(target_main_fp):
                    QMessageBox.warning(self, tr('errors.no_save'), tr('errors.no_import_save'))
                    return
                shutil.copy2(target_main_fp, src_main_fp)
                if os.path.exists(target_fin_fp):
                    shutil.copy2(target_fin_fp, src_fin_fp)
                elif os.path.exists(src_fin_fp):
                    os.remove(src_fin_fp)
            else:
                if not os.path.exists(src_main_fp):
                    QMessageBox.warning(self, tr('errors.no_save'), tr('errors.empty_slot'))
                    return
                shutil.copy2(src_main_fp, target_main_fp)
                if os.path.exists(src_fin_fp):
                    shutil.copy2(src_fin_fp, target_fin_fp)
                elif os.path.exists(target_fin_fp):
                    os.remove(target_fin_fp)
        self._refresh_save_slots()

    def _on_bg_ready(self, obj):
        if isinstance(obj, tuple):
            if obj[0] == 'gif':
                if self.background_movie is not None:
                    self.background_movie.stop()
                    self.background_movie.deleteLater()
                self.background_movie = QMovie(obj[1])
                self.background_movie.frameChanged.connect(self.update)
                self.background_movie.start()
                self.background_pixmap = None
            elif obj[0] == 'img':
                self.background_movie = None
                self.background_pixmap = QPixmap.fromImage(obj[1]).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.update()

    def _switch_settings_page(self, page: QWidget):
        if self.current_settings_page and self.current_settings_page is not page:
            self.settings_nav_stack.append(self.current_settings_page)
            if len(self.settings_nav_stack) > 20:
                self.settings_nav_stack.pop(0)
            self.current_settings_page.setVisible(False)
        page.setVisible(True)
        self.current_settings_page = page

    def _lock_window_size(self):
        try:
            sz = self.size()
            self._locked_size = sz
            self.setMinimumSize(sz)
            self.setMaximumSize(sz)
        except Exception:
            pass

    def _unlock_window_size(self):
        try:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self._locked_size = None
        except Exception:
            pass

    def _go_back(self):
        if hasattr(self, 'settings_nav_stack') and self.settings_nav_stack:
            prev = self.settings_nav_stack.pop()
            if self.current_settings_page:
                self.current_settings_page.setVisible(False)
            prev.setVisible(True)
            self.current_settings_page = prev
        else:
            self._toggle_settings_view()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.background_movie is not None:
            painter.drawPixmap(self.rect(), self.background_movie.currentPixmap())
        elif self.background_pixmap:
            painter.drawPixmap(self.rect(), self.background_pixmap)
        else:
            bg_color_str = self.local_config.get('custom_color_background') or 'rgba(0, 0, 0, 200)'
            try:
                painter.fillRect(self.rect(), QColor(bg_color_str))
            except Exception:
                painter.fillRect(self.rect(), QColor('rgba(0, 0, 0, 200)'))
        super().paintEvent(event)

    def _on_reset_settings_click(self):
        reply = QMessageBox.question(self, tr('dialogs.reset_settings_confirm_title'),
                                     tr('dialogs.reset_settings_confirm_text'),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._stop_background_music()
            language = self.local_config.get('language', 'en')

            # Удаляем кастомные файлы
            custom_files = [
                os.path.join(self.config_dir, 'custom_background_music.mp3'),
                os.path.join(self.config_dir, 'custom_background_music.wav'),
                os.path.join(self.config_dir, 'custom_startup_sound.mp3'),
                os.path.join(self.config_dir, 'custom_startup_sound.wav')
            ]
            for file_path in custom_files:
                if os.path.exists(file_path):
                    os.remove(file_path)

            # Сохраняем только язык
            self.local_config.clear()
            self.local_config['language'] = language

            # Сбрасываем все слоты
            config_keys_to_clear = [
                'saved_slots_deltarune',
                'saved_slots_deltarune_chapter',
                'saved_slots_deltarunedemo',
                'saved_slots_undertale'
            ]
            for key in config_keys_to_clear:
                if key in self.local_config:
                    del self.local_config[key]

            self._write_local_config()

            # Обновляем UI после сброса
            self._load_local_data()
            self._migrate_config_if_needed()

            # Сброс чекбоксов и связанных UI элементов
            self.launch_via_steam_checkbox.setChecked(False)
            self.use_custom_executable_checkbox.setChecked(False)
            self.chapter_mode_checkbox.setChecked(False)
            self.full_install_checkbox.setChecked(False)
            self.disable_background_checkbox.setChecked(False)
            self.disable_splash_checkbox.setChecked(False)

            self._update_custom_executable_ui()
            self._update_checkbox_visibility()

            self._clear_all_slots()
            self._save_slots_state()
            self._load_slots_state()

            self.apply_theme()
            self._update_settings_page_visibility()
            self._load_custom_style_settings()
            self._update_action_button_state()

            # Обновление кнопок управления звуком
            self.background_music_button.setText(self._get_background_music_button_text())
            self.startup_sound_button.setText(self._get_startup_sound_button_text())

            QMessageBox.information(self, tr('dialogs.success'), tr('status.settings_reset_success'))

            # Полное обновление UI
            self.update()
            self.repaint()

    def _on_background_button_click(self):
        if self.local_config.get('custom_background_path'):
            self.local_config['custom_background_path'] = ''
        else:
            filepath, _ = QFileDialog.getOpenFileName(self, tr('ui.select_background_image'), '', get_file_filter('background_images'))
            if not filepath:
                return
            self.local_config['custom_background_path'] = filepath
        self._write_local_config()
        self.apply_theme()
        self._update_background_button_state()

    def _update_background_button_state(self):
        background_disabled = self.local_config.get('background_disabled', False)
        self.change_background_button.setEnabled(not background_disabled)
        self.change_background_button.setText(tr('buttons.remove_background') if self.local_config.get('custom_background_path') else tr('buttons.change_background'))

    def _toggle_settings_view(self, show_changelog=False):
        if show_changelog:
            self.is_changelog_view = not self.is_changelog_view
        else:
            self.is_settings_view = not self.is_settings_view
            if not self.is_settings_view:
                if self.is_save_manager_view:
                    self._on_configure_saves_click()
                if self.is_changelog_view:
                    self.is_changelog_view = False
        if self.is_settings_view:
            self._lock_window_size()
            self.settings_button.setText(tr('ui.back_button'))
            self.chapter_btn_widget.setVisible(False)
            self.tab_widget.setVisible(False)
            self.bottom_widget.setVisible(False)
            self.settings_widget.setVisible(True)
            self._switch_settings_page(self.settings_menu_page)
            self._update_settings_page_visibility()
            self._load_custom_style_settings()
            self._update_status(tr('status.launcher_settings'), UI_COLORS['status_info'])
        else:
            self._unlock_window_size()
            self.settings_button.setText(tr('ui.settings_title'))
            self.apply_theme()
            self.settings_widget.setVisible(False)
            self.main_tab_widget.setVisible(True)
            self.bottom_widget.setVisible(True)
            self.update()
            self.repaint()
            self._update_action_button_state()

    def _toggle_changelog_view(self):
        self._toggle_settings_view(show_changelog=True)

    def _toggle_help_view(self):
        self.is_help_view = not self.is_help_view
        if self.is_help_view and self.is_changelog_view:
            self.is_changelog_view = False
        if self.is_help_view:
            self._load_help_content()
        self._update_settings_page_visibility()

    def _load_help_content(self):
        from threads.background_workers import FetchHelpContentThread
        manager = get_localization_manager()
        current_language = manager.get_current_language() if manager else 'en'
        if current_language == 'ru':
            help_url = self.global_settings.get('help_ru_url', self.global_settings.get('help_url', ''))
        else:
            help_url = self.global_settings.get('help_en_url', self.global_settings.get('help_url', ''))
        if not help_url:
            self.help_text_edit.setMarkdown(f"<i>{tr('dialogs.help_not_available')}</i>")
            return
        self.help_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")
        self.help_thread = FetchHelpContentThread(help_url.strip(), self)
        self.help_thread.finished.connect(self._on_help_content_loaded)
        self.help_thread.start()

    def _on_help_content_loaded(self, content: str):
        self.help_text_edit.setMarkdown(content)

    def _update_settings_page_visibility(self):
        is_changelog = self.is_changelog_view
        is_help = self.is_help_view
        self.settings_pages_container.setVisible(not is_changelog and (not is_help))
        self.changelog_widget.setVisible(is_changelog)
        self.help_widget.setVisible(is_help)
        self.changelog_button.setText(tr('buttons.changelog_close') if is_changelog else tr('buttons.changelog'))
        self.help_button.setText(tr('buttons.changelog_close') if is_help else tr('buttons.help'))
        if is_changelog:
            self._update_status(tr('status.changelog'), UI_COLORS['status_info'])
        elif is_help:
            self._update_status(tr('dialogs.help_title'), UI_COLORS['status_info'])
        else:
            self._update_status(tr('status.launcher_settings'), UI_COLORS['status_info'])

    def _on_toggle_disable_background(self, state):
        is_disabled = bool(state)
        self.local_config['background_disabled'] = is_disabled
        self._write_local_config()
        self._update_background_button_state()
        self.apply_theme()
        self.update()

    def _on_toggle_disable_splash(self, state):
        is_disabled = bool(state)
        self.local_config['disable_splash'] = is_disabled
        self._write_local_config()

    def _is_valid_hex_color(self, s: str) -> bool:
        return bool(re.fullmatch('#[0-9a-fA-F]{6}', s or ''))

    def _on_custom_style_edited(self):
        for key, widget in self.color_widgets.items():
            color = widget.text()
            config_key = f'custom_color_{key}'
            self.local_config[config_key] = color if self._is_valid_hex_color(color) else ''
        self._write_local_config()
        self.apply_theme()
        self._update_dynamic_elements()

    def _update_dynamic_elements(self):
        if hasattr(self, 'slots'):
            self._update_slots_display()
        self._update_chapter_indicators_style()
        if hasattr(self, 'sort_combo') and hasattr(self, 'sort_order_btn'):
            search_tab = None
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == tr('ui.search_tab'):
                    search_tab = self.tab_widget.widget(i)
                    break
            if search_tab:
                layout = search_tab.layout()
                if layout and layout.count() > 0:
                    item0 = layout.itemAt(0)
                    filters = item0.widget() if item0 is not None else None
                    if filters and filters.objectName() == 'filters':
                        filter_bg_color = self.local_config.get('custom_color_background') or 'rgba(0, 0, 0, 150)'
                        filter_border_color = self.local_config.get('custom_color_border') or 'white'
                        filters.setStyleSheet(f'QFrame#filters {{ background-color: {filter_bg_color}; border: 2px solid {filter_border_color}; padding: 8px; }}')
                elif layout:
                    new_filters = self._create_filters_widget()
                    layout.addWidget(new_filters)
        self._update_mod_plaques_styles()

    def _update_mod_plaques_styles(self):
        if hasattr(self, 'mod_list_widget') and self.mod_list_widget:
            layout = self.mod_list_widget.layout()
            if layout:
                for i in range(layout.count() - 1):
                    item = layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, ModPlaqueWidget):
                            widget._update_style()
        if hasattr(self, 'installed_mods_widget') and self.installed_mods_widget:
            layout = self.installed_mods_widget.layout()
            if layout:
                for i in range(layout.count() - 1):
                    item = layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, InstalledModWidget):
                            widget._update_style()

    def _load_custom_style_settings(self):
        theme_defaults = THEMES['default']
        for key, widget in self.color_widgets.items():
            config_key = f'custom_color_{key}'
            placeholder = theme_defaults['colors'].get(key, '#000000')
            widget.setText(self.local_config.get(config_key, ''))
            widget.setPlaceholderText(placeholder)
        self.apply_theme()

    def _load_launcher_icon(self):
        try:
            splash_path = resource_path('images/splash.png')
            if os.path.exists(splash_path):
                pixmap = QPixmap(splash_path)
                if not pixmap.isNull():
                    target_w, target_h = (200, 60)
                    scaled_pixmap = pixmap.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    x = max(0, (scaled_pixmap.width() - target_w) // 2)
                    y = max(0, (scaled_pixmap.height() - target_h) // 2)
                    cropped = scaled_pixmap.copy(x, y, target_w, target_h)
                    self.launcher_icon_label.setFixedSize(target_w, target_h)
                    self.launcher_icon_label.setScaledContents(False)
                    self.launcher_icon_label.setPixmap(cropped)
                    return
        except Exception:
            pass
        target_w, target_h = (200, 60)
        fallback_pixmap = QPixmap(target_w, target_h)
        fallback_pixmap.fill(QColor('#333'))
        self.launcher_icon_label.setFixedSize(target_w, target_h)
        self.launcher_icon_label.setScaledContents(False)
        self.launcher_icon_label.setPixmap(fallback_pixmap)

    def _get_background_music_path(self):
        mp3_path = os.path.join(self.config_dir, 'custom_background_music.mp3')
        wav_path = os.path.join(self.config_dir, 'custom_background_music.wav')
        if os.path.exists(mp3_path):
            return mp3_path
        if os.path.exists(wav_path):
            return wav_path
        return ''

    def _get_startup_sound_path(self):
        mp3 = os.path.join(self.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.config_dir, 'custom_startup_sound.wav')
        if os.path.exists(mp3):
            return mp3
        if os.path.exists(wav):
            return wav
        return ''

    def _get_background_music_button_text(self):
        mp3 = os.path.join(self.config_dir, 'custom_background_music.mp3')
        wav = os.path.join(self.config_dir, 'custom_background_music.wav')
        custom_exists = os.path.exists(mp3) or os.path.exists(wav)
        return tr('buttons.remove_background_music') if custom_exists else tr('buttons.select_background_music')

    def _get_startup_sound_button_text(self):
        if os.path.exists(self._get_startup_sound_path()):
            return tr('buttons.remove_startup_sound')
        return tr('buttons.select_startup_sound')

    def _on_background_music_button_click(self):
        mp3 = os.path.join(self.config_dir, 'custom_background_music.mp3')
        wav = os.path.join(self.config_dir, 'custom_background_music.wav')
        custom_exists = os.path.exists(mp3) or os.path.exists(wav)
        if custom_exists:
            try:
                self._stop_background_music()
                for p in (mp3, wav):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                self.background_music_button.setText(self._get_background_music_button_text())
                QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.background_music_removed'))
            except Exception as e:
                print(f'Error removing background music: {e}')
                QMessageBox.warning(self, tr('errors.error'), tr('errors.remove_background_music_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, tr('dialogs.select_background_music'), '', 'Audio Files (*.mp3 *.wav)')
            if file_path:
                lower = file_path.lower()
                if not (lower.endswith('.mp3') or lower.endswith('.wav')):
                    QMessageBox.warning(self, tr('errors.error'), 'Можно выбрать только MP3 или WAV файл')
                    return
                try:
                    self._stop_background_music()
                    os.makedirs(self.config_dir, exist_ok=True)
                    ext = '.mp3' if lower.endswith('.mp3') else '.wav'
                    dest_path = os.path.join(self.config_dir, f'custom_background_music{ext}')
                    shutil.copy2(file_path, dest_path)
                    self.background_music_button.setText(self._get_background_music_button_text())
                    self._maybe_start_background_music()
                    QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.background_music_selected'))
                except Exception as e:
                    print(f'Error copying background music: {e}')
                    QMessageBox.warning(self, tr('errors.error'), tr('errors.copy_background_music_failed'))

    def _on_startup_sound_button_click(self):
        mp3 = os.path.join(self.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.config_dir, 'custom_startup_sound.wav')
        existing = self._get_startup_sound_path()
        if existing:
            try:
                for p in (mp3, wav):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                self.startup_sound_button.setText(self._get_startup_sound_button_text())
                QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.startup_sound_removed'))
            except Exception as e:
                print(f'Error removing startup sound: {e}')
                QMessageBox.warning(self, tr('errors.error'), tr('errors.remove_startup_sound_failed'))
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, tr('dialogs.select_startup_sound'), '', 'Audio Files (*.mp3 *.wav)')
            if file_path:
                lower = file_path.lower()
                if not (lower.endswith('.mp3') or lower.endswith('.wav')):
                    QMessageBox.warning(self, tr('errors.error'), 'Можно выбрать только MP3 или WAV файл')
                    return
                try:
                    os.makedirs(self.config_dir, exist_ok=True)
                    ext = '.mp3' if lower.endswith('.mp3') else '.wav'
                    dest = os.path.join(self.config_dir, f'custom_startup_sound{ext}')
                    shutil.copy2(file_path, dest)
                    self.startup_sound_button.setText(self._get_startup_sound_button_text())
                    QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.startup_sound_selected'))
                except Exception as e:
                    print(f'Error copying startup sound: {e}')
                    QMessageBox.warning(self, tr('errors.error'), tr('errors.copy_startup_sound_failed'))

    def _start_background_music(self):
        try:
            music_path = self._get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                return
            self._stop_background_music()
            from PyQt6.QtCore import QThread
            from playsound3 import playsound
            self._bg_music_running = True
            self._bg_music_instance = None

            class _MusicLoop(QThread):

                def __init__(self, outer, path):
                    super().__init__()
                    self.outer, self.path = (outer, path)

                def run(self):
                    while getattr(self.outer, '_bg_music_running', False):
                        try:
                            inst = playsound(self.path, block=False)
                            self.outer._bg_music_instance = inst
                            while getattr(self.outer, '_bg_music_running', False) and hasattr(inst, 'is_alive') and inst.is_alive():
                                time.sleep(0.05)
                            if not getattr(self.outer, '_bg_music_running', False):
                                try:
                                    if hasattr(inst, 'stop'):
                                        inst.stop()
                                except Exception:
                                    pass
                                break
                        except Exception:
                            time.sleep(3)
                            continue
            self._bg_music_thread = _MusicLoop(self, music_path)
            self._bg_music_thread.start()
        except Exception as e:
            print(f'Error starting background music: {e}')

    def _stop_background_music(self):
        try:
            self._bg_music_running = False
            inst = getattr(self, '_bg_music_instance', None)
            if inst and hasattr(inst, 'stop'):
                try:
                    if hasattr(inst, 'is_alive') and inst.is_alive():
                        inst.stop()
                    elif hasattr(inst, 'stop'):
                        inst.stop()
                except Exception:
                    pass
            self._bg_music_instance = None
            thr = getattr(self, '_bg_music_thread', None)
            if thr and thr.isRunning():
                thr.wait(300)
            self._bg_music_thread = None
        except Exception as e:
            print(f'Error stopping background music: {e}')
        try:
            if hasattr(self, 'bg_fallback_proc') and self.bg_fallback_proc:
                if self.bg_fallback_proc.poll() is None:
                    self.bg_fallback_proc.terminate()
            if platform.system() == 'Windows':
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.bg_fallback_proc = None

    def _maybe_start_background_music(self):
        try:
            music_path = self._get_background_music_path()
            if not music_path or not os.path.exists(music_path):
                return
            if self.initialization_completed and getattr(self, 'is_shown_to_user', False) and self.isVisible():
                self._start_background_music()
            else:
                QTimer.singleShot(500, self._maybe_start_background_music)
        except Exception:
            pass

    def _on_toggle_direct_launch_for_slot(self, slot_id):
        if not self.game_mode.direct_launch_allowed:
            return
        if self.local_config.get('launch_via_steam', False):
            QMessageBox.warning(self, tr('dialogs.incompatibility'), tr('dialogs.direct_launch_steam_incompatible'))
            return
        if platform.system() == 'Darwin':
            QMessageBox.warning(self, tr('dialogs.incompatibility'), tr('dialogs.direct_launch_macos_incompatible'))
            return
        self.local_config['direct_launch_slot_id'] = slot_id
        self._write_local_config()
        self._update_all_slots_visual_state()
        self.launch_via_steam_checkbox.setEnabled(False)

    def _update_action_button_state(self):
        if getattr(self, 'is_installing', False):
            self.action_button.setText(tr('ui.cancel_button'))
            self.action_button.setEnabled(True)
            return
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        is_full_install_enabled = is_demo_mode and hasattr(self, 'full_install_checkbox') and self.full_install_checkbox.isChecked()
        if is_full_install_enabled:
            action_text = tr('buttons.install')
        elif self._check_active_slots_need_updates():
            action_text = tr('ui.update_button')
        else:
            action_text = tr('ui.launch_button')
        self.action_button.setText(action_text)
        self.action_button.setEnabled(True)

    def _disable_direct_launch(self):
        self.local_config['direct_launch_slot_id'] = -1
        self._write_local_config()
        self._update_all_slots_visual_state()
        self.launch_via_steam_checkbox.setEnabled(True)

    def _update_all_slots_visual_state(self):
        if hasattr(self, 'slots'):
            for slot in self.slots.values():
                self._update_slot_visual_state(slot)

    def _initialize_mutual_exclusions(self):
        is_direct_launch = self.local_config.get('direct_launch_slot_id', -1) >= 0
        if is_direct_launch:
            self.launch_via_steam_checkbox.setEnabled(False)
        self.apply_theme()

    def _perform_initial_setup(self):
        try:
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            response = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
            if response.status_code == 200:
                self.global_settings = response.json() or {}
        except requests.RequestException:
            self.update_status_signal.emit(tr('status.global_settings_load_failed'), UI_COLORS['status_warning'])
        manager = get_localization_manager()
        current_language = manager.get_current_language() if manager else 'en'
        if current_language == 'ru':
            changelog_url = self.global_settings.get('changelog_ru_url', self.global_settings.get('changelog_url'))
        else:
            changelog_url = self.global_settings.get('changelog_en_url', self.global_settings.get('changelog_url'))
        if changelog_url:
            changelog_thread = FetchChangelogThread(changelog_url.strip(), self)
            changelog_thread.finished.connect(self.changelog_text_edit.setMarkdown)
            changelog_thread.start()
        else:
            self.changelog_text_edit.setMarkdown(tr('status.changelog_load_failed'))
        self._check_and_manage_steam_deck_saves()
        if is_game_running():
            self.update_status_signal.emit(tr('status.deltarune_already_running'), UI_COLORS['status_error'])
            return
        self._load_local_data()
        self.game_path = self.local_config.get('game_path', '')
        self.demo_game_path = self.local_config.get('demo_game_path', '')
        saved_demo_mode = self.local_config.get('demo_mode_enabled', False)
        saved_chapter_mode = self.local_config.get('chapter_mode_enabled', False)
        if hasattr(self, 'game_type_combo') and saved_demo_mode:
            self.game_type_combo.blockSignals(True)
            for i in range(self.game_type_combo.count()):
                if self.game_type_combo.itemData(i) == 'deltarunedemo':
                    self.game_type_combo.setCurrentIndex(i)
                    break
            self.game_type_combo.blockSignals(False)
        if hasattr(self, 'chapter_mode_checkbox'):
            self.chapter_mode_checkbox.blockSignals(True)
            self.chapter_mode_checkbox.setChecked(saved_chapter_mode)
            self.chapter_mode_checkbox.blockSignals(False)
        self.disable_background_checkbox.setChecked(self.local_config.get('background_disabled', False))
        self.disable_splash_checkbox.setChecked(self.local_config.get('disable_splash', False))
        self._update_change_path_button_text()
        self._update_background_button_state()
        self._migrate_config_if_needed()
        self.use_custom_executable_checkbox.setChecked(self.local_config.get('use_custom_executable', False))
        self.launch_via_steam_checkbox.setChecked(self.local_config.get('launch_via_steam', False))
        self._initialize_mutual_exclusions()
        self._on_toggle_steam_launch()
        self._update_all_slots_visual_state()
        self.apply_theme()
        self._load_local_mods_from_folders()
        self.setEnabled(False)
        self._refresh_mods_list(force=True, blocking=False)
        self.setEnabled(True)
        self._update_installed_mods_display()
        if not self._find_and_validate_game_path(is_initial=True):
            self.action_button.setEnabled(False)

    def _check_and_manage_steam_deck_saves(self):
        if platform.system() != 'Linux':
            return
        try:
            home_dir = os.path.expanduser('~')
            if isinstance(self.game_mode, UndertaleGameMode):
                game_name = 'UNDERTALE'
            else:
                game_name = 'DELTARUNE'
            steam_app_id = self.game_mode.steam_id
            native_save_path = os.path.join(home_dir, '.config', game_name)
            proton_save_path = os.path.join(home_dir, '.steam', 'steam', 'steamapps', 'compatdata', steam_app_id, 'pfx', 'drive_c', 'users', 'steamuser', 'AppData', 'Local', game_name)
            if not os.path.isdir(proton_save_path):
                return
            if os.path.lexists(native_save_path):
                if os.path.islink(native_save_path) and os.readlink(native_save_path) == proton_save_path:
                    return
                if os.path.isdir(native_save_path) and (not os.listdir(native_save_path)):
                    os.rmdir(native_save_path)
                else:
                    backup_path = f'{native_save_path}_backup_{int(time.time())}'
                    os.rename(native_save_path, backup_path)
                    QMessageBox.information(self, tr('dialogs.backup'), tr('dialogs.backup_created_for_steam_deck', backup_path=backup_path))
            os.symlink(proton_save_path, native_save_path)
            QMessageBox.information(self, tr('dialogs.steam_deck_setup'), tr('dialogs.steam_deck_compatibility_configured'))
        except Exception as e:
            print(tr('startup.steam_deck_setup_error', error=str(e)))

    def _get_platform_string(self) -> str:
        system = platform.system()
        if system == 'Windows':
            return 'setup'
        elif system == 'Darwin':
            return f'macOS-{ARCH}'
        else:
            return 'Linux'

    def _check_for_launcher_updates(self):
        try:
            launcher_files = self.global_settings.get('launcher_files')
            if not isinstance(launcher_files, dict):
                self.update_status_signal.emit(tr('status.update_info_not_found'), UI_COLORS['status_warning'])
                return
            remote_version = launcher_files.get('version')
            from utils.file_utils import version_sort_key as _vkey
            if not remote_version or _vkey(remote_version) <= _vkey(LAUNCHER_VERSION):
                self.update_status_signal.emit(tr('status.launcher_version_up_to_date'), UI_COLORS['status_success'])
                return
            platform_key_map = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': f'macos-{ARCH}'}
            current_platform_key = platform_key_map.get(platform.system())
            download_url = launcher_files.get('urls', {}).get(current_platform_key)
            update_message = launcher_files.get('message', tr('dialogs.new_version_available_simple'))
            update_message_ru = launcher_files.get('message_ru')
            update_message_en = launcher_files.get('message_en')
            if not download_url:
                self.update_status_signal.emit(tr('errors.no_build_for_os', platform=current_platform_key), UI_COLORS['status_warning'])
                return
            update_info = {'version': remote_version, 'url': download_url, 'message': update_message, 'message_ru': update_message_ru, 'message_en': update_message_en}
            self.update_info_ready.emit(update_info)
        except requests.RequestException as e:
            self.update_status_signal.emit(tr('errors.update_check_network_error', error=str(e)), UI_COLORS['status_error'])
        except Exception as e:
            self.update_status_signal.emit(tr('errors.update_check_general_error', error=str(e)), UI_COLORS['status_error'])

    def _handle_update_info(self, update_info):
        if self.initialization_completed and getattr(self, 'is_shown_to_user', False):
            self.show_update_prompt.emit(update_info)
        else:
            QTimer.singleShot(1000, lambda: self._handle_update_info(update_info))

    def _maybe_run_legacy_cleanup(self):
        if self._legacy_cleanup_done:
            return
        if self.initialization_completed and getattr(self, 'is_shown_to_user', False):
            self._cleanup_legacy_ylauncher_folder()
            self._legacy_cleanup_done = True
        else:
            QTimer.singleShot(1000, self._maybe_run_legacy_cleanup)

    def _cleanup_legacy_ylauncher_folder(self):
        try:
            legacy_path = get_legacy_ylauncher_path()
            if legacy_path and os.path.isdir(legacy_path):
                try:
                    shutil.rmtree(legacy_path, ignore_errors=True)
                except Exception:
                    pass
                QMessageBox.information(self, tr('dialogs.legacy_cleanup_title'), tr('dialogs.legacy_cleanup_message'))
        except Exception:
            pass

    def _prompt_for_update(self, update_info):
        if self.update_in_progress:
            return
        self.update_in_progress = True
        update_message = tr('dialogs.new_version_banner', version=update_info['version']) + '<br>' + tr('dialogs.current_version_banner', current_version=LAUNCHER_VERSION)
        manager = get_localization_manager()
        current_language = manager.get_current_language() if manager else 'en'
        if current_language == 'ru':
            message_text = update_info.get('message_ru') or update_info.get('message', '')
        else:
            message_text = update_info.get('message_en') or update_info.get('message', '')
        update_message += f"<b>{tr('dialogs.whats_new')}</b><br>{message_text}<br><br>"
        update_message += tr('dialogs.want_download_install_now') + tr('dialogs.app_will_restart')
        reply = QMessageBox.question(self, tr('status.update_available'), update_message)
        if reply == QMessageBox.StandardButton.Yes:
            self._perform_update(update_info)
        else:
            self.update_in_progress = False
            self.update_status_signal.emit(tr('status.update_rejected'), UI_COLORS['status_info'])

    def _perform_update(self, update_info):
        for widget in [self.action_button, self.saves_button, self.shortcut_button, self.change_path_button, self.change_background_button]:
            widget.setEnabled(False)
        try:
            if hasattr(self, 'top_refresh_button') and self.top_refresh_button:
                self.top_refresh_button.setEnabled(False)
        except Exception:
            pass
        self.settings_button.setEnabled(False)
        if not self.is_settings_view:
            self.tab_widget.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        threading.Thread(target=self._update_worker, args=(update_info,), daemon=True).start()

    def _on_update_cleanup(self):
        try:
            self.progress_bar.setVisible(False)
        except Exception:
            pass
        self.update_in_progress = False
        try:
            if not self.is_settings_view:
                self.tab_widget.setEnabled(True)
            for w in [self.action_button, self.saves_button, self.shortcut_button, self.change_path_button, self.change_background_button]:
                w.setEnabled(True)
            try:
                if hasattr(self, 'top_refresh_button') and self.top_refresh_button:
                    self.top_refresh_button.setEnabled(True)
            except Exception:
                pass
            self.settings_button.setEnabled(True)
            self._update_action_button_state()
        except Exception:
            pass

    def _update_worker(self, update_info):
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub-update-') as tmp_dir:
                archive_path = os.path.join(tmp_dir, 'update' + os.path.splitext(update_info['url'].split('?')[0])[1])
                self.update_status_signal.emit(tr('status.downloading_version', version=update_info['version']), UI_COLORS['status_warning'])
                response = requests.get(update_info['url'], stream=True, timeout=60)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                with open(archive_path, 'wb') as f:
                    downloaded_size = 0
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        downloaded_size += len(data)
                        if total_size > 0:
                            self.set_progress_signal.emit(int(downloaded_size / total_size * 100))
                self.update_status_signal.emit(tr('status.unpacking_and_installing'), UI_COLORS['status_warning'])
                system = platform.system()
                extraction_dir = os.path.join(tmp_dir, 'extracted')
                os.makedirs(extraction_dir, exist_ok=True)
                if system != 'Darwin':
                    from utils.file_utils import _extract_archive
                    _extract_archive(archive_path, extraction_dir, os.path.basename(archive_path))
                if system == 'Windows':
                    new_exe_path = next((os.path.join(root, f) for root, _, files in os.walk(extraction_dir) for f in files if f.lower().endswith('.exe')), None)
                    if not new_exe_path:
                        raise RuntimeError(tr('errors.exe_not_found_in_archive'))
                    ctypes.windll.shell32.ShellExecuteW(None, 'runas', new_exe_path, None, None, 1)
                    self.update_status_signal.emit(tr('status.installer_launched_closing'), UI_COLORS['status_success'])
                    self.quit_signal.emit()
                    return
                current_exe_path = os.path.realpath(sys.executable)
                replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), '..', '..')) if system == 'Darwin' else current_exe_path
                backup_path = f'{replace_target}.old'
                if system == 'Darwin':
                    if archive_path.lower().endswith('.zip'):
                        subprocess.run(['/usr/bin/ditto', '-x', '-k', archive_path, extraction_dir], check=True)
                    new_content_path = next((os.path.join(extraction_dir, d) for d in os.listdir(extraction_dir) if d.endswith('.app')), None)
                    if new_content_path is None:
                        raise RuntimeError(tr('errors.app_not_found_after_unpack'))
                    fix_macos_python_symlink(Path(new_content_path))
                else:
                    new_content_path = next((os.path.join(root, file) for root, _, files in os.walk(extraction_dir) for file in files if os.path.isfile(os.path.join(root, file)) and os.access(os.path.join(root, file), os.X_OK)), None)
                    if new_content_path is None or not os.path.exists(new_content_path):
                        raise RuntimeError(tr('errors.executable_not_found_after_unpack'))
                    os.chmod(new_content_path, 493)
                if os.path.exists(backup_path):
                    shutil.rmtree(backup_path, ignore_errors=True)
                os.rename(replace_target, backup_path)
                if system == 'Darwin':
                    shutil.copytree(new_content_path, replace_target)
                else:
                    shutil.move(new_content_path, replace_target)
                self.update_status_signal.emit(tr('status.restarting'), UI_COLORS['status_success'])
                os.execv(current_exe_path, sys.argv)
        except PermissionError:
            self.update_status_signal.emit(tr('errors.update_permission_error'), UI_COLORS['status_error'])
            self.error_signal.emit(tr('dialogs.update_permission_error_details'))
        except Exception as e:
            self.update_status_signal.emit(tr('errors.update_failed', error=str(e)), UI_COLORS['status_error'])
            self.error_signal.emit(tr('errors.update_could_not_complete', error=str(e)))
        finally:
            self.update_cleanup.emit()

    def _on_action_button_click(self):
        if self.is_installing and self.current_install_thread:
            self._operation_cancelled = True
            self.update_status_signal.emit(tr('status.operation_cancelled'), UI_COLORS['status_error'])
            try:
                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(False)
            except Exception:
                pass
            try:
                self.current_install_thread.cancel()
            except Exception:
                pass
            return
        if isinstance(self.game_mode, DemoGameMode) and getattr(self, 'full_install_checkbox', None) is not None and self.full_install_checkbox.isChecked():
            self._perform_full_install()
            return
        if self.is_installing:
            return
        if self._check_active_slots_need_updates():
            self._update_mods_in_active_slots()
            return
        if getattr(self, '_operation_cancelled', False):
            return
        self.action_button.setEnabled(False)
        self.saves_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self._launch_game_with_all_mods()

    def _refresh_mods_list(self, force=False, blocking=False):
        if is_game_running():
            self.update_status_signal.emit(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
            return
        self._stop_fetch_thread()
        threading.Thread(target=self._check_for_launcher_updates, daemon=True).start()
        self.fetch_thread = FetchModsThread(self, force_update=force)
        self.fetch_thread.status.connect(self.update_status_signal)
        self.fetch_thread.result.connect(self._on_fetch_translations_finished)
        if blocking:
            loop = QEventLoop()
            self.fetch_thread.finished.connect(loop.quit)
            self.fetch_thread.start()
            loop.exec()
        else:
            self.fetch_thread.start()

    def _stop_fetch_thread(self):
        self._safe_stop_thread(getattr(self, 'fetch_thread', None))
        self.fetch_thread = None

    def _safe_stop_thread(self, thr: Optional[QThread], timeout: int = 2000):
        if isinstance(thr, QThread) and thr.isRunning():
            thr.requestInterruption()
            thr.quit()
            if not thr.wait(timeout):
                thr.terminate()
                thr.wait()

    def _stop_presence_thread(self):
        self._safe_stop_thread(getattr(self, 'presence_thread', None))
        self.presence_thread = None
        self.presence_worker = None

    def _on_fetch_translations_finished(self, success: bool):
        try:
            self._load_local_mods_from_folders()
            if hasattr(self, 'mod_list_layout'):
                self._populate_search_mods()
                if not self.mods_loaded:
                    self.mods_loaded = True
                    self.mods_loaded_signal.emit()
            if hasattr(self, 'installed_mods_layout'):
                self._update_installed_mods_display()
            self._refresh_mods_in_slots()
            self._refresh_slots_content()
            self._update_action_button_state()
            if success:
                self.update_status_signal.emit(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.all_mods else tr('ui.network_update_failed')
                self.update_status_signal.emit(fallback_msg, UI_COLORS['status_error'])
        except Exception as e:
            self.update_status_signal.emit(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])

    def _refresh_mods_in_slots(self):
        if not hasattr(self, 'slots') or not self.all_mods:
            return
        for slot_frame in self.slots.values():
            if slot_frame.assigned_mod:
                old_mod = slot_frame.assigned_mod
                mod_key = getattr(old_mod, 'key', None) or getattr(old_mod, 'mod_key', None)
                for updated_mod in self.all_mods:
                    updated_mod_key = getattr(updated_mod, 'key', None) or getattr(updated_mod, 'mod_key', None)
                    if updated_mod_key == mod_key:
                        slot_frame.assigned_mod = updated_mod
                        break
        self._refresh_all_slot_status_displays()

    def _has_internet_connection(self) -> bool:
        try:
            requests.head('https://clients3.google.com/generate_204', timeout=3)
            return True
        except requests.RequestException:
            return False
        self._update_action_button_state()
        self.install_thread.start()

    def _on_install_finished(self, success):
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        if not success:
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        if success:
            self._load_local_mods_from_folders()
            self.update_status_signal.emit(tr('status.installation_complete'), UI_COLORS['status_success'])
            self._update_installed_mods_display()
        self._update_action_button_state()
        if hasattr(self, 'full_install_checkbox') and self.full_install_checkbox is not None and isinstance(self.game_mode, DemoGameMode):
            self.full_install_checkbox.setEnabled(True)
        self._update_action_button_state()

    def _perform_full_install(self):
        if self.is_installing:
            return
        if hasattr(self, 'full_install_thread') and self.full_install_thread and self.full_install_thread.isRunning():
            return
        self.action_button.setEnabled(False)
        self.saves_button.setEnabled(False)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('dialogs.full_demo_install'))
        v = QVBoxLayout(dlg)
        lbl = QLabel(self._full_install_tooltip())
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.action_button.setEnabled(True)
            return
        base_dir = QFileDialog.getExistingDirectory(self, tr('dialogs.install_demo_location'))
        if not base_dir:
            self.action_button.setEnabled(True)
            return
        target_dir = os.path.join(base_dir, 'DELTARUNEdemo')
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            self.error_signal.emit(tr('errors.folder_creation_failed', error=str(e)))
            self.action_button.setEnabled(True)
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.full_install_thread = FullInstallThread(self, target_dir, False)
        self.full_install_thread.progress.connect(self.set_progress_signal)
        self.full_install_thread.progress.connect(self.progress_bar.setValue)
        self.full_install_thread.status.connect(self.update_status_signal)
        self.full_install_thread.progress.connect(self.progress_bar.setValue)
        self.full_install_thread.finished.connect(self._on_full_install_finished)
        self.full_install_thread.start()

    def _on_full_install_finished(self, success, target_dir):
        self.progress_bar.setVisible(False)
        self.full_install_checkbox.blockSignals(True)
        self.progress_bar.setValue(0)
        self.full_install_checkbox.setChecked(False)
        self.full_install_checkbox.blockSignals(False)
        if success:
            if isinstance(self.game_mode, DemoGameMode):
                self.demo_game_path = target_dir
                self.local_config['demo_game_path'] = target_dir
            else:
                self.game_path = target_dir
                self.local_config['game_path'] = target_dir
            self._write_local_config()
            self.update_status_signal.emit(tr('status.game_files_install_complete'), UI_COLORS['status_success'])
            self._update_action_button_state()
            return
        else:
            self.update_status_signal.emit(tr('status.game_files_install_failed'), UI_COLORS['status_error'])
        self._write_local_config()
        self._update_action_button_state()

    def _run_as_admin_windows(self, path: str) -> bool:
        script = f"import os, stat; p = r'{path}'; [os.chmod(os.path.join(r, f), os.stat(os.path.join(r, f)).st_mode | stat.S_IWRITE) for r, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE) if os.path.exists(p) else None"
        command = f'Start-Process python -ArgumentList "-c \\"{script}\\"" -Verb RunAs -WindowStyle Hidden'
        try:
            subprocess.run(['powershell', '-Command', command], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.update_status_signal.emit(tr('status.permission_change_failed'), UI_COLORS['status_error'])
            return False

    def _get_xdelta_chapters(self, source_dir: str, mod_info) -> List[int]:
        available_chapters = []
        if mod_info and getattr(mod_info, 'is_xdelta', getattr(mod_info, 'is_piracy_protected', False)):
            for chapter_id in range(-1, 5):
                if chapter_id == -1:
                    if mod_info.is_valid_for_demo():
                        available_chapters.append(chapter_id)
                elif mod_info.get_chapter_data(chapter_id):
                    available_chapters.append(chapter_id)
        else:
            for file in os.listdir(source_dir):
                if file.lower().endswith('.xdelta'):
                    available_chapters.append(0)
                    break
            for chapter_id in range(-1, 5):
                if chapter_id == -1:
                    demo_dir = os.path.join(source_dir, 'demo')
                    if os.path.isdir(demo_dir):
                        for file in os.listdir(demo_dir):
                            if file.lower().endswith('.xdelta'):
                                available_chapters.append(chapter_id)
                                break
                elif chapter_id == 0:
                    chapter_dir = os.path.join(source_dir, 'chapter_0')
                    chapter_dir_alt = os.path.join(source_dir, 'menu')
                    for chk in (chapter_dir, chapter_dir_alt):
                        if os.path.isdir(chk):
                            for file in os.listdir(chk):
                                if file.lower().endswith('.xdelta'):
                                    available_chapters.append(chapter_id)
                                    break
                else:
                    chapter_dir = os.path.join(source_dir, f'chapter_{chapter_id}')
                    if os.path.isdir(chapter_dir):
                        for file in os.listdir(chapter_dir):
                            if file.lower().endswith('.xdelta'):
                                available_chapters.append(chapter_id)
                                break
        return list(set(available_chapters))

    def _prepare_game_files(self, selections: Dict[int, str]) -> bool:
        try:
            applied_chapters = set()
            for ui_index, mod_key in selections.items():
                if mod_key == 'no_change':
                    continue
                chapter_id = self.game_mode.get_chapter_id(ui_index)
                mod = next((m for m in self.all_mods if m.key == mod_key), None)
                if not mod:
                    continue
                is_local = mod_key.startswith('local_')
                folder_name = sanitize_filename(mod.name)
                source_dir = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(source_dir):
                    self.update_status_signal.emit(tr('errors.mod_folder_not_found', mod_name=mod.name, path=source_dir), UI_COLORS['status_warning'])
                    continue
                mod_type_str = tr('ui.mod_type_local') if is_local else tr('ui.mod_type_public')
                self.update_status_signal.emit(tr('status.applying_mod', mod_name=mod.name, mod_type=mod_type_str), UI_COLORS['status_warning'])
                print(f'[XDELTA-DEBUG] UI index={ui_index}, chapter_id={chapter_id}, mod_key={mod_key}, mod_name={mod.name}')
                print(f'[XDELTA-DEBUG] source_dir={source_dir}')
                if chapter_id in applied_chapters:
                    continue
                is_xdelta_mod = self._is_xdelta_mod(mod, source_dir, chapter_id)
                print(f'[XDELTA-DEBUG] is_xdelta_mod={is_xdelta_mod}')
                if not is_xdelta_mod and (not mod.get_chapter_data(chapter_id)) and (not is_local):
                    continue
                target_dir = self._get_target_dir(chapter_id)
                if not target_dir:
                    print(f'[XDELTA-DEBUG] target_dir not found for chapter_id={chapter_id}')
                    continue
                print(f'[XDELTA-DEBUG] target_dir={target_dir}')
                if not ensure_writable(target_dir):
                    raise PermissionError(tr('errors.no_write_permission_for', path=target_dir))
                if not self._create_backup_and_copy_mod_files(source_dir, target_dir, chapter_id, mod):
                    return False
                applied_chapters.add(chapter_id)
            return True
        except PermissionError as e:
            path = e.filename or (e.args[0] if e.args else tr('errors.unknown_path'))
            if not self.is_shortcut_launch:
                self._handle_permission_error(path)
            return False
        except Exception as e:
            self.error_signal.emit(tr('errors.file_prep_error', error=str(e)))
            return False

    def _is_xdelta_mod(self, mod_info, source_dir: str, chapter_id: Optional[int] = None) -> bool:
        if mod_info and getattr(mod_info, 'is_xdelta', getattr(mod_info, 'is_piracy_protected', False)):
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
        print(f'[XDELTA-DEBUG] _is_xdelta_mod: chapter_id={chapter_id}, search_dir={search_dir}')
        if os.path.exists(search_dir):
            for root, _, files in os.walk(search_dir):
                for file in files:
                    if file.lower().endswith('.xdelta'):
                        return True
        return False

    def _create_backup_and_copy_mod_files(self, source_dir: str, target_dir: str, chapter_id: Optional[int] = None, mod_info=None):
        if not os.path.isdir(source_dir):
            self.update_status_signal.emit(tr('errors.mod_folder_not_found_simple', path=source_dir), UI_COLORS['status_error'])
            return False
        if not hasattr(self, '_mod_files_to_cleanup'):
            self._mod_files_to_cleanup = []
        if not hasattr(self, '_backup_files'):
            self._backup_files = {}
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
            self.update_status_signal.emit(tr('status.no_files_to_copy'), UI_COLORS['status_warning'])
            return True
        if not hasattr(self, '_backup_temp_dir') or not self._backup_temp_dir:
            self._backup_temp_dir = tempfile.mkdtemp(prefix='deltahub_backup_')
            self._update_session_manifest(backup_temp_dir=self._backup_temp_dir)
        print(f'[XDELTA-DEBUG] _create_backup_and_copy_mod_files: chapter_id={chapter_id}, mod_source_dir={mod_source_dir}, target_dir={target_dir}, is_xdelta_mod={is_xdelta_mod}')
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
                        if not hasattr(self, '_mod_dirs_to_cleanup'):
                            self._mod_dirs_to_cleanup = []
                        if target_dirname not in self._mod_dirs_to_cleanup:
                            self._mod_dirs_to_cleanup.append(target_dirname)
                            self._update_session_manifest(mod_dirs=[target_dirname])
                    except Exception:
                        pass
                    if is_xdelta_mod and file_lower.endswith('.xdelta') and is_core_data_file:
                        if applied_xdelta_for_this_chapter:
                            continue
                        print(f"[XDELTA-DEBUG] Chapter {chapter_id}: applying xdelta '{cache_file_path}' -> original in '{target_dir}' (computed game_file_path={game_file_path})")
                        if not self._apply_xdelta_patch(cache_file_path, game_file_path, target_dir):
                            self.update_status_signal.emit(tr('errors.xdelta_apply_error', file=file), UI_COLORS['status_error'])
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
                    if file_lower.endswith(('.zip', '.rar', '.7z')) and (not is_core_data_file):
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
                    self.update_status_signal.emit(tr('errors.file_copy_error', file=file, error=str(e)), UI_COLORS['status_error'])
        if files_copied > 0:
            self.update_status_signal.emit(tr('status.files_copied_count', count=files_copied), UI_COLORS['status_info'])
        else:
            self.update_status_signal.emit(tr('status.no_files_to_copy'), UI_COLORS['status_warning'])
        return True

    def _apply_xdelta_patch(self, xdelta_file_path: str, target_game_file_path: str, target_dir: str) -> bool:
        xdelta_exe = get_xdelta_path()
        if not os.path.exists(xdelta_exe):
            QMessageBox.critical(self, tr('errors.xdelta_error'), tr('errors.xdelta_not_found', path=xdelta_exe))
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
            QMessageBox.critical(self, tr('errors.xdelta_error'), tr('errors.original_data_file_not_found', target_dir=target_dir))
            return False
        if not hasattr(self, '_backup_files'):
            self._backup_files = {}
        if original_data_file not in self._backup_files:
            if not hasattr(self, '_backup_temp_dir') or not self._backup_temp_dir:
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
            if platform.system() != 'Windows' and xdelta_exe.lower().endswith('.exe'):
                runner = shutil.which('wine') or shutil.which('proton')
                if runner:
                    command_to_run.insert(0, runner)
                else:
                    QMessageBox.critical(self, tr('errors.xdelta_error'), tr('errors.wine_not_found'))
                    return False
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.run(command_to_run, capture_output=True, text=True, check=False, startupinfo=startupinfo, encoding='utf-8', errors='replace')
            if process.returncode == 0:
                self._mod_files_to_cleanup.append(original_data_file)
                self.update_status_signal.emit(tr('status.xdelta_patch_applied', patch_name=os.path.basename(xdelta_file_path)), UI_COLORS['status_success'])
                return True
            else:
                shutil.copy2(self._backup_files[original_data_file], original_data_file)
                error_message = process.stderr.strip() or process.stdout.strip()
                logging.error(f'Xdelta error: {error_message}')
                QMessageBox.critical(self, tr('errors.xdelta_patch_failed'), tr('errors.patch_incompatible_details', error=error_message))
                return False
        except FileNotFoundError:
            QMessageBox.critical(self, tr('errors.xdelta_error'), tr('errors.xdelta_not_found', path=xdelta_exe))
            return False
        except Exception as e:
            QMessageBox.critical(self, tr('errors.xdelta_critical_error'), tr('errors.xdelta_patch_critical_error', error=str(e)))
            try:
                shutil.copy2(self._backup_files[original_data_file], original_data_file)
            except Exception as restore_e:
                logging.error(f'Failed to restore from backup: {restore_e}')
            return False

    def _extract_archive_to_target(self, archive_path: str, target_dir: str):
        import tempfile
        import zipfile
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
                    try:
                        import py7zr
                        with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                            zf.extractall(path=temp_dir)
                    except Exception:
                        raise
                else:
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        zf.extractall(temp_dir)
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
                            if not hasattr(self, '_mod_dirs_to_cleanup'):
                                self._mod_dirs_to_cleanup = []
                            if target_dirname not in self._mod_dirs_to_cleanup:
                                self._mod_dirs_to_cleanup.append(target_dirname)
                                self._update_session_manifest(mod_dirs=[target_dirname])
                        except Exception:
                            pass
                        if os.path.exists(target_file):
                            backup_rel_path = os.path.relpath(target_file, target_dir)
                            if hasattr(self, '_backup_temp_dir') and self._backup_temp_dir:
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
            self.update_status_signal.emit(tr('errors.archive_unpack_error', archive_name=os.path.basename(archive_path), error=str(e)), UI_COLORS['status_error'])
        return extracted_files

    def _determine_launch_config(self, selections: Dict[int, str]) -> Optional[Dict[str, Any]]:
        use_steam = self.local_config.get('launch_via_steam', False)
        direct_launch_slot_id = self.local_config.get('direct_launch_slot_id', -1)
        direct_launch = direct_launch_slot_id > 0 and self.game_mode.direct_launch_allowed and (platform.system() != 'Darwin')
        if use_steam:
            return {'target': f'steam://rungameid/{self.game_mode.steam_id}', 'cwd': None, 'type': 'webbrowser'}
        if direct_launch:
            return self._handle_direct_launch(direct_launch_slot_id)
        launch_target = self._get_executable_path()
        if not launch_target:
            self.update_status_signal.emit(tr('errors.executable_not_found'), UI_COLORS['status_error'])
            return None
        return {'target': launch_target, 'cwd': self._get_current_game_path(), 'type': 'subprocess'}

    def _handle_direct_launch(self, selected_tab_index: int) -> Optional[Dict[str, Any]]:
        chapter_folder = self._get_target_dir(self.game_mode.get_chapter_id(selected_tab_index))
        source_exe = self._get_source_executable_path()
        use_custom_exe = self.local_config.get('use_custom_executable', False)
        if not chapter_folder or not source_exe:
            self.update_status_signal.emit(tr('errors.direct_launch_error'), UI_COLORS['status_error'])
            return None
        try:
            if not ensure_writable(chapter_folder):
                raise PermissionError(tr('errors.no_write_permission_for', path=chapter_folder))
            if use_custom_exe:
                target_exe = os.path.join(chapter_folder, os.path.basename(source_exe))
            else:
                exe_name = 'UNDERTALE.exe' if isinstance(self.game_mode, UndertaleGameMode) else 'DELTARUNE.exe'
                target_exe = os.path.join(chapter_folder, exe_name)
            shutil.copy2(source_exe, target_exe)
            self._direct_launch_cleanup_info = {'target_exe': target_exe, 'source_exe': source_exe, 'chapter_folder': chapter_folder, 'use_custom_exe': use_custom_exe}
            self._update_session_manifest(direct_launch=self._direct_launch_cleanup_info)
            return {'target': target_exe, 'cwd': chapter_folder, 'type': 'subprocess'}
        except PermissionError as e:
            if not self.is_shortcut_launch:
                self._handle_permission_error(e.filename or chapter_folder)
            return None

    def _cleanup_direct_launch_files(self):
        try:
            backed_up_targets = set(self._backup_files.keys()) if hasattr(self, '_backup_files') and self._backup_files else set()
            if hasattr(self, '_backup_files') and self._backup_files:
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
            if hasattr(self, '_mod_files_to_cleanup') and self._mod_files_to_cleanup:
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
            if hasattr(self, '_backup_temp_dir') and self._backup_temp_dir and os.path.exists(self._backup_temp_dir):
                try:
                    shutil.rmtree(self._backup_temp_dir)
                    self._backup_temp_dir = None
                except Exception:
                    pass
            try:
                dirs = []
                if hasattr(self, '_mod_dirs_to_cleanup') and self._mod_dirs_to_cleanup:
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
            cleanup_info = getattr(self, '_direct_launch_cleanup_info', None)
            if cleanup_info:
                if 'target_exe' in cleanup_info and os.path.exists(cleanup_info['target_exe']):
                    os.remove(cleanup_info['target_exe'])
                self._direct_launch_cleanup_info = None
            self.update_status_signal.emit(tr('status.files_restored'), UI_COLORS['status_success'])
            self._clear_session_manifest()
        except Exception as e:
            self.update_status_signal.emit(tr('errors.files_restore_error', error=str(e)), UI_COLORS['status_error'])

    def _launch_game_with_all_mods(self):
        selections = self._get_slot_selections()
        self._launch_game_with_selections(selections)

    def _get_slot_selections(self):
        selections = {}
        if not hasattr(self, 'slots'):
            return selections
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        is_undertale_mode = isinstance(self.game_mode, UndertaleGameMode)
        if is_demo_mode:
            demo_slot = self.slots.get(-10)
            if demo_slot and demo_slot.assigned_mod:
                selections[-1] = demo_slot.assigned_mod.key
            else:
                selections[-1] = 'no_change'
        elif is_undertale_mode:
            undertale_slot = self.slots.get(-20)
            if undertale_slot and undertale_slot.assigned_mod:
                selections[-1] = undertale_slot.assigned_mod.key
            else:
                selections[-1] = 'no_change'
        elif self.current_mode == 'normal':
            universal_slot = self.slots.get(-1)
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
        elif self.current_mode == 'chapter':
            for chapter_id in range(5):
                slot = self.slots.get(chapter_id)
                if slot and slot.assigned_mod:
                    selections[chapter_id] = slot.assigned_mod.key
                else:
                    selections[chapter_id] = 'no_change'
        return selections

    def _launch_game_with_selections(self, selections: Dict[int, str]):
        self.hide_window_signal.emit()

        def restore_and_return():
            self.restore_window_signal.emit()
            self._update_action_button_state()
        if not self._find_and_validate_game_path(selections):
            restore_and_return()
            return
        if not self._prepare_game_files(selections):
            restore_and_return()
            return
        if not (launch_config := self._determine_launch_config(selections)):
            restore_and_return()
            return
        self.update_status_signal.emit(tr('status.launching_game'), UI_COLORS['status_success'])
        self._execute_game(launch_config)

    def _execute_game(self, launch_config: Dict[str, Any], vanilla_mode: bool = False):
        target_path = launch_config.get('target')
        working_directory = launch_config.get('cwd')
        launch_type = launch_config.get('type')
        if not target_path:
            self.update_status_signal.emit(tr('errors.launch_target_not_defined'), 'red')
            self.restore_window_signal.emit()
            return
        try:
            if launch_type == 'webbrowser':
                self.monitor_thread = GameMonitorThread(None, vanilla_mode, self)
                self.monitor_thread.finished.connect(self._on_game_process_finished)
                self.monitor_thread.start()
                webbrowser.open(target_path)
                self.update_status_signal.emit(tr('status.launching_via_steam'), UI_COLORS['status_steam'])
                return
            if not working_directory or not os.path.isdir(working_directory):
                msg = tr('errors.working_directory_not_found', path=working_directory)
                self.update_status_signal.emit(msg, 'red')
                self.error_signal.emit(msg)
                self.restore_window_signal.emit()
                return
            system = platform.system()
            if system == 'Darwin':
                use_custom_exe = self.local_config.get('use_custom_executable', False)
                if use_custom_exe:
                    subprocess.Popen(['open', target_path])
                    self.update_status_signal.emit(tr('status.macos_file_opened'), UI_COLORS['status_steam'])
                    if self.is_shortcut_launch:
                        sys.exit(0)
                    else:
                        QTimer.singleShot(2000, self.restore_window_signal.emit)
                    return
                if target_path.endswith('.app'):
                    process = subprocess.Popen(['open', '-W', target_path])
            else:
                command = [target_path]
                if platform.system() == 'Linux' and target_path.lower().endswith('.exe'):
                    runner = shutil.which('wine') or shutil.which('proton')
                    if runner:
                        command.insert(0, runner)
                    else:
                        self.error_signal.emit(tr('errors.wine_not_found'))
                        self.restore_window_signal.emit()
                        return
                creationflags = 0
                if system == 'Windows':
                    creationflags = 8
                process = subprocess.Popen(command, cwd=working_directory, creationflags=creationflags)
            self.update_status_signal.emit(tr('status.game_launched_waiting_for_exit'), UI_COLORS['status_steam'])
            self.monitor_thread = GameMonitorThread(process, vanilla_mode, self)
            self.monitor_thread.finished.connect(self._on_game_process_finished)
            self.monitor_thread.start()
        except Exception as e:
            self.update_status_signal.emit(tr('errors.game_launch_error', error=str(e)), 'red')
            self.error_signal.emit(tr('errors.game_launch_failed', error=str(e)))
            self.restore_window_signal.emit()

    def _get_source_executable_path(self):
        if self.local_config.get('use_custom_executable', False):
            cfg_key = self.game_mode.get_custom_exec_config_key()
            return self.local_config.get(cfg_key, '')
        return self._get_executable_path()

    def _on_game_process_finished(self, vanilla_mode: bool):
        if self.is_shortcut_launch:
            sys.exit(0)
        else:
            self._check_game_running(vanilla_mode)

    def _check_game_running(self, vanilla_mode):
        if is_game_running():
            QTimer.singleShot(2000, lambda: self._check_game_running(vanilla_mode))
        else:
            self.update_status_signal.emit(tr('status.game_closed_restoring_files'), UI_COLORS['status_info'])
            self._cleanup_direct_launch_files()
            self.restore_window_signal.emit()

    def _hide_window_for_game(self):
        try:
            self._stop_background_music()
        except Exception:
            pass
        self.hide()

    def _restore_window_after_game(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.progress_bar.setVisible(False)
        self._update_action_button_state()
        QTimer.singleShot(100, self.updateGeometry)
        if hasattr(self, '_update_installed_mods_display'):
            self._update_installed_mods_display()
        if hasattr(self, '_update_mod_display'):
            self._update_mod_display()
        self._maybe_start_background_music()

    def _force_ui_update_after_restore(self):
        if hasattr(self, '_update_installed_mods_display'):
            self._update_installed_mods_display()
        if hasattr(self, '_update_mod_display'):
            self._update_mod_display()
        self.updateGeometry()

    def _update_status(self, message: str, color: str = 'white'):
        if not self.is_shortcut_launch:
            self.status_label.setText(message)
            self.status_label.setStyleSheet(f'color: {color};')

    def _run_presence_tick(self):
        if self.is_shortcut_launch:
            return
        thr = getattr(self, 'presence_thread', None)
        try:
            if thr and thr.isRunning():
                return
        except RuntimeError:
            self.presence_thread = None
            thr = None
        self.presence_thread = QThread(self)
        self.presence_worker = PresenceWorker(self.session_id)
        self.presence_worker.moveToThread(self.presence_thread)
        self.presence_thread.started.connect(self.presence_worker.run)
        self.presence_worker.finished.connect(self.presence_thread.quit)
        self.presence_thread.finished.connect(lambda: setattr(self, 'presence_thread', None))
        self.presence_thread.finished.connect(self.presence_thread.deleteLater)
        self.presence_worker.finished.connect(self.presence_worker.deleteLater)
        self.presence_worker.update_online_count.connect(self._update_online_label)
        self.presence_thread.start()

    def _update_online_label(self, count: int):
        if not self.is_shortcut_launch:
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=count)}")

    def _on_toggle_custom_executable(self):
        use_custom = self.use_custom_executable_checkbox.isChecked()
        self.local_config['use_custom_executable'] = use_custom
        if not use_custom:
            self.local_config[self.game_mode.get_custom_exec_config_key()] = ''
        self._write_local_config()
        self._update_custom_executable_ui()

    def _select_custom_executable_file(self):
        dlg_title = tr('ui.select_launch_file')
        filepath = QFileDialog.getOpenFileName(self, dlg_title)[0]
        if filepath:
            self.local_config[self.game_mode.get_custom_exec_config_key()] = filepath
            self._write_local_config()
            self._update_custom_executable_ui()

    def _update_custom_executable_ui(self):
        use_custom = self.local_config.get('use_custom_executable', False)
        path = self.local_config.get(self.game_mode.get_custom_exec_config_key(), '')
        self.custom_exe_frame.setVisible(use_custom and self.use_custom_executable_checkbox.isEnabled())
        if self.custom_exe_frame.isVisible():
            self.custom_executable_path_label.setText(tr('ui.currently_selected', filename=os.path.basename(path)) if path else tr('ui.file_not_selected'))

    def _on_toggle_steam_launch(self, state=None):
        is_steam_launch = self.launch_via_steam_checkbox.isChecked()
        self.local_config['launch_via_steam'] = is_steam_launch
        self._write_local_config()
        self._update_custom_executable_ui()

    def _on_language_changed(self):
        selected_data = self.language_combo.currentData()
        if not selected_data:
            return
        manager = get_localization_manager()
        current_language = manager.get_current_language()
        if selected_data == current_language:
            return
        self.local_config['language'] = selected_data
        self._write_json(self.config_path, self.local_config)
        manager = get_localization_manager()
        manager.load_language(selected_data)
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(tr('ui.restart_required'))
        msg_box.setText(tr('ui.restart_message'))
        msg_box.setIcon(QMessageBox.Icon.Information)
        restart_button = msg_box.addButton(tr('ui.restart_button'), QMessageBox.ButtonRole.AcceptRole)
        msg_box.setDefaultButton(restart_button)
        if msg_box.clickedButton() == restart_button:
            try:
                from PyQt6.QtCore import QProcess
                launcher_dir = get_launcher_dir()
                QProcess.startDetached(sys.executable, sys.argv, launcher_dir)
            except Exception:
                import subprocess
                launcher_dir = get_launcher_dir()
                subprocess.Popen([sys.executable] + sys.argv, cwd=launcher_dir)
            QApplication.quit()

    def _check_active_slots_need_updates(self):
        if not self.all_mods:
            return False
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        if is_demo_mode:
            active_slot_ids = [-10]
        elif isinstance(self.game_mode, UndertaleGameMode):
            active_slot_ids = [-20]
        elif not is_chapter_mode:
            active_slot_ids = [-1]
        else:
            active_slot_ids = [0, 1, 2, 3, 4]
        for slot_id in active_slot_ids:
            for slot_frame in self.slots.values():
                if slot_frame.chapter_id == slot_id and slot_frame.assigned_mod:
                    mod_data = slot_frame.assigned_mod
                    mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                    if mod_key and mod_key.startswith('local_'):
                        continue
                    if slot_id < 0:
                        needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                    else:
                        needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                    if needs_update:
                        return True
        return False

    def _update_mods_in_active_slots(self):
        if self.is_installing:
            return
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        if is_demo_mode:
            active_slot_ids = [-10]
        elif isinstance(self.game_mode, UndertaleGameMode):
            active_slot_ids = [-20]
        elif not is_chapter_mode:
            active_slot_ids = [-1]
        else:
            active_slot_ids = [0, 1, 2, 3, 4]
        mods_to_update = []
        for slot_id in active_slot_ids:
            for slot_frame in self.slots.values():
                if slot_frame.chapter_id == slot_id and slot_frame.assigned_mod:
                    mod_data = slot_frame.assigned_mod
                    mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None)
                    if mod_key and mod_key.startswith('local_'):
                        continue
                    needs_update = any((self._mod_has_files_for_chapter(mod_data, i) and self._get_mod_status_for_chapter(mod_data, i) == 'update' for i in range(5)))
                    if needs_update and mod_data not in mods_to_update:
                        mods_to_update.append(mod_data)
        if mods_to_update:
            self.pending_updates = mods_to_update[1:] if len(mods_to_update) > 1 else []
            self._update_mod(mods_to_update[0])

    def _refresh_slots_content(self):
        self._refresh_all_slot_status_displays()

    def _on_manage_mods_click(self):
        if not check_internet_connection():
            QMessageBox.critical(self, tr('errors.connection_error'), tr('errors.internet_required'))
            return
        self._show_main_mod_management_dialog()

    def _on_xdelta_patch_click(self):
        try:
            dialog = XdeltaDialog(self)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.patching_window_failed', error=str(e)))

    def _show_main_mod_management_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.mod_management'))
        dialog.setModal(True)
        dialog.resize(400, 300)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr('dialogs.what_do_you_want_to_do'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size: 18px; font-weight: bold; margin-bottom: 20px;')
        layout.addWidget(title)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        create_button = QPushButton(tr('ui.create_mod'))
        create_button.setFixedSize(180, 50)
        create_button.clicked.connect(lambda: self._on_create_mod_choice(dialog))
        edit_button = QPushButton(tr('ui.edit_mod'))
        edit_button.setFixedSize(180, 50)
        edit_button.clicked.connect(lambda: self._on_edit_mod_choice(dialog))
        buttons_layout.addWidget(create_button)
        buttons_layout.addWidget(edit_button)
        layout.addLayout(buttons_layout)
        layout.addSpacing(30)
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)
        dialog.exec()

    def _on_create_mod_choice(self, parent_dialog):
        parent_dialog.accept()
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.create_mod'))
        dialog.setModal(True)
        dialog.resize(300, 200)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr('ui.how_to_create_mod'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size: 16px; font-weight: bold;')
        layout.addWidget(title)
        type_buttons_layout = QHBoxLayout()
        type_buttons_layout.setSpacing(15)
        public_button = QPushButton(tr('buttons.public'))
        public_button.setFixedSize(130, 40)
        public_button.clicked.connect(lambda: self._create_mod(dialog, public=True))
        local_button = QPushButton(tr('buttons.local'))
        local_button.setFixedSize(130, 40)
        local_button.clicked.connect(lambda: self._create_mod(dialog, public=False))
        type_buttons_layout.addWidget(public_button)
        type_buttons_layout.addWidget(local_button)
        layout.addLayout(type_buttons_layout)
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)
        dialog.exec()

    def _on_edit_mod_choice(self, parent_dialog):
        parent_dialog.accept()
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('ui.edit_mod'))
        dialog.setModal(True)
        dialog.resize(300, 200)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr('dialogs.what_mod_type_to_change'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size: 16px; font-weight: bold;')
        layout.addWidget(title)
        edit_buttons_layout = QHBoxLayout()
        edit_buttons_layout.setSpacing(15)
        public_button = QPushButton(tr('buttons.public_button'))
        public_button.setFixedSize(130, 40)
        public_button.clicked.connect(lambda: self._edit_public_mod(dialog))
        local_button = QPushButton(tr('status.local'))
        local_button.setFixedSize(130, 40)
        local_button.clicked.connect(lambda: self._edit_local_mod(dialog))
        edit_buttons_layout.addWidget(public_button)
        edit_buttons_layout.addWidget(local_button)
        layout.addLayout(edit_buttons_layout)
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)
        dialog.exec()

    def _create_mod(self, parent_dialog, public: bool):
        parent_dialog.accept()
        if public and (not check_internet_connection()):
            QMessageBox.critical(self, tr('errors.no_internet'), tr('errors.public_mod_internet'))
            return
        editor = ModEditorDialog(self, is_creating=True, is_public=public)
        editor.exec()
        try:
            self.activateWindow()
            self.raise_()
            self.setFocus()
        except Exception:
            pass

    def _edit_public_mod(self, parent_dialog):
        parent_dialog.accept()
        if not check_internet_connection():
            QMessageBox.critical(self, tr('errors.no_internet'), tr('errors.edit_mod_internet'))
            return
        secret_key, ok = QInputDialog.getText(self, tr('dialogs.enter_secret_key'), tr('dialogs.secret_key_mod'), QLineEdit.EchoMode.Password)
        if not ok or not secret_key.strip():
            return
        from utils.crypto_utils import possible_secret_hashes
        candidate_hashes = possible_secret_hashes(secret_key.strip())
        mod_data = None
        found_in_pending = False
        try:
            found_hash = None
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            for h in candidate_hashes:
                resp = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getModData?modId={h}', timeout=10)
                if resp.status_code == 200 and resp.json():
                    mod_data = resp.json()
                    found_hash = h
                    break
                resp = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingModData?modId={h}', timeout=10)
                if resp.status_code == 200 and resp.json():
                    mod_data = resp.json()
                    found_hash = h
                    found_in_pending = True
                    break
            if found_hash and isinstance(mod_data, dict):
                mod_data['key'] = found_hash
                hashed_key = found_hash
        except requests.RequestException as e:
            QMessageBox.critical(self, tr('errors.error'), tr('errors.key_check_failed', error=str(e)))
            return
        if not mod_data:
            QMessageBox.warning(self, tr('errors.mod_not_found'), tr('errors.secret_key_invalid'))
            return
        if mod_data.get('ban_status', False):
            ban_reason = mod_data.get('ban_reason', tr('defaults.not_specified_fem'))
            QMessageBox.critical(self, tr('dialogs.mod_blocked_title'), tr('dialogs.mod_blocked_message', ban_reason=ban_reason, error_message=tr('dialogs.error_occurred')))
            return
        if found_in_pending:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr('dialogs.mod_on_moderation'))
            msg_box.setText(tr('dialogs.mod_on_moderation_message'))
            withdraw_btn = msg_box.addButton(tr('buttons.withdraw_request'), QMessageBox.ButtonRole.DestructiveRole)
            ok_btn = msg_box.addButton(tr('buttons.ok'), QMessageBox.ButtonRole.AcceptRole)
            msg_box.setDefaultButton(ok_btn)
            msg_box.exec()
            if msg_box.clickedButton() == withdraw_btn:
                try:
                    from config.constants import CLOUD_FUNCTIONS_BASE_URL
                    requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingMod', json={'hashedKey': hashed_key}, timeout=10)
                    QMessageBox.information(self, tr('dialogs.request_withdrawn'), tr('dialogs.withdrawal_success'))
                except Exception as e:
                    QMessageBox.critical(self, tr('errors.error'), tr('errors.request_revoke_failed', error=str(e)))
            return
        try:
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            pending_changes_response = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingChangeData?modId={hashed_key}', timeout=10)
            if pending_changes_response.status_code == 200 and pending_changes_response.json():
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(tr('dialogs.changes_under_review'))
                msg_box.setText(tr('dialogs.request_pending'))
                msg_box.setIcon(QMessageBox.Icon.Information)
                withdraw_button = msg_box.addButton(tr('buttons.withdraw_request'), QMessageBox.ButtonRole.DestructiveRole)
                msg_box.exec()
                reply = msg_box.clickedButton()
                if reply == withdraw_button:
                    try:
                        from config.constants import CLOUD_FUNCTIONS_BASE_URL
                        delete_response = requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingChange', json={'hashedKey': hashed_key}, timeout=10)
                        delete_response.raise_for_status()
                        QMessageBox.information(self, tr('dialogs.request_withdrawn'), tr('dialogs.withdrawal_success'))
                    except requests.RequestException as e:
                        QMessageBox.critical(self, tr('errors.error'), tr('errors.request_revoke_failed', error=str(e)))
                        return
                else:
                    return
        except requests.RequestException:
            pass
        editor = ModEditorDialog(self, is_creating=False, is_public=True, mod_data=mod_data)
        editor.exec()
        try:
            self.activateWindow()
            self.raise_()
            self.setFocus()
        except Exception:
            pass

    def _edit_local_mod(self, parent_dialog):
        parent_dialog.accept()
        local_mods = []
        if os.path.exists(self.mods_dir):
            for folder_name in os.listdir(self.mods_dir):
                folder_path = os.path.join(self.mods_dir, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                config_path = os.path.join(folder_path, 'config.json')
                if not os.path.exists(config_path):
                    continue
                try:
                    config_data = self._read_json(config_path)
                    if config_data and config_data.get('is_local_mod'):
                        mod_info = {'key': config_data.get('mod_key'), 'name': config_data.get('name', 'Неизвестный мод'), 'data': config_data, 'folder_path': folder_path}
                        local_mods.append(mod_info)
                except Exception:
                    continue
        if not local_mods:
            QMessageBox.information(self, tr('dialogs.no_local_mods_title'), tr('dialogs.no_local_mods_message'))
            return
        mod_names = [mod_info['name'] for mod_info in local_mods]
        selected_name, ok = QInputDialog.getItem(self, tr('dialogs.select_mod'), tr('dialogs.local_mods'), mod_names, 0, False)
        if not ok:
            return
        selected_mod = None
        for mod_info in local_mods:
            if mod_info['name'] == selected_name:
                selected_mod = mod_info
                break
        if not selected_mod:
            QMessageBox.warning(self, tr('errors.error'), tr('errors.selected_mod_not_found'))
            return
        mod_data = selected_mod['data'].copy()
        mod_data['key'] = selected_mod['key']
        mod_data['folder_name'] = os.path.basename(selected_mod['folder_path']) if selected_mod.get('folder_path') else ''
        editor = ModEditorDialog(self, is_creating=False, is_public=False, mod_data=mod_data)
        editor.exec()
        try:
            self.activateWindow()
            self.raise_()
            self.setFocus()
        except Exception:
            pass

    def _get_mod_status_for_chapter(self, mod: ModInfo, chapter_id: int) -> str:
        if mod.key.startswith('local_'):
            return 'ready'
        if not os.path.exists(self.mods_dir):
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
        for mod_folder in os.listdir(self.mods_dir):
            mod_cache_dir = os.path.join(self.mods_dir, mod_folder)
            config_path = os.path.join(mod_cache_dir, 'config.json')
            if not os.path.isfile(config_path):
                continue
            try:
                config_data = self._read_json(config_path)
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
                        extra_files = file_info.get('extra_files', {})
                        versions_data = file_info.get('versions', {})
                        for group_key in extra_files.keys():
                            local_versions[group_key] = versions_data.get(group_key, '1.0.0')
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

    def _is_mod_installed(self, mod_key: str) -> bool:
        if not os.path.exists(self.mods_dir):
            return False
        for mod_folder in os.listdir(self.mods_dir):
            config_path = os.path.join(self.mods_dir, mod_folder, 'config.json')
            if os.path.isfile(config_path):
                try:
                    config_data = self._read_json(config_path)
                    stored_key = config_data.get('mod_key') or config_data.get('key')
                    if stored_key == mod_key:
                        return True
                except Exception as e:
                    logging.warning(f'Failed to parse local config {config_path}: {e}')
                    continue
        return False

    def closeEvent(self, event):
        self._stop_background_music()
        self._online_timer.stop()
        if self.is_shortcut_launch:
            super().closeEvent(event)
            return
        self._cleanup_direct_launch_files()
        self._save_window_geometry()
        self._stop_presence_thread()
        self._stop_fetch_thread()
        for attr in ('install_thread', 'full_install_thread', '_bg_loader', 'monitor_thread'):
            self._safe_stop_thread(getattr(self, attr, None))
        super().closeEvent(event)

    def _schedule_geometry_save(self):
        if hasattr(self, '_geometry_save_timer'):
            self._geometry_save_timer.stop()
        else:
            from PyQt6.QtCore import QTimer
            self._geometry_save_timer = QTimer()
            self._geometry_save_timer.setSingleShot(True)
            self._geometry_save_timer.timeout.connect(self._save_window_geometry)
        self._geometry_save_timer.start(500)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'launcher_icon_label') and hasattr(self, 'top_panel_widget'):
            panel_width = self.top_panel_widget.width()
            logo_width = self.launcher_icon_label.width()
            logo_height = self.launcher_icon_label.height()
            panel_height = self.top_panel_widget.height()
            y = max(0, (panel_height - logo_height) // 2)
            self.launcher_icon_label.move((panel_width - logo_width) // 2, y)
        self._schedule_geometry_save()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_geometry_save()

    def _load_local_data(self):
        self.local_config = self._read_json(self.config_path) or {}

    def _migrate_config_if_needed(self):
        self.local_config['cache_format_version'] = LAUNCHER_VERSION
        defaults = {'game_path': '', 'last_selected': {}, 'use_custom_executable': False, 'demo_game_path': '', 'launch_via_steam': False, 'direct_launch_slot_id': -1, 'demo_mode_enabled': False, 'chapter_mode_enabled': False, 'custom_background_path': '', 'custom_executable_path': '', 'background_disabled': False, 'custom_color_background': '', 'custom_color_button': '', 'custom_color_border': '', 'custom_color_button_hover': '', 'custom_color_text': '', 'mods_dir_path': '', 'custom_color_version_text': ''}
        for key, value in defaults.items():
            self.local_config.setdefault(key, value)
        self._write_local_config()

    def _write_local_config(self):
        self._write_json(self.config_path, self.local_config)

    def _write_json(self, path: str, data):
        try:
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except (PermissionError, OSError):
            self._handle_permission_error(os.path.dirname(path))
        except Exception as e:
            self.update_status_signal.emit(tr('errors.file_write_error', error=str(e)), UI_COLORS['status_error'])

    def _read_json(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and path.endswith('config.json'):
                needs_migration = False
                if 'chapters' in data and 'files' not in data:
                    data['files'] = data['chapters']
                    del data['chapters']
                    needs_migration = True
                if 'is_demo_mod' in data and 'modtype' not in data:
                    if data.get('is_demo_mod', False):
                        data['modtype'] = 'deltarunedemo'
                    else:
                        data['modtype'] = 'deltarune'
                    del data['is_demo_mod']
                    needs_migration = True
                if needs_migration:
                    self._write_json(path, data)
            return data
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            backup_path = f'{path}.invalid.bak'
            try:
                os.replace(path, backup_path)
            except OSError:
                pass
            self.update_status_signal.emit(tr('dialogs.corrupted_files_found'), UI_COLORS['status_warning'])
            return {}

    def _init_localization(self):
        manager = get_localization_manager()
        saved_language = self.local_config.get('language', '')
        if not saved_language:
            detected_language = manager.detect_system_language()
            self.local_config['language'] = detected_language
            self._write_json(self.config_path, self.local_config)
            saved_language = detected_language
        if saved_language in manager.get_available_languages():
            if manager.get_current_language() != saved_language:
                manager.load_language(saved_language)
        else:
            manager.load_language('en')
            self.local_config['language'] = 'en'
            self._write_json(self.config_path, self.local_config)
            saved_language = 'en'
        self._update_qt_translations(saved_language)

    def _update_qt_translations(self, language_code):
        from PyQt6.QtCore import QLibraryInfo, QTranslator
        manager = get_localization_manager()
        qt_translation = manager.get_qt_translation_name(language_code)
        if not qt_translation:
            return
        app = QApplication.instance()
        if app is None:
            return
        if hasattr(self, '_qt_translator') and self._qt_translator:
            app.removeTranslator(self._qt_translator)
        self._qt_translator = QTranslator()
        if self._qt_translator.load(qt_translation, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(self._qt_translator)

    def _get_executable_path(self):
        use_custom_exe = self.local_config.get('use_custom_executable', False)
        if use_custom_exe:
            custom_path = self.local_config.get(self.game_mode.get_custom_exec_config_key(), '')
            if custom_path and os.path.isfile(custom_path):
                return custom_path
        current_game_path = self._get_current_game_path()
        if not current_game_path or not os.path.isdir(current_game_path):
            return None
        system = platform.system()
        is_undertale = isinstance(self.game_mode, UndertaleGameMode)
        base_exe_name = 'UNDERTALE' if is_undertale else 'DELTARUNE'
        if system == 'Windows':
            exe_path = os.path.join(current_game_path, f'{base_exe_name}.exe')
            if os.path.isfile(exe_path):
                return exe_path
        elif system == 'Linux':
            exe_path = os.path.join(current_game_path, f'{base_exe_name}.exe')
            if os.path.isfile(exe_path):
                return exe_path
            native_path = os.path.join(current_game_path, base_exe_name)
            if os.path.isfile(native_path):
                return native_path
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
        if not self.is_shortcut_launch:
            self.update_status_signal.emit(tr('errors.executable_not_found_deltarune'), UI_COLORS['status_error'])
        return None

    def _gather_shortcut_settings(self) -> Optional[Dict[str, Any]]:
        current_path = self._get_current_game_path()
        if not current_path:
            return None
        is_demo_mode = isinstance(self.game_mode, DemoGameMode)
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        is_undertale_mode = isinstance(self.game_mode, UndertaleGameMode)
        settings = {'launcher_version': LAUNCHER_VERSION, 'game_path': self.game_path, 'demo_game_path': self.demo_game_path, 'is_demo_mode': is_demo_mode, 'is_chapter_mode': is_chapter_mode, 'is_undertale_mode': is_undertale_mode, 'launch_via_steam': self.launch_via_steam_checkbox.isChecked(), 'use_custom_executable': self.use_custom_executable_checkbox.isChecked(), 'custom_executable_path': self.local_config.get(FullGameMode().get_custom_exec_config_key(), ''), 'demo_custom_executable_path': self.local_config.get(DemoGameMode().get_custom_exec_config_key(), ''), 'direct_launch_slot_id': self.local_config.get('direct_launch_slot_id', -1), 'mods': {}}
        if is_demo_mode:
            demo_mod_key = None
            try:
                demo_slot = self.slots.get(-10) if hasattr(self, 'slots') else None
                if demo_slot and getattr(demo_slot, 'assigned_mod', None):
                    demo_mod_key = getattr(demo_slot.assigned_mod, 'key', None) or getattr(demo_slot.assigned_mod, 'mod_key', None)
            except Exception:
                demo_mod_key = None
            settings['mods']['demo'] = demo_mod_key
        elif is_undertale_mode:
            undertale_mod_key = None
            try:
                undertale_slot = self.slots.get(-20) if hasattr(self, 'slots') else None
                if undertale_slot and getattr(undertale_slot, 'assigned_mod', None):
                    undertale_mod_key = getattr(undertale_slot.assigned_mod, 'key', None) or getattr(undertale_slot.assigned_mod, 'mod_key', None)
            except Exception:
                undertale_mod_key = None
            settings['mods']['undertale'] = undertale_mod_key
        elif is_chapter_mode:
            for slot_frame in self.slots.values():
                chapter_id = slot_frame.chapter_id
                if chapter_id >= 0:
                    mod_key = None
                    if slot_frame.assigned_mod:
                        mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None)
                    settings['mods'][str(chapter_id)] = mod_key
        else:
            universal_mod_key = None
            try:
                universal_slot = self.slots.get(-1) if hasattr(self, 'slots') else None
                if universal_slot and getattr(universal_slot, 'assigned_mod', None):
                    universal_mod_key = getattr(universal_slot.assigned_mod, 'key', None) or getattr(universal_slot.assigned_mod, 'mod_key', None)
            except Exception:
                universal_mod_key = None
            settings['mods']['universal'] = universal_mod_key
        return settings

    def _apply_shortcut_mods(self, mods_settings: Dict[str, str]):
        try:
            if not mods_settings:
                return
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)
            is_undertale_mode = isinstance(self.game_mode, UndertaleGameMode)
            if is_demo_mode:
                mod_key = mods_settings.get('demo')
                if mod_key and mod_key != 'no_change':
                    self._apply_demo_mod(mod_key)
            elif is_undertale_mode:
                mod_key = mods_settings.get('undertale')
                if mod_key and mod_key != 'no_change':
                    self._apply_mod_by_key(mod_key)
            else:
                for key, mod_key in mods_settings.items():
                    if mod_key and mod_key != 'no_change':
                        if key.isdigit():
                            self._apply_mod_by_key(mod_key)
                        elif key == 'demo':
                            continue
                        else:
                            self._apply_mod_by_key(mod_key)
        except Exception as e:
            raise Exception(tr('errors.mod_apply_error', error=str(e)))

    def _apply_demo_mod(self, mod_key: str):
        mod_config = self._get_mod_config_by_key(mod_key)
        if not mod_config:
            raise Exception(tr('errors.mod_not_found_by_key', mod_key=mod_key))

    def _apply_mod_by_key(self, mod_key: str):
        mod_config = self._get_mod_config_by_key(mod_key)
        if not mod_config:
            raise Exception(tr('errors.mod_not_found_by_key', mod_key=mod_key))
        mod_folder = os.path.join(self.mods_dir, mod_key)
        if not os.path.exists(mod_folder):
            mod_folder = os.path.join(self.mods_dir, mod_config.get('name', ''))
            if not os.path.exists(mod_folder):
                raise Exception(tr('errors.mod_files_not_found_by_key', mod_key=mod_key))

    def _launch_game_from_shortcut(self, launch_via_steam=False, use_custom_executable=False, custom_exec_path='', demo_custom_exec_path='', direct_launch_slot_id=-1):
        try:
            is_demo_mode = isinstance(self.game_mode, DemoGameMode)
            current_game_path = self._get_current_game_path()
            if not current_game_path or not os.path.exists(current_game_path):
                raise Exception(tr('errors.game_files_not_found'))
            executable_path = None
            if use_custom_executable:
                exec_path = demo_custom_exec_path if is_demo_mode else custom_exec_path
                if exec_path and os.path.exists(exec_path):
                    executable_path = exec_path
                else:
                    raise Exception(tr('errors.specified_executable_not_found'))
            else:
                if isinstance(self.game_mode, UndertaleGameMode):
                    possible_names = ['UNDERTALE.exe', 'undertale.exe']
                else:
                    possible_names = ['DELTARUNE.exe', 'deltarune.exe', 'SURVEY_PROGRAM.exe', 'survey_program.exe']
                for name in possible_names:
                    test_path = os.path.join(current_game_path, name)
                    if os.path.exists(test_path):
                        executable_path = test_path
                        break
                if not executable_path:
                    raise Exception(tr('errors.executable_not_found_simple'))
            if launch_via_steam:
                steam_app_id = self.game_mode.steam_id
                webbrowser.open(f'steam://run/{steam_app_id}')
            else:
                args = []
                if direct_launch_slot_id >= 0:
                    if direct_launch_slot_id == 1:
                        args.extend(['-chapter', '1'])
                    elif direct_launch_slot_id == 2:
                        args.extend(['-chapter', '2'])
                command = [executable_path] + args
                if platform.system() == 'Linux' and executable_path.lower().endswith('.exe'):
                    runner = shutil.which('wine') or shutil.which('proton')
                    if runner:
                        command.insert(0, runner)
                    else:
                        raise Exception(tr('errors.wine_not_found'))
                subprocess.Popen(command, cwd=current_game_path)
        except Exception as e:
            raise Exception(tr('errors.launch_error_details', error=str(e)))

    def _save_shortcut(self, settings: Dict[str, Any]):
        system = platform.system()
        if system == 'Windows':
            file_filter = tr('ui.windows_shortcut_filter')
            default_name = tr('ui.default_shortcut_name_bat')
        elif system == 'Darwin':
            file_filter = 'macOS Command Script (*.command)'
            default_name = tr('ui.default_shortcut_name_command')
        else:
            file_filter = tr('ui.desktop_shortcut_filter')
            default_name = 'DELTAHUB-Deltarune.desktop'
        shortcut_path, _ = QFileDialog.getSaveFileName(self, tr('dialogs.save_shortcut'), os.path.expanduser(f'~/{default_name}'), file_filter)
        if not shortcut_path:
            return
        if getattr(sys, 'frozen', False):
            launcher_executable_path = sys.executable
        else:
            launcher_executable_path = sys.executable
            main_script_path = os.path.join(os.path.dirname(__file__), 'main.py')
        settings_json = json.dumps(settings)
        settings_b64 = base64.b64encode(settings_json.encode('utf-8')).decode('utf-8')
        args = f'--shortcut-launch "{settings_b64}" --shortcut-path "{shortcut_path}"'
        try:
            if system == 'Windows':
                if getattr(sys, 'frozen', False):
                    content = f'@echo off\nstart "" "{launcher_executable_path}" {args}'
                else:
                    content = f'@echo off\nstart "" "{launcher_executable_path}" "{main_script_path}" {args}'
            elif system == 'Darwin':
                content = f'#!/bin/bash\nnohup "{launcher_executable_path}" {args} > /dev/null 2>&1 &'
            else:
                icon_path = resource_path('icons/icon.ico')
                content = f'[Desktop Entry]\nVersion=1.0\nType=Application\nName=Deltarune (DELTAHUB)\nExec="{launcher_executable_path}" {args}\nIcon={icon_path}\nTerminal=false\n'
            with open(shortcut_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if system in ['Linux', 'Darwin']:
                os.chmod(shortcut_path, 493)
            QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.shortcut_created_successfully', path=shortcut_path))
        except Exception as e:
            self.update_status_signal.emit(tr('status.shortcut_creation_error', error=str(e)), UI_COLORS['status_error'])
            QMessageBox.critical(self, tr('errors.error'), tr('errors.shortcut_creation_failed', error=str(e)))

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
            self.update_status_signal.emit(tr('errors.chapter_folder_search_error', error=str(e)), UI_COLORS['status_error'])
            return None

    def _has_mods_with_data_files(self, selections: Dict[int, str]) -> bool:
        for ui_index, mod_key in selections.items():
            if mod_key == 'no_change':
                continue
            mod = next((m for m in self.all_mods if m.key == mod_key), None)
            if not mod:
                continue
            chapter_id = self.game_mode.get_chapter_id(ui_index)
            if mod_key.startswith('local_'):
                mod_config = self._get_mod_config_by_key(mod_key)
                if mod_config:
                    chapter_files = mod_config.get('files', {}).get(str(chapter_id), {})
                    if chapter_files.get('data_file_url'):
                        return True
            else:
                chapter_data = mod.get_chapter_data(chapter_id)
                if chapter_data and hasattr(chapter_data, 'data_file_url') and chapter_data.data_file_url:
                    return True
        return False

    def _find_and_validate_game_path(self, selections: Optional[Dict[int, str]] = None, is_initial: bool = False):
        path_from_config = self._get_current_game_path()
        skip_data_check = bool(selections and self._has_mods_with_data_files(selections))
        if isinstance(self.game_mode, DemoGameMode):
            game_type = 'deltarune'
        elif isinstance(self.game_mode, UndertaleGameMode):
            game_type = 'undertale'
        else:
            game_type = 'deltarune'
        if is_valid_game_path(path_from_config, skip_data_check, game_type):
            self.update_status_signal.emit(tr('status.game_path', path=path_from_config), UI_COLORS['status_info'])
            return True
        self.update_status_signal.emit(tr('status.autodetecting_path'), UI_COLORS['status_info'])
        if isinstance(self.game_mode, DemoGameMode):
            game_name = 'DELTARUNEdemo'
        elif isinstance(self.game_mode, UndertaleGameMode):
            game_name = 'UNDERTALE'
        else:
            game_name = 'DELTARUNE'
        autodetected_path = autodetect_path(game_name)
        if autodetected_path and is_valid_game_path(autodetected_path, skip_data_check, game_type):
            self.game_mode.set_game_path(self.local_config, autodetected_path)
            self.update_status_signal.emit(tr('status.game_folder_found', path=autodetected_path), UI_COLORS['status_success'])
            self._write_local_config()
            return True
        if is_initial:
            self.update_status_signal.emit(tr('status.no_game_path'), UI_COLORS['status_error'])
        return False

    def _prompt_for_game_path(self, is_initial=False):
        if isinstance(self.game_mode, DemoGameMode):
            title = tr('dialogs.select_demo_folder')
            message = tr('dialogs.demo_not_found')
        elif isinstance(self.game_mode, UndertaleGameMode):
            title = tr('dialogs.select_undertale_folder')
            message = tr('dialogs.undertale_not_found')
        else:
            title = tr('dialogs.select_deltarune_folder')
            message = tr('dialogs.deltarune_not_found')
        if is_initial:
            QMessageBox.information(self, tr('dialogs.path_not_found'), tr('dialogs.game_path_instruction', message=message))
        if platform.system() == 'Darwin':
            path, _ = QFileDialog.getOpenFileName(self, title, '', 'Application bundle (*.app);;All files (*)')
            if not path:
                path = QFileDialog.getExistingDirectory(self, title)
        else:
            path = QFileDialog.getExistingDirectory(self, title)
        if path:
            corrected_path = path
            if platform.system() == 'Darwin' and (not path.endswith('.app')):
                if isinstance(self.game_mode, UndertaleGameMode):
                    app_names = ('UNDERTALE.app',)
                else:
                    app_names = ('DELTARUNE.app', 'DELTARUNEdemo.app')
                for app_name in app_names:
                    candidate = os.path.join(path, app_name)
                    if os.path.isdir(candidate):
                        corrected_path = candidate
                        break
            if isinstance(self.game_mode, UndertaleGameMode):
                game_type = 'undertale'
            else:
                game_type = 'deltarune'
            if is_valid_game_path(corrected_path, False, game_type):
                self.game_mode.set_game_path(self.local_config, corrected_path)
                self._write_local_config()
                self.update_status_signal.emit(tr('status.game_path_set', path=corrected_path), UI_COLORS['status_success'])
                self._update_action_button_state()
                return True
            else:
                QMessageBox.warning(self, tr('dialogs.invalid_folder'), tr('dialogs.invalid_game_folder'))
        if is_initial:
            self._start_background_music()
            self.initialization_finished.emit()
            self.update_status_signal.emit(tr('status.no_game_path'), UI_COLORS['status_error'])

    def _save_slots_state(self):
        if not hasattr(self, 'slots'):
            return
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        config_key = self._get_slots_config_key(self.game_mode, is_chapter_mode)
        slots_data = {}
        for slot_id, slot_frame in self.slots.items():
            if slot_frame.assigned_mod:
                mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if mod_key:
                    slots_data[str(slot_id)] = {'mod_key': mod_key, 'mod_name': slot_frame.assigned_mod.name}
        self.local_config[config_key] = slots_data
        self._write_local_config()

    def _load_slots_state(self, mode=None):
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        config_key = self._get_slots_config_key(self.game_mode, is_chapter_mode)
        slots_data = self.local_config.get(config_key, {})
        for slot in self.slots.values():
            if slot.assigned_mod:
                self._remove_mod_from_slot(slot, slot.assigned_mod)
        if isinstance(self.game_mode, DemoGameMode):
            config_key = 'saved_slots_deltarunedemo'
        elif isinstance(self.game_mode, UndertaleGameMode):
            config_key = 'saved_slots_undertale'
        else:
            is_chapter_mode = getattr(self, 'chapter_mode_checkbox', None) and self.chapter_mode_checkbox.isChecked()
            config_key = 'saved_slots_deltarune_chapter' if is_chapter_mode else 'saved_slots_deltarune'
        slots_data = self.local_config.get(config_key, {})
        if not slots_data:
            return
        for slot_id, slot_data in slots_data.items():
            try:
                numeric_slot_id = int(slot_id)
            except ValueError:
                continue
            is_chapter_mode = getattr(self, 'chapter_mode_checkbox', None) and self.chapter_mode_checkbox.isChecked()
            if isinstance(self.game_mode, DemoGameMode):
                if numeric_slot_id != -10:
                    continue
            elif isinstance(self.game_mode, UndertaleGameMode):
                if numeric_slot_id != -20:
                    continue
            elif is_chapter_mode:
                if numeric_slot_id not in [0, 1, 2, 3, 4]:
                    continue
            elif numeric_slot_id != -1:
                continue
            if numeric_slot_id not in self.slots:
                continue
            slot_frame = self.slots[numeric_slot_id]
            mod_key = slot_data.get('mod_key')
            if not mod_key:
                continue
            mod_data = None
            if hasattr(self, 'all_mods') and self.all_mods:
                for mod in self.all_mods:
                    if getattr(mod, 'key', None) == mod_key:
                        mod_data = mod
                        break
            if not mod_data:
                installed_mods = self._get_installed_mods_list()
                for installed_mod in installed_mods:
                    installed_mod_key = installed_mod.get('mod_key') or installed_mod.get('key') or installed_mod.get('name')
                    if installed_mod_key == mod_key:
                        mod_data = self._create_mod_object_from_info(installed_mod)
                        break
            if mod_data:
                current_slot = self._find_mod_in_slots(mod_data)
                if not current_slot:
                    self._assign_mod_to_slot(slot_frame, mod_data, save_state=False)
        QTimer.singleShot(100, self._refresh_slots_content)
        QTimer.singleShot(200, self._update_mod_widgets_slot_status)
        QTimer.singleShot(300, self._refresh_all_slot_status_displays)
        QTimer.singleShot(300, self._update_action_button_state)

    def _is_mod_in_specific_slot(self, mod_data, chapter_id):
        if not mod_data:
            return False
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return False
        for slot_frame in self.slots.values():
            if slot_frame.chapter_id == chapter_id and slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    return True
        return False
