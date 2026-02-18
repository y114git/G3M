import os
import platform
import shutil
import uuid
import webbrowser
import argparse
from typing import Optional
import logging
from PyQt6.QtCore import QTranslator, Qt, QEvent, QThread, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QDesktopServices
from PyQt6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QColorDialog
from services.localization_service import localization_service, tr
from models.game_modes import DeltaruneGame, get_game
from config.constants import UI_COLORS, SOCIAL_LINKS, ONLINE_UPDATE_INTERVAL, INITIALIZATION_TIMEOUT, CLOUD_FUNCTIONS_BASE_URL
from ui.utils.ui_utils import DebounceTimer
from ui.common.styling import get_theme_color
from utils.path_utils import get_user_data_root, resource_path, get_launcher_dir, get_user_plugins_dir
from utils.network_utils import get_session
from workers.presence_worker import PresenceWorker
from controllers.mod_operations_controller import ModOperationsController
from controllers.library_display_controller import LibraryDisplayController
from controllers.search_display_controller import SearchDisplayController
from controllers.settings_controller import SettingsUiController
from controllers.theme_controller import ThemeController
from controllers.game_launch_controller import GameLaunchController
from ui.common.feedback import FeedbackManager
from core.startup import SingleInstanceServer
from core.app_state import AppState
from services.mod_service import ModManager
from services.launch_service import GameLauncher
from services.updatecheck_service import UpdateChecker
from services.settings_service import SettingsManager
from ui.builders.search_tab_builder import SearchTabBuilder
from ui.builders.settings_view_builder import SettingsViewBuilder
from services.plugin_service import PluginManager
from services.customization_service import CustomizationManager
from services.used_mods_service import UsedModsManager
from utils.network_utils import check_internet_connection
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
    mods_display_ready = pyqtSignal()
    install_from_gb_signal = pyqtSignal(object)

    def __init__(self, args: Optional[argparse.Namespace] = None, parent_for_dialogs: Optional[QWidget] = None, initial_url: str | None = None):
        super().__init__()
        self.app_state = AppState()
        from utils.network_utils import _build_session
        self.app_state.network_session = _build_session()
        self.server: SingleInstanceServer | None = None
        self.app_state.config_dir = os.path.join(get_user_data_root(), 'settings')
        self.app_state.cache_dir = os.path.join(get_user_data_root(), 'cache')
        self.launcher_dir = get_launcher_dir()
        from utils.path_utils import get_user_mods_dir
        self.app_state.mods_dir = get_user_mods_dir()
        self.app_state.plugins_dir = get_user_plugins_dir()
        self.app_state.mods_metadata_path = os.path.join(self.app_state.mods_dir, 'metadata.json')
        self.app_state.plugins_metadata_path = os.path.join(self.app_state.plugins_dir, 'metadata.json')
        for d in (self.app_state.config_dir, self.app_state.cache_dir, self.app_state.mods_dir, self.app_state.plugins_dir):
            os.makedirs(d, exist_ok=True)
        self.lang_service = localization_service
        self.app_state.config_path = os.path.join(self.app_state.config_dir, 'settings.json')
        self._migrate_settings_config_file()
        self.feedback_service = FeedbackManager(self)
        self.feedback_service.app_state = self.app_state
        self.settings_service = SettingsManager(self.app_state, self.feedback_service, self.lang_service, parent=self)
        self._pending_install_url = initial_url
        self.dialog_parent = parent_for_dialogs or self
        self.session_id = uuid.uuid4().hex
        self.presence_thread = QThread(self)
        self.presence_worker = PresenceWorker(self.session_id, self.app_state)
        self.presence_worker.moveToThread(self.presence_thread)
        self.presence_worker.update_online_count.connect(self._update_online_label)
        self.presence_thread.start()
        self._online_timer = QTimer(self)
        self._online_timer.timeout.connect(self.presence_worker.run)
        self._online_timer.start(ONLINE_UPDATE_INTERVAL)
        self.presence_worker.run()
        self.setWindowTitle('DELTAHUB')
        self._supports_volume = platform.system() == 'Windows'
        self._initial_size = None
        self.app_state.local_config = self.settings_service.read_json(self.app_state.config_path) or {}
        self._init_localization()
        self._splash_was_shown = False
        self.settings_service.migrate_config_if_needed()
        is_first_launch = not self.app_state.local_config.get('first_launch_splash_shown', False)
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
        self._install_op_id = 0
        self.pending_updates = []
        self._mods_display_ready_emitted = False
        self.feedback_service.status_updated.connect(self.update_status_signal.emit)
        self.settings_service.language_changed.connect(lambda _: self._relocalize_ui())
        self.settings_service.restart_required.connect(lambda msg: self.feedback_service.show_message('info', 'dialogs.restart_required', msg))
        self.settings_service.status_changed.connect(self.update_status_signal.emit)
        self.mod_service = ModManager(self.app_state, self.feedback_service, self.settings_service, self)
        self.mod_service.progress_updated.connect(self.set_progress_signal.emit)
        self.mod_service.status_changed.connect(self.update_status_signal.emit)
        self.mod_service.url_prompt_required.connect(self._handle_url_install_prompt)
        self.game_launcher = GameLauncher(self.app_state, self.feedback_service, self.mod_service, self)
        self.game_launcher.status_changed.connect(self.update_status_signal.emit)
        self.game_launcher.progress_updated.connect(self.set_progress_signal.emit)
        self.game_launcher.game_launch_started.connect(self.hide_window_signal.emit)
        self.game_launcher.game_launch_finished.connect(self.restore_window_signal.emit)
        self.game_launcher.recover_previous_session()
        self.update_checker = UpdateChecker(self.app_state, self.feedback_service, self)
        self.update_checker.update_available.connect(self._handle_update_info)
        self.update_checker.status_changed.connect(self.update_status_signal.emit)
        self.update_checker.progress_updated.connect(self.set_progress_signal.emit)
        self.update_checker.update_finished.connect(self._on_update_cleanup)
        self.update_checker.update_error.connect(lambda msg: self.feedback_service.show_message('error', 'errors.error', msg))
        self.update_checker.quit_requested.connect(QApplication.quit)
        self.plugin_service = PluginManager(self.app_state, self.settings_service, self)
        self.plugin_service.app_window = self
        self.customization_service = CustomizationManager(self.app_state, self)
        self.used_mods_service = UsedModsManager(self.app_state, self.mod_service, self.feedback_service, self.settings_service, self)
        self.used_mods_service.used_mods_updated.connect(self._on_used_mods_service_used_mods_updated)
        self._load_used_mods_debounce = DebounceTimer(delay_ms=200)
        self.mod_ops = ModOperationsController(self.app_state, self.feedback_service, self.mod_service, self)
        self.library_display = LibraryDisplayController(self.app_state, self.feedback_service, self.mod_service, self.used_mods_service, self)
        self.search_display = SearchDisplayController(self.app_state, self.feedback_service, self.mod_service, self.mod_ops, self)
        self.search_display.ui_button_text_update.connect(lambda w, v: self._set_widget_attr(w, 'setText', v))
        self.search_display.ui_button_tooltip_update.connect(lambda w, v: self._set_widget_attr(w, 'setToolTip', v))
        self.search_display.ui_button_enabled_update.connect(lambda w, v: self._set_widget_attr(w, 'setEnabled', v))
        self.search_display.ui_widget_updates_enabled.connect(lambda w, v: self._set_widget_attr(w, 'setUpdatesEnabled', v))
        self.settings_ui = SettingsUiController(self.app_state, self.feedback_service, self.settings_service, self.used_mods_service, self.customization_service, self)
        self.theme = ThemeController(self.app_state, self.feedback_service, self.settings_service, self.customization_service, self)
        self.game_launch = GameLaunchController(self.app_state, self.feedback_service, self.mod_service, self.used_mods_service, self.settings_service, self.game_launcher, self.customization_service, self.plugin_service, self)
        from controllers.refresh_controller import RefreshController
        self.refresh_controller = RefreshController(self.app_state, self.feedback_service, self.mod_service, self.used_mods_service, self.game_launch, self.update_checker, self.settings_service, app_window=self)
        self._connect_cross_service_signals()
        self.initialization_finished.connect(self.game_launch.update_button_state)
        self.initialization_finished.connect(self._try_start_background_music)
        if is_first_launch:
            self.initialization_finished.connect(self._handle_first_launch_settings)
        self.init_ui()

        self._update_plugin_tabs()
        self.custom_font_family = localization_service.load_font()
        self.ui_ready.emit()
        self._connect_own_signals()
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(INITIALIZATION_TIMEOUT)
        self.settings_service.load_window_geometry(self)

    def _handle_first_launch_settings(self):
        try:
            self.initialization_finished.disconnect(self._handle_first_launch_settings)
        except TypeError:
            pass
        if self.app_state.local_config.get('first_launch_splash_shown', False):
            return
        self.app_state.local_config['first_launch_splash_shown'] = True
        if not self.app_state.local_config.get('disable_splash'):
            self.app_state.local_config['disable_splash'] = True
        self.settings_service.write_local_config()

    def _connect_cross_service_signals(self):
        """Connect signals between services, controllers, and display components."""
        self.mod_service.mod_list_updated.connect(self.library_display.update_display)
        self.mod_service.mod_list_updated.connect(self.used_mods_service._retry_load_missing_mods)
        self.mod_service.mod_list_updated.connect(lambda: self._load_used_mods_debounce.call(self.used_mods_service.load_used_mods_state))
        self.used_mods_service.used_mod_changed.connect(lambda chapter_id: self.game_launch.update_button_state())
        self.used_mods_service.used_mod_changed.connect(lambda chapter_id: self.library_display._update_priority_button_visibility(chapter_id) if hasattr(self.library_display, '_update_priority_button_visibility') else None)
        self.used_mods_service.action_button_update_needed.connect(self.game_launch.update_button_state)
        self.used_mods_service.mod_widgets_update_needed.connect(self.library_display.update_mod_widgets_active_status)
        self.game_launch.window_hide_requested.connect(self.hide)
        self.game_launch.window_restore_requested.connect(self._on_window_restore_requested)
        self.game_launch.library_display_update_requested.connect(lambda: self.library_display.update_display())
        self.game_launch.search_display_update_requested.connect(lambda: self.search_display.update_display())
        self.game_launch.update_geometry_requested.connect(self.updateGeometry)
        self.game_launch.show_pending_dialogs_requested.connect(self._show_pending_dialogs)
        self.game_launch.pending_updates_changed.connect(lambda updates: setattr(self, 'pending_updates', updates))
        self.settings_service.theme_changed.connect(self.theme.apply_theme)
        self.settings_service.theme_changed.connect(self.theme.on_theme_changed_by_service)

    def _connect_own_signals(self):
        """Connect AppWindow's own pyqtSignals to their handlers."""
        self.update_status_signal.connect(self._update_status)
        self.hide_window_signal.connect(self.game_launch.hide_window)
        self.restore_window_signal.connect(self.game_launch.restore_window)
        self.set_progress_signal.connect(self._on_progress_update)
        self.show_update_prompt.connect(self._prompt_for_update)
        self.mods_loaded_signal.connect(self._on_mods_loaded)
        self.url_received_signal.connect(self.handle_one_click_install)
        self.install_from_gb_signal.connect(lambda mod: self.mod_ops.install_mod(mod, force=True))
        self.initialization_finished.connect(self._handle_pending_install)
        self.app_state.all_mods_updated.connect(lambda mods: setattr(self.app_state, 'all_mods', mods))

    def _handle_pending_install(self):
        if self._pending_install_url:
            self.handle_one_click_install(self._pending_install_url)
            self._pending_install_url = None

    def _on_window_restore_requested(self):
        geometry_restored = self.settings_service.load_window_geometry(self)
        if geometry_restored:
            self.show()
        else:
            self.showNormal()
        self.activateWindow()
        self.raise_()

    def _refresh_after_install(self) -> None:
        if self.plugin_service:
            self.plugin_service.convert_plugin_archives()
            self.plugin_service.load_plugins()
        if hasattr(self, '_update_plugin_tabs'):
            self._update_plugin_tabs()
        if hasattr(self, 'plugin_display'):
            self.plugin_display.update_display()
        if self.mod_service:
            self.mod_service.invalidate_mods_cache()
            self.mod_service.load_local_mods(_skip_conversion=True)
            self.mod_service.mod_list_updated.emit()
        if hasattr(self, 'library_display'):
            self.library_display.update_display()
        if hasattr(self, 'search_display'):
            self.search_display.update_search_cards()
            self.search_display.update_filtered_mods(preserve_page=True)
        if hasattr(self, 'settings_service'):
            self.settings_service.theme_changed.emit()

    def handle_one_click_install(self, url: str):
        from core.app_install_handler import handle_one_click_install
        handle_one_click_install(self, url)

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.mod_ops.set_install_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        if success:
            self.library_display.update_display()
            if hasattr(self, 'search_display'):
                self.search_display.update_search_cards()
                self.search_display.update_filtered_mods(preserve_page=True)
        status_color = UI_COLORS['status_success'] if success else UI_COLORS['status_error']
        self._update_status(message, status_color)

    def _handle_url_install_prompt(self, title, message):
        reply = self.feedback_service.ask_question(title, message)
        self.mod_service.handle_url_prompt_response(reply)

    def _handle_permission_error(self, path: str):
        self.feedback_service.show_message('error', 'errors.access_denied', path=path)

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
        self.settings_button.clicked.connect(self.settings_ui.toggle_settings_view)
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
        self.launcher_icon_label.setFixedSize(250, 80)
        self.launcher_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.customization_service.load_launcher_icon(self.launcher_icon_label)
        self.bottom_widget = QFrame()
        self.bottom_widget.setObjectName('bottom_widget')
        self.bottom_frame = QVBoxLayout(self.bottom_widget)
        self.status_label = QLabel(tr('ui.initialization'))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.action_frame = QHBoxLayout()
        self.shortcut_button = QPushButton(tr('buttons.shortcut'))
        self.action_button = QPushButton(tr('status.please_wait'))
        self.action_button.setEnabled(False)
        self.action_button.setMinimumWidth(200)
        self.action_button.clicked.connect(self.game_launch.on_action_button_click)
        self.app_state.is_installing = False
        self.pending_updates = []
        self.chat_button = QPushButton(tr('ui.chat_button'))
        self.chat_button.clicked.connect(self._open_chat)
        self.action_frame.addWidget(self.shortcut_button)
        self.action_frame.addWidget(self.action_button)
        self.action_frame.addWidget(self.chat_button)
        self.app_state.action_button_text_changed.connect(self.action_button.setText)
        self.app_state.action_button_enabled_changed.connect(self.action_button.setEnabled)
        self.app_state.progress_bar_visible_changed.connect(self.progress_bar.setVisible)
        self.app_state.progress_bar_value_changed.connect(self.progress_bar.setValue)
        self.bottom_frame.addWidget(self.status_label)
        self.bottom_frame.addWidget(self.progress_bar)
        self.bottom_frame.addLayout(self.action_frame)
        self.main_layout.addSpacing(20)
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.app_state.current_page = 1
        default_mods_per_page = self.app_state.local_config.get('mods_per_page', 20)
        self.app_state.mods_per_page = default_mods_per_page
        self.app_state.gamebanana_sort = 'default'
        self.app_state.filtered_mods = []
        self.sort_ascending = False
        self.app_state.search_text = ''
        self._setup_search_tab()
        self.library_sort_ascending = False
        self.app_state.library_search_text = ''
        self._previous_mode = 'normal'
        self._setup_library_tab()
        self._setup_plugins_tab()
        self.main_tab_widget.addTab(self.search_mods_tab, tr('ui.search_tab'))
        self.main_tab_widget.addTab(self.library_tab, tr('ui.library_tab'))
        self.main_tab_widget.addTab(self.plugins_tab, tr('ui.plugins_tab'))
        self.previous_tab_index = 0
        self.main_tab_widget.currentChanged.connect(self._on_tab_changed)
        self.main_tab_widget.setStyleSheet('\n            QTabWidget::tab-bar {\n                alignment: center;\n            }\n            QTabBar::tab {\n                min-width: 120px;\n                padding: 8px 16px;\n            }\n        ')
        self.main_layout.addWidget(self.main_tab_widget)
        self.main_layout.addWidget(self.bottom_widget)
        self._setup_settings_tab()
        self.search_display.update_filtered_mods()
        self.main_layout.addWidget(self.settings_widget)
        self.app_state.current_settings_page = self.settings_menu_page
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.setWindowIcon(QIcon(resource_path('assets/icons/icon.ico')))

    def _setup_search_tab(self):
        search_builder = SearchTabBuilder(self.app_state, self)
        self.search_mods_tab = search_builder.build()
        search_widgets = search_builder.get_widgets()
        self._bind_widgets(search_widgets, required=(
            'search_container', 'search_mods_scroll', 'mod_list_widget', 'mod_list_layout',
            'sort_combo', 'sort_order_btn', 'modgame_combo', 'tags_label', 'tag_textedit',
            'tag_customization', 'tag_gameplay', 'tag_other', 'search_button',
            'prev_page_btn', 'page_label', 'next_page_btn', 'mods_per_page_spinbox',
            'mods_per_page_label', 'gb_sort_combo', 'gb_sort_label', 'auto_sorting_checkbox',
            'blocklist_button',
        ))
        self.mods_per_page_spinbox.setValue(self.app_state.mods_per_page)
        self.mods_per_page_spinbox.valueChanged.connect(self._on_mods_per_page_changed)
        self.auto_sorting_checkbox.stateChanged.connect(self._on_auto_sorting_changed)
        self.blocklist_button.clicked.connect(self.search_display.show_blocklist_dialog)
        self.app_state.auto_sorting = self.app_state.local_config.get('auto_sorting', False)
        self.auto_sorting_checkbox.setChecked(self.app_state.auto_sorting)
        self.gb_sort_combo.setCurrentIndex(0)
        self.gb_sort_combo.currentIndexChanged.connect(self._on_gamebanana_sort_changed)
        self.sort_combo.currentIndexChanged.connect(self._on_search_sort_changed)
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        if 'selected_search_game' not in self.app_state.local_config:
            default_game = self.modgame_combo.currentData() or 'deltarune'
            self.app_state.local_config['selected_search_game'] = default_game
            self.settings_service.write_local_config()

        def on_modgame_changed():
            selected_game = self.modgame_combo.currentData() or 'deltarune'
            self.app_state.local_config['selected_search_game'] = selected_game
            self.settings_service.write_local_config()
            self.app_state.current_page = 1
            self.search_display.load_mods_for_selected_game()
        self.modgame_combo.currentIndexChanged.connect(on_modgame_changed)
        for tag_cb in (self.tag_textedit, self.tag_customization, self.tag_gameplay, self.tag_other):
            tag_cb.stateChanged.connect(lambda: (setattr(self.app_state, 'current_page', 1), self.search_display.update_filtered_mods()))
        self.search_button.clicked.connect(self.search_display.show_search_dialog)
        self.prev_page_btn.clicked.connect(self.search_display.prev_page)
        self.next_page_btn.clicked.connect(self.search_display.next_page)

    def _setup_library_tab(self):
        from ui.builders.library_tab_builder import LibraryTabBuilder
        library_builder = LibraryTabBuilder(self.app_state, self)
        self.library_tab_builder = library_builder
        self.library_tab = library_builder.build()
        library_widgets = library_builder.get_widgets()
        self._bind_widgets(library_widgets, required=(
            'library_filters_widget', 'game_type_combo', 'chapter_mode_checkbox',
            'full_install_checkbox', 'chapter_tabs_widget', 'chapter_tabs_layout',
            'chapter_tab_buttons', 'installed_mods_container', 'installed_mods_scroll',
            'installed_mods_widget', 'installed_mods_layout', 'library_sort_combo',
            'library_sort_order_btn', 'library_tags_label', 'library_tag_textedit',
            'library_tag_customization', 'library_tag_gameplay', 'library_tag_other',
            'library_tag_gamebanana', 'library_tag_widgets', 'library_search_button',
        ), optional=(
            'import_export_button', 'custom_executable_button', 'reset_custom_exe_button',
            'change_path_button', 'installed_mods_label', 'priority_button',
            'create_modpack_button',
        ))
        if self.priority_button:
            self.priority_button.clicked.connect(self.library_display.on_priority_button_click)
        if self.create_modpack_button:
            self.create_modpack_button.clicked.connect(self.library_display.on_create_modpack_button_click)
        if self.import_export_button:
            from controllers.mod_import_export_controller import ModImportExportController
            self.mod_import_export_controller = ModImportExportController(self.app_state, self.mod_service, self)
            self.import_export_button.clicked.connect(self.mod_import_export_controller.show_import_export_dialog)
        self.game_type_combo.currentIndexChanged.connect(self.settings_ui.on_game_type_changed)
        self.chapter_mode_checkbox.stateChanged.connect(self.settings_ui.on_chapter_mode_changed)
        self.full_install_checkbox.stateChanged.connect(self._on_toggle_full_install)
        self.library_sort_combo.currentIndexChanged.connect(self.library_display.update_display)
        self.library_sort_order_btn.clicked.connect(self._toggle_library_sort_order)
        for tag in self.library_tag_widgets:
            tag.stateChanged.connect(self.library_display.update_display)
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
        self._set_checkbox_checked_silently(self.chapter_mode_checkbox, saved_chapter_mode)
        self.game_type_combo.setEnabled(not saved_chapter_mode)
        self._set_checkbox_checked_silently(self.full_install_checkbox, saved_full_install)
        self.game_launch._full_install_checkbox_is_checked = saved_full_install
        self.app_state.is_installing_changed.connect(self.game_launch.update_button_state)
        self.app_state.is_installing_changed.connect(lambda v: self.mod_ops.set_install_buttons_enabled(not v))
        self.app_state.is_installing_changed.connect(lambda v: self._update_all_install_buttons())
        self.app_state.current_mode = 'chapter' if saved_chapter_mode else 'normal'
        self.game_launch.update_button_state()
        self._previous_mode = self.app_state.current_mode
        self.app_state.selected_chapter_id = None
        if saved_chapter_mode and hasattr(self, 'chapter_tabs_widget'):
            self.chapter_tabs_widget.setVisible(True)
        game_def = get_game(saved_game_type)
        self.app_state.game_mode = game_def if game_def else DeltaruneGame()
        self.app_state.game_mode_changed.connect(self._on_game_mode_updated_by_state)
        self._update_checkbox_visibility()
        self._update_change_path_button_text()
        self._setup_chapter_tabs()
        if saved_chapter_mode and hasattr(self, '_show_chapter_mode_instruction'):
            self._show_chapter_mode_instruction()

            def update_priority_button():
                if self.app_state.selected_chapter_id is not None:
                    self.library_display._update_priority_button_visibility(self.app_state.selected_chapter_id)
                if hasattr(self, 'chapter_tab_buttons') and self.chapter_tab_buttons:
                    for btn in self.chapter_tab_buttons:
                        if btn.isChecked():
                            chapter_id = getattr(btn, '_chapter_id', None)
                            if chapter_id is not None:
                                self.library_display._update_priority_button_visibility(chapter_id)
                                break
            update_priority_button()
        elif not saved_chapter_mode:
            self.library_display.update_display()
            self.library_display._update_priority_button_visibility()
            self.app_state.library_initialized = True
        self.library_display.update_mod_widgets_active_status()

    def _setup_plugins_tab(self):
        from ui.builders.plugin_tab_builder import PluginTabBuilder
        plugin_builder = PluginTabBuilder(self.app_state, self)
        self.plugin_tab_builder = plugin_builder
        self.plugins_tab = plugin_builder.build()
        plugin_widgets = plugin_builder.get_widgets()
        for attr, key in (('plugins_search_button', 'search_button'), ('plugins_import_button', 'import_button'),
                          ('plugins_container', 'plugins_container'), ('plugins_scroll', 'plugins_scroll'),
                          ('plugins_widget', 'plugins_widget'), ('plugins_layout', 'plugins_layout')):
            setattr(self, attr, plugin_widgets[key])
        from controllers.plugin_display_controller import PluginDisplayController
        self.plugin_display = PluginDisplayController(self.app_state, self.feedback_service, self.plugin_service, self)
        self.plugins_search_button.clicked.connect(self.plugin_display.on_search_plugins)
        self.plugins_import_button.clicked.connect(self.plugin_display.on_import_plugin)

    def _setup_settings_tab(self):
        settings_builder = SettingsViewBuilder(self.app_state, self)
        self.settings_widget = settings_builder.build()
        settings_widgets = settings_builder.get_widgets()
        self._bind_widgets(settings_widgets, required=(
            'settings_pages_container', 'settings_menu_page', 'settings_customization_page',
            'changelog_widget', 'settings_title_label', 'language_label', 'language_combo',
            'beta_updates_checkbox', 'skip_patching_warnings_checkbox', 'fullscreen_checkbox',
            'hide_library_filters_checkbox', 'launch_via_steam_checkbox',
            'hide_mods_without_files_checkbox', 'open_deltahub_folder_button',
            'customization_button', 'settings_customization_button', 'reset_button',
            'disable_background_checkbox', 'disable_splash_checkbox', 'back_button_cust',
            'change_background_button', 'change_logo_button', 'background_music_button',
            'startup_sound_button', 'custom_style_frame', 'color_widgets', 'color_labels',
            'color_config', 'theme_button', 'changelog_text_edit', 'changelog_button',
            'report_bug_button',
        ), optional=(
            'use_portproton_checkbox', 'select_portproton_path_button',
            'portproton_path_label', 'portproton_frame',
        ))
        self.language_combo.currentTextChanged.connect(lambda: self.settings_ui.on_language_changed(self.language_combo.currentData()))
        self.beta_updates_checkbox.stateChanged.connect(self.settings_ui.on_toggle_beta_updates)
        self.fullscreen_checkbox.stateChanged.connect(self.settings_ui.on_toggle_fullscreen)
        self.hide_library_filters_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_library_filters)
        self.launch_via_steam_checkbox.stateChanged.connect(self.settings_ui.on_toggle_steam_launch)
        if self.use_portproton_checkbox:
            self.use_portproton_checkbox.stateChanged.connect(self.settings_ui.on_toggle_portproton)
            self.use_portproton_checkbox.stateChanged.connect(self._update_portproton_ui)
        if self.select_portproton_path_button:
            self.select_portproton_path_button.clicked.connect(self._select_portproton_path)
        self.hide_mods_without_files_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_mods_without_files)
        self.skip_patching_warnings_checkbox.stateChanged.connect(self.settings_ui.on_toggle_skip_patching_warnings)
        if self.change_path_button:
            self.change_path_button.clicked.connect(self._prompt_for_game_path)
        if self.custom_executable_button:
            self.custom_executable_button.clicked.connect(self._select_custom_executable_file)
        if self.reset_custom_exe_button:
            self.reset_custom_exe_button.clicked.connect(self._reset_custom_executable)
        self.open_deltahub_folder_button.clicked.connect(self._open_deltahub_folder)
        self.customization_button.clicked.connect(lambda: self.settings_ui.switch_settings_page(self.settings_customization_page))
        self.reset_button.clicked.connect(self.settings_ui.reset_settings)
        self.disable_background_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_background)
        self.disable_splash_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_splash)
        self.back_button_cust.clicked.connect(self.settings_ui.go_back_to_settings_menu)
        self.change_background_button.clicked.connect(self.theme.on_background_button_click)
        self.change_logo_button.setText(self.customization_service.get_logo_button_text())
        self.change_logo_button.clicked.connect(self.theme.on_logo_button_click)
        self.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.background_music_button.clicked.connect(self.theme.on_background_music_button_click)
        self.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())
        self.startup_sound_button.clicked.connect(self.theme.on_startup_sound_button_click)
        self.theme_button.clicked.connect(self.theme.on_theme_button_click)

        def pick_color_for_edit(target_edit):
            if (color := QColorDialog.getColor()).isValid():
                target_edit.setText(color.name())
                self.theme.on_custom_style_edited()
        self._color_btns = {}
        for key in self.color_config.keys():
            line_edit = self.color_widgets[key]
            btn = settings_widgets[f'color_btn_{key}']
            self._color_btns[key] = btn
            reset_btn = settings_widgets[f'color_reset_{key}']
            line_edit.editingFinished.connect(self.theme.on_custom_style_edited)
            btn.clicked.connect(lambda _, le=line_edit: pick_color_for_edit(le))
            reset_btn.clicked.connect(lambda _, le=line_edit: (le.clear(), self.theme.on_custom_style_edited()))
        self.changelog_button.clicked.connect(lambda: self.settings_ui.toggle_settings_view(show_changelog=True))
        self.report_bug_button.clicked.connect(self.settings_ui.show_report_bug_dialog)

    def _finish_initialization(self):
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        if hasattr(self.app_state, 'pending_announce_check') and self.app_state.pending_announce_check and (not self.app_state.update_in_progress):
            self._check_and_show_announce()

    def _on_mods_loaded(self):
        if self.initialization_timer and self.initialization_timer.isActive():
            self.initialization_timer.stop()
        self._finish_initialization()

    def _force_finish_initialization(self):
        if self.app_state.initialization_completed:
            return
        self.app_state.mods_loaded = True
        self._finish_initialization()

    def _try_start_background_music(self):
        if getattr(self, 'is_shown_to_user', False) and self.isVisible():
            self.customization_service.maybe_start_background_music(force=True)

    def _on_search_sort_changed(self):
        if not hasattr(self, 'search_display'):
            return
        if hasattr(self, 'sort_combo'):
            sort_index = self.sort_combo.currentIndex()
            self.app_state.local_config['search_sort_index'] = sort_index
            self.settings_service.write_local_config()
        self.search_display.update_filtered_mods()

    def _apply_sort_order(self, ascending: bool, btn):
        btn.setText('▲' if ascending else '▼')
        btn.setToolTip(tr('ui.ascending') if ascending else tr('ui.descending'))

    def _toggle_library_sort_order(self):
        self.library_sort_ascending = not self.library_sort_ascending
        self._apply_sort_order(self.library_sort_ascending, self.library_sort_order_btn)
        self.library_display.update_display()

    def _toggle_sort_order(self):
        self.sort_ascending = not self.sort_ascending
        self._apply_sort_order(self.sort_ascending, self.sort_order_btn)
        self.search_display.update_filtered_mods()

    def _on_mods_per_page_changed(self, value: int):
        try:
            self.app_state.mods_per_page = value
            self.app_state.local_config['mods_per_page'] = value
            self.settings_service.write_local_config()
            self.app_state.current_page = 1
            self.search_display.update_filtered_mods()
            logging.info(f'Mods per page changed to {value}')
        except Exception as e:
            logging.error(f'Error in _on_mods_per_page_changed: {e}', exc_info=True)

    def _on_auto_sorting_changed(self, state: int):
        try:
            is_checked = state == Qt.CheckState.Checked.value
            self.app_state.auto_sorting = is_checked
            self.app_state.local_config['auto_sorting'] = is_checked
            self.settings_service.write_local_config()
            if is_checked:
                self.search_display.update_filtered_mods(preserve_page=True)
            logging.info(f'Auto-sorting changed to {is_checked}')
        except Exception as e:
            logging.error(f'Error in _on_auto_sorting_changed: {e}', exc_info=True)

    def _on_gamebanana_sort_changed(self, index: int):
        from core.app_sort_handler import handle_gamebanana_sort_changed
        handle_gamebanana_sort_changed(self, index)

    def _update_checkbox_visibility(self):
        game_type = self.game_type_combo.currentData()
        game_def = self.app_state.game_mode
        self.chapter_mode_checkbox.setVisible(game_def.is_multi_tab)
        self.full_install_checkbox.setVisible(game_type in ('deltarunedemo', 'undertaleyellow', 'sugaryspire'))

    def _on_game_mode_updated_by_state(self, mode_obj):
        try:
            self._update_checkbox_visibility()
            game_type = self.game_type_combo.currentData()
            if game_type != 'deltarune':
                self._set_checkbox_checked_silently(self.chapter_mode_checkbox, False)
                if getattr(self.app_state, 'current_mode', 'normal') != 'normal':
                    self.app_state.current_mode = 'normal'
                self.game_type_combo.setEnabled(True)
            self.used_mods_service.load_used_mods_state()
            self.library_display.update_display()
            self._update_change_path_button_text()
        except Exception:
            pass

    def _update_change_path_button_text(self):
        if self.change_path_button:
            self.change_path_button.setText(self.app_state.game_mode.path_change_button_text)

    def _full_install_tooltip(self) -> str:
        if platform.system() == 'Darwin':
            return tr('tooltips.macos_install_unavailable')
        if self.app_state.game_mode.game_id == 'sugaryspire':
            return tr('tooltips.full_spire_install_instructions')
        elif self.app_state.game_mode.game_id == 'undertaleyellow':
            return tr('tooltips.full_yellow_install_instructions')
        return tr('tooltips.full_install_instructions')

    def _safe_set_parent_none(self, obj):
        try:
            if obj:
                obj.setParent(None)
        except Exception:
            pass

    def _bind_widgets(self, widgets_dict, required=(), optional=()):
        """Assign widgets from a dict to self attributes by name."""
        for name in required:
            setattr(self, name, widgets_dict[name])
        for name in optional:
            setattr(self, name, widgets_dict.get(name))

    @staticmethod
    def _localized_value(data, ru_key, en_key, fallback_key=None):
        return data.get(ru_key if localization_service.get_current_language() == 'ru' else en_key, '') or (data.get(fallback_key, '') if fallback_key else '')

    def _set_checkbox_checked_silently(self, checkbox, checked):
        checkbox.blockSignals(True)
        try:
            checkbox.setChecked(checked)
        finally:
            checkbox.blockSignals(False)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonDblClick and hasattr(obj, '_chapter_id'):
            chapter_id = getattr(obj, '_chapter_id', None)
            if chapter_id is not None:
                self.used_mods_service.toggle_direct_launch_for_chapter(chapter_id)
                return True
        return super().eventFilter(obj, ev)

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
            except (ValueError, TypeError) as e:
                logging.debug(f"Failed to parse color '{bg_color_str}': {e}")
                painter.fillRect(self.rect(), QColor('rgba(0, 0, 0, 200)'))
        super().paintEvent(event)

    def _initialize_mutual_exclusions(self):
        direct_launch_id = self.app_state.local_config.get('direct_launch_chapter', '')
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        is_deltarune = self.app_state.game_mode.game_id == 'deltarune'
        should_block = is_deltarune and is_chapter_mode and bool(direct_launch_id)
        if not hasattr(self, 'launch_via_steam_checkbox'):
            return
        self.launch_via_steam_checkbox.setEnabled(not should_block)
        self.theme.apply_theme()

    def _post_show_initialization(self):
        from core.app_post_init import post_show_initialization
        post_show_initialization(self)

    def _on_mod_scan_finished(self, scan_cache: dict):
        try:
            if hasattr(self.mod_service, '_mods_cache') and hasattr(self.mod_service, '_cache_lock'):
                with self.mod_service._cache_lock:
                    self.mod_service._mods_cache = scan_cache
                    self.mod_service._mods_cache_valid = True
            self.mod_service.load_local_mods()
            saved_chapter_mode = self.app_state.local_config.get('chapter_mode_enabled', False)
            self.setEnabled(False)
            self._load_mods_and_build_list_synchronously(saved_chapter_mode)
            self.setEnabled(True)
            self._load_used_mods_debounce.call(self.used_mods_service.load_used_mods_state)
        except Exception as e:
            logging.error(f'AppWindow: Error in _on_mod_scan_finished: {e}', exc_info=True)
            self.feedback_service.update_status(tr('status.mod_scan_error', details=str(e)), UI_COLORS['status_error'])
            self.setEnabled(True)

    def _update_installed_mods_display(self, set_library_initialized=False):
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        selected_id = self.app_state.selected_chapter_id
        if is_chapter_mode and selected_id is None:
            if hasattr(self, '_show_chapter_mode_instruction'):
                self._show_chapter_mode_instruction()
        else:
            self.library_display.update_display()
            if set_library_initialized:
                self.app_state.library_initialized = True

    def _load_mods_and_build_list_synchronously(self, saved_chapter_mode=False):
        try:
            logging.info('AppWindow: Starting mods loading in background before window show')

            def update_filtered_mods_callback():
                try:
                    logging.info('AppWindow: Building mods list after fetch (from callback)')
                    if hasattr(self, 'search_display'):
                        self.search_display.update_filtered_mods(preserve_page=False)
                    logging.info('AppWindow: Mods list built successfully (from callback)')
                except Exception as e:
                    logging.error(f'AppWindow: Error building mods list: {e}', exc_info=True)
            on_fetch_finished_kwargs = {'update_filtered_mods_callback': update_filtered_mods_callback, 'update_installed_mods_callback': lambda: self._update_installed_mods_display(set_library_initialized=not saved_chapter_mode), 'update_action_button_callback': lambda: self.game_launch.update_button_state(), 'mods_loaded_signal': self.mods_loaded_signal}
            self.refresh_controller.refresh_mods_list(is_initial=True, language_combo=self.language_combo, localization_callback=self._relocalize_ui, on_fetch_finished_kwargs=on_fetch_finished_kwargs)
            try:
                if hasattr(self, 'search_display'):
                    if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                        logging.info(f'AppWindow: Building initial mods list with {len(self.app_state.all_mods)} mods')
                        self.search_display.update_filtered_mods(preserve_page=False)
                    else:
                        logging.info('AppWindow: No mods loaded yet, list will be built after fetch completes')
            except Exception as e:
                logging.error(f'AppWindow: Error building initial mods list: {e}', exc_info=True)
            logging.info('AppWindow: Mods loading started in background, window can be shown now')
        except Exception as e:
            logging.error(f'AppWindow: Error in _load_mods_and_build_list_synchronously: {e}', exc_info=True)

    def _handle_update_info(self, update_info, retry_count=0):
        from core.app_update_handler import handle_update_info
        handle_update_info(self, update_info, retry_count)

    def _get_update_widgets(self):
        widgets = [self.action_button, self.chat_button, self.open_deltahub_folder_button, self.change_background_button]
        if self.change_path_button:
            widgets.append(self.change_path_button)
        return widgets

    def _set_update_ui_enabled(self, enabled: bool):
        for w in self._get_update_widgets():
            if w:
                w.setEnabled(enabled)
        if getattr(self, 'top_refresh_button', None):
            self.top_refresh_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)

    def _perform_update_ui_prep(self):
        self._set_update_ui_enabled(False)
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
            self._set_update_ui_enabled(True)
            self.game_launch.update_button_state()
        except Exception:
            pass

    def _on_progress_update(self, value: int):
        self.progress_bar.setValue(value)
        if value > 0 and (not self.progress_bar.isVisible()):
            self.progress_bar.setVisible(True)

    def _update_status(self, message: str, color: str = 'white'):
        actual_color = UI_COLORS.get(color, color)
        if not self.status_label.wordWrap():
            self.status_label.setWordWrap(True)
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f'color: {actual_color};')

    def _update_online_label(self, count: int):
        if hasattr(self, 'online_label') and (self.online_label is not None):
            self._last_online_count = count
            display_count = '?' if count < 0 else count
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=display_count)}")

    def _save_custom_executable(self, path: str):
        config_key = self.app_state.game_mode.get_custom_exec_config_key()
        self.app_state.local_config[config_key] = path
        self.settings_service.write_local_config()
        self.settings_service.settings_changed.emit()
        self._update_custom_executable_ui()

    def _select_custom_executable_file(self):
        from PyQt6.QtWidgets import QFileDialog
        filepath, _ = QFileDialog.getOpenFileName(self, tr('ui.select_launch_file'))
        if filepath:
            self._save_custom_executable(filepath)

    def _reset_custom_executable(self):
        self._save_custom_executable('')

    def _update_custom_executable_ui(self):
        if not hasattr(self, 'custom_executable_button') or not self.custom_executable_button:
            return
        config_key = self.app_state.game_mode.get_custom_exec_config_key()
        path = self.app_state.local_config.get(config_key, '')
        has_custom_exe = bool(path)
        if self.reset_custom_exe_button:
            self.reset_custom_exe_button.setVisible(has_custom_exe)

    def _select_portproton_path(self):
        if not self.select_portproton_path_button:
            return
        filepath = self.settings_service.select_portproton_path()
        if filepath:
            self._update_portproton_ui()

    def _update_portproton_ui(self):
        if not self.portproton_frame or not self.portproton_path_label:
            return
        is_steam_launch = self.app_state.local_config.get('launch_via_steam', False)
        if self.use_portproton_checkbox:
            self.use_portproton_checkbox.setEnabled(not is_steam_launch)
            if is_steam_launch:
                self.use_portproton_checkbox.setToolTip(tr('tooltips.portproton_disabled_steam'))
            else:
                self.use_portproton_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>')
        use_portproton = self.app_state.local_config.get('use_portproton', False)
        path = self.app_state.local_config.get('portproton_path', '')
        show_frame = use_portproton and not is_steam_launch and (self.use_portproton_checkbox.isEnabled() if self.use_portproton_checkbox else False)
        self.portproton_frame.setVisible(show_frame)
        if self.portproton_frame.isVisible():
            if path:
                self.portproton_path_label.setText(tr('ui.currently_selected', filename=os.path.basename(path)))
            else:
                self.portproton_path_label.setText(tr('ui.file_not_selected') + ' (using PATH)')

    def _on_used_mods_service_used_mods_updated(self):
        logging.debug('Used mods updated, refreshing UI')
        if hasattr(self, 'library_display'):
            self.library_display.update_mod_widgets_active_status()
            self.library_display._update_priority_button_visibility()
        if self.app_state.current_mode == 'chapter':
            selected_chapter_id = getattr(self.app_state, 'selected_chapter_id', None)
            if selected_chapter_id is not None:
                self.library_display.update_for_chapter_mode(selected_chapter_id)

    def _setup_chapter_tabs(self):
        tabs = self.app_state.game_mode.tabs
        for i, tab in enumerate(tabs):
            if i < len(self.chapter_tab_buttons):
                btn = self.chapter_tab_buttons[i]
                btn.clicked.connect(lambda checked, tid=tab.tab_id: self._on_chapter_tab_clicked(tid) if checked else None)
                btn.installEventFilter(self)
                setattr(btn, '_chapter_id', tab.tab_id)
        self._update_chapter_tabs_style()

    def _on_chapter_tab_clicked(self, chapter_id):
        logging.debug(f'Chapter tab clicked: {chapter_id}')
        tabs = self.app_state.game_mode.tabs
        for i, btn in enumerate(self.chapter_tab_buttons):
            btn.setChecked(tabs[i].tab_id == chapter_id if i < len(tabs) else False)
        self.app_state.selected_chapter_id = chapter_id
        self.library_display.update_display()
        if hasattr(self.library_display, '_update_priority_button_visibility'):
            self.library_display._update_priority_button_visibility(chapter_id)

    def _update_chapter_tabs_style(self):
        if not hasattr(self, 'chapter_tab_buttons'):
            return
        tabs = self.app_state.game_mode.tabs
        direct_launch_chapter_id = self.app_state.local_config.get('direct_launch_chapter', '')
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        for i, (tab, btn) in enumerate(zip(tabs, self.chapter_tab_buttons)):
            is_direct_launch = direct_launch_chapter_id == tab.tab_id
            border_style = 'dashed' if is_direct_launch else 'solid'
            text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
            btn.setStyleSheet(f'\n                QPushButton#chapter_tab_{i} {{\n                    background-color: {button_color};\n                    border: 2px {border_style} {border_color};\n                    color: {text_color};\n                    font-weight: bold;\n                    font-size: 13px;\n                    border-radius: 0px;\n                    padding: 5px;\n                }}\n                QPushButton#chapter_tab_{i}:checked {{\n                    background-color: {hover_color};\n                    border: 3px {border_style} {border_color};\n                }}\n                QPushButton#chapter_tab_{i}:hover {{\n                    background-color: {hover_color};\n                }}\n            ')

    def _apply_widget_localizations(self, localizations):
        """Apply a list of (widget_name, method, tr_key) localizations.
        Skips widgets that don't exist or are None."""
        for widget_name, method, tr_key in localizations:
            widget = getattr(self, widget_name, None)
            if widget and hasattr(widget, method):
                getattr(widget, method)(tr(tr_key))

    def _apply_combo_localizations(self, combo_name, item_keys):
        """Apply setItemText for a combo box from a list of tr keys."""
        combo = getattr(self, combo_name, None)
        if combo:
            for i, key in enumerate(item_keys):
                combo.setItemText(i, tr(key))

    def _relocalize_texts(self):
        from core.app_localization_utils import relocalize_texts
        relocalize_texts(self)

    def _relocalize_ui(self):
        from core.app_localization_utils import relocalize_ui
        relocalize_ui(self)

    def closeEvent(self, event):
        from core.app_cleanup import perform_close_cleanup
        perform_close_cleanup(self)
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
        self.settings_service.schedule_geometry_save(self)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.settings_service.schedule_geometry_save(self)

    def _load_local_data(self):
        protected_first_launch_splash_shown = self.app_state.local_config.get('first_launch_splash_shown')
        protected_disable_splash = self.app_state.local_config.get('disable_splash')
        self.app_state.local_config = self.settings_service.read_json(self.app_state.config_path) or {}
        if protected_first_launch_splash_shown is not None:
            self.app_state.local_config['first_launch_splash_shown'] = protected_first_launch_splash_shown
        if protected_disable_splash is not None:
            self.app_state.local_config['disable_splash'] = protected_disable_splash
        try:
            self.mod_service.migrate_metadata_from_local_configs()
        except Exception as e:
            logging.warning(f'Metadata migration failed: {e}')
        self.app_state.local_config['metadata_migrated_v2'] = True
        self.settings_service.write_local_config()

    def _init_localization(self):
        if not hasattr(self, '_qt_translator_holder'):
            self._qt_translator_holder = {}
        saved_language = localization_service.initialize_localization(self.app_state.local_config, self.app_state.config_path, self.settings_service.write_local_config, self.settings_service.write_json)
        localization_service.update_qt_locale(saved_language, self._qt_translator_holder)

    def _update_qt_locale(self, language_code):
        if not hasattr(self, '_qt_translator_holder'):
            self._qt_translator_holder = {}
        localization_service.update_qt_locale(language_code, self._qt_translator_holder)

    def _init_session(self):
        if not self.app_state.has_internet:
            return
        try:
            get_session(self.app_state).post(f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat', json={'sessionId': self.session_id}, timeout=5)
        except Exception:
            self.app_state.has_internet = False

    def _show_library_search_dialog(self):
        self.app_state.library_search_text = ''
        self.library_search_button.setText('🔍')
        self.library_search_button.setToolTip(tr('ui.search_placeholder'))
        self.library_display.update_display()

    def _prompt_for_game_path(self, is_initial=False):
        result = self.settings_service.prompt_for_game_path(is_initial)
        if result:
            self.game_launch.update_button_state()
        if is_initial and (not result):
            self.customization_service.start_background_music()
        return result

    def _open_deltahub_folder(self):
        deltahub_path = get_user_data_root()
        if os.path.exists(deltahub_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(deltahub_path))
        else:
            logging.warning(f'DELTAHUB folder not found: {deltahub_path}')

    def _show_chapter_mode_instruction(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        from ui.common.styling import clear_layout_widgets
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        instruction_widget = QLabel(tr('ui.chapter_mode_instruction'))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        secondary_text_color = get_theme_color(self.app_state.local_config, 'version_text', '#CCCCCC')
        border_color = get_theme_color(self.app_state.local_config, 'border', '#666666')
        instruction_widget.setStyleSheet(f'\n            QLabel {{\n                color: {secondary_text_color};\n                font-size: 14px;\n                font-style: italic;\n                padding: 20px;\n                border: 2px dashed {border_color};\n                background-color: rgba(255, 255, 255, 0.1);\n            }}\n        ')
        instruction_widget.setWordWrap(True)
        instruction_widget.setMinimumHeight(80)
        self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, instruction_widget)

    def _on_toggle_full_install(self, state):
        self.app_state.is_full_install = bool(state)
        if hasattr(self, 'game_launch'):
            self.game_launch._full_install_checkbox_is_checked = bool(state)
        if platform.system() == 'Darwin' and self.app_state.is_full_install:
            self.feedback_service.show_message('info', 'dialogs.unavailable', tr('dialogs.macos_install_unavailable'))
            self._set_checkbox_checked_silently(self.full_install_checkbox, False)
            return
        self.game_launch.update_button_state()

    def _update_all_install_buttons(self):
        if hasattr(self, 'search_display'):
            self.search_display.update_search_cards()

    def _on_refresh_clicked(self, is_initial=False):
        if not is_initial and self.app_state.has_internet:
            if self._reload_global_settings():
                self._check_and_show_announce(force_check=True)

        self.refresh_controller.refresh_mods_list(is_initial=is_initial, language_combo=self.language_combo, localization_callback=self._relocalize_ui, on_fetch_finished_kwargs={'update_filtered_mods_callback': lambda: self.search_display.update_filtered_mods(preserve_page=False), 'update_installed_mods_callback': lambda: self._update_installed_mods_display(), 'update_action_button_callback': lambda: self.game_launch.update_button_state(), 'update_plugin_tabs_callback': self._update_plugin_tabs, 'mods_loaded_signal': self.mods_loaded_signal})

    def _update_plugin_tabs(self):
        if not hasattr(self, 'plugin_service') or not hasattr(self, 'main_tab_widget'):
            return
        if self._handling_plugin_tab:
            return
        self._handling_plugin_tab = True
        self.plugin_service.load_plugins()
        self._plugin_tab_map = self.plugin_service.update_plugin_tabs(self.main_tab_widget, num_original_tabs=3)
        if hasattr(self, 'plugin_display'):
            self.plugin_display.update_display()
        self._handling_plugin_tab = False

    def _restore_last_active_tab(self):
        last_tab = self.app_state.local_config.get('last_active_tab', 0)
        if last_tab == 0:
            return
        max_tabs = self.main_tab_widget.count() - 1
        if last_tab > max_tabs:
            return
        self.main_tab_widget.setCurrentIndex(last_tab)

    def _run_with_plugin_api(self, plugin, handler):
        plugin_api = plugin.get('api')
        if plugin_api:
            setattr(self, 'plugin_api', plugin_api)
        try:
            return handler(self)
        finally:
            if hasattr(self, 'plugin_api'):
                delattr(self, 'plugin_api')

    def _resolve_plugin_from_widget(self, current_widget, visible_plugins, plugin):
        try:
            bound = getattr(current_widget, '_plugin_info', None)
            if isinstance(bound, dict):
                return bound
        except Exception:
            pass
        try:
            if current_widget is not None and hasattr(current_widget, 'property'):
                name_key = current_widget.property('plugin_name_key')
                if name_key:
                    for p in visible_plugins:
                        if p.get('name_key') == name_key:
                            return p
        except Exception:
            pass
        return plugin

    def _on_tab_changed(self, index):
        from core.app_tab_handler import handle_tab_changed
        handle_tab_changed(self, index)

    def _reload_global_settings(self):
        from core.app_update_handler import reload_global_settings
        return reload_global_settings(self)

    def _check_and_show_announce(self, retry_count=0, force_check=False):
        from core.app_update_handler import check_and_show_announce
        check_and_show_announce(self, retry_count, force_check)

    def _save_announce(self, version: int):
        from core.app_update_handler import save_announce
        save_announce(self, version)

    def _prompt_for_update(self, update_info):
        from core.app_update_handler import prompt_for_update
        prompt_for_update(self, update_info)

    def _open_chat(self):
        if not check_internet_connection():
            self.feedback_service.show_message('warning', 'chat.no_internet', tr('chat.no_internet'))
            return
        from ui.dialogs.chat_dialog import ChatWindow
        chat_window = ChatWindow(self.app_state, self)
        chat_window.exec()

    def _migrate_settings_config_file(self):
        old_config_path = os.path.join(self.app_state.config_dir, 'config.json')
        new_config_path = os.path.join(self.app_state.config_dir, 'settings.json')
        if os.path.exists(old_config_path) and (not os.path.exists(new_config_path)):
            shutil.move(old_config_path, new_config_path)
            logging.info('Migrated settings config.json to settings.json')

    def _set_widget_attr(self, widget_name: str, method: str, value):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, method):
            getattr(widget, method)(value)

    def _show_pending_dialogs(self):
        if not self.app_state.pending_dialogs:
            return
        pending = self.app_state.pending_dialogs.copy()
        self.app_state.pending_dialogs.clear()
        for dialog_type, dialog_data in pending:
            if dialog_type == 'update':
                self._prompt_for_update(dialog_data)
