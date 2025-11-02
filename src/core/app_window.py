import base64
import json
import os
import platform
import shutil
import threading
import uuid
import subprocess
import webbrowser
import argparse
from typing import Callable, Optional
import logging
import requests
from PyQt6.QtCore import QTranslator, Qt, QEvent, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QFrame, QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QInputDialog, QColorDialog
from managers.localization_manager import localization_manager, tr
from models.game_modes import FullGameMode, DemoGameMode, UndertaleGameMode
from config.constants import UI_COLORS, SOCIAL_LINKS, ARCH, ONLINE_UPDATE_INTERVAL, INITIALIZATION_TIMEOUT, LEGACY_CLEANUP_DELAY, THREAD_WAIT_TIMEOUT
from utils.game_utils import is_game_running
from utils.path_utils import get_user_data_root, resource_path, get_launcher_dir, get_legacy_ylauncher_path, get_user_plugins_dir
from utils.network_utils import check_internet_connection
from managers.mod_manager import parse_mod_date
from workers.background_workers import PresenceWorker, FetchChangelogThread, FetchHelpContentThread
from ui.common.styling import clear_layout_widgets, show_empty_message_in_layout
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
from ui.widgets.mod.installed_mod_widget import InstalledModWidget
from controllers.mod_operations_controller import ModOperationsController
from controllers.library_display_controller import LibraryDisplayController
from controllers.search_display_controller import SearchDisplayController
from controllers.save_ui_controller import SaveUiController
from controllers.settings_ui_controller import SettingsUiController
from controllers.theme_controller import ThemeController
from controllers.game_launch_controller import GameLaunchController
from ui.dialogs.xdelta import XdeltaDialog
from ui.dialogs.mod_editor import ModEditorDialog
from ui.common.feedback import FeedbackManager
from core.startup import SingleInstanceServer, ShortcutLaunchError
from core.app_state import AppState
from managers.mod_manager import ModManager
from managers.launch_manager import GameLauncher
from managers.updatecheck_manager import UpdateChecker
from managers.settings_manager import SettingsManager
from managers.save_manager import SaveManager
from ui.main_window.search_tab_builder import SearchTabBuilder
from ui.main_window.library_tab_builder import LibraryTabBuilder
from ui.main_window.settings_view_builder import SettingsViewBuilder
from ui.main_window.save_manager_view_builder import SaveManagerViewBuilder
from managers.plugin_manager import PluginManager
from managers.customization_manager import CustomizationManager
from managers.slot_manager import SlotManager
from managers.shortcut_manager import ShortcutManager
_translator = QTranslator()
_lock_file = None


class AppWindow(QWidget):
    update_status_signal = pyqtSignal(str, str)
    set_progress_signal = pyqtSignal(int)
    show_update_prompt = pyqtSignal(dict)
    initialization_finished = pyqtSignal()
    ui_ready = pyqtSignal()
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
        os.makedirs(self.app_state.config_dir, exist_ok=True)
        os.makedirs(self.app_state.mods_dir, exist_ok=True)
        os.makedirs(self.app_state.plugins_dir, exist_ok=True)
        self.lang_manager = localization_manager
        self.app_state.config_path = os.path.join(self.app_state.config_dir, 'config.json')
        self.feedback_manager = FeedbackManager(self)
        self.feedback_manager.app_state = self.app_state
        self.settings_manager = SettingsManager(self.app_state, self.feedback_manager, self.lang_manager, self)
        self.save_manager = SaveManager(self.app_state, self.feedback_manager, self.settings_manager, self)
        self.save_manager.slots_updated.connect(self._refresh_save_slots)
        self.save_manager.status_changed.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
        self._pending_install_url = initial_url
        self.dialog_parent = parent_for_dialogs or self
        self.session_id = uuid.uuid4().hex
        self.presence_thread = QThread(self)
        self.presence_worker = PresenceWorker(self.session_id)
        self.presence_worker.moveToThread(self.presence_thread)
        self.presence_worker.update_online_count.connect(self._update_online_label)
        self.presence_thread.start()
        self._online_timer = QTimer(self)
        self._online_timer.timeout.connect(self.presence_worker.run)
        self._online_timer.start(ONLINE_UPDATE_INTERVAL)
        QTimer.singleShot(0, self.presence_worker.run)
        self.setWindowTitle('DELTAHUB')
        self._supports_volume = platform.system() == 'Windows'
        self._initial_size = None
        self.app_state.local_config = self.settings_manager.read_json(self.app_state.config_path) or {}
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
        self.settings_manager.language_changed.connect(lambda _: self._retranslate_ui())
        self.settings_manager.theme_changed.connect(self.apply_theme)
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
        self.game_launcher.game_launch_finished.connect(self.restore_window_signal.emit)
        self.game_launcher.recover_previous_session()
        self.update_checker = UpdateChecker(self.app_state, self.feedback_manager, self)
        self.update_checker.update_available.connect(self._handle_update_info)
        self.update_checker.status_changed.connect(self.update_status_signal.emit)
        self.update_checker.progress_updated.connect(self.set_progress_signal.emit)
        self.update_checker.update_finished.connect(self._on_update_cleanup)
        self.update_checker.update_error.connect(lambda msg: self.feedback_manager.show_error('errors.error', msg))
        self.update_checker.quit_requested.connect(QApplication.quit)
        self.plugin_manager = PluginManager(self.app_state, self)
        self.customization_manager = CustomizationManager(self.app_state, self)
        self.slot_manager = SlotManager(self.app_state, self.mod_manager, self.feedback_manager, self.settings_manager, self)
        self.slot_manager.slots_updated.connect(self._on_slot_manager_slots_updated)
        self.slot_manager.slot_state_changed.connect(lambda slot_id: self._refresh_slot_status_display(self.app_state.slots.get(slot_id)))
        self.slot_manager.action_button_update_needed.connect(self._update_action_button_state)
        self.slot_manager.mod_widgets_update_needed.connect(self._update_mod_widgets_slot_status)
        self.shortcut_manager = ShortcutManager(self.app_state, self.feedback_manager, self.mod_manager, self)
        self.shortcut_manager.shortcut_created.connect(lambda path: self.feedback_manager.update_status(tr('status.shortcut_created', path=path), UI_COLORS['status_success']))
        self.shortcut_manager.status_changed.connect(self.feedback_manager.update_status)
        self.mod_ops = ModOperationsController(self)
        self.library_display = LibraryDisplayController(self)
        self.search_display = SearchDisplayController(self)
        self.save_ui = SaveUiController(self)
        self.settings_ui = SettingsUiController(self)
        self.theme = ThemeController(self)
        self.game_launch = GameLaunchController(self)
        if self.is_shortcut_launch:
            self._shortcut_launch(args)
            return
        self.init_ui()
        self.custom_font_family = localization_manager.load_font()
        QTimer.singleShot(0, lambda: self.ui_ready.emit())
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
        QTimer.singleShot(LEGACY_CLEANUP_DELAY, self._maybe_run_legacy_cleanup)
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(INITIALIZATION_TIMEOUT)
        self.settings_manager.load_window_geometry(self)
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
            logging.error(f'Shortcut settings read error: {e}')
            raise ShortcutLaunchError('Failed to read shortcut settings')
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
                logging.error('Game files not found for launch')
                raise ShortcutLaunchError('Game files not found for launch')
            mods_settings = settings.get('mods', {})
            if not mods_settings:
                mods_settings = settings.get('selections', {})
            self.shortcut_manager.apply_shortcut_mods(mods_settings)
            self.shortcut_manager.launch_game_from_shortcut(launch_via_steam=launch_via_steam, use_custom_executable=use_custom_executable, custom_exec_path=custom_exec_path, demo_custom_exec_path=demo_custom_exec_path, direct_launch_slot_id=direct_launch_slot_id)
        except Exception as e:
            logging.error(f'Launch error: {e}')
            raise ShortcutLaunchError(str(e) or 'Shortcut launch failed')

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
        self.online_label = QLabel(tr('status.online_count', count='?'))
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
        self.customization_manager.load_launcher_icon(self.launcher_icon_label)
        self.bottom_widget = QFrame()
        self.bottom_widget.setObjectName('bottom_widget')
        self.bottom_frame = QVBoxLayout(self.bottom_widget)
        self.status_label = QLabel(tr('ui.initialization'))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.action_frame = QHBoxLayout()
        self.shortcut_button = QPushButton(tr('buttons.shortcut'))
        self.shortcut_button.clicked.connect(self.shortcut_manager.create_shortcut_flow)
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
        self.main_tab_widget = QTabWidget()
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
        self.sort_combo.currentIndexChanged.connect(lambda: self._update_filtered_mods())
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        self.modgame_combo.currentIndexChanged.connect(lambda: (setattr(self, 'current_page', 1), self._update_filtered_mods()))
        self.tag_translation.stateChanged.connect(lambda: (setattr(self, 'current_page', 1), self._update_filtered_mods()))
        self.tag_customization.stateChanged.connect(lambda: (setattr(self, 'current_page', 1), self._update_filtered_mods()))
        self.tag_gameplay.stateChanged.connect(lambda: (setattr(self, 'current_page', 1), self._update_filtered_mods()))
        self.tag_other.stateChanged.connect(lambda: (setattr(self, 'current_page', 1), self._update_filtered_mods()))
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
        self.app_state.is_installing_changed.connect(self._update_action_button_state)
        self.app_state.is_installing_changed.connect(lambda v: self._set_install_buttons_enabled(not v))
        self.app_state.current_mode = 'chapter' if saved_chapter_mode else 'normal'
        self._previous_mode = self.app_state.current_mode
        self.app_state.selected_chapter_id = None
        if saved_game_type == 'deltarunedemo':
            self.app_state.game_mode = DemoGameMode()
        elif saved_game_type == 'undertale':
            self.app_state.game_mode = UndertaleGameMode()
        else:
            self.app_state.game_mode = FullGameMode()
        self.app_state.game_mode_changed.connect(self._on_game_mode_updated_by_state)
        self._update_checkbox_visibility()
        self._update_saves_button_state()
        QTimer.singleShot(500, self._update_installed_mods_display)
        QTimer.singleShot(700, self._update_mod_widgets_slot_status)
        self.slot_manager.update_slots_display(self.active_slots_layout)
        QTimer.singleShot(400, self.slot_manager.load_slots_state)
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
        self.change_mods_dir_button.clicked.connect(self.settings_manager.prompt_for_mods_dir)
        self.customization_button.clicked.connect(lambda: self._switch_settings_page(self.settings_customization_page))
        self.reset_button.clicked.connect(self._on_reset_settings_click)
        self.disable_background_checkbox.stateChanged.connect(self._on_toggle_disable_background)
        self.disable_splash_checkbox.stateChanged.connect(self._on_toggle_disable_splash)
        self.back_button_cust.clicked.connect(self._go_back_to_settings_menu)
        self.change_background_button.clicked.connect(self._on_background_button_click)
        self.background_music_button.setText(self.customization_manager.get_background_music_button_text())
        self.background_music_button.clicked.connect(self._on_background_music_button_click)
        self.startup_sound_button.setText(self.customization_manager.get_startup_sound_button_text())
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
        self.changelog_button.clicked.connect(lambda: self._toggle_settings_view(show_changelog=True))
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
        self.change_save_path_btn.clicked.connect(self.save_manager.prompt_for_save_path)
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
        self.left_col_btn.clicked.connect(lambda: self.save_manager.navigate_collection(-1))
        self.switch_collection_btn.clicked.connect(self.save_manager.toggle_collection_view)
        self.right_col_btn.clicked.connect(lambda: self.save_manager.navigate_collection(1))
        self.rename_collection_btn.clicked.connect(lambda: self.save_manager.rename_current_collection(self.app_state.current_collection_idx))
        self.delete_collection_btn.clicked.connect(lambda: self.save_manager.delete_current_collection(self.app_state.current_collection_idx))
        self.copy_from_main_btn.clicked.connect(lambda: self.save_manager.copy_between_storages(self.save_tabs.currentIndex() + 1, True, self.app_state.selected_slot))
        self.copy_to_main_btn.clicked.connect(lambda: self.save_manager.copy_between_storages(self.save_tabs.currentIndex() + 1, False, self.app_state.selected_slot))
        self.show_btn.clicked.connect(lambda: self.save_manager.action_show_save(*self.app_state.selected_slot) if self.app_state.selected_slot else None)
        self.erase_btn.clicked.connect(lambda: self.save_manager.action_delete_save(*self.app_state.selected_slot) if self.app_state.selected_slot else None)
        self.import_btn.clicked.connect(lambda: self.save_manager.action_import_export(*self.app_state.selected_slot, True) if self.app_state.selected_slot else None)
        self.export_btn.clicked.connect(lambda: self.save_manager.action_import_export(*self.app_state.selected_slot, False) if self.app_state.selected_slot else None)
        self.save_tabs.currentChanged.connect(lambda _: self._on_chapter_tab_changed())
        self.save_manager_widget.installEventFilter(self)
        self._update_slot_highlight()
        self.main_layout.addWidget(self.save_manager_widget)
        self.app_state.current_settings_page = self.settings_menu_page
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.setWindowIcon(QIcon(resource_path('assets/icons/icon.ico')))

    def _on_mods_loaded(self):
        if self.initialization_timer and self.initialization_timer.isActive():
            self.initialization_timer.stop()
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        self.customization_manager.maybe_start_background_music(getattr(self, 'is_shown_to_user', False), self.isVisible())

    def _force_finish_initialization(self):
        if self.app_state.initialization_completed:
            return
        self.app_state.mods_loaded = True
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        if not is_game_running():
            self.customization_manager.maybe_start_background_music(getattr(self, 'is_shown_to_user', False), self.isVisible())

    def _update_saves_button_state(self):
        game_type = self.game_type_combo.currentData()
        self.saves_button.setEnabled(game_type != 'undertale')

    def _on_library_filter_changed(self):
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

    def _on_game_mode_updated_by_state(self, mode_obj):
        try:
            self._update_checkbox_visibility()
            game_type = self.game_type_combo.currentData()
            if game_type != 'deltarune':
                try:
                    self.chapter_mode_checkbox.blockSignals(True)
                    self.chapter_mode_checkbox.setChecked(False)
                finally:
                    self.chapter_mode_checkbox.blockSignals(False)
                if getattr(self.app_state, 'current_mode', 'normal') != 'normal':
                    self.app_state.current_mode = 'normal'
                self.game_type_combo.setEnabled(True)
            self.slot_manager.update_slots_display(self.active_slots_layout)
            self.slot_manager.load_slots_state()
            self._update_installed_mods_display()
            self._update_change_path_button_text()
            self._update_saves_button_state()
        except Exception:
            pass

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
                mod_data = self.mod_manager.create_mod_object_from_info(mod_info, getattr(self.app_state, 'all_mods', None))
                if mod_data:
                    mod_widget = InstalledModWidget(mod_data, is_local, is_available, has_update, parent=self)
                    mod_widget.clicked.connect(self._on_installed_mod_clicked)
                    mod_widget.remove_requested.connect(self._on_installed_mod_remove)
                    mod_widget.use_requested.connect(self._on_installed_mod_use)
                    self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, mod_widget)
            if self.installed_mods_layout.count() <= 1:
                show_empty_message_in_layout(self.installed_mods_layout, tr('ui.empty'), self.app_state.local_config, font_size=18)
            self._update_mod_widgets_slot_status()
            self._update_action_button_state()
            self.installed_mods_container.setUpdatesEnabled(True)
        except Exception:
            if hasattr(self, 'installed_mods_container'):
                self.installed_mods_container.setUpdatesEnabled(True)

    def _get_installed_mods_list(self):
        return self.mod_manager.get_installed_mods_list()

    def _clear_all_installed_mod_selections(self):
        for i in range(self.installed_mods_layout.count() - 1):
            item = self.installed_mods_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, InstalledModWidget):
                    widget.set_selected(False)

    def _sort_filtered_mods(self):
        if not hasattr(self, 'sort_combo') or not self.filtered_mods:
            return
        sort_type = self.sort_combo.currentIndex()
        reverse = not self.sort_ascending
        if sort_type == 0:
            self.filtered_mods.sort(key=lambda mod: getattr(mod, 'downloads', 0), reverse=reverse)
        elif sort_type == 1:
            self.filtered_mods.sort(key=lambda mod: parse_mod_date(getattr(mod, 'last_updated', '')), reverse=reverse)
        elif sort_type == 2:
            self.filtered_mods.sort(key=lambda mod: parse_mod_date(getattr(mod, 'created_date', '')), reverse=reverse)

    def _update_pagination_controls(self):
        if not hasattr(self, 'page_label') or not hasattr(self, 'prev_page_btn') or (not hasattr(self, 'next_page_btn')):
            return
        total_mods = len(self.filtered_mods)
        total_pages = max(1, (total_mods - 1) // self.mods_per_page + 1) if total_mods > 0 else 1
        self.page_label.setText(tr('ui.page_label', current=self.current_page, total=total_pages))
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < total_pages)

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

    def _update_search_mod_plaques(self):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.update_installation_status()

    def _clear_all_mod_selections(self):
        for i in range(self.mod_list_layout.count() - 1):
            item = self.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.set_selected(False)

    def _on_mod_install_finished(self, success, from_gb=False):
        self.app_state.is_installing = False
        self._set_install_buttons_enabled(True)
        self.current_install_thread = None
        self.progress_bar.setVisible(False)
        self._update_action_button_state()

    def _update_change_path_button_text(self):
        self.change_path_button.setText(self.app_state.game_mode.path_change_button_text)

    def _full_install_tooltip(self) -> str:
        if platform.system() == 'Darwin':
            return tr('tooltips.macos_install_unavailable')
        return tr('tooltips.full_install_instructions')

    def eventFilter(self, obj, ev):
        if obj is getattr(self, 'save_manager_widget', None) and ev.type() == QEvent.Type.MouseButtonPress:
            click_pos = ev.pos()
            inside = any((lbl.rect().contains(lbl.mapFrom(self.save_manager_widget, click_pos)) for lbl in self._slot_labels.values()))
            if not inside:
                self._clear_selected_slot()
        return super().eventFilter(obj, ev)

    def _return_from_save_manager(self):
        self.save_ui.return_from_save_manager()

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
        self.help_thread.finished.connect(self.help_text_edit.setMarkdown)
        self.help_thread.start()

    def _disable_direct_launch(self):
        self.settings_manager.disable_direct_launch()
        self.slot_manager.update_all_slots_visual_state()
        self.launch_via_steam_checkbox.setEnabled(True)

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
            from utils.network_utils import get_session
            response = get_session().get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
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
        self.save_manager.manage_steam_deck_saves()
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
        self.settings_manager.migrate_config_if_needed()
        self.use_custom_executable_checkbox.setChecked(self.app_state.local_config.get('use_custom_executable', False))
        self.launch_via_steam_checkbox.setChecked(self.app_state.local_config.get('launch_via_steam', False))
        self._initialize_mutual_exclusions()
        self._on_toggle_steam_launch()
        self.slot_manager.update_all_slots_visual_state()
        self.apply_theme()
        self.mod_manager.load_local_mods()
        self.setEnabled(False)
        self._on_refresh_clicked(is_initial=True)
        self.setEnabled(True)
        self._update_installed_mods_display()
        if not self.game_launcher._find_and_validate_game_path(is_initial=True):
            self.action_button.setEnabled(False)

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

    def _on_install_finished(self, success):
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        if not success:
            try:
                thr = self.current_install_thread
                temp_root = getattr(thr, 'temp_root', None)
                if temp_root and os.path.isdir(temp_root):
                    shutil.rmtree(temp_root, ignore_errors=True)
            except Exception as e:
                logging.debug(f'_on_url_install_finished: temp cleanup failed: {e}')
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

    def _run_as_admin_windows(self, path: str) -> bool:
        script = f"import os, stat; p = r'{path}'; [os.chmod(os.path.join(r, f), os.stat(os.path.join(r, f)).st_mode | stat.S_IWRITE) for r, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE) if os.path.exists(p) else None"
        command = f'Start-Process python -ArgumentList "-c \\"{script}\\"" -Verb RunAs -WindowStyle Hidden'
        try:
            subprocess.run(['powershell', '-Command', command], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.feedback_manager.update_status(tr('status.permission_change_failed'), UI_COLORS['status_error'])
            return False

    def _launch_game_with_all_mods(self):
        self.game_launcher.launch_game_with_all_mods(execute_plugin_hooks=lambda hook_name: self.plugin_manager.execute_hooks(hook_name, self), restore_window_callback=self.restore_window_signal.emit)

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
        if hasattr(self, 'presence_worker') and self.presence_worker:
            self.presence_worker.run()

    def _update_online_label(self, count: int):
        if not self.is_shortcut_launch:
            self._last_online_count = count
            display_count = '?' if count < 0 else count
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=display_count)}")

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

    def _on_slot_manager_slots_updated(self):
        self._refresh_save_slots()
        if self.app_state.current_mode == 'chapter':
            selected_chapter_id = getattr(self.app_state, 'selected_chapter_id', None)
            if selected_chapter_id is not None:
                self._update_installed_mods_for_chapter_mode(selected_chapter_id)

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
        self.modgame_combo.setItemText(1, tr('ui.deltarune'))
        self.modgame_combo.setItemText(2, tr('ui.deltarunedemo'))
        self.modgame_combo.setItemText(3, tr('ui.undertale'))
        self.tags_label.setText(tr('ui.tags_label'))
        self.tag_translation.setText(tr('tags.translation'))
        self.tag_customization.setText(tr('tags.customization'))
        self.tag_gameplay.setText(tr('tags.gameplay'))
        self.tag_other.setText(tr('tags.other'))
        self.search_button.setToolTip(tr('ui.search_placeholder'))
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
        self.customization_button.setText(tr('tags.customization'))
        self.reset_button.setText(tr('buttons.reset_settings'))
        self.back_button_cust.setText(tr('ui.back_button'))
        self._update_background_button_state()
        self.background_music_button.setText(self.customization_manager.get_background_music_button_text())
        self.startup_sound_button.setText(self.customization_manager.get_startup_sound_button_text())
        self.disable_background_checkbox.setText(tr('checkboxes.disable_background'))
        self.disable_splash_checkbox.setText(tr('checkboxes.disable_splash'))
        for key in self.color_widgets.keys():
            if key in self.color_labels:
                self.color_labels[key].setText(self.color_config[key])
        self.changelog_button.setText(tr('buttons.close') if self.app_state.is_changelog_view else tr('buttons.changelog'))
        self.help_button.setText(tr('buttons.close') if self.app_state.is_help_view else tr('buttons.help'))

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
            self.custom_font_family = localization_manager.load_font()
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
            self.slot_manager.update_slots_display(self.active_slots_layout)
            self._update_pagination_controls()
            if self.app_state.is_save_manager_view:
                self._refresh_save_slots()
            self._update_action_button_state()
            self.update()
        finally:
            self._suppress_tab_handlers = False

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
        local_button = QPushButton(tr('tags.local'))
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
        public_button = QPushButton(tr('buttons.public'))
        public_button.setFixedSize(130, 40)
        public_button.clicked.connect(lambda: self._edit_public_mod(dialog))
        public_button.setEnabled(has_internet)
        if not has_internet:
            public_button.setToolTip(tr('errors.internet_required'))
        local_button = QPushButton(tr('tags.local'))
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
        secret_key, ok = QInputDialog.getText(self, tr('dialogs.enter_secret_key'), tr('ui.secret_key_label'), QLineEdit.EchoMode.Password)
        if not ok or not secret_key.strip():
            return
        try:
            mod_data, hashed_key, found_in_pending = self.mod_manager.fetch_mod_data_by_secret(secret_key)
        except Exception as e:
            self.feedback_manager.show_error('errors.error', tr('errors.key_check_failed', error=str(e)))
            return
        if not mod_data:
            self.feedback_manager.show_warning('errors.mod_not_found', tr('errors.secret_key_invalid'))
            return
        if not hashed_key:
            self.feedback_manager.show_warning('errors.mod_not_found', tr('errors.secret_key_invalid'))
            return
        if mod_data.get('ban_status', False):
            ban_reason = mod_data.get('ban_reason', tr('defaults.not_specified'))
            self.feedback_manager.show_error('dialogs.mod_blocked_title', tr('dialogs.mod_blocked_message', ban_reason=ban_reason, error_message=tr('dialogs.error_occurred')))
            return
        if found_in_pending:
            result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'dialogs.mod_on_moderation', 'dialogs.mod_on_moderation_message', [('buttons.withdraw_request', QMessageBox.ButtonRole.DestructiveRole, 'withdraw'), ('buttons.ok', QMessageBox.ButtonRole.AcceptRole, 'ok')], 'ok')
            if result == 'withdraw':
                try:
                    self.mod_manager.withdraw_pending_mod(hashed_key)
                    self.feedback_manager.show_info('dialogs.request_withdrawn', tr('dialogs.withdrawal_success'))
                except Exception as e:
                    self.feedback_manager.show_error('errors.error', tr('errors.request_revoke_failed', error=str(e)))
            return
        if self.mod_manager.has_pending_changes(hashed_key):
            result = self.feedback_manager.ask_custom_question(QMessageBox.Icon.Information, 'dialogs.changes_under_review', 'dialogs.request_pending', [('buttons.withdraw_request', QMessageBox.ButtonRole.DestructiveRole, 'withdraw')])
            if result == 'withdraw':
                try:
                    self.mod_manager.withdraw_pending_change(hashed_key)
                    self.feedback_manager.show_info('dialogs.request_withdrawn', tr('dialogs.withdrawal_success'))
                except Exception as e:
                    self.feedback_manager.show_error('errors.error', tr('errors.request_revoke_failed', error=str(e)))
                    return
            else:
                return
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
        local_mods = self.mod_manager.list_local_mods()
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
        self.customization_manager.stop_background_music()
        self._online_timer.stop()
        if self.is_shortcut_launch:
            super().closeEvent(event)
            return
        self.game_launcher._cleanup_direct_launch_files()
        self.settings_manager.save_window_geometry(self)
        self._stop_presence_thread()
        self._stop_fetch_thread()
        if hasattr(self, 'game_launcher') and hasattr(self.game_launcher, 'monitor_thread'):
            self._safe_stop_thread(self.game_launcher.monitor_thread)
        for attr in ('install_thread', 'full_install_thread', '_bg_loader'):
            self._safe_stop_thread(getattr(self, attr, None))
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'launcher_icon_label') and hasattr(self, 'top_panel_widget'):
            panel_width = self.top_panel_widget.width()
            logo_width = self.launcher_icon_label.width()
            logo_height = self.launcher_icon_label.height()
            panel_height = self.top_panel_widget.height()
            y = max(0, (panel_height - logo_height) // 2)
            self.launcher_icon_label.move((panel_width - logo_width) // 2, y)
        self.settings_manager.schedule_geometry_save(self)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.settings_manager.schedule_geometry_save(self)

    def _load_local_data(self):
        self.app_state.local_config = self.settings_manager.read_json(self.app_state.config_path) or {}
        try:
            self.mod_manager.migrate_metadata_from_local_configs()
        except Exception as e:
            logging.warning(f'Metadata migration failed: {e}')
        self.app_state.local_config['metadata_migrated_v2'] = True
        self.settings_manager.write_local_config()

    def _init_localization(self):
        if not hasattr(self, '_qt_translator_holder'):
            self._qt_translator_holder = {}
        saved_language = localization_manager.initialize_localization(self.app_state.local_config, self.app_state.config_path, self.settings_manager.write_local_config, self.settings_manager.write_json)
        localization_manager.update_qt_translations(saved_language, self._qt_translator_holder)

    def _update_qt_translations(self, language_code):
        if not hasattr(self, '_qt_translator_holder'):
            self._qt_translator_holder = {}
        localization_manager.update_qt_translations(language_code, self._qt_translator_holder)

    def _init_session(self):
        try:
            from utils.network_utils import get_session
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            get_session().post(f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat', json={'sessionId': self.session_id}, timeout=5)
        except Exception as e:
            import logging
            logging.debug(f'_init_session: heartbeat failed: {e}')

    def _handle_first_launch_settings(self):
        self.app_state.local_config['first_launch_splash_shown'] = True
        self.app_state.local_config['disable_splash'] = True
        self.settings_manager.write_local_config()
        try:
            self.initialization_finished.disconnect(self._handle_first_launch_settings)
        except TypeError:
            pass

    def _on_theme_changed_by_manager(self):
        self.theme.on_theme_changed_by_manager()

    def _prev_page(self):
        self.search_display.prev_page()

    def _next_page(self):
        self.search_display.next_page()

    def _show_search_dialog(self):
        self.search_display.show_search_dialog()

    def _show_library_search_dialog(self):
        self.library_search_text = ''
        self.library_search_button.setText('🔍')
        self.library_search_button.setToolTip(tr('ui.search_placeholder'))
        self.library_display.update_display()

    def _switch_settings_page(self, page):
        self.settings_ui.switch_settings_page(page)

    def _go_back_to_settings_menu(self):
        self.settings_ui.go_back_to_settings_menu()

    def _prompt_for_game_path(self, is_initial=False):
        result = self.settings_manager.prompt_for_game_path(is_initial)
        if result:
            self._update_action_button_state()
        if is_initial and (not result):
            self.customization_manager.start_background_music()
        return result

    def _update_filtered_mods(self):
        self.search_display.update_filtered_mods()

    def _update_mod_display(self):
        self.search_display.update_display()

    def _update_action_button_state(self):
        self.game_launch.update_button_state()

    def _update_installed_mods_display(self):
        self.library_display.update_display()

    def _update_installed_mods_for_chapter_mode(self, chapter_id):
        self.library_display.update_for_chapter_mode(chapter_id)

    def _update_mod_widgets_slot_status(self):
        self.library_display.update_mod_widgets_slot_status()

    def _refresh_installed_mods_async(self):
        self.library_display.refresh_async()

    def _cleanup_missing_mods(self, mods):
        self.library_display.cleanup_missing_mods(mods)

    def _install_single_mod(self, mod, force=False):
        self.mod_ops.install_mod(mod, force)

    def _on_mod_install_requested(self, mod):
        self.mod_ops.on_mod_install_requested(mod)

    def _on_single_mod_install_finished(self, success):
        self.mod_ops.on_install_finished(success)

    def _on_mod_uninstall_requested(self, mod):
        self.mod_ops.on_mod_uninstall_requested(mod)

    def _uninstall_single_mod(self, mod):
        self.mod_ops.uninstall_mod(mod)

    def _on_mod_clicked(self, mod):
        self.search_display.on_mod_clicked(mod)

    def _on_mod_installation_finished(self, success, message):
        self.mod_ops.on_mod_installation_finished(success, message)

    def _show_mod_details_dialog(self, mod_data):
        self.search_display.show_details(mod_data)

    def _show_chapter_mode_instruction(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        from ui.common.styling import clear_layout_widgets
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        instruction_widget = QLabel(tr('ui.chapter_mode_instruction'))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_widget.setStyleSheet('\n            QLabel {\n                color: #CCCCCC;\n                font-size: 14px;\n                font-style: italic;\n                padding: 20px;\n                border: 2px dashed #666666;\n                background-color: rgba(255, 255, 255, 0.1);\n            }\n        ')
        instruction_widget.setWordWrap(True)
        instruction_widget.setMinimumHeight(80)
        self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, instruction_widget)

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
                self.slot_manager.assign_mod_to_slot(selected_slot, mod_data)

    def _on_bg_ready(self, obj):
        self.theme.on_background_ready(obj)

    def apply_theme(self):
        self.theme.apply_theme()

    def _on_chapter_mode_mod_use(self, mod_data, chapter_id):
        self.library_display.on_chapter_mode_mod_use(mod_data, chapter_id)

    def _on_installed_mod_clicked(self, mod_data):
        self.library_display.on_mod_clicked(mod_data)

    def _on_installed_mod_remove(self, mod_data):
        self.library_display.on_mod_remove(mod_data)

    def _on_installed_mod_use(self, mod_data):
        self.library_display.on_mod_use(mod_data)

    def _set_install_buttons_enabled(self, enabled):
        self.mod_ops.set_install_buttons_enabled(enabled)

    def _refresh_save_slots(self):
        self.save_ui.refresh_slots()

    def _update_collection_ui(self):
        self.save_ui.update_collection_ui()

    def _update_slot_highlight(self):
        self.save_ui.update_slot_highlight()

    def _update_slot_action_bar(self):
        self.save_ui.update_slot_action_bar()

    def _clear_selected_slot(self):
        self.save_ui.clear_selected_slot()

    def _configure_hidden_tab_bar(self, tab_widget):
        self.save_ui.configure_hidden_tab_bar(tab_widget)

    def _on_save_manager_slot_clicked(self, chapter, slot):
        self.save_ui.on_slot_clicked(chapter, slot)

    def _on_slot_double_clicked(self, chapter, slot):
        self.save_ui.on_slot_double_clicked(chapter, slot)

    def _on_configure_saves_click(self):
        self.save_ui.show_save_manager()

    def _hide_save_manager(self):
        self.save_ui.hide_save_manager()

    def _on_chapter_tab_changed(self):
        self.save_ui.on_chapter_tab_changed()

    def _toggle_settings_view(self, show_changelog=False):
        self.settings_ui.toggle_settings_view(show_changelog)

    def _toggle_help_view(self):
        self.settings_ui.toggle_help_view()

    def _update_settings_page_visibility(self):
        self.settings_ui.update_settings_page_visibility()

    def _on_reset_settings_click(self):
        self.settings_ui.reset_settings()

    def _on_language_changed(self):
        language_code = self.language_combo.currentData()
        self.settings_ui.on_language_changed(language_code)

    def _on_game_type_changed(self, index):
        self.settings_ui.on_game_type_changed(index)

    def _on_chapter_mode_changed(self, state):
        self.settings_ui.on_chapter_mode_changed(state)

    def _on_toggle_beta_updates(self):
        self.settings_ui.on_toggle_beta_updates()

    def _on_toggle_fullscreen(self):
        self.settings_ui.on_toggle_fullscreen()

    def _on_toggle_steam_launch(self, state=None):
        self.settings_ui.on_toggle_steam_launch(state)

    def _on_toggle_custom_executable(self):
        self.settings_ui.on_toggle_custom_executable()

    def _on_toggle_hide_library_filters(self, state):
        self.settings_ui.on_toggle_hide_library_filters(state)

    def _on_toggle_disable_background(self, state):
        self.settings_ui.on_toggle_disable_background(state)

    def _on_toggle_disable_splash(self, state):
        self.settings_ui.on_toggle_disable_splash(state)

    def _on_background_button_click(self):
        self.theme.on_background_button_click()

    def _update_background_button_state(self):
        self.theme.update_background_button_state()

    def _on_background_music_button_click(self):
        self.theme.on_background_music_button_click()

    def _on_startup_sound_button_click(self):
        self.theme.on_startup_sound_button_click()

    def _on_theme_button_click(self):
        self.theme.on_theme_button_click()

    def _on_custom_style_edited(self):
        self.theme.on_custom_style_edited()

    def _update_dynamic_elements(self):
        self.theme.update_dynamic_elements()

    def _on_action_button_click(self):
        self.game_launch.on_action_button_click()

    def _perform_full_install(self):
        self.game_launch.perform_full_install()

    def _on_full_install_finished(self, success, target_dir):
        self.game_launch.on_full_install_finished(success, target_dir)

    def _hide_window_for_game(self):
        self.game_launch.hide_window()

    def _restore_window_after_game(self):
        self.game_launch.restore_window()

    def _refresh_mods_in_slots(self):
        self.game_launch.refresh_mods_in_slots()

    def _refresh_all_slot_status_displays(self):
        self.game_launch.refresh_slot_displays()

    def _refresh_slot_status_display(self, slot_frame):
        self.game_launch.refresh_slot_status_display(slot_frame)

    def _update_mods_in_active_slots(self):
        self.game_launch.update_mods_in_active_slots()

    def _on_toggle_full_install(self, state):
        self.app_state.is_full_install = bool(state)
        if platform.system() == 'Darwin' and self.app_state.is_full_install:
            self.feedback_manager.show_info('dialogs.unavailable', tr('dialogs.macos_install_unavailable'))
            self.full_install_checkbox.blockSignals(True)
            self.full_install_checkbox.setChecked(False)
            self.full_install_checkbox.blockSignals(False)
            return
        self._update_action_button_state()

    def _on_refresh_clicked(self, is_initial=False):
        from workers.fetch_mods import FetchModsThread
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
        from utils.game_utils import is_game_running
        if is_game_running():
            self.feedback_manager.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
            return
        self._stop_fetch_thread()
        threading.Thread(target=self.update_checker.check_for_updates, daemon=True).start()
        self.fetch_thread = FetchModsThread(self, force_update=True)
        self.fetch_thread.status.connect(self.update_status_signal)
        self.fetch_thread.result.connect(self._on_fetch_translations_finished)
        self.fetch_thread.start()

    def _on_fetch_translations_finished(self, success: bool):
        try:
            self.mod_manager.load_local_mods()
            if hasattr(self, 'mod_list_layout'):
                self._update_filtered_mods()
                if not self.app_state.mods_loaded:
                    self.app_state.mods_loaded = True
                    self.mods_loaded_signal.emit()
            if hasattr(self, 'installed_mods_layout'):
                self._update_installed_mods_display()
            self._refresh_mods_in_slots()
            self.slot_manager.refresh_slots_content()
            self._update_action_button_state()
            if success:
                self.feedback_manager.update_status(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.app_state.all_mods else tr('ui.network_update_failed')
                self.feedback_manager.update_status(fallback_msg, UI_COLORS['status_error'])
            QTimer.singleShot(100, self.slot_manager.load_slots_state)
            self._update_plugin_tabs()
        except Exception as e:
            self.feedback_manager.update_status(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])

    def _update_plugin_tabs(self):
        if not hasattr(self, 'plugin_manager') or not hasattr(self, 'main_tab_widget'):
            return
        if self._handling_plugin_tab:
            return
        self._handling_plugin_tab = True
        self._plugin_tab_map = self.plugin_manager.update_plugin_tabs(self.main_tab_widget, num_original_tabs=4)
        self._handling_plugin_tab = False

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
            self._show_main_mod_management_dialog()
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 3:
            self._on_xdelta_patch_click()
            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
        elif index == 1:
            self._update_installed_mods_display()
            self.previous_tab_index = index
        else:
            self.previous_tab_index = index

    def _prompt_for_update(self, update_info):
        from config.constants import LAUNCHER_VERSION, UI_COLORS
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
            if hasattr(self, '_perform_update_ui_prep'):
                self._perform_update_ui_prep()
            self.update_checker.perform_update(update_info)
        else:
            self.app_state.update_in_progress = False
            self.feedback_manager.update_status(tr('status.update_rejected'), UI_COLORS['status_info'])

    def _show_pending_dialogs(self):
        if not self.app_state.pending_dialogs:
            return
        pending = self.app_state.pending_dialogs.copy()
        self.app_state.pending_dialogs.clear()
        for dialog_type, dialog_data in pending:
            if dialog_type == 'update':
                self._prompt_for_update(dialog_data)

    def _stop_fetch_thread(self):
        self._safe_stop_thread(getattr(self, 'fetch_thread', None))
        self.fetch_thread = None

    def _safe_stop_thread(self, thread, timeout=THREAD_WAIT_TIMEOUT):
        if isinstance(thread, QThread) and thread.isRunning():
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(timeout):
                thread.terminate()
                thread.wait()

    def _stop_presence_thread(self):
        self._safe_stop_thread(getattr(self, 'presence_thread', None))
        self.presence_thread = None
        self.presence_worker = None

    def _current_tab_names(self):
        return self.app_state.game_mode.tab_names
