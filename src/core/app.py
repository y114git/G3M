import base64
import json
import os
import platform
import shutil
import sys
import threading
import time
import uuid
import subprocess
import webbrowser
import argparse
import importlib.util
import importlib.machinery
from typing import Callable, Optional, Dict, Any
import logging
import requests
from PyQt6.QtCore import QTranslator, Qt, QEvent, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QMovie, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QInputDialog, QColorDialog, QListWidget, QScrollArea
from localization import localization_manager, tr
from models.game_modes import FullGameMode, DemoGameMode, UndertaleGameMode
from config.constants import LAUNCHER_VERSION, UI_COLORS, SOCIAL_LINKS, THEMES, ARCH
from utils.file_utils import autodetect_path
from utils.game_utils import is_game_running, is_valid_game_path
from utils.path_utils import get_user_data_root, resource_path, get_launcher_dir, get_legacy_ylauncher_path, get_user_plugins_dir
from utils.network_utils import check_internet_connection
from threads.fetch_mods import FetchModsThread
from threads.background_workers import PresenceWorker, FetchChangelogThread, BgLoader, FullInstallThread, InstallModsThread, FetchHelpContentThread
from ui.styling import get_theme_color, clear_layout_widgets, load_mod_icon_universal, show_empty_message_in_layout
from ui.widgets.custom_controls import NoScrollTabWidget, SlotFrame
from ui.widgets.outlined_label import OutlinedTextLabel
from ui.components.screenshots_carousel import ScreenshotsCarousel
from ui.widgets.mod_plaque_widget import ModPlaqueWidget
from ui.widgets.installed_mod_widget import InstalledModWidget
from ui.dialogs.xdelta_dialog import XdeltaDialog
from ui.dialogs.save_editor import SaveEditorDialog
from ui.dialogs.mod_editor import ModEditorDialog
from ui.feedback import FeedbackManager
from core.startup import SingleInstanceServer
from core.app_state import AppState
from core.managers.mod_manager import ModManager
from core.managers.launch_manager import GameLauncher
from core.managers.updatecheck_manager import UpdateChecker
from core.managers.settings_manager import SettingsManager
from core.managers.save_manager import SaveManager
from ui.builders.search_tab_builder import SearchTabBuilder
from ui.builders.library_tab_builder import LibraryTabBuilder
from ui.builders.settings_view_builder import SettingsViewBuilder
from ui.builders.save_manager_view_builder import SaveManagerViewBuilder
_translator = QTranslator()
_lock_file = None


class DeltaHubApp(QWidget):
    update_status_signal = pyqtSignal(str, str)
    set_progress_signal = pyqtSignal(int)
    show_update_prompt = pyqtSignal(dict)
    initialization_finished = pyqtSignal()
    hide_window_signal = pyqtSignal()
    restore_window_signal = pyqtSignal()
    mods_loaded_signal = pyqtSignal()
    url_received_signal = pyqtSignal(str)
    install_from_gb_signal = pyqtSignal(object)

    def __init__(self, args: Optional[argparse.Namespace] = None, parent_for_dialogs: Optional[QWidget] = None, initial_url: str | None = None):
        super().__init__()
        self.app_state = AppState()
        self.server: SingleInstanceServer | None = None
        self.is_shortcut_launch = args and args.shortcut_launch
        self.app_state.config_dir = os.path.join(get_user_data_root(), 'settings')
        self.launcher_dir = get_launcher_dir()
        from utils.path_utils import get_user_mods_dir
        self.app_state.mods_dir = get_user_mods_dir()
        self.app_state.plugins_dir = get_user_plugins_dir()
        self.app_state.mods_metadata_path = os.path.join(self.app_state.mods_dir, 'metadata.json')
        self._mods_metadata_lock = threading.Lock()
        os.makedirs(self.app_state.config_dir, exist_ok=True)
        os.makedirs(self.app_state.mods_dir, exist_ok=True)
        os.makedirs(self.app_state.plugins_dir, exist_ok=True)
        self.lang_manager = localization_manager
        self.app_state.config_path = os.path.join(self.app_state.config_dir, 'config.json')
        self.feedback_manager = FeedbackManager(self)
        self.feedback_manager.app_state = self.app_state
        self.settings_manager = SettingsManager(self.app_state, self.feedback_manager, self.lang_manager, self)
        self.save_manager = SaveManager(self.app_state, self.feedback_manager, self.settings_manager, self)
        self.save_manager.slots_updated.connect(self._on_slots_updated)
        self.save_manager.status_changed.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
        self.presence_thread = None
        self.presence_worker = None
        self._online_timer = QTimer(self)
        self._online_timer.timeout.connect(self._run_presence_tick)
        self._online_timer.start(30000)
        if self.is_shortcut_launch:
            self._shortcut_launch(args)
            return
        self._pending_install_url = initial_url
        self.dialog_parent = parent_for_dialogs or self
        self.session_id = uuid.uuid4().hex
        QTimer.singleShot(0, self._run_presence_tick)
        self.setWindowTitle('DELTAHUB')
        self._supports_volume = platform.system() == 'Windows'
        self._initial_size = None
        self.app_state.local_config = self._read_json(self.app_state.config_path) or {}
        self._init_localization()
        self.app_state.save_path = ''
        self.resize(875, 750)
        self._initial_size = self.size()
        self.background_movie = None
        self.background_pixmap: Optional[QPixmap] = None
        self.custom_font_family = None
        self.app_state.game_path = ''
        self.app_state.demo_game_path = ''
        self.initialization_timer = None
        self._bg_music_running = False
        self._bg_music_thread = None
        self._suppress_tab_handlers = False
        self._handling_plugin_tab = False
        self._plugin_tab_map = {}
        self._last_online_count = 0
        self.feedback_manager.status_updated.connect(self.update_status_signal.emit)
        self.settings_manager.settings_changed.connect(self._on_settings_changed)
        self.settings_manager.language_changed.connect(self._on_language_changed_by_manager)
        self.settings_manager.theme_changed.connect(self._on_theme_changed_by_manager)
        self.settings_manager.restart_required.connect(lambda msg: self.feedback_manager.show_info('dialogs.restart_required', msg))
        self.settings_manager.status_changed.connect(self.update_status_signal.emit)
        self.mod_manager = ModManager(self.app_state, self.feedback_manager, self)
        self.mod_manager.progress_updated.connect(self.set_progress_signal.emit)
        self.mod_manager.status_changed.connect(self.update_status_signal.emit)
        self.mod_manager.mod_list_updated.connect(self._update_installed_mods_display)
        self.mod_manager.installation_finished.connect(self._on_mod_installation_finished)
        self.mod_manager.url_prompt_required.connect(self._handle_url_install_prompt)
        self.game_launcher = GameLauncher(self.app_state, self.feedback_manager, self.mod_manager, self.save_manager, self)
        self.game_launcher.status_changed.connect(self.update_status_signal.emit)
        self.game_launcher.progress_updated.connect(self.set_progress_signal.emit)
        self.game_launcher.game_launch_started.connect(self.hide_window_signal.emit)
        self.game_launcher.game_launch_finished.connect(self._on_game_launch_finished)
        self.game_launcher.recover_previous_session()
        self.update_checker = UpdateChecker(self.app_state, self.feedback_manager, self)
        self.update_checker.update_available.connect(self._handle_update_info)
        self.update_checker.status_changed.connect(self.update_status_signal.emit)
        self.update_checker.progress_updated.connect(self.set_progress_signal.emit)
        self.update_checker.update_finished.connect(self._on_update_cleanup)
        self.update_checker.update_error.connect(lambda msg: self.feedback_manager.show_error('errors.error', msg))
        self.update_checker.quit_requested.connect(QApplication.quit)
        self.init_ui()
        self.load_font()
        self.update_status_signal.connect(self._update_status)
        self.hide_window_signal.connect(self._hide_window_for_game)
        self.restore_window_signal.connect(self._restore_window_after_game)
        self.set_progress_signal.connect(self._on_progress_update)
        self.show_update_prompt.connect(self._prompt_for_update)
        self.mods_loaded_signal.connect(self._on_mods_loaded)
        self.url_received_signal.connect(self.handle_one_click_install)
        self.install_from_gb_signal.connect(lambda mod: self._install_single_mod(mod, force=True))
        self.initialization_finished.connect(self._handle_pending_install)
        self._legacy_cleanup_done = False
        QTimer.singleShot(1000, self._maybe_run_legacy_cleanup)
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(5000)
        if (saved := self.app_state.local_config.get('window_geometry')):
            from PyQt6.QtCore import QByteArray
            try:
                self.restoreGeometry(QByteArray.fromHex(saved.encode()))
            except Exception:
                pass
        if not self.app_state.local_config.get('first_launch_splash_shown', False):
            self.initialization_finished.connect(self._handle_first_launch_settings)

    def _handle_pending_install(self):
        if self._pending_install_url:
            self.handle_one_click_install(self._pending_install_url)
            self._pending_install_url = None

    def handle_one_click_install(self, url: str):
        if is_game_running():
            return
        self.activateWindow()
        self.raise_()
        if self.app_state.is_installing:
            self.feedback_manager.show_warning('dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
            return
        self.mod_manager.install_from_url(url)

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self._update_installed_mods_display()
        status_color = UI_COLORS['status_success'] if success else UI_COLORS['status_error']
        self._update_status(message, status_color)

    def _handle_url_install_prompt(self, title, message):
        reply = self.feedback_manager.ask_question(title, message)
        self.mod_manager.handle_url_prompt_response(reply)

    def _shortcut_launch(self, args):
        try:
            settings_json = base64.b64decode(args.shortcut_launch).decode('utf-8')
            settings = json.loads(settings_json)
        except Exception as e:
            print(tr('startup.shortcut_settings_read_error', error=str(e)))
            sys.exit(1)
        self._load_local_data()
        self.mod_manager.load_local_mods()
        try:
            if settings.get('is_undertale_mode', False):
                self.app_state.game_mode = UndertaleGameMode()
            else:
                self.app_state.game_mode = DemoGameMode() if settings.get('is_demo_mode', False) else FullGameMode()
            self.app_state.game_path = settings.get('game_path', '')
            self.app_state.demo_game_path = settings.get('demo_game_path', '')
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
            self.feedback_manager.show_warning('dialogs.cannot_create_shortcut_title', tr('dialogs.path_not_specified'))
            return
        description_lines = [tr('dialogs.shortcut_description'), '', tr('dialogs.current_shortcut_settings'), '']
        game_name = tr('ui.undertale_label') if settings.get('is_undertale_mode', False) else tr('ui.deltarunedemo_label') if settings.get('is_demo_mode', False) else tr('ui.deltarune_label')
        description_lines.append(f"<b>{tr('ui.mod_type_label')}</b> {game_name}")
        if settings.get('is_demo_mode', False):
            mod_key = settings['mods'].get('demo')
            if mod_key:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                description_lines.append(f"<b>{tr('status.mod_label')}</b> {mod_name}")
            else:
                description_lines.append(f"<b>{tr('status.mod_label')}</b> <i>{tr('status.vanilla')}</i>")
        elif settings.get('is_undertale_mode', False):
            mod_key = settings['mods'].get('undertale')
            if mod_key:
                mod_config = self.mod_manager.get_mod_config(mod_key)
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
                        mod_config = self.mod_manager.get_mod_config(mod_key)
                        mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                        description_lines.append(f"<b>{tr('status.mod_for_chapter_label', chapter_name=chapter_name)}</b> {mod_name}")
                    else:
                        description_lines.append(f"<b>{tr('status.mod_for_chapter_label', chapter_name=chapter_name)}</b> <i>{tr('status.no_mod')}</i>")
                else:
                    description_lines.append(f"<b>{tr('status.direct_launch_label')}</b> {tr('status.disabled')}")
                    for chapter_id in [0, 1, 2, 3, 4]:
                        mod_key = settings['mods'].get(str(chapter_id))
                        if mod_key:
                            mod_config = self.mod_manager.get_mod_config(mod_key)
                            mod_name = mod_config.get('name', tr('errors.mod_not_found', mod_key=mod_key)) if mod_config else tr('errors.mod_not_found', mod_key=mod_key)
                            chapter_names = {0: tr('chapters.menu'), 1: tr('tabs.chapter_1'), 2: tr('tabs.chapter_2'), 3: tr('tabs.chapter_3'), 4: tr('tabs.chapter_4')}
                            chapter_name = chapter_names.get(chapter_id, tr('ui.chapter_tab_title', chapter_num=chapter_id))
                            description_lines.append(f'<b>{chapter_name}:</b> {mod_name}')
            else:
                uni_key = settings['mods'].get('universal')
                if uni_key:
                    mod_config = self.mod_manager.get_mod_config(uni_key)
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
        description_text = '<br>'.join(description_lines) + f"<br><br><p>{tr('dialogs.shortcut_create_description')}</p>"
        if self.feedback_manager.ask_question('dialogs.create_shortcut_question', 'dialogs.shortcut_create_description', description_text):
            self._save_shortcut(settings)

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
        self.feedback_manager.show_error('errors.access_denied', path=path)

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ''

    def _current_tab_names(self):
        return self.app_state.game_mode.tab_names

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
        self.top_refresh_button.clicked.connect(self._on_refresh_clicked)
        self.top_frame.addWidget(self.top_refresh_button)
        self.top_frame.addWidget(self.online_label)
        self.top_frame.addStretch()
        logo_placeholder = QWidget()
        logo_placeholder.setFixedWidth(225)
        self.top_frame.addWidget(logo_placeholder)
        self.top_frame.addStretch()
        self.telegram_button = QPushButton(tr('buttons.telegram'))
        self.telegram_button.clicked.connect(lambda: webbrowser.open(self.app_state.global_settings.get('telegram_url', SOCIAL_LINKS['telegram'])))
        self.telegram_button.setStyleSheet(f"color: {UI_COLORS['link']};")
        self.top_frame.addWidget(self.telegram_button)
        self.discord_button = QPushButton(tr('buttons.discord'))
        self.discord_button.clicked.connect(lambda: webbrowser.open(self.app_state.global_settings.get('discord_url', SOCIAL_LINKS['discord'])))
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
        self.app_state.is_installing = False
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
        self.current_page = 1
        self.mods_per_page = 15
        self.filtered_mods = []
        self.sort_ascending = False
        self.search_text = ''
        search_builder = SearchTabBuilder(self.app_state, self)
        self.search_mods_tab = search_builder.build()
        search_widgets = search_builder.get_widgets()
        self.search_container = search_widgets['search_container']
        self.search_mods_scroll = search_widgets['search_mods_scroll']
        self.mod_list_widget = search_widgets['mod_list_widget']
        self.mod_list_layout = search_widgets['mod_list_layout']
        self.sort_combo = search_widgets['sort_combo']
        self.sort_order_btn = search_widgets['sort_order_btn']
        self.modgame_combo = search_widgets['modgame_combo']
        self.tags_label = search_widgets['tags_label']
        self.tag_translation = search_widgets['tag_translation']
        self.tag_customization = search_widgets['tag_customization']
        self.tag_gameplay = search_widgets['tag_gameplay']
        self.tag_other = search_widgets['tag_other']
        self.search_button = search_widgets['search_button']
        self.prev_page_btn = search_widgets['prev_page_btn']
        self.page_label = search_widgets['page_label']
        self.next_page_btn = search_widgets['next_page_btn']
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        self.modgame_combo.currentIndexChanged.connect(self._on_modgame_filter_changed)
        self.tag_translation.stateChanged.connect(self._on_tag_filter_changed)
        self.tag_customization.stateChanged.connect(self._on_tag_filter_changed)
        self.tag_gameplay.stateChanged.connect(self._on_tag_filter_changed)
        self.tag_other.stateChanged.connect(self._on_tag_filter_changed)
        self.search_button.clicked.connect(self._show_search_dialog)
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.next_page_btn.clicked.connect(self._next_page)
        self.library_sort_ascending = False
        self.library_search_text = ''
        self._previous_mode = 'normal'
        library_builder = LibraryTabBuilder(self.app_state, self)
        self.library_tab = library_builder.build()
        library_widgets = library_builder.get_widgets()
        self.library_filters_widget = library_widgets['library_filters_widget']
        self.game_type_combo = library_widgets['game_type_combo']
        self.chapter_mode_checkbox = library_widgets['chapter_mode_checkbox']
        self.full_install_checkbox = library_widgets['full_install_checkbox']
        self.slots_container = library_widgets['slots_container']
        self.slots_layout = library_widgets['slots_layout']
        self.active_slots_widget = library_widgets['active_slots_widget']
        self.active_slots_layout = library_widgets['active_slots_layout']
        self.installed_mods_container = library_widgets['installed_mods_container']
        self.installed_mods_scroll = library_widgets['installed_mods_scroll']
        self.installed_mods_widget = library_widgets['installed_mods_widget']
        self.installed_mods_layout = library_widgets['installed_mods_layout']
        self.library_sort_combo = library_widgets['library_sort_combo']
        self.library_sort_order_btn = library_widgets['library_sort_order_btn']
        self.library_tags_label = library_widgets['library_tags_label']
        self.library_tag_translation = library_widgets['library_tag_translation']
        self.library_tag_customization = library_widgets['library_tag_customization']
        self.library_tag_gameplay = library_widgets['library_tag_gameplay']
        self.library_tag_other = library_widgets['library_tag_other']
        self.library_tag_local = library_widgets['library_tag_local']
        self.library_tag_widgets = library_widgets['library_tag_widgets']
        self.library_search_button = library_widgets['library_search_button']
        self.game_type_combo.currentIndexChanged.connect(self._on_game_type_changed)
        self.chapter_mode_checkbox.stateChanged.connect(self._on_chapter_mode_changed)
        self.full_install_checkbox.stateChanged.connect(self._on_toggle_full_install)
        self.library_sort_combo.currentIndexChanged.connect(self._on_library_filter_changed)
        self.library_sort_order_btn.clicked.connect(self._toggle_library_sort_order)
        for tag in self.library_tag_widgets:
            tag.stateChanged.connect(self._on_library_filter_changed)
        self.library_search_button.clicked.connect(self._show_library_search_dialog)
        saved_game_type = self.app_state.local_config.get('selected_game_type', 'deltarune')
        saved_chapter_mode = self.app_state.local_config.get('chapter_mode_enabled', False)
        saved_full_install = self.app_state.local_config.get('full_install_enabled', False)
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
            self.app_state.game_mode = DemoGameMode()
        elif saved_game_type == 'undertale':
            self.app_state.game_mode = UndertaleGameMode()
        else:
            self.app_state.game_mode = FullGameMode()
        self.app_state.current_mode = 'chapter' if saved_chapter_mode else 'normal'
        self._previous_mode = self.app_state.current_mode
        self.app_state.selected_chapter_id = None
        self._update_checkbox_visibility()
        self._update_saves_button_state()
        QTimer.singleShot(500, self._update_installed_mods_display)
        QTimer.singleShot(700, self._update_mod_widgets_slot_status)
        self._update_slots_display()
        QTimer.singleShot(400, self._load_slots_state)
        self.manage_mods_tab = QWidget()
        self.xdelta_patch_tab = QWidget()
        self.main_tab_widget.addTab(self.search_mods_tab, tr('ui.search_tab'))
        self.main_tab_widget.addTab(self.library_tab, tr('ui.library_tab'))
        self.main_tab_widget.addTab(self.manage_mods_tab, tr('ui.mod_management'))
        self.main_tab_widget.addTab(self.xdelta_patch_tab, tr('ui.patching_tab'))
        self._update_plugin_tabs()
        self.previous_tab_index = 0
        self.main_tab_widget.currentChanged.connect(self._on_tab_changed)
        self.main_tab_widget.setStyleSheet('\n            QTabWidget::tab-bar {\n                alignment: center;\n            }\n            QTabBar::tab {\n                min-width: 120px;\n                padding: 8px 16px;\n            }\n        ')
        self.main_layout.addWidget(self.main_tab_widget)
        self.main_layout.addWidget(self.bottom_widget)
        settings_builder = SettingsViewBuilder(self.app_state, self)
        self.settings_widget = settings_builder.build()
        settings_widgets = settings_builder.get_widgets()
        self.settings_pages_container = settings_widgets['settings_pages_container']
        self.settings_menu_page = settings_widgets['settings_menu_page']
        self.settings_customization_page = settings_widgets['settings_customization_page']
        self.changelog_widget = settings_widgets['changelog_widget']
        self.help_widget = settings_widgets['help_widget']
        self.settings_title_label = settings_widgets['settings_title_label']
        self.language_label = settings_widgets['language_label']
        self.language_combo = settings_widgets['language_combo']
        self.beta_updates_checkbox = settings_widgets['beta_updates_checkbox']
        self.fullscreen_checkbox = settings_widgets['fullscreen_checkbox']
        self.hide_library_filters_checkbox = settings_widgets['hide_library_filters_checkbox']
        self.launch_via_steam_checkbox = settings_widgets['launch_via_steam_checkbox']
        self.use_custom_executable_checkbox = settings_widgets['use_custom_executable_checkbox']
        self.select_custom_executable_button = settings_widgets['select_custom_executable_button']
        self.custom_executable_path_label = settings_widgets['custom_executable_path_label']
        self.custom_exe_frame = settings_widgets['custom_exe_frame']
        self.change_path_button = settings_widgets['change_path_button']
        self.change_mods_dir_button = settings_widgets['change_mods_dir_button']
        self.customization_button = settings_widgets['customization_button']
        self.settings_customization_button = settings_widgets['settings_customization_button']
        self.reset_button = settings_widgets['reset_button']
        self.disable_background_checkbox = settings_widgets['disable_background_checkbox']
        self.disable_splash_checkbox = settings_widgets['disable_splash_checkbox']
        self.back_button_cust = settings_widgets['back_button_cust']
        self.change_background_button = settings_widgets['change_background_button']
        self.background_music_button = settings_widgets['background_music_button']
        self.startup_sound_button = settings_widgets['startup_sound_button']
        self.custom_style_frame = settings_widgets['custom_style_frame']
        self.color_widgets = settings_widgets['color_widgets']
        self.color_labels = settings_widgets['color_labels']
        self.color_config = settings_widgets['color_config']
        self.theme_button = settings_widgets['theme_button']
        self.changelog_text_edit = settings_widgets['changelog_text_edit']
        self.changelog_button = settings_widgets['changelog_button']
        self.help_text_edit = settings_widgets['help_text_edit']
        self.help_button = settings_widgets['help_button']
        self.language_combo.currentTextChanged.connect(self._on_language_changed)
        self.beta_updates_checkbox.stateChanged.connect(self._on_toggle_beta_updates)
        self.fullscreen_checkbox.stateChanged.connect(self._on_toggle_fullscreen)
        self.hide_library_filters_checkbox.stateChanged.connect(self._on_toggle_hide_library_filters)
        self.launch_via_steam_checkbox.stateChanged.connect(self._on_toggle_steam_launch)
        self.use_custom_executable_checkbox.stateChanged.connect(self._on_toggle_custom_executable)
        self.select_custom_executable_button.clicked.connect(self._select_custom_executable_file)
        self.change_path_button.clicked.connect(self._prompt_for_game_path)
        self.change_mods_dir_button.clicked.connect(self._prompt_for_mods_dir)
        self.customization_button.clicked.connect(lambda: self._switch_settings_page(self.settings_customization_page))
        self.reset_button.clicked.connect(self._on_reset_settings_click)
        self.disable_background_checkbox.stateChanged.connect(self._on_toggle_disable_background)
        self.disable_splash_checkbox.stateChanged.connect(self._on_toggle_disable_splash)
        self.back_button_cust.clicked.connect(self._go_back_to_settings_menu)
        self.change_background_button.clicked.connect(self._on_background_button_click)
        self.background_music_button.setText(self._get_background_music_button_text())
        self.background_music_button.clicked.connect(self._on_background_music_button_click)
        self.startup_sound_button.setText(self._get_startup_sound_button_text())
        self.startup_sound_button.clicked.connect(self._on_startup_sound_button_click)
        self.theme_button.clicked.connect(self._on_theme_button_click)

        def pick_color_for_edit(target_edit):
            if (color := QColorDialog.getColor()).isValid():
                target_edit.setText(color.name())
                self._on_custom_style_edited()
        for key in self.color_config.keys():
            line_edit = self.color_widgets[key]
            btn = settings_widgets[f'color_btn_{key}']
            reset_btn = settings_widgets[f'color_reset_{key}']
            line_edit.editingFinished.connect(self._on_custom_style_edited)
            btn.clicked.connect(lambda _, le=line_edit: pick_color_for_edit(le))
            reset_btn.clicked.connect(lambda _, le=line_edit: (le.clear(), self._on_custom_style_edited()))
        self.changelog_button.clicked.connect(self._toggle_changelog_view)
        self.help_button.clicked.connect(self._toggle_help_view)
        self._update_filtered_mods()
        self.main_layout.addWidget(self.settings_widget)
        save_manager_builder = SaveManagerViewBuilder(self.app_state, self)
        self.save_manager_widget = save_manager_builder.build()
        save_manager_widgets = save_manager_builder.get_widgets()
        self.save_back_btn = save_manager_widgets['save_back_btn']
        self.change_save_path_btn = save_manager_widgets['change_save_path_btn']
        self.save_tabs = save_manager_widgets['save_tabs']
        self._slot_labels = save_manager_widgets['slot_labels']
        self._chapter_buttons = save_manager_widgets['chapter_buttons']
        self.collection_name_lbl = save_manager_widgets['collection_name_lbl']
        self.left_col_btn = save_manager_widgets['left_col_btn']
        self.switch_collection_btn = save_manager_widgets['switch_collection_btn']
        self.right_col_btn = save_manager_widgets['right_col_btn']
        self.rename_collection_btn = save_manager_widgets['rename_collection_btn']
        self.delete_collection_btn = save_manager_widgets['delete_collection_btn']
        self.copy_from_main_btn = save_manager_widgets['copy_from_main_btn']
        self.copy_to_main_btn = save_manager_widgets['copy_to_main_btn']
        self.slot_actions = save_manager_widgets['slot_actions']
        self.show_btn = save_manager_widgets['show_btn']
        self.erase_btn = save_manager_widgets['erase_btn']
        self.import_btn = save_manager_widgets['import_btn']
        self.export_btn = save_manager_widgets['export_btn']
        self.save_back_btn.clicked.connect(self._hide_save_manager)
        self.change_save_path_btn.clicked.connect(self._prompt_for_save_path)
        for lbl in self._slot_labels.values():
            lbl.clicked.connect(self._on_save_manager_slot_clicked)
            lbl.doubleClicked.connect(self._on_slot_double_clicked)
        self._configure_hidden_tab_bar(self.save_tabs)
        for ch, btn in enumerate(self._chapter_buttons, start=0):
            btn.clicked.connect(lambda _checked, idx=ch: self.save_tabs.setCurrentIndex(idx))

        def _sync_buttons(index: int):
            for i, b in enumerate(self._chapter_buttons):
                b.setChecked(i == index)
        self.save_tabs.currentChanged.connect(_sync_buttons)
        self.left_col_btn.clicked.connect(lambda: self._navigate_collection(-1))
        self.switch_collection_btn.clicked.connect(self._toggle_collection_view)
        self.right_col_btn.clicked.connect(lambda: self._navigate_collection(1))
        self.rename_collection_btn.clicked.connect(self._rename_current_collection)
        self.delete_collection_btn.clicked.connect(self._delete_current_collection)
        self.copy_from_main_btn.clicked.connect(lambda: self._copy_between_storages(to_collection=True))
        self.copy_to_main_btn.clicked.connect(lambda: self._copy_between_storages(to_collection=False))
        self.show_btn.clicked.connect(self._action_show_save)
        self.erase_btn.clicked.connect(self._action_delete_save)
        self.import_btn.clicked.connect(lambda: self._action_import_export(True))
        self.export_btn.clicked.connect(lambda: self._action_import_export(False))
        self.save_tabs.currentChanged.connect(lambda _: self._on_chapter_tab_changed())
        self.save_manager_widget.installEventFilter(self)
        self._update_slot_highlight()
        self.main_layout.addWidget(self.save_manager_widget)
        self.app_state.current_settings_page = self.settings_menu_page
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.setWindowIcon(QIcon(resource_path('resources/icons/icon.ico')))

    def _on_tab_changed(self, index):
        num_original_tabs = 4
        if getattr(self, '_suppress_tab_handlers', False):
            self.previous_tab_index = index
            return
        if index >= num_original_tabs:
            visible_plugins = [p for p in self.app_state.plugins if not p.get('tab_hide', False)]
            plugin_index = index - num_original_tabs
            if 0 <= plugin_index < len(visible_plugins):
                plugin = self._plugin_tab_map.get(index) or visible_plugins[plugin_index]
                current_widget = self.main_tab_widget.widget(index)
                is_placeholder = type(current_widget) is QWidget and current_widget.layout() is None
                if is_placeholder:
                    if self._handling_plugin_tab:
                        return
                    self._handling_plugin_tab = True
                    try:
                        bound = getattr(current_widget, '_plugin_info', None)
                        if isinstance(bound, dict):
                            plugin = bound
                    except Exception:
                        pass
                    try:
                        if current_widget is not None and hasattr(current_widget, 'property'):
                            name_key = current_widget.property('plugin_name_key')
                            if name_key:
                                for p in visible_plugins:
                                    if p.get('name_key') == name_key:
                                        plugin = p
                                        break
                    except Exception:
                        pass
                    try:
                        new_widget = None
                        handler = plugin.get('page_init') if callable(plugin.get('page_init')) else plugin.get('on_tab_open')
                        if callable(handler):
                            new_widget = handler(self)
                        if isinstance(new_widget, QWidget):
                            self.main_tab_widget.removeTab(index)
                            self.main_tab_widget.insertTab(index, new_widget, tr(plugin['name_key']))
                            self.main_tab_widget.setCurrentIndex(index)
                            self.previous_tab_index = index
                        else:
                            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
                    except Exception as e:
                        logging.error(f"Error running plugin '{plugin['name_key']}': {e}")
                        self.feedback_manager.show_error('errors.error', f"Failed to run plugin '{tr(plugin['name_key'])}':\n{e}")
                        self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
                    finally:
                        self._handling_plugin_tab = False
                    return
            self.previous_tab_index = index
            return
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

    def _update_plugin_tabs(self):
        num_original_tabs = 4
        while self.main_tab_widget.count() > num_original_tabs:
            self.main_tab_widget.removeTab(num_original_tabs)
        for plugin_name in list(sys.modules.keys()):
            if plugin_name.startswith('plugins.'):
                del sys.modules[plugin_name]
        self._load_plugins()
        self._plugin_tab_map = {}
        for plugin in self.app_state.plugins:
            if not plugin.get('tab_hide', False):
                plugin_tab = QWidget()
                try:
                    setattr(plugin_tab, '_plugin_info', plugin)
                    plugin_tab.setProperty('plugin_name_key', plugin.get('name_key'))
                except Exception:
                    pass
                tab_name = tr(plugin['name_key'])
                self.main_tab_widget.addTab(plugin_tab, tab_name)
                try:
                    tab_idx = self.main_tab_widget.indexOf(plugin_tab)
                    if tab_idx >= 0:
                        self._plugin_tab_map[tab_idx] = plugin
                except Exception:
                    pass

    def _load_plugins(self):
        self.app_state.plugins.clear()
        if not os.path.isdir(self.app_state.plugins_dir):
            return
        for plugin_name in os.listdir(self.app_state.plugins_dir):
            plugin_path = os.path.join(self.app_state.plugins_dir, plugin_name)
            main_py_path = os.path.join(plugin_path, 'main.py')
            if os.path.isdir(plugin_path) and os.path.isfile(main_py_path):
                try:
                    spec = importlib.util.spec_from_file_location(f'plugins.{plugin_name}', main_py_path)
                    if spec and spec.loader:
                        plugin_module = importlib.util.module_from_spec(spec)
                        sys.modules[f'plugins.{plugin_name}'] = plugin_module
                        spec.loader.exec_module(plugin_module)
                        plugin_display_name_key = getattr(plugin_module, 'PLUGIN_NAME', None)
                        on_tab_open_function = getattr(plugin_module, 'on_tab_open', None)
                        page_init_function = getattr(plugin_module, 'page_init', None)
                        tab_hide = getattr(plugin_module, 'TAB_HIDE', False)
                        hooks = {'on_before_game_launch': getattr(plugin_module, 'on_before_game_launch', None), 'on_after_game_launch': getattr(plugin_module, 'on_after_game_launch', None), 'on_before_game_exit': getattr(plugin_module, 'on_before_game_exit', None), 'on_after_game_exit': getattr(plugin_module, 'on_after_game_exit', None)}
                        if hasattr(plugin_module, 'on_game_launch') and callable(getattr(plugin_module, 'on_game_launch')) and (not hooks['on_after_game_launch']):
                            hooks['on_after_game_launch'] = getattr(plugin_module, 'on_game_launch')
                        if hasattr(plugin_module, 'on_game_exit') and callable(getattr(plugin_module, 'on_game_exit')) and (not hooks['on_before_game_exit']):
                            hooks['on_before_game_exit'] = getattr(plugin_module, 'on_game_exit')
                        is_background_plugin = any((callable(h) for h in hooks.values()))
                        is_ui_plugin = not tab_hide and plugin_display_name_key and (callable(on_tab_open_function) or callable(page_init_function))
                        if not is_background_plugin and (not is_ui_plugin):
                            logging.warning(f"Plugin '{plugin_name}' is invalid. It must have at least one hook function or be a UI plugin with PLUGIN_NAME.")
                            continue
                        current_lang = localization_manager.get_current_language().upper()
                        lang_dict_name = f'LANG_{current_lang}'
                        plugin_translations = getattr(plugin_module, lang_dict_name, None)
                        if isinstance(plugin_translations, dict):
                            localization_manager.merge_translations(plugin_translations)
                        elif current_lang != 'EN':
                            en_translations = getattr(plugin_module, 'LANG_EN', None)
                            if isinstance(en_translations, dict):
                                localization_manager.merge_translations(en_translations)
                        plugin_info = {'name_key': plugin_display_name_key, 'module': plugin_module, 'on_tab_open': on_tab_open_function, 'page_init': page_init_function, 'tab_hide': tab_hide, 'path': plugin_path, **hooks}
                        self.app_state.plugins.append(plugin_info)
                        logging.info(f'Successfully loaded plugin: {plugin_name}')
                except Exception as e:
                    logging.error(f"Failed to load plugin '{plugin_name}': {e}")

    def _on_mods_loaded(self):
        if self.initialization_timer and self.initialization_timer.isActive():
            self.initialization_timer.stop()
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        self._maybe_start_background_music()

    def _force_finish_initialization(self):
        if self.app_state.initialization_completed:
            return
        self.app_state.mods_loaded = True
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        if not is_game_running():
            self._maybe_start_background_music()

    def _update_saves_button_state(self):
        game_type = self.game_type_combo.currentData()
        self.saves_button.setEnabled(game_type != 'undertale')

    def _on_library_filter_changed(self):
        self._update_installed_mods_display()

    def _show_library_search_dialog(self):
        if self.library_search_text:
            self.library_search_text = ''
            self.library_search_button.setText('🔍')
            self.library_search_button.setToolTip(tr('ui.search_mods_placeholder'))
            self._update_installed_mods_display()
        else:
            text, ok = QInputDialog.getText(self, tr('ui.search_mods'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.library_search_text = text.strip()
                self.library_search_button.setText('↻')
                self.library_search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.library_search_text))
                self._update_installed_mods_display()

    def _toggle_library_sort_order(self):
        self.library_sort_ascending = not self.library_sort_ascending
        if self.library_sort_ascending:
            self.library_sort_order_btn.setText('▲')
            self.library_sort_order_btn.setToolTip(tr('ui.ascending'))
        else:
            self.library_sort_order_btn.setText('▼')
            self.library_sort_order_btn.setToolTip(tr('ui.descending'))
        self._on_library_filter_changed()

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

    def _on_modgame_filter_changed(self, index):
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
        self._update_slots_display()

    def _on_game_type_changed(self, index):
        game_type = self.game_type_combo.itemData(index)
        if not game_type:
            return
        self._save_slots_state()
        if game_type == 'deltarunedemo':
            self.app_state.game_mode = DemoGameMode()
        elif game_type == 'undertale':
            self.app_state.game_mode = UndertaleGameMode()
        else:
            self.app_state.game_mode = FullGameMode()
        self._update_checkbox_visibility()
        self._update_slots_display()
        self._load_slots_state()
        self._update_installed_mods_display()
        self._update_change_path_button_text()
        self._update_saves_button_state()
        self.app_state.local_config['selected_game_type'] = game_type
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
        old_is_chapter = self.app_state.current_mode == 'chapter'
        if old_is_chapter != is_chapter:
            old_config_key = self._get_slots_config_key(self.app_state.game_mode, old_is_chapter)
            slots_data = {}
            if hasattr(self.app_state, 'slots'):
                for slot_id, slot_frame in self.app_state.slots.items():
                    if slot_frame.assigned_mod:
                        mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                        if mod_key:
                            slots_data[str(slot_id)] = {'mod_key': mod_key, 'mod_name': slot_frame.assigned_mod.name}
            self.app_state.local_config[old_config_key] = slots_data
            self._write_local_config()
        self.app_state.current_mode = 'chapter' if is_chapter else 'normal'
        self.game_type_combo.setEnabled(not is_chapter)
        self._update_slots_display()
        self._update_mod_widgets_slot_status()
        self._update_action_button_state()
        if is_chapter:
            for slot_frame in self.app_state.slots.values():
                slot_frame.is_selected = False
                self._update_slot_visual_state(slot_frame)
            self.app_state.selected_chapter_id = None
            self._show_chapter_mode_instruction()
        else:
            self.app_state.selected_chapter_id = None
            self._update_installed_mods_display()
            if self.app_state.local_config.get('direct_launch_slot_id', -1) >= 0:
                self.app_state.local_config['direct_launch_slot_id'] = -1
        self._update_change_path_button_text()
        self.app_state.local_config['chapter_mode_enabled'] = is_chapter
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
        if not hasattr(self.app_state, 'slots'):
            self.app_state.slots = {}
        else:
            self.app_state.slots.clear()
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        if self.app_state.current_mode == 'normal':
            if is_demo_mode:
                slot = self._create_slot_widget(tr('ui.demo_slot'), -10)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.app_state.slots[-10] = slot
            elif isinstance(self.app_state.game_mode, UndertaleGameMode):
                slot = self._create_slot_widget(tr('ui.universal_slot'), -20)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.app_state.slots[-20] = slot
            else:
                slot = self._create_slot_widget(tr('ui.mod_slot'), -1)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.app_state.slots[-1] = slot
                self._create_chapter_indicators()
        else:
            slot_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
            for i, name in enumerate(slot_names):
                slot = self._create_slot_widget(name, i)
                if hasattr(self, 'active_slots_layout'):
                    self.active_slots_layout.addWidget(slot)
                self.app_state.slots[i] = slot
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
        main_text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
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
                    has_files = self.mod_manager.mod_has_files_for_chapter(mod, i)
                    if has_files:
                        self.chapter_indicators[i]['status_label'].setText('✓')
                        self.chapter_indicators[i]['status_label'].setStyleSheet('color: #00FF00; font-size: 16px; font-weight: bold;')
                    else:
                        self.chapter_indicators[i]['status_label'].setText('✗')
                        self.chapter_indicators[i]['status_label'].setStyleSheet('color: #FF0000; font-size: 16px; font-weight: bold;')

    def _update_chapter_indicators_style(self):
        if hasattr(self, 'chapter_indicators'):
            main_text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
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
        user_bg_hex = get_theme_color(self.app_state.local_config, 'background', None)
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            slot_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            slot_bg_color = 'rgba(0, 0, 0, 150)'
        slot_border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', -1)
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
                if self.feedback_manager.ask_question('ui.remove_mod_from_slot', 'ui.remove_mod_question', '', False, mod_name=getattr(slot_frame.assigned_mod, 'name', getattr(slot_frame.assigned_mod, 'key', 'Unknown'))):
                    self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
                    self._save_slots_state()
            else:
                self._show_mod_selection_for_slot(slot_frame)
        else:
            for other_slot in self.app_state.slots.values():
                if other_slot != slot_frame:
                    other_slot.is_selected = False
                    self._update_slot_visual_state(other_slot)
            slot_frame.is_selected = not slot_frame.is_selected
            self._update_slot_visual_state(slot_frame)
            if slot_frame.is_selected:
                selected_chapter = slot_frame.chapter_id
                self.app_state.selected_chapter_id = selected_chapter
                self._update_installed_mods_for_chapter_mode(selected_chapter)
            else:
                self.app_state.selected_chapter_id = None
                self._show_chapter_mode_instruction()

    def _on_slot_frame_double_clicked(self, slot_frame):
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        if not is_chapter_mode or slot_frame.chapter_id < 0:
            return
        current_direct_launch_slot = self.app_state.local_config.get('direct_launch_slot_id', -1)
        is_direct_launch_active = current_direct_launch_slot == slot_frame.chapter_id
        if is_direct_launch_active:
            if self.feedback_manager.ask_question('ui.direct_launch', 'ui.disable_direct_launch', '', False, chapter=slot_frame.chapter_id):
                self._disable_direct_launch()
        elif self.feedback_manager.ask_question('ui.direct_launch', 'ui.enable_direct_launch', '', False, chapter=slot_frame.chapter_id):
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
            if is_demo_mode and (not mod_info.get('modgame', 'deltarune') == 'deltarunedemo'):
                continue
            elif not is_demo_mode and mod_info.get('modgame', 'deltarune') == 'deltarunedemo':
                continue
            if selected_chapter_id is not None:
                mod_data = self._create_mod_object_from_info(mod_info)
                if mod_data and (not self.mod_manager.mod_has_files_for_chapter(mod_data, selected_chapter_id)):
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
        for slot_frame in self.app_state.slots.values():
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
        for slot_frame in self.app_state.slots.values():
            if slot_frame.chapter_id == chapter_id:
                target_slot = slot_frame
                break
        if target_slot:
            self._assign_mod_to_slot(target_slot, mod_data)
            self._update_installed_mods_for_chapter_mode(chapter_id)
        else:
            self.feedback_manager.show_warning('errors.target_slot_not_found')

    def _show_mod_selection_for_slot(self, slot_frame):
        installed_mods = self._get_installed_mods_list()
        available_mods = []
        for mod_info in installed_mods:
            if mod_info:
                mod_exists = self.mod_manager.check_mod_exists(mod_info)
                if not mod_exists:
                    continue
                mod_modgame = mod_info.get('modgame', 'deltarune')
                slot_id = slot_frame.chapter_id
                if slot_id == -10:
                    if mod_modgame != 'deltarunedemo':
                        continue
                elif slot_id == -20:
                    if mod_modgame != 'undertale':
                        continue
                elif slot_id == -1:
                    if mod_modgame not in ['deltarune', 'deltarunedemo']:
                        continue
                elif mod_modgame != 'deltarune':
                    continue
                mod_data = self._create_mod_object_from_info(mod_info)
                if mod_data and (not self._find_mod_in_slots(mod_data)):
                    available_mods.append(mod_data)
        if not available_mods:
            self.feedback_manager.show_info('ui.no_available_mods', tr('ui.no_mods_to_insert'))
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
            if hasattr(self, 'selected_chapter_id') and self.app_state.selected_chapter_id is not None:
                self._update_installed_mods_for_chapter_mode(self.app_state.selected_chapter_id)
                return
            else:
                self._show_chapter_mode_instruction()
                return
        self._refresh_installed_mods_async()

    def _update_installed_mods_display_from_list(self, installed_mods):
        try:
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
            if hasattr(self, 'library_sort_combo'):
                sort_type = self.library_sort_combo.currentIndex()
                reverse = not self.library_sort_ascending
                if sort_type == 0:
                    installed_mods.sort(key=lambda mod: mod.get('name', '').lower(), reverse=reverse)
                elif sort_type == 1:

                    def get_sort_date(mod):
                        if mod.get('is_local_mod'):
                            return mod.get('created_date', '0')
                        else:
                            return mod.get('updated_date') or mod.get('installed_date', '0')
                    installed_mods.sort(key=get_sort_date, reverse=reverse)
            selected_tags = []
            if hasattr(self, 'library_tag_widgets'):
                tag_map = {self.library_tag_translation: 'translation', self.library_tag_customization: 'customization', self.library_tag_gameplay: 'gameplay', self.library_tag_other: 'other', self.library_tag_local: 'local'}
                for checkbox, tag in tag_map.items():
                    if checkbox.isChecked():
                        selected_tags.append(tag)
            search_text = getattr(self, 'library_search_text', '').lower()
            current_game_type = 'deltarune'
            if hasattr(self, 'game_type_combo'):
                current_game_type = self.game_type_combo.currentData() or 'deltarune'
            for idx, mod_info in enumerate(installed_mods):
                mod_exists = self.mod_manager.check_mod_exists(mod_info)
                if not mod_exists:
                    continue
                mod_modgame = mod_info.get('modgame', 'deltarune')
                if mod_modgame != current_game_type:
                    continue
                mod_tags = mod_info.get('tags', [])
                if mod_info.get('is_local_mod'):
                    if 'local' not in mod_tags:
                        mod_tags.append('local')
                if selected_tags and (not all((tag in mod_tags for tag in selected_tags))):
                    continue
                if search_text:
                    mod_name_lower = mod_info.get('name', '').lower()
                    mod_tagline = mod_info.get('tagline', '').lower()
                    if search_text not in mod_name_lower and search_text not in mod_tagline:
                        continue
                is_local = mod_info.get('is_local_mod', False)
                is_available = mod_info.get('is_available_on_server', True)
                has_update = False
                if not is_local and is_available:
                    public_mod = next((mod for mod in self.app_state.all_mods if mod.key == mod_info.get('key')), None)
                    if public_mod:
                        has_update = any((self.mod_manager.mod_has_files_for_chapter(public_mod, i) and self.mod_manager.get_mod_status(public_mod, i) == 'update' for i in range(5)))
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
        except Exception:
            if hasattr(self, 'installed_mods_container'):
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
        show_empty_message_in_layout(self.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)

    def _show_empty_chapter_message(self, chapter_name):
        show_empty_message_in_layout(self.installed_mods_layout, tr('ui.no_mods_for_chapter', chapter_name=chapter_name), self.app_state.local_config, font_size=16)

    def _cleanup_missing_mods(self, installed_mods):
        installed_mod_keys = {mod.get('mod_key') for mod in installed_mods if mod.get('mod_key')}
        mods_metadata = self.mod_manager._read_metadata()
        metadata_updated = False
        orphaned_keys = set(mods_metadata.keys()) - installed_mod_keys
        if orphaned_keys:
            for key in orphaned_keys:
                del mods_metadata[key]
            metadata_updated = True
        if metadata_updated:
            self.mod_manager._write_metadata(mods_metadata)
        for orphaned_key in orphaned_keys:
            dummy_mod_data = self._create_mod_object_from_info({'mod_key': orphaned_key, 'name': 'Orphaned Mod'})
            if not dummy_mod_data:
                continue
            self._remove_mod_from_all_slots(dummy_mod_data)
            config_keys = ['saved_slots_deltarune', 'saved_slots_deltarune_chapter', 'saved_slots_deltarunedemo', 'saved_slots_undertale']
            for config_key in config_keys:
                slots_data = self.app_state.local_config.get(config_key, {})
                slots_to_clear = []
                for slot_id_str, slot_info in list(slots_data.items()):
                    if isinstance(slot_info, dict):
                        saved_mod_key = slot_info.get('mod_key')
                        if saved_mod_key == orphaned_key:
                            slots_to_clear.append(slot_id_str)
                for slot_id_str in slots_to_clear:
                    del slots_data[slot_id_str]
                if slots_to_clear:
                    self.app_state.local_config[config_key] = slots_data
                    self._write_local_config()

    def _get_installed_mods_list(self):
        installed_mods = []
        if not hasattr(self, 'app_state') or not os.path.exists(self.app_state.mods_dir):
            return installed_mods
        mods_metadata = self.mod_manager._read_metadata()
        metadata_updated = False
        found_mod_keys = set()
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if os.path.exists(config_path):
                try:
                    config_data = self._read_json(config_path)
                    if config_data:
                        mod_key = config_data.get('mod_key')
                        if not mod_key:
                            continue
                        found_mod_keys.add(mod_key)
                        mod_meta = mods_metadata.get(mod_key)
                        if not mod_meta:
                            mods_metadata[mod_key] = {'installed_date': time.strftime('%Y-%m-%d %H:%M:%S'), 'is_available_on_server': not config_data.get('is_local_mod', False)}
                            metadata_updated = True
                            mod_meta = mods_metadata[mod_key]
                        config_data['installed_date'] = mod_meta.get('installed_date')
                        config_data['is_available_on_server'] = mod_meta.get('is_available_on_server', False)
                        config_data['is_local_mod'] = config_data.get('is_local_mod', False)
                        config_data['folder_name'] = folder_name
                        installed_mods.append(config_data)
                except Exception as e:
                    logging.warning(f'Failed to read config {config_path}: {e}')
                    continue
        orphaned_keys = set(mods_metadata.keys()) - found_mod_keys
        if orphaned_keys:
            for key in list(orphaned_keys):
                del mods_metadata[key]
            metadata_updated = True
        if metadata_updated:
            self.mod_manager._write_metadata(mods_metadata)
        return installed_mods

    def _create_mod_object_from_info(self, mod_info):
        mod_key = mod_info.get('mod_key', '')
        if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
            for mod in self.app_state.all_mods:
                if hasattr(mod, 'key') and mod.key == mod_key:
                    return mod
        from models.mod_models import ModInfo
        return ModInfo(key=mod_key, name=mod_info.get('name', mod_key), version=mod_info.get('version', '1.0.0'), author=mod_info.get('author', tr('defaults.unknown')), tagline=mod_info.get('tagline', tr('defaults.no_description')), game_version=mod_info.get('game_version', '1.04'), description_url='', downloads=0, modgame=mod_info.get('modgame', 'deltarune'), is_verified=False, is_local_mod=mod_info.get('is_local_mod', False))

    def _on_installed_mod_clicked(self, mod_data):
        for i in range(self.installed_mods_layout.count() - 1):
            try:
                item = self.installed_mods_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, InstalledModWidget):
                        widget_mod_key = getattr(widget.mod_data, 'key', None)
                        mod_data_key = getattr(mod_data, 'key', None)
                        if widget_mod_key == mod_data_key:
                            self._clear_all_installed_mod_selections()
                            widget.set_selected(True)
                            break
            except Exception:
                continue

    def _clear_all_installed_mod_selections(self):
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _on_installed_mod_remove(self, mod_data):
        try:
            if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=getattr(mod_data, 'name', getattr(mod_data, 'key', 'Unknown'))):
                self.mod_manager.delete_mod_files(mod_data)
                self._remove_mod_from_all_slots(mod_data)
                self._update_installed_mods_display()
                try:
                    self._update_search_mod_plaques()
                except Exception:
                    pass
        except Exception as e:
            print(f'Error removing mod {mod_data.name}: {e}')
            self.feedback_manager.show_error('errors.mod_removal_failed', error=str(e))

    def _on_installed_mod_use(self, mod_data):
        current_slot = self._find_mod_in_slots(mod_data)
        if current_slot:
            self._remove_mod_from_slot(current_slot, mod_data)
            self._save_slots_state()
        else:
            is_chapter_mode = self.chapter_mode_checkbox.isChecked()
            is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
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
                elif hasattr(mod_data, 'modgame') and mod_data.modgame == 'undertale':
                    target_slot_id = -20
                else:
                    target_slot_id = -1
                for key, slot_frame in self.app_state.slots.items():
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
        for slot_frame in self.app_state.slots.values():
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
        for key, slot_frame in self.app_state.slots.items():
            if slot_frame.assigned_mod is None:
                if slot_frame.chapter_id == -1:
                    slot_name = tr('ui.mod_slot')
                else:
                    chapter_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
                    slot_name = chapter_names[slot_frame.chapter_id]
                slot_list.addItem(slot_name)
                available_slots.append(slot_frame)
        if not available_slots:
            self.feedback_manager.show_info('dialogs.no_free_slots', tr('dialogs.all_slots_occupied'))
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
        secondary_text_color = get_theme_color(self.app_state.local_config, 'version_text', 'rgba(255, 255, 255, 178)')
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
        if hasattr(mod_data, 'external_url') and mod_data.external_url:
            external_url_button = QPushButton(tr('ui.view_on_external_site'))
            external_url_button.clicked.connect(lambda: webbrowser.open(mod_data.external_url))
            external_url_button.setStyleSheet('color: #FFD700; font-weight: bold;')
            right_layout.addWidget(external_url_button)
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
        modgame_container = QVBoxLayout()
        modgame_container.setSpacing(4)
        modgame_label = OutlinedTextLabel(tr(f'ui.{mod_data.modgame}_label'))
        fill_color = 'white'
        outline_color = '#222222'
        if mod_data.modgame == 'deltarune':
            outline_color = '#222222'
        elif mod_data.modgame == 'deltarunedemo':
            outline_color = 'lightgreen'
        elif mod_data.modgame == 'undertale':
            outline_color = '#750B0B'
        f = modgame_label.font()
        f.setBold(True)
        f.setPointSize(15)
        modgame_label.setFont(f)
        modgame_label.setColors(fill_color, outline_color)
        modgame_label.setOutlineWidth(0.8)
        modgame_label.setMinimumHeight(26)
        modgame_label.setLeftMargin(0)
        modgame_container.addWidget(modgame_label)
        modgame_desc = OutlinedTextLabel(tr(f'ui.{mod_data.modgame}_desc'))
        df = modgame_desc.font()
        df.setPointSize(11)
        modgame_desc.setFont(df)
        modgame_desc.setColors(fill_color, outline_color)
        modgame_desc.setOutlineWidth(0.7)
        modgame_desc.setMinimumHeight(18)
        modgame_desc.setLeftMargin(12)
        modgame_container.addWidget(modgame_desc)
        status_layout.addLayout(modgame_container)
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
        if getattr(mod_data, 'is_xdelta', False):
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
        border_color = self.app_state.local_config.get('custom_color_border') or 'white'
        mod_icon.setStyleSheet(f'border: 1px solid {border_color};')
        text_vbox = QVBoxLayout()
        text_vbox.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        name_label = QLabel()
        status_text, status_color = ('', 'gray')
        is_local_mod = getattr(mod_data, 'is_local_mod', False)
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
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
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
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
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
        for slot_frame in self.app_state.slots.values():
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
            is_local_mod = getattr(mod_data, 'is_local_mod', False)
            if is_local_mod:
                if is_large_slot:
                    status_text, status_color = (tr('status.local_mod'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
                else:
                    status_text, status_color = (tr('status.local'), '#FFD700')
                    version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            elif is_large_slot:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_available'), 'orange') if needs_update else (tr('status.version_current'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 10px; border: none; background: transparent;')
            else:
                needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                status_text, status_color = (tr('status.update_short'), 'orange') if needs_update else (tr('status.current_short'), 'lightgreen')
                version_label.setStyleSheet(f'color: {status_color}; font-size: 9px; border: none; background: transparent;')
            version_label.setText(status_text)

    def _remove_mod_from_all_slots(self, mod_data):
        if not mod_data:
            return
        mod_key = getattr(mod_data, 'key', None) or getattr(mod_data, 'mod_key', None) or getattr(mod_data, 'name', None)
        if not mod_key:
            return
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    self._remove_mod_from_slot(slot_frame, slot_frame.assigned_mod)
        self._save_slots_state()

    def _populate_search_mods(self):
        self._update_filtered_mods()

    def _update_filtered_mods(self):
        if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
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
        selected_modgame = ''
        if hasattr(self, 'modgame_combo'):
            selected_modgame = self.modgame_combo.currentData() or ''
        self.filtered_mods = []
        for mod in self.app_state.all_mods:
            if getattr(mod, 'hide_mod', False) in [True, 'true', 'True', 1]:
                continue
            if getattr(mod, 'ban_status', False) in [True, 'true', 'True', 1]:
                continue
            mod_status = getattr(mod, 'status', 'approved')
            if mod_status not in ['approved', 'pending']:
                continue
            if getattr(mod, 'is_local_mod', False):
                continue
            if selected_tags:
                mod_tags = getattr(mod, 'tags', []) or []
                if not all((tag in mod_tags for tag in selected_tags)):
                    continue
            if selected_modgame:
                mod_modgame = getattr(mod, 'modgame', 'deltarune')
                if mod_modgame != selected_modgame:
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
                plaque.install_button.setEnabled(not self.app_state.is_installing)
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
        if self.app_state.is_installing:
            return
        self._install_single_mod(mod)

    def _install_single_mod(self, mod, force=False):
        try:
            if self.app_state.is_installing and (not force):
                return
            available_chapters = []
            if mod.modgame == 'undertale':
                if mod.files.get('undertale'):
                    available_chapters.append(0)
            elif mod.modgame == 'deltarunedemo':
                if mod.files.get('demo'):
                    available_chapters.append(-1)
            else:
                for chapter_id in range(0, 5):
                    chapter_data = mod.get_chapter_data(chapter_id)
                    if chapter_data:
                        available_chapters.append(chapter_id)
            if not available_chapters:
                self.feedback_manager.show_warning('errors.mod_no_files', mod_name=mod.name)
                return
            was_installed_before = self.mod_manager.is_mod_installed(mod.key)
            is_xdelta_mod = getattr(mod, 'is_xdelta', False)
            if not is_xdelta_mod and (not was_installed_before):
                if not self.feedback_manager.ask_question('dialogs.file_replacement_warning_title', 'dialogs.file_replacement_warning_body', '', False):
                    self.feedback_manager.update_status(tr('status.install_cancelled_by_user'), UI_COLORS['status_info'])
                    return
            install_tasks = [(mod, chapter_id) for chapter_id in available_chapters]
            self.app_state.is_installing = True
            self._set_install_buttons_enabled(False)
            self.action_button.setText(tr('ui.cancel_button'))
            self._install_op_id = getattr(self, '_install_op_id', 0) + 1
            op_id = self._install_op_id
            self.current_install_thread = InstallModsThread(self, install_tasks, was_installed_before)
            self.install_thread = self.current_install_thread
            self.install_thread.progress.connect(lambda v, oid=op_id: self._on_install_progress_token(v, oid))
            self.install_thread.status.connect(lambda msg, col, oid=op_id: self._on_install_status_token(msg, col, oid))
            self.install_thread.finished.connect(lambda ok, oid=op_id: self._on_install_finished_token(ok, oid))
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            try:
                self.feedback_manager.update_status(tr('status.preparing_download'), UI_COLORS['status_warning'])
            except Exception:
                pass
            self._update_action_button_state()
            self.install_thread.start()
        except Exception as e:
            print(f'Error installing mod {mod.name}: {e}')
            self.feedback_manager.show_error('errors.mod_install_failed', error=str(e))

    def _on_install_progress_token(self, value: int, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.app_state.is_installing:
            self.progress_bar.setValue(value)

    def _on_install_status_token(self, message: str, color: str, op_id: int):
        if getattr(self, '_install_op_id', 0) == op_id and self.app_state.is_installing:
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
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
        else:
            if getattr(self, '_operation_cancelled', False):
                try:
                    self._operation_cancelled = False
                except Exception:
                    pass
            else:
                self.feedback_manager.update_status(tr('status.mod_install_error'), UI_COLORS['status_error'])
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        if success:
            self.mod_manager.load_local_mods()
            self._update_search_mod_plaques()
            if hasattr(self, '_update_installed_mods_display'):
                self._update_installed_mods_display()
            QTimer.singleShot(100, self._refresh_specific_mod_widget_after_update)
            if not was_installed_before:
                self.feedback_manager.show_info('dialogs.mod_installed_title', tr('dialogs.mod_installed_apply_info'))
            self.feedback_manager.update_status(tr('status.mod_installed_success'), UI_COLORS['status_success'])
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
        if self.app_state.is_installing:
            return
        if self.feedback_manager.ask_question('dialogs.delete_confirmation', 'dialogs.delete_mod_confirmation', '', False, mod_name=mod.name):
            self._uninstall_single_mod(mod)

    def _uninstall_single_mod(self, mod):
        self.mod_manager.uninstall_mod(mod)
        self._update_search_mod_plaques()

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
        self.mod_manager.update_mod(mod_data)

    def _on_mod_install_finished(self, success, from_gb=False):
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        self.progress_bar.setVisible(False)
        self._update_action_button_state()

    def _on_mod_installation_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self._update_action_button_state()

    def _prompt_for_mods_dir(self):
        self.settings_manager.prompt_for_mods_dir()

    def _update_change_path_button_text(self):
        self.change_path_button.setText(self.app_state.game_mode.path_change_button_text)

    def _full_install_tooltip(self) -> str:
        if platform.system() == 'Darwin':
            return tr('tooltips.macos_install_unavailable')
        return tr('tooltips.full_install_instructions')

    def _on_toggle_full_install(self, state):
        self.app_state.is_full_install = bool(state)
        if platform.system() == 'Darwin' and self.app_state.is_full_install:
            self.feedback_manager.show_info('dialogs.unavailable', tr('dialogs.macos_install_unavailable'))
            self.full_install_checkbox.blockSignals(True)
            self.full_install_checkbox.setChecked(False)
            self.full_install_checkbox.blockSignals(False)
            return
        self._update_action_button_state()

    def _save_window_geometry(self):
        geom_ba = self.saveGeometry()
        self.app_state.local_config['window_geometry'] = geom_ba.toHex().data().decode()
        self._write_local_config()

    def load_font(self):
        language = localization_manager.get_current_language()
        font_path = localization_manager.get_font_path(language)
        self.custom_font_family = None
        if font_path and os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    self.custom_font_family = families[0]

    def apply_theme(self):
        theme = THEMES['default']
        background_path = None
        background_disabled = self.app_state.local_config.get('background_disabled', False)
        if self.background_movie is not None:
            self.background_movie.stop()
            self.background_movie.deleteLater()
            self.background_movie = None
        self.background_pixmap = None
        if not background_disabled:
            background_path = self.app_state.local_config.get('custom_background_path') or resource_path(f"resources/{theme.get('background', '')}")
            if background_path:
                self._bg_loader = BgLoader(background_path, self.size())
                self._bg_loader.loaded.connect(self._on_bg_ready)
                self._bg_loader.start()
        user_bg_hex = self.app_state.local_config.get('custom_color_background')
        if user_bg_hex and self._is_valid_hex_color(user_bg_hex):
            frame_bg_color = f"#C0{user_bg_hex.lstrip('#')}"
        else:
            frame_bg_color = 'rgba(0, 0, 0, 150)'
        button_color = self.app_state.local_config.get('custom_color_button') or theme['colors']['button']
        border_color = self.app_state.local_config.get('custom_color_border') or theme['colors']['border']
        button_hover_color = self.app_state.local_config.get('custom_color_button_hover') or theme['colors']['button_hover']
        main_text_color = self.app_state.local_config.get('custom_color_text') or theme['colors']['text']
        base_family = self.custom_font_family or theme['font_family']
        font_family_main = base_family
        font_size_main = theme['font_size_main']
        font_size_small = theme['font_size_small']
        status_font = QFont(font_family_main, font_size_small)
        self.status_label.setFont(status_font)
        explicit_color_widgets = [getattr(self, 'telegram_button', None), getattr(self, 'discord_button', None)]
        explicit_colors = [UI_COLORS['link'], UI_COLORS['social_discord']]
        for widget, color in zip(explicit_color_widgets, explicit_colors):
            if widget is not None:
                widget.setStyleSheet(f'color: {color};')
        style_sheet = f'''\n                    QFrame#bottom_widget, QFrame#settings_widget {{ background-color: {frame_bg_color}; }}\n                    QWidget {{ font-family: "{font_family_main}", sans-serif; outline: none; font-size: {font_size_main}pt; color: {main_text_color}; background-color: transparent; }}\n                    QDialog, QMessageBox {{ font-family: "{font_family_main}", sans-serif; font-size: {font_size_small}pt; color: {main_text_color}; background-color: {frame_bg_color}; border: 3px solid {border_color}; }}\n                    QDialog > QLabel, QMessageBox > QLabel {{ background: transparent; font-size: {font_size_small}pt; }}\n                    QDialog QPushButton, QMessageBox QPushButton {{ font-size: {font_size_small}pt; }}\n                    QPushButton {{ background-color: {button_color}; border: 2px solid {border_color}; color: {theme['colors']['button_text']}; padding: 5px; min-height: 30px; min-width: 100px; }}\n                    QPushButton:hover {{ background-color: {button_hover_color}; }}\n                    QPushButton:disabled, QComboBox:disabled {{ background-color: #333333; color: #888888; border: 2px solid #555555; }}\n                    QPushButton#addTranslationButton {{ min-width: 33px; min-height: 33px; padding: 2px; }}\n                    QComboBox {{ background-color: {button_color}; color: {theme['colors']['button_text']}; border: 2px solid {border_color}; padding: 4px; min-height: 30px; }}\n                    QComboBox QAbstractItemView {{ background-color: {button_color}; border: 2px solid {border_color}; color: {theme['colors']['button_text']}; selection-background-color: {button_hover_color}; }}\n                    QTextEdit, QTextBrowser {{ background-color: {frame_bg_color}; border: 2px solid {border_color}; }}\n                    QFrame#filters {{\n                        background-color: {frame_bg_color};\n                        border: 2px solid {border_color};\n                        padding: 4px 8px;\n                    }}\n                    QPushButton#sortOrderBtn {{\n                        min-width: 35px;\n                        max-width: 35px;\n                        padding-left: 0px;\n                        padding-right: 0px;\n                        background-color: {button_color};\n                        border: 2px solid {border_color};\n                        color: {theme['colors']['button_text']};\n                        font-weight: bold;\n                        font-size: 12px;\n                    }}\n                    QPushButton#sortOrderBtn:hover {{\n                        background-color: {button_hover_color};\n                    }}\n                    QPushButton#searchBtn {{\n                        min-width: 35px;\n                        max-width: 35px;\n                        min-height: 30px;\n                        max-height: 30px;\n                        padding-left: 0px;\n                        padding-right: 0px;\n                        background-color: {button_color};\n                        border: 2px solid {border_color};\n                        color: {theme['colors']['button_text']};\n                        font-weight: bold;\n                        font-size: 16px;\n                    }}\n                    QPushButton#searchBtn:hover {{\n                        background-color: {button_hover_color};\n                    }}\n                    QTextEdit, QTextBrowser {{ background-color: {frame_bg_color}; color: {main_text_color}; border: 2px solid {border_color}; min-height: 100px; }}\n                    QTabBar::tab {{ background-color: {button_color}; color: {theme['colors']['button_text']}; border: 2px solid {border_color}; padding: 5px; min-height: 25px; min-width: 80px; }}\n                    QTabBar::tab:selected, QTabBar::tab:hover {{ background-color: {button_hover_color}; }}\n                    QTabBar::tab:disabled {{ background-color: #333333; color: #888888; border: 2px solid #555555; }}\n                    QTabWidget::pane {{ background: transparent; border: 0px; }}\n                    QCheckBox:disabled {{ color: #888888; }}\n                    QCheckBox::indicator {{ width: 15px; height: 15px; background-color: {button_color}; border: 2px solid {border_color}; }}\n                    QCheckBox::indicator:checked {{ background-color: {('#ffffff' if not self.color_widgets['button_hover'].text() else button_hover_color)}; }}\n                    QCheckBox::indicator:disabled {{ background-color: #333333; border: 2px solid #555555; }}\n                    QPushButton:checked {{ background-color: {button_hover_color}; border: 2px solid {main_text_color}; }}\n            '''
        scroll_handle_color = self.app_state.local_config.get('custom_color_button') or 'white'
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
        self._update_translucent_backgrounds()
        self.update()

    def _update_translucent_backgrounds(self):
        bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        if bg_color.startswith('#'):
            r = int(bg_color[1:3], 16)
            g = int(bg_color[3:5], 16)
            b = int(bg_color[5:7], 16)
            bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            bg_rgba = 'rgba(0, 0, 0, 128)'
        if hasattr(self, 'search_container'):
            self.search_container.setStyleSheet(f'\n            QWidget#search_mods_background {{\n                background-color: {bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        if hasattr(self, 'active_slots_widget'):
            self.active_slots_widget.setStyleSheet(f'\n            QWidget#slots_background {{\n                background-color: {bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        if hasattr(self, 'installed_mods_container'):
            self.installed_mods_container.setStyleSheet(f'\n            QWidget#mods_background {{\n                background-color: {bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')

    def _configure_hidden_tab_bar(self, tab_widget: QTabWidget):
        bar = tab_widget.tabBar()
        if bar:
            bar.hide()
            bar.setEnabled(False)
            bar.setMaximumSize(0, 0)
            bar.setMinimumSize(0, 0)
            bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _hide_save_manager(self):
        self.save_manager_widget.setVisible(False)
        self.app_state.is_save_manager_view = False
        if self.app_state.is_settings_view:
            self.settings_widget.setVisible(True)
        else:
            self.main_tab_widget.setVisible(True)
            self.bottom_widget.setVisible(True)

    def _clear_selected_slot(self):
        self.app_state.selected_slot = None
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
        in_main = self.app_state.current_collection_idx == -1
        visible = self.app_state.selected_slot is not None
        for b in (self.show_btn, self.import_btn, self.erase_btn, self.export_btn):
            b.setVisible(visible)
        has_data = False
        if self.app_state.selected_slot:
            ch, s = self.app_state.selected_slot
            idx = self.app_state.current_collection_idx
            base = self.save_manager.get_collection_path(idx)
            fp = os.path.join(base, f'filech{ch}_{s}')
            has_data = os.path.exists(fp) and os.path.getsize(fp) > 0
        self.erase_btn.setEnabled(has_data)
        self.export_btn.setEnabled(has_data)
        self.copy_from_main_btn.setEnabled(not in_main)
        self.copy_to_main_btn.setEnabled(not in_main)

    def _on_slot_double_clicked(self, chapter: int, slot: int):
        idx = self.app_state.current_collection_idx
        base = self.save_manager.get_collection_path(idx)
        fp = os.path.join(base, f'filech{chapter}_{slot}')
        if not (os.path.exists(fp) and os.path.getsize(fp) > 0):
            return
        dlg = SaveEditorDialog(fp, self)
        if dlg.exec():
            self._refresh_save_slots()

    def _on_save_manager_slot_clicked(self, chapter: int, slot: int):
        self.app_state.selected_slot = (chapter, slot)
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _update_slot_highlight(self):
        user_bg = self.app_state.local_config.get('custom_color_background')
        if user_bg and self._is_valid_hex_color(user_bg):
            slot_bg = f"#80{user_bg.lstrip('#')}"
        else:
            slot_bg = '#80000000'
        for (ch, sl), lbl in self._slot_labels.items():
            if self.app_state.selected_slot == (ch, sl):
                lbl.setStyleSheet(f'border:2px solid white; background-color: {slot_bg}; padding:4px;')
            else:
                lbl.setStyleSheet(f'border:1px solid white; background-color: {slot_bg}; padding:4px;')

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
        self.app_state.is_save_manager_view = True
        self.main_tab_widget.setVisible(False)
        self.bottom_widget.setVisible(False)
        self.settings_widget.setVisible(False)
        self.save_manager_widget.setVisible(True)
        self.app_state.selected_slot = None
        self._refresh_save_slots()
        self.feedback_manager.update_status(tr('status.save_path_info', save_path=self.app_state.save_path), UI_COLORS['status_info'])
        self.settings_button.setText(tr('ui.back_button'))
        try:
            self.settings_button.clicked.disconnect(self._toggle_settings_view)
        except TypeError:
            pass
        self.settings_button.clicked.connect(self._return_from_save_manager)

    def _refresh_save_slots(self):
        if not (self.app_state.save_path and os.path.isdir(self.app_state.save_path)):
            return
        chapter = self.save_tabs.currentIndex() + 1
        slots_data = self.save_manager.refresh_save_slots_data(chapter)
        for s, (active, text) in slots_data.items():
            self._slot_labels[chapter, s].setText(text)
        self._update_collection_ui()
        self._update_slot_highlight()
        self._update_slot_action_bar()

    def _find_and_validate_save_path(self) -> bool:
        return self.save_manager.find_and_validate_save_path()

    def _prompt_for_save_path(self) -> bool:
        return self.save_manager.prompt_for_save_path()

    def _toggle_collection_view(self):
        self.save_manager.toggle_collection_view()

    def _navigate_collection(self, direction: int):
        self.save_manager.navigate_collection(direction)

    def _create_new_collection(self) -> bool:
        return self.save_manager.create_new_collection()

    def _prompt_collection_name(self, default: str = 'Collection') -> Optional[str]:
        return self.save_manager.prompt_collection_name(default)

    def _update_collection_ui(self):
        ui_state = self.save_manager.get_collection_ui_state()
        in_col = ui_state['in_collection']
        self.switch_collection_btn.setText(tr('buttons.main_slots') if in_col else tr('buttons.additional_slots'))
        self.left_col_btn.setEnabled(ui_state['can_navigate_left'])
        self.right_col_btn.setEnabled(ui_state['can_navigate_right'])
        self.rename_collection_btn.setVisible(in_col)
        self.delete_collection_btn.setVisible(in_col)
        self.copy_from_main_btn.setVisible(in_col)
        self.copy_to_main_btn.setVisible(in_col)
        if in_col and ui_state['collection_name']:
            self.collection_name_lbl.setText(ui_state['collection_name'])
            self.collection_name_lbl.setVisible(True)
        else:
            self.collection_name_lbl.setVisible(False)
        self.change_save_path_btn.setVisible(not in_col)

    def _on_chapter_tab_changed(self):
        self.app_state.selected_slot = None
        self._refresh_save_slots()

    def _rename_current_collection(self):
        idx = self.app_state.current_collection_idx
        self.save_manager.rename_current_collection(idx)

    def _delete_current_collection(self):
        idx = self.app_state.current_collection_idx
        self.save_manager.delete_current_collection(idx)

    def _copy_between_storages(self, to_collection: bool):
        chapter = self.save_tabs.currentIndex() + 1
        self.save_manager.copy_between_storages(chapter, to_collection, self.app_state.selected_slot)

    def _action_show_save(self):
        if not self.app_state.selected_slot:
            return
        ch, s = self.app_state.selected_slot
        self.save_manager.action_show_save(ch, s)

    def _action_delete_save(self):
        if not self.app_state.selected_slot:
            return
        ch, s = self.app_state.selected_slot
        self.save_manager.action_delete_save(ch, s)

    def _action_import_export(self, is_import: bool):
        if not self.app_state.selected_slot:
            return
        ch, s = self.app_state.selected_slot
        self.save_manager.action_import_export(ch, s, is_import)

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
        if self.app_state.current_settings_page and self.app_state.current_settings_page is not page:
            self.app_state.settings_nav_stack.append(self.app_state.current_settings_page)
            if len(self.app_state.settings_nav_stack) > 20:
                self.app_state.settings_nav_stack.pop(0)
            self.app_state.current_settings_page.setVisible(False)
        page.setVisible(True)
        self.app_state.current_settings_page = page

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

    def _go_back_or_to_main_menu(self):
        if hasattr(self, 'settings_nav_stack') and self.app_state.settings_nav_stack:
            prev = self.app_state.settings_nav_stack.pop()
            if self.app_state.current_settings_page:
                self.app_state.current_settings_page.setVisible(False)
            prev.setVisible(True)
            self.app_state.current_settings_page = prev
        else:
            self._toggle_settings_view()

    def _go_back_to_settings_menu(self):
        if self.app_state.current_settings_page and self.app_state.current_settings_page is not self.settings_menu_page:
            self.app_state.current_settings_page.setVisible(False)
        self.settings_menu_page.setVisible(True)
        self.app_state.current_settings_page = self.settings_menu_page
        if self.app_state.settings_nav_stack and self.app_state.settings_nav_stack[-1] is self.settings_menu_page:
            self.app_state.settings_nav_stack.pop()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.background_movie is not None:
            painter.drawPixmap(self.rect(), self.background_movie.currentPixmap())
        elif self.background_pixmap:
            painter.drawPixmap(self.rect(), self.background_pixmap)
        else:
            bg_color_str = self.app_state.local_config.get('custom_color_background') or 'rgba(0, 0, 0, 200)'
            try:
                painter.fillRect(self.rect(), QColor(bg_color_str))
            except Exception:
                painter.fillRect(self.rect(), QColor('rgba(0, 0, 0, 200)'))
        super().paintEvent(event)

    def _on_reset_settings_click(self):
        self._stop_background_music()
        callbacks = {'migrate_config': lambda: (self._load_local_data(), self._migrate_config_if_needed())}
        self.settings_manager.on_reset_settings_click(callbacks)
        self.launch_via_steam_checkbox.setChecked(False)
        self.use_custom_executable_checkbox.setChecked(False)
        self.chapter_mode_checkbox.setChecked(False)
        self.beta_updates_checkbox.setChecked(False)
        self.fullscreen_checkbox.setChecked(False)
        self.hide_library_filters_checkbox.setChecked(False)
        self.full_install_checkbox.setChecked(False)
        self.disable_background_checkbox.setChecked(False)
        self.disable_splash_checkbox.setChecked(False)
        self._update_custom_executable_ui()
        self._update_checkbox_visibility()
        self._clear_all_slots()
        self._save_slots_state()
        self._load_slots_state()
        self._update_settings_page_visibility()
        self._load_custom_style_settings()
        self._update_action_button_state()
        self.background_music_button.setText(self._get_background_music_button_text())
        self.startup_sound_button.setText(self._get_startup_sound_button_text())

    def _on_background_button_click(self):
        self.settings_manager.on_background_button_click()
        self._update_background_button_state()

    def _update_background_button_state(self):
        background_disabled = self.app_state.local_config.get('background_disabled', False)
        self.change_background_button.setEnabled(not background_disabled)
        self.change_background_button.setText(tr('buttons.remove_background') if self.app_state.local_config.get('custom_background_path') else tr('buttons.change_background'))

    def _toggle_settings_view(self, show_changelog=False):
        if show_changelog:
            self.app_state.is_changelog_view = not self.app_state.is_changelog_view
        else:
            self.app_state.is_settings_view = not self.app_state.is_settings_view
            if not self.app_state.is_settings_view:
                if self.app_state.is_save_manager_view:
                    self._on_configure_saves_click()
                if self.app_state.is_changelog_view:
                    self.app_state.is_changelog_view = False
        if self.app_state.is_settings_view:
            self.settings_button.setText(tr('ui.back_button'))
            self.tab_widget.setVisible(False)
            self.bottom_widget.setVisible(False)
            self.settings_widget.setVisible(True)
            self._switch_settings_page(self.settings_menu_page)
            self._update_settings_page_visibility()
            self._load_custom_style_settings()
            self._update_status(tr('status.launcher_settings'), UI_COLORS['status_info'])
        else:
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
        self.app_state.is_help_view = not self.app_state.is_help_view
        if self.app_state.is_help_view and self.app_state.is_changelog_view:
            self.app_state.is_changelog_view = False
        if self.app_state.is_help_view:
            self._load_help_content()
        self._update_settings_page_visibility()

    def _load_help_content(self):
        if localization_manager.get_current_language() == 'ru':
            help_url = self.app_state.global_settings.get('help_ru_url', self.app_state.global_settings.get('help_url', ''))
        else:
            help_url = self.app_state.global_settings.get('help_en_url', self.app_state.global_settings.get('help_url', ''))
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
        is_changelog = self.app_state.is_changelog_view
        is_help = self.app_state.is_help_view
        self.settings_pages_container.setVisible(not is_changelog and (not is_help))
        self.changelog_widget.setVisible(is_changelog)
        self.help_widget.setVisible(is_help)
        self.changelog_button.setText(tr('buttons.changelog_close') if is_changelog else tr('buttons.changelog'))
        self.help_button.setText(tr('buttons.changelog_close') if is_help else tr('buttons.help'))

    def _on_toggle_disable_background(self, state):
        is_disabled = bool(state)
        self.settings_manager.on_toggle_disable_background(is_disabled)
        self._update_background_button_state()

    def _on_toggle_disable_splash(self, state):
        is_disabled = bool(state)
        self.settings_manager.on_toggle_disable_splash(is_disabled)

    def _on_toggle_hide_library_filters(self, state):
        is_hidden = bool(state)
        self.settings_manager.on_toggle_hide_library_filters(is_hidden)
        if hasattr(self, 'library_filters_widget'):
            self.library_filters_widget.setVisible(not is_hidden)

    def _is_valid_hex_color(self, s: str) -> bool:
        return self.settings_manager.is_valid_hex_color(s)

    def _on_custom_style_edited(self):
        self.settings_manager.on_custom_style_edited(self.color_widgets)
        self._update_dynamic_elements()

    def _update_dynamic_elements(self):
        if hasattr(self.app_state, 'slots'):
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
                        filter_bg_color = self.app_state.local_config.get('custom_color_background') or 'rgba(0, 0, 0, 150)'
                        filter_border_color = self.app_state.local_config.get('custom_color_border') or 'white'
                        filters.setStyleSheet(f'QFrame#filters {{ background-color: {filter_bg_color}; border: 2px solid {filter_border_color}; padding: 8px; }}')
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
            widget.setText(self.app_state.local_config.get(config_key, ''))
            widget.setPlaceholderText(placeholder)
        self.apply_theme()

    def _load_launcher_icon(self):
        try:
            splash_path = resource_path('resources/images/splash.png')
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
        mp3_path = os.path.join(self.app_state.config_dir, 'custom_background_music.mp3')
        wav_path = os.path.join(self.app_state.config_dir, 'custom_background_music.wav')
        if os.path.exists(mp3_path):
            return mp3_path
        if os.path.exists(wav_path):
            return wav_path
        return ''

    def _get_startup_sound_path(self):
        mp3 = os.path.join(self.app_state.config_dir, 'custom_startup_sound.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_startup_sound.wav')
        if os.path.exists(mp3):
            return mp3
        if os.path.exists(wav):
            return wav
        return ''

    def _get_background_music_button_text(self):
        mp3 = os.path.join(self.app_state.config_dir, 'custom_background_music.mp3')
        wav = os.path.join(self.app_state.config_dir, 'custom_background_music.wav')
        custom_exists = os.path.exists(mp3) or os.path.exists(wav)
        return tr('buttons.remove_background_music') if custom_exists else tr('buttons.select_background_music')

    def _get_startup_sound_button_text(self):
        if os.path.exists(self._get_startup_sound_path()):
            return tr('buttons.remove_startup_sound')
        return tr('buttons.select_startup_sound')

    def _on_background_music_button_click(self):
        self._stop_background_music()
        self.settings_manager.on_background_music_button_click()
        self.background_music_button.setText(self._get_background_music_button_text())
        self._maybe_start_background_music()

    def _on_startup_sound_button_click(self):
        self.settings_manager.on_startup_sound_button_click()
        self.startup_sound_button.setText(self._get_startup_sound_button_text())

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
            if self.app_state.initialization_completed and getattr(self, 'is_shown_to_user', False) and self.isVisible():
                self._start_background_music()
            else:
                QTimer.singleShot(500, self._maybe_start_background_music)
        except Exception:
            pass

    def _on_toggle_direct_launch_for_slot(self, slot_id):
        self.settings_manager.on_toggle_direct_launch_for_slot(slot_id)
        self._update_all_slots_visual_state()
        self.launch_via_steam_checkbox.setEnabled(False)

    def _update_action_button_state(self):
        if getattr(self, 'is_installing', False) and (not getattr(self, '_operation_cancelled', False)):
            self.action_button.setText(tr('ui.cancel_button'))
            self.action_button.setEnabled(True)
            return
        if not self.app_state.initialization_completed:
            self.action_button.setText(tr('status.please_wait'))
            self.action_button.setEnabled(False)
            return
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
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
        self.settings_manager.disable_direct_launch()
        self._update_all_slots_visual_state()
        self.launch_via_steam_checkbox.setEnabled(True)

    def _update_all_slots_visual_state(self):
        if hasattr(self.app_state, 'slots'):
            for slot in self.app_state.slots.values():
                self._update_slot_visual_state(slot)

    def _initialize_mutual_exclusions(self):
        is_direct_launch = self.app_state.local_config.get('direct_launch_slot_id', -1) >= 0 and self.app_state.game_mode.direct_launch_allowed and (platform.system() != 'Darwin')
        if not hasattr(self, 'launch_via_steam_checkbox'):
            return
        if is_direct_launch:
            self.launch_via_steam_checkbox.setEnabled(False)
        self.apply_theme()

    def _post_show_initialization(self):
        self._init_session()
        try:
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            response = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
            if response.status_code == 200:
                self.app_state.global_settings = response.json() or {}
        except requests.RequestException:
            self.feedback_manager.update_status(tr('status.global_settings_load_failed'), UI_COLORS['status_warning'])
        if localization_manager.get_current_language() == 'ru':
            changelog_url = self.app_state.global_settings.get('changelog_ru_url', self.app_state.global_settings.get('changelog_url'))
        else:
            changelog_url = self.app_state.global_settings.get('changelog_en_url', self.app_state.global_settings.get('changelog_url'))
        if changelog_url:
            changelog_thread = FetchChangelogThread(changelog_url.strip(), self)
            changelog_thread.finished.connect(self.changelog_text_edit.setMarkdown)
            changelog_thread.start()
        else:
            self.changelog_text_edit.setMarkdown(tr('status.changelog_load_failed'))
        self._check_and_manage_steam_deck_saves()
        if is_game_running():
            self.feedback_manager.update_status(tr('status.deltarune_already_running'), UI_COLORS['status_error'])
            return
        self._load_local_data()
        self.app_state.game_path = self.app_state.local_config.get('game_path', '')
        self.app_state.demo_game_path = self.app_state.local_config.get('demo_game_path', '')
        saved_demo_mode = self.app_state.local_config.get('demo_mode_enabled', False)
        saved_chapter_mode = self.app_state.local_config.get('chapter_mode_enabled', False)
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
        self.disable_background_checkbox.blockSignals(True)
        self.disable_background_checkbox.setChecked(self.app_state.local_config.get('background_disabled', False))
        self.disable_background_checkbox.blockSignals(False)
        self.disable_splash_checkbox.blockSignals(True)
        self.disable_splash_checkbox.setChecked(self.app_state.local_config.get('disable_splash', False))
        self.beta_updates_checkbox.setChecked(self.app_state.local_config.get('beta_updates_enabled', False))
        self.fullscreen_checkbox.setChecked(self.app_state.local_config.get('fullscreen_enabled', False))
        if hasattr(self, 'hide_library_filters_checkbox'):
            self.hide_library_filters_checkbox.setChecked(self.app_state.local_config.get('hide_library_filters', False))
        self.disable_splash_checkbox.blockSignals(False)
        self._update_change_path_button_text()
        self._update_background_button_state()
        self._migrate_config_if_needed()
        self.use_custom_executable_checkbox.setChecked(self.app_state.local_config.get('use_custom_executable', False))
        self.launch_via_steam_checkbox.setChecked(self.app_state.local_config.get('launch_via_steam', False))
        self._initialize_mutual_exclusions()
        self._on_toggle_steam_launch()
        self._update_all_slots_visual_state()
        self.apply_theme()
        self.mod_manager.load_local_mods()
        self.setEnabled(False)
        self._on_refresh_clicked(is_initial=True)
        self.setEnabled(True)
        self._update_installed_mods_display()
        if not self._find_and_validate_game_path(is_initial=True):
            self.action_button.setEnabled(False)

    def _check_and_manage_steam_deck_saves(self):
        if platform.system() != 'Linux':
            return
        try:
            home_dir = os.path.expanduser('~')
            if isinstance(self.app_state.game_mode, UndertaleGameMode):
                game_name = 'UNDERTALE'
            else:
                game_name = 'DELTARUNE'
            steam_app_id = self.app_state.game_mode.steam_id
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
                    self.feedback_manager.show_info('dialogs.backup', tr('dialogs.backup_created_for_steam_deck', backup_path=backup_path))
            os.symlink(proton_save_path, native_save_path)
            self.feedback_manager.show_info('dialogs.steam_deck_setup', tr('dialogs.steam_deck_compatibility_configured'))
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

    def _handle_update_info(self, update_info):
        if self.app_state.initialization_completed and getattr(self, 'is_shown_to_user', False):
            self.show_update_prompt.emit(update_info)
        else:
            QTimer.singleShot(1000, lambda: self._handle_update_info(update_info))

    def _maybe_run_legacy_cleanup(self):
        if self._legacy_cleanup_done:
            return
        if self.app_state.initialization_completed and getattr(self, 'is_shown_to_user', False):
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
                self.feedback_manager.show_info('dialogs.legacy_cleanup_title', tr('dialogs.legacy_cleanup_message'))
        except Exception:
            pass

    def _prompt_for_update(self, update_info):
        if self.app_state.update_in_progress:
            return
        if self.app_state.game_is_running:
            self.app_state.pending_dialogs.append(('update', update_info))
            return
        self.app_state.update_in_progress = True
        update_message = f"<b>{tr('dialogs.new_version_banner', version=update_info['version']).replace('<br>', '')}</b><br>"
        update_message += tr('dialogs.current_version_banner', current_version=LAUNCHER_VERSION).replace('<br><br>', '') + '<br><br>'
        if localization_manager.get_current_language() == 'ru':
            message_text = update_info.get('message_ru') or update_info.get('message', '')
        else:
            message_text = update_info.get('message_en') or update_info.get('message', '')
        update_message += f"<b>{tr('dialogs.whats_new')}</b><br>{message_text}<br><br>"
        update_message += tr('dialogs.want_download_install_now') + tr('dialogs.app_will_restart')
        if self.feedback_manager.ask_question('status.update_available', 'status.update_available', update_message, True):
            self._perform_update_ui_prep()
            self.update_checker.perform_update(update_info)
        else:
            self.app_state.update_in_progress = False
            self.feedback_manager.update_status(tr('status.update_rejected'), UI_COLORS['status_info'])

    def _perform_update_ui_prep(self):
        for widget in [self.action_button, self.saves_button, self.shortcut_button, self.change_path_button, self.change_background_button]:
            widget.setEnabled(False)
        try:
            if hasattr(self, 'top_refresh_button') and self.top_refresh_button:
                self.top_refresh_button.setEnabled(False)
        except Exception:
            pass
        self.settings_button.setEnabled(False)
        if not self.app_state.is_settings_view:
            self.tab_widget.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

    def _on_update_cleanup(self):
        try:
            self.progress_bar.setVisible(False)
        except Exception:
            pass
        self.app_state.update_in_progress = False
        try:
            if not self.app_state.is_settings_view:
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

    def _on_action_button_click(self):
        if self.app_state.is_installing and self.current_install_thread:
            self._operation_cancelled = True
            self.feedback_manager.update_status(tr('status.operation_cancelled'), UI_COLORS['status_error'])
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
        if isinstance(self.app_state.game_mode, DemoGameMode) and getattr(self, 'full_install_checkbox', None) is not None and self.full_install_checkbox.isChecked():
            self._perform_full_install()
            return
        if self.app_state.is_installing:
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

    def _on_refresh_clicked(self, is_initial=False):
        current_lang_code = localization_manager.get_current_language()
        localization_manager.rescan_languages()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        available_languages = localization_manager.get_available_languages()
        for code, name in available_languages.items():
            self.language_combo.addItem(name, code)
        index = self.language_combo.findData(current_lang_code)
        if index != -1:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)
        if not is_initial:
            self._retranslate_ui()
        if is_game_running():
            self.feedback_manager.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
            return
        self._stop_fetch_thread()
        threading.Thread(target=self.update_checker.check_for_updates, daemon=True).start()
        self.fetch_thread = FetchModsThread(self, force_update=True)
        self.fetch_thread.status.connect(self.update_status_signal)
        self.fetch_thread.result.connect(self._on_fetch_translations_finished)
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
            self.mod_manager.load_local_mods()
            if hasattr(self, 'mod_list_layout'):
                self._populate_search_mods()
                if not self.app_state.mods_loaded:
                    self.app_state.mods_loaded = True
                    self.mods_loaded_signal.emit()
            if hasattr(self, 'installed_mods_layout'):
                self._update_installed_mods_display()
            self._refresh_mods_in_slots()
            self._refresh_slots_content()
            self._update_action_button_state()
            if success:
                self.feedback_manager.update_status(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.app_state.all_mods else tr('ui.network_update_failed')
                self.feedback_manager.update_status(fallback_msg, UI_COLORS['status_error'])
            QTimer.singleShot(100, self._load_slots_state)
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])

    def _refresh_mods_in_slots(self):
        if not hasattr(self, 'slots') or not self.app_state.all_mods:
            return
        for slot_frame in self.app_state.slots.values():
            if slot_frame.assigned_mod:
                old_mod = slot_frame.assigned_mod
                mod_key = getattr(old_mod, 'key', None) or getattr(old_mod, 'mod_key', None)
                if not mod_key:
                    continue
                updated_mod = None
                for mod in self.app_state.all_mods:
                    updated_mod_key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                    if updated_mod_key == mod_key:
                        updated_mod = mod
                        break
                if not updated_mod:
                    mod_config = self.mod_manager.get_mod_config(mod_key)
                    if mod_config:
                        updated_mod = self._create_mod_object_from_info(mod_config)
                if updated_mod:
                    slot_frame.assigned_mod = updated_mod
        self._refresh_all_slot_status_displays()

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
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        if success:
            self.mod_manager.load_local_mods()
            self.feedback_manager.update_status(tr('status.installation_complete'), UI_COLORS['status_success'])
            self._update_installed_mods_display()
        self._update_action_button_state()
        if hasattr(self, 'full_install_checkbox') and self.full_install_checkbox is not None and isinstance(self.app_state.game_mode, DemoGameMode):
            self.full_install_checkbox.setEnabled(True)
        self._update_action_button_state()

    def _perform_full_install(self):
        if self.app_state.is_installing:
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
            self.feedback_manager.show_error('errors.error', tr('errors.folder_creation_failed', error=str(e)))
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
            if isinstance(self.app_state.game_mode, DemoGameMode):
                self.app_state.demo_game_path = target_dir
                self.app_state.local_config['demo_game_path'] = target_dir
            else:
                self.app_state.game_path = target_dir
                self.app_state.local_config['game_path'] = target_dir
            self._write_local_config()
            self.feedback_manager.update_status(tr('status.game_files_install_complete'), UI_COLORS['status_success'])
            self._update_action_button_state()
            return
        else:
            self.feedback_manager.update_status(tr('status.game_files_install_failed'), UI_COLORS['status_error'])
        self._write_local_config()
        self._update_action_button_state()

    def _run_as_admin_windows(self, path: str) -> bool:
        script = f"import os, stat; p = r'{path}'; [os.chmod(os.path.join(r, f), os.stat(os.path.join(r, f)).st_mode | stat.S_IWRITE) for r, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE) if os.path.exists(p) else None"
        command = f'Start-Process python -ArgumentList "-c \\"{script}\\"" -Verb RunAs -WindowStyle Hidden'
        try:
            subprocess.run(['powershell', '-Command', command], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.feedback_manager.update_status(tr('status.permission_change_failed'), UI_COLORS['status_error'])
            return False

    def _cleanup_direct_launch_files(self):
        self.game_launcher._cleanup_direct_launch_files()

    def _launch_game_with_all_mods(self):
        self.game_launcher.launch_game_with_all_mods(execute_plugin_hooks=self._execute_plugin_hooks, restore_window_callback=self.restore_window_signal.emit)

    def _execute_plugin_hooks(self, hook_name: str):
        for plugin in self.app_state.plugins:
            hook_func = plugin.get(hook_name)
            if callable(hook_func):
                try:
                    logging.info(f"Executing {hook_name} hook for plugin: {plugin.get('name_key')}")
                    hook_func(self)
                except Exception as e:
                    logging.error(f"Error executing {hook_name} hook for plugin '{plugin.get('name_key')}': {e}", exc_info=True)

    def _on_game_launch_finished(self):
        self.restore_window_signal.emit()

    def _hide_window_for_game(self):
        try:
            self._stop_background_music()
        except Exception:
            pass
        self.app_state.game_is_running = True
        self.hide()

    def _restore_window_after_game(self):
        self.app_state.game_is_running = False
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.saves_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._update_action_button_state()
        QTimer.singleShot(100, self.updateGeometry)
        if hasattr(self, '_update_installed_mods_display'):
            self._update_installed_mods_display()
        if hasattr(self, '_update_mod_display'):
            self._update_mod_display()
        self._maybe_start_background_music()
        self._show_pending_dialogs()
        self._execute_plugin_hooks('on_after_game_exit')

    def _show_pending_dialogs(self):
        if not self.app_state.pending_dialogs:
            return
        pending = self.app_state.pending_dialogs.copy()
        self.app_state.pending_dialogs.clear()
        for dialog_type, dialog_data in pending:
            if dialog_type == 'update':
                self._prompt_for_update(dialog_data)

    def _force_ui_update_after_restore(self):
        if hasattr(self, '_update_installed_mods_display'):
            self._update_installed_mods_display()
        if hasattr(self, '_update_mod_display'):
            self._update_mod_display()
        self.updateGeometry()

    def _on_progress_update(self, value: int):
        self.progress_bar.setValue(value)
        if value > 0 and (not self.progress_bar.isVisible()):
            self.progress_bar.setVisible(True)

    def _update_status(self, message: str, color: str = 'white'):
        if not self.is_shortcut_launch:
            from config.constants import UI_COLORS
            actual_color = UI_COLORS.get(color, color)
            self.status_label.setText(message)
            self.status_label.setStyleSheet(f'color: {actual_color};')

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
        if thr and (not thr.isRunning()):
            try:
                thr.deleteLater()
            except RuntimeError:
                pass
            self.presence_thread = None
            self.presence_worker = None
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
            self._last_online_count = count
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=count)}")

    def _on_toggle_custom_executable(self):
        use_custom = self.use_custom_executable_checkbox.isChecked()
        self.settings_manager.on_toggle_custom_executable(use_custom)
        self._update_custom_executable_ui()

    def _select_custom_executable_file(self):
        filepath = self.settings_manager.select_custom_executable_file()
        if filepath:
            self._update_custom_executable_ui()

    def _update_custom_executable_ui(self):
        use_custom = self.app_state.local_config.get('use_custom_executable', False)
        path = self.app_state.local_config.get(self.app_state.game_mode.get_custom_exec_config_key(), '')
        self.custom_exe_frame.setVisible(use_custom and self.use_custom_executable_checkbox.isEnabled())
        if self.custom_exe_frame.isVisible():
            self.custom_executable_path_label.setText(tr('ui.currently_selected', filename=os.path.basename(path)) if path else tr('ui.file_not_selected'))

    def _on_toggle_steam_launch(self, state=None):
        is_steam_launch = self.launch_via_steam_checkbox.isChecked()
        self.settings_manager.on_toggle_steam_launch(is_steam_launch)
        self._update_custom_executable_ui()

    def _on_language_changed(self):
        selected_data = self.language_combo.currentData()
        if not selected_data:
            return
        self.settings_manager.on_language_changed(selected_data)

    def _on_language_changed_by_manager(self, language_code: str):
        self._retranslate_ui()

    def _on_settings_changed(self):
        pass

    def _on_slots_updated(self):
        self._refresh_save_slots()

    def _on_theme_changed_by_manager(self):
        self.apply_theme()

    def _on_toggle_beta_updates(self):
        beta_enabled = self.beta_updates_checkbox.isChecked()
        self.settings_manager.on_toggle_beta_updates(beta_enabled)
        self.update_checker.check_for_updates()

    def _on_toggle_fullscreen(self):
        fullscreen_enabled = self.fullscreen_checkbox.isChecked()
        self.settings_manager.on_toggle_fullscreen(fullscreen_enabled)
        if fullscreen_enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def _retranslate_texts(self):
        self.color_config = {'background': tr('ui.background_color'), 'button': tr('ui.elements_color'), 'border': tr('ui.border_color'), 'button_hover': tr('ui.hover_color'), 'text': tr('ui.main_text_color'), 'version_text': tr('ui.secondary_text_color')}
        self.settings_button.setText(tr('ui.back_button') if self.app_state.is_settings_view or self.app_state.is_save_manager_view else tr('ui.settings_title'))
        self.online_label.setToolTip(tr('tooltips.online_counter'))
        self.top_refresh_button.setToolTip(tr('ui.update_mod_list'))
        self.telegram_button.setText(tr('buttons.telegram'))
        self.beta_updates_checkbox.setToolTip(tr('tooltips.beta_updates'))
        self.discord_button.setText(tr('buttons.discord'))
        self.shortcut_button.setText(tr('buttons.shortcut'))
        self.saves_button.setText(tr('ui.saves_button'))
        self.main_tab_widget.setTabText(0, tr('ui.search_tab'))
        self.main_tab_widget.setTabText(1, tr('ui.library_tab'))
        self.main_tab_widget.setTabText(2, tr('ui.mod_management'))
        self.main_tab_widget.setTabText(3, tr('ui.patching_tab'))
        self.sort_combo.setItemText(0, tr('ui.sort_by_downloads'))
        self.sort_combo.setItemText(1, tr('ui.sort_by_update_date'))
        self.sort_combo.setItemText(2, tr('ui.sort_by_creation_date'))
        self.modgame_combo.setItemText(0, tr('dropdowns.all_mods'))
        self.modgame_combo.setItemText(1, tr('dropdowns.filter_deltarune'))
        self.modgame_combo.setItemText(2, tr('dropdowns.filter_deltarunedemo'))
        self.modgame_combo.setItemText(3, tr('dropdowns.filter_undertale'))
        self.tags_label.setText(tr('ui.tags_label'))
        self.tag_translation.setText(tr('tags.translation'))
        self.tag_customization.setText(tr('tags.customization'))
        self.tag_gameplay.setText(tr('tags.gameplay'))
        self.tag_other.setText(tr('tags.other'))
        self.search_button.setToolTip(tr('tooltips.search'))
        self.prev_page_btn.setText(tr('ui.prev_page'))
        self.next_page_btn.setText(tr('ui.next_page'))
        self.chapter_mode_checkbox.setText(tr('ui.chapter_mode'))
        self.full_install_checkbox.setText(tr('ui.full_install'))
        self.full_install_checkbox.setToolTip(self._full_install_tooltip())
        self.settings_title_label.setText(f"<h1>{tr('ui.settings_title')}</h1>")
        self.language_label.setText(tr('ui.language_label'))
        self.beta_updates_checkbox.setText(tr('ui.beta_updates'))
        self.fullscreen_checkbox.setText(tr('ui.fullscreen'))
        self.fullscreen_checkbox.setToolTip(tr('tooltips.fullscreen_tooltip'))
        self.launch_via_steam_checkbox.setText(tr('ui.steam_launch'))
        self.launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>')
        self.use_custom_executable_checkbox.setText(tr('ui.custom_executable'))
        self.use_custom_executable_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.custom_exe') + '</body></html>')
        self.select_custom_executable_button.setText(tr('buttons.select_file'))
        self._update_change_path_button_text()
        self.change_mods_dir_button.setText(tr('ui.change_mods_dir'))
        self.change_mods_dir_button.setToolTip(tr('tooltips.change_mods_dir'))
        self.customization_button.setText(tr('ui.launcher_customization'))
        self.reset_button.setText(tr('buttons.reset_settings'))
        self.back_button_cust.setText(tr('ui.back_button'))
        self._update_background_button_state()
        self.background_music_button.setText(self._get_background_music_button_text())
        self.startup_sound_button.setText(self._get_startup_sound_button_text())
        self.disable_background_checkbox.setText(tr('checkboxes.disable_background'))
        self.disable_splash_checkbox.setText(tr('checkboxes.disable_splash'))
        for key in self.color_widgets.keys():
            if key in self.color_labels:
                self.color_labels[key].setText(self.color_config[key])
        self.changelog_button.setText(tr('buttons.changelog_close') if self.app_state.is_changelog_view else tr('buttons.changelog'))
        self.help_button.setText(tr('buttons.help_close') if self.app_state.is_help_view else tr('buttons.help'))

    def _retranslate_ui(self):
        self._suppress_tab_handlers = True
        try:
            current_index = self.main_tab_widget.currentIndex() if hasattr(self, 'main_tab_widget') else -1
            current_widget = None
            current_plugin = None
            try:
                if current_index >= 0:
                    current_widget = self.main_tab_widget.widget(current_index)
                    if isinstance(current_widget, QWidget) and current_index in getattr(self, '_plugin_tab_map', {}):
                        current_plugin = self._plugin_tab_map.get(current_index)
            except Exception:
                pass
            language_code = self.app_state.local_config.get('language', 'en')
            localization_manager.load_language(language_code)
            self._update_qt_translations(language_code)
            self.load_font()
            self._update_plugin_tabs()
            try:
                if hasattr(self, 'main_tab_widget') and current_index >= 0 and (current_index < self.main_tab_widget.count()):
                    self.main_tab_widget.setCurrentIndex(current_index)
                    if current_plugin:
                        w = self.main_tab_widget.widget(current_index)
                        if isinstance(w, QWidget) and w.layout() is None:
                            handler = current_plugin.get('page_init') if callable(current_plugin.get('page_init')) else current_plugin.get('on_tab_open')
                            try:
                                new_widget = handler(self) if callable(handler) else None
                                if isinstance(new_widget, QWidget):
                                    self.main_tab_widget.removeTab(current_index)
                                    self.main_tab_widget.insertTab(current_index, new_widget, tr(current_plugin['name_key']))
                                    self.main_tab_widget.setCurrentIndex(current_index)
                            except Exception:
                                pass
            except Exception:
                pass
            self._retranslate_texts()
            try:
                if hasattr(self, 'hide_library_filters_checkbox'):
                    self.hide_library_filters_checkbox.setText(tr('ui.hide_library_filters'))
                    self.hide_library_filters_checkbox.setToolTip(tr('tooltips.hide_library_filters'))
            except Exception:
                pass
            self.apply_theme()
            try:
                if hasattr(self, 'online_label'):
                    self._update_online_label(getattr(self, '_last_online_count', 0))
            except Exception:
                pass
            self._update_filtered_mods()
            self._update_installed_mods_display()
            self._update_slots_display()
            self._update_pagination_controls()
            if self.app_state.is_save_manager_view:
                self._refresh_save_slots()
            self._update_action_button_state()
            self.update()
        finally:
            self._suppress_tab_handlers = False

    def _check_active_slots_need_updates(self):
        if not self.app_state.all_mods:
            return False
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        if is_demo_mode:
            active_slot_ids = [-10]
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            active_slot_ids = [-20]
        elif not is_chapter_mode:
            active_slot_ids = [-1]
        else:
            active_slot_ids = [0, 1, 2, 3, 4]
        for slot_id in active_slot_ids:
            for slot_frame in self.app_state.slots.values():
                if slot_frame.chapter_id == slot_id and slot_frame.assigned_mod:
                    mod_data = slot_frame.assigned_mod
                    if getattr(mod_data, 'is_local_mod', False):
                        continue
                    if slot_id < 0:
                        needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                    else:
                        needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                    if needs_update:
                        return True
        return False

    def _update_mods_in_active_slots(self):
        if self.app_state.is_installing:
            return
        is_chapter_mode = self.chapter_mode_checkbox.isChecked()
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        if is_demo_mode:
            active_slot_ids = [-10]
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            active_slot_ids = [-20]
        elif not is_chapter_mode:
            active_slot_ids = [-1]
        else:
            active_slot_ids = [0, 1, 2, 3, 4]
        mods_to_update = []
        for slot_id in active_slot_ids:
            for slot_frame in self.app_state.slots.values():
                if slot_frame.chapter_id == slot_id and slot_frame.assigned_mod:
                    mod_data = slot_frame.assigned_mod
                    if getattr(mod_data, 'is_local_mod', False):
                        continue
                    needs_update = any((self.mod_manager.mod_has_files_for_chapter(mod_data, i) and self.mod_manager.get_mod_status(mod_data, i) == 'update' for i in range(5)))
                    if needs_update and mod_data not in mods_to_update:
                        mods_to_update.append(mod_data)
        if mods_to_update:
            self.pending_updates = mods_to_update[1:] if len(mods_to_update) > 1 else []
            self._update_mod(mods_to_update[0])

    def _refresh_slots_content(self):
        self._refresh_all_slot_status_displays()

    def _on_manage_mods_click(self):
        self._show_main_mod_management_dialog()

    def _on_xdelta_patch_click(self):
        try:
            dialog = XdeltaDialog(self)
            dialog.exec()
        except Exception as e:
            self.feedback_manager.show_error('errors.error', tr('errors.patching_window_failed', error=str(e)))

    def _show_main_mod_management_dialog(self):
        has_internet = check_internet_connection()
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
        create_button.clicked.connect(lambda: self._on_create_mod_choice(dialog, has_internet))
        edit_button = QPushButton(tr('ui.edit_mod'))
        edit_button.setFixedSize(180, 50)
        edit_button.clicked.connect(lambda: self._on_edit_mod_choice(dialog, has_internet))
        buttons_layout.addWidget(create_button)
        buttons_layout.addWidget(edit_button)
        layout.addLayout(buttons_layout)
        layout.addSpacing(30)
        cancel_button = QPushButton(tr('ui.cancel_button'))
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button)
        dialog.exec()

    def _on_create_mod_choice(self, parent_dialog, has_internet):
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
        public_button.setEnabled(has_internet)
        if not has_internet:
            public_button.setToolTip(tr('errors.internet_required'))
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

    def _on_edit_mod_choice(self, parent_dialog, has_internet):
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
        public_button.setEnabled(has_internet)
        if not has_internet:
            public_button.setToolTip(tr('errors.internet_required'))
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
            self.feedback_manager.show_error('errors.no_internet', tr('errors.public_mod_internet'))
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
            self.feedback_manager.show_error('errors.no_internet', tr('errors.edit_mod_internet'))
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
            self.feedback_manager.show_error('errors.error', tr('errors.key_check_failed', error=str(e)))
            return
        if not mod_data:
            self.feedback_manager.show_warning('errors.mod_not_found', tr('errors.secret_key_invalid'))
            return
        if mod_data.get('ban_status', False):
            ban_reason = mod_data.get('ban_reason', tr('defaults.not_specified_fem'))
            self.feedback_manager.show_error('dialogs.mod_blocked_title', tr('dialogs.mod_blocked_message', ban_reason=ban_reason, error_message=tr('dialogs.error_occurred')))
            return
        if found_in_pending:
            result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'dialogs.mod_on_moderation', 'dialogs.mod_on_moderation_message', [('buttons.withdraw_request', QMessageBox.ButtonRole.DestructiveRole, 'withdraw'), ('buttons.ok', QMessageBox.ButtonRole.AcceptRole, 'ok')], 'ok')
            if result == 'withdraw':
                try:
                    from config.constants import CLOUD_FUNCTIONS_BASE_URL
                    requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingMod', json={'hashedKey': hashed_key}, timeout=10)
                    self.feedback_manager.show_info('dialogs.request_withdrawn', tr('dialogs.withdrawal_success'))
                except Exception as e:
                    self.feedback_manager.show_error('errors.error', tr('errors.request_revoke_failed', error=str(e)))
            return
        try:
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            pending_changes_response = requests.get(f'{CLOUD_FUNCTIONS_BASE_URL}/getPendingChangeData?modId={hashed_key}', timeout=10)
            if pending_changes_response.status_code == 200 and pending_changes_response.json():
                result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'dialogs.changes_under_review', 'dialogs.request_pending', [('buttons.withdraw_request', QMessageBox.ButtonRole.DestructiveRole, 'withdraw')])
                if result == 'withdraw':
                    try:
                        from config.constants import CLOUD_FUNCTIONS_BASE_URL
                        delete_response = requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/withdrawPendingChange', json={'hashedKey': hashed_key}, timeout=10)
                        delete_response.raise_for_status()
                        self.feedback_manager.show_info('dialogs.request_withdrawn', tr('dialogs.withdrawal_success'))
                    except requests.RequestException as e:
                        self.feedback_manager.show_error('errors.error', tr('errors.request_revoke_failed', error=str(e)))
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
        if os.path.exists(self.app_state.mods_dir):
            for folder_name in os.listdir(self.app_state.mods_dir):
                folder_path = os.path.join(self.app_state.mods_dir, folder_name)
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
            self.feedback_manager.show_info('dialogs.no_local_mods_title', tr('dialogs.no_local_mods_message'))
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
            self.feedback_manager.show_warning('errors.error', tr('errors.selected_mod_not_found'))
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
        if hasattr(self, 'game_launcher') and hasattr(self.game_launcher, 'monitor_thread'):
            self._safe_stop_thread(self.game_launcher.monitor_thread)
        for attr in ('install_thread', 'full_install_thread', '_bg_loader'):
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
        self.app_state.local_config = self._read_json(self.app_state.config_path) or {}
        mods_metadata = self.mod_manager._read_metadata()
        updated = False
        if not os.path.exists(self.app_state.mods_dir):
            return
        for folder_name in os.listdir(self.app_state.mods_dir):
            folder_path = os.path.join(self.app_state.mods_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, 'config.json')
            if not os.path.exists(config_path):
                continue
            try:
                config_data = self._read_json(config_path)
                if not config_data or not isinstance(config_data, dict):
                    continue
                mod_key = config_data.get('mod_key')
                if not mod_key:
                    continue
                if 'installed_date' in config_data or 'is_available_on_server' in config_data:
                    if mod_key not in mods_metadata:
                        mods_metadata[mod_key] = {}
                    if 'installed_date' in config_data:
                        mods_metadata[mod_key]['installed_date'] = config_data.pop('installed_date')
                    if 'is_available_on_server' in config_data:
                        mods_metadata[mod_key]['is_available_on_server'] = config_data.pop('is_available_on_server')
                    self._write_json(config_path, config_data)
                    updated = True
            except Exception as e:
                logging.warning(f'Failed to migrate metadata for mod in {folder_name}: {e}')
        if updated:
            self.mod_manager._write_metadata(mods_metadata)
        self.app_state.local_config['metadata_migrated_v2'] = True
        self._write_local_config()

    def _migrate_config_if_needed(self):
        self.settings_manager.migrate_config_if_needed()

    def _write_local_config(self):
        self.settings_manager.write_local_config()

    def _write_json(self, path: str, data):
        self.settings_manager.write_json(path, data)

    def _read_json(self, path: str):
        return self.settings_manager.read_json(path)

    def _init_localization(self):
        saved_language = self.app_state.local_config.get('language')
        if not saved_language or saved_language not in localization_manager.get_available_languages():
            saved_language = localization_manager.detect_system_language()
            self.app_state.local_config['language'] = saved_language
            self._write_json(self.app_state.config_path, self.app_state.local_config)
        if not localization_manager.load_language(saved_language):
            saved_language = localization_manager.detect_system_language()
            localization_manager.load_language(saved_language)
            self.app_state.local_config['language'] = saved_language
            self._write_local_config()
        self._update_qt_translations(saved_language)

    def _update_qt_translations(self, language_code):
        from PyQt6.QtCore import QLibraryInfo, QTranslator
        qt_translation = localization_manager.get_qt_translation_name(language_code)
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
        if not self.is_shortcut_launch:
            self.feedback_manager.update_status(tr('errors.executable_not_found_deltarune'), UI_COLORS['status_error'])
        return None

    def _gather_shortcut_settings(self) -> Optional[Dict[str, Any]]:
        current_path = self._get_current_game_path()
        if not current_path:
            return None
        is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
        settings = {'launcher_version': LAUNCHER_VERSION, 'game_path': self.app_state.game_path, 'demo_game_path': self.app_state.demo_game_path, 'is_demo_mode': is_demo_mode, 'is_chapter_mode': is_chapter_mode, 'is_undertale_mode': is_undertale_mode, 'launch_via_steam': self.launch_via_steam_checkbox.isChecked(), 'use_custom_executable': self.use_custom_executable_checkbox.isChecked(), 'custom_executable_path': self.app_state.local_config.get(FullGameMode().get_custom_exec_config_key(), ''), 'demo_custom_executable_path': self.app_state.local_config.get(DemoGameMode().get_custom_exec_config_key(), ''), 'direct_launch_slot_id': self.app_state.local_config.get('direct_launch_slot_id', -1), 'mods': {}}
        if is_demo_mode:
            demo_mod_key = None
            try:
                demo_slot = self.app_state.slots.get(-10) if hasattr(self.app_state, 'slots') else None
                if demo_slot and getattr(demo_slot, 'assigned_mod', None):
                    demo_mod_key = getattr(demo_slot.assigned_mod, 'key', None) or getattr(demo_slot.assigned_mod, 'mod_key', None)
            except Exception:
                demo_mod_key = None
            settings['mods']['demo'] = demo_mod_key
        elif is_undertale_mode:
            undertale_mod_key = None
            try:
                undertale_slot = self.app_state.slots.get(-20) if hasattr(self.app_state, 'slots') else None
                if undertale_slot and getattr(undertale_slot, 'assigned_mod', None):
                    undertale_mod_key = getattr(undertale_slot.assigned_mod, 'key', None) or getattr(undertale_slot.assigned_mod, 'mod_key', None)
            except Exception:
                undertale_mod_key = None
            settings['mods']['undertale'] = undertale_mod_key
        elif is_chapter_mode:
            for slot_frame in self.app_state.slots.values():
                chapter_id = slot_frame.chapter_id
                if chapter_id >= 0:
                    mod_key = None
                    if slot_frame.assigned_mod:
                        mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None)
                    settings['mods'][str(chapter_id)] = mod_key
        else:
            universal_mod_key = None
            try:
                universal_slot = self.app_state.slots.get(-1) if hasattr(self.app_state, 'slots') else None
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
            is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
            is_undertale_mode = isinstance(self.app_state.game_mode, UndertaleGameMode)
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
        mod_config = self.mod_manager.get_mod_config(mod_key)
        if not mod_config:
            raise Exception(tr('errors.mod_not_found_by_key', mod_key=mod_key))

    def _apply_mod_by_key(self, mod_key: str):
        mod_config = self.mod_manager.get_mod_config(mod_key)
        if not mod_config:
            raise Exception(tr('errors.mod_not_found_by_key', mod_key=mod_key))
        mod_folder = os.path.join(self.app_state.mods_dir, mod_key)
        if not os.path.exists(mod_folder):
            mod_folder = os.path.join(self.app_state.mods_dir, mod_config.get('name', ''))
            if not os.path.exists(mod_folder):
                raise Exception(tr('errors.mod_files_not_found_by_key', mod_key=mod_key))

    def _launch_game_from_shortcut(self, launch_via_steam=False, use_custom_executable=False, custom_exec_path='', demo_custom_exec_path='', direct_launch_slot_id=-1):
        try:
            is_demo_mode = isinstance(self.app_state.game_mode, DemoGameMode)
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
                if isinstance(self.app_state.game_mode, UndertaleGameMode):
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
                steam_app_id = self.app_state.game_mode.steam_id
                webbrowser.open(f'steam://run/{steam_app_id}')
            else:
                args = []
                if direct_launch_slot_id >= 0:
                    if direct_launch_slot_id == 1:
                        args.extend(['-chapter', '1'])
                    elif direct_launch_slot_id == 2:
                        args.extend(['-chapter', '2'])
                command = [executable_path] + args
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
                icon_path = resource_path('resources/icons/icon.ico')
                content = f'[Desktop Entry]\nVersion=1.0\nType=Application\nName=Deltarune (DELTAHUB)\nExec="{launcher_executable_path}" {args}\nIcon={icon_path}\nTerminal=false\n'
            with open(shortcut_path, 'w', encoding='utf-8') as f:
                f.write(content)
            if system in ['Linux', 'Darwin']:
                os.chmod(shortcut_path, 493)
            self.feedback_manager.show_info('dialogs.success', tr('dialogs.shortcut_created_successfully', path=shortcut_path))
        except Exception as e:
            self.feedback_manager.update_status(tr('status.shortcut_creation_error', error=str(e)), UI_COLORS['status_error'])
            self.feedback_manager.show_error('errors.error', tr('errors.shortcut_creation_failed', error=str(e)))

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
            self.feedback_manager.update_status(tr('errors.chapter_folder_search_error', error=str(e)), UI_COLORS['status_error'])
            return None

    def _has_mods_with_data_files(self, selections: Dict[int, str]) -> bool:
        for ui_index, mod_key in selections.items():
            if mod_key == 'no_change':
                continue
            mod = next((m for m in self.app_state.all_mods if m.key == mod_key), None)
            if not mod:
                continue
            chapter_id = self.app_state.game_mode.get_chapter_id(ui_index)
            if getattr(mod, 'is_local_mod', False):
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

    def _find_and_validate_game_path(self, selections: Optional[Dict[int, str]] = None, is_initial: bool = False):
        path_from_config = self._get_current_game_path()
        skip_data_check = bool(selections and self._has_mods_with_data_files(selections))
        if isinstance(self.app_state.game_mode, DemoGameMode):
            game_type = 'deltarune'
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            game_type = 'undertale'
        else:
            game_type = 'deltarune'
        if is_valid_game_path(path_from_config, skip_data_check, game_type):
            self.feedback_manager.update_status(tr('status.game_path', path=path_from_config), UI_COLORS['status_info'])
            return True
        self.feedback_manager.update_status(tr('status.autodetecting_path'), UI_COLORS['status_info'])
        if isinstance(self.app_state.game_mode, DemoGameMode):
            game_name = 'DELTARUNEdemo'
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            game_name = 'UNDERTALE'
        else:
            game_name = 'DELTARUNE'
        autodetected_path = autodetect_path(game_name)
        if autodetected_path and is_valid_game_path(autodetected_path, skip_data_check, game_type):
            self.app_state.game_mode.set_game_path(self.app_state.local_config, autodetected_path)
            self.feedback_manager.update_status(tr('status.game_folder_found', path=autodetected_path), UI_COLORS['status_success'])
            self._write_local_config()
            return True
        if is_initial:
            self.feedback_manager.update_status(tr('status.no_game_path'), UI_COLORS['status_error'])
        return False

    def _init_session(self):
        try:
            import requests
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            requests.post(f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat', json={'sessionId': self.session_id}, timeout=5)
        except Exception:
            pass

    def _prompt_for_game_path(self, is_initial=False):
        result = self.settings_manager.prompt_for_game_path(is_initial)
        if result:
            self._update_action_button_state()
        if is_initial and (not result):
            self._start_background_music()
            self.initialization_finished.emit()

    def _handle_first_launch_settings(self):
        self.app_state.local_config['first_launch_splash_shown'] = True
        self.app_state.local_config['disable_splash'] = True
        self._write_local_config()
        try:
            self.initialization_finished.disconnect(self._handle_first_launch_settings)
        except TypeError:
            pass

    def _on_theme_button_click(self):
        result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'buttons.theme_management', 'dialogs.theme_choice', [('buttons.import', QMessageBox.ButtonRole.AcceptRole, 'import'), ('buttons.export', QMessageBox.ButtonRole.AcceptRole, 'export')])
        if result == 'import':
            self._import_theme()
        elif result == 'export':
            self._export_theme()

    def _export_theme(self):
        self.settings_manager.export_theme()

    def _import_theme(self):
        self.settings_manager.import_theme()
        self._load_custom_style_settings()
        self.disable_background_checkbox.setChecked(self.app_state.local_config.get('background_disabled', False))
        self.disable_splash_checkbox.setChecked(self.app_state.local_config.get('disable_splash', False))
        self.background_music_button.setText(self._get_background_music_button_text())
        self.startup_sound_button.setText(self._get_startup_sound_button_text())
        self._stop_background_music()
        self._maybe_start_background_music()
        self.app_state.local_config['first_launch_splash_shown'] = True
        self.app_state.local_config['disable_splash'] = True
        self._write_local_config()
        try:
            self.initialization_finished.disconnect(self._handle_first_launch_settings)
        except TypeError:
            pass

    def _save_slots_state(self):
        if not hasattr(self.app_state, 'slots'):
            return
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        config_key = self._get_slots_config_key(self.app_state.game_mode, is_chapter_mode)
        slots_data = {}
        for slot_id, slot_frame in self.app_state.slots.items():
            if slot_frame.assigned_mod:
                mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if mod_key:
                    slots_data[str(slot_id)] = {'mod_key': mod_key, 'mod_name': slot_frame.assigned_mod.name}
        self.app_state.local_config[config_key] = slots_data
        self._write_local_config()

    def _load_slots_state(self, mode=None):
        is_chapter_mode = hasattr(self, 'chapter_mode_checkbox') and self.chapter_mode_checkbox.isChecked()
        config_key = self._get_slots_config_key(self.app_state.game_mode, is_chapter_mode)
        slots_data = self.app_state.local_config.get(config_key, {})
        for slot in self.app_state.slots.values():
            if slot.assigned_mod:
                self._remove_mod_from_slot(slot, slot.assigned_mod)
        if isinstance(self.app_state.game_mode, DemoGameMode):
            config_key = 'saved_slots_deltarunedemo'
        elif isinstance(self.app_state.game_mode, UndertaleGameMode):
            config_key = 'saved_slots_undertale'
        else:
            is_chapter_mode = getattr(self, 'chapter_mode_checkbox', None) and self.chapter_mode_checkbox.isChecked()
            config_key = 'saved_slots_deltarune_chapter' if is_chapter_mode else 'saved_slots_deltarune'
        slots_data = self.app_state.local_config.get(config_key, {})
        if not slots_data:
            return
        for slot_id, slot_data in list(slots_data.items()):
            try:
                numeric_slot_id = int(slot_id)
            except ValueError:
                continue
            is_chapter_mode = getattr(self, 'chapter_mode_checkbox', None) and self.chapter_mode_checkbox.isChecked()
            if isinstance(self.app_state.game_mode, DemoGameMode):
                if numeric_slot_id != -10:
                    continue
            elif isinstance(self.app_state.game_mode, UndertaleGameMode):
                if numeric_slot_id != -20:
                    continue
            elif is_chapter_mode:
                if numeric_slot_id not in [0, 1, 2, 3, 4]:
                    continue
            elif numeric_slot_id != -1:
                continue
            if numeric_slot_id not in self.app_state.slots:
                continue
            slot_frame = self.app_state.slots[numeric_slot_id]
            mod_key = slot_data.get('mod_key')
            if not mod_key:
                continue
            mod_data = None
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                for mod in self.app_state.all_mods:
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
            if not mod_data:
                mod_config = self.mod_manager.get_mod_config(mod_key)
                if mod_config:
                    mod_data = self._create_mod_object_from_info(mod_config)
            if mod_data:
                current_slot = self._find_mod_in_slots(mod_data)
                if not current_slot:
                    self._assign_mod_to_slot(slot_frame, mod_data, save_state=False)
            elif slot_id in slots_data:
                del slots_data[slot_id]
        if slots_data != self.app_state.local_config.get(config_key, {}):
            self.app_state.local_config[config_key] = slots_data
            self._write_json(self.app_state.config_path, self.app_state.local_config)
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
        for slot_frame in self.app_state.slots.values():
            if slot_frame.chapter_id == chapter_id and slot_frame.assigned_mod:
                assigned_mod_key = getattr(slot_frame.assigned_mod, 'key', None) or getattr(slot_frame.assigned_mod, 'mod_key', None) or getattr(slot_frame.assigned_mod, 'name', None)
                if assigned_mod_key == mod_key:
                    return True
        return False
