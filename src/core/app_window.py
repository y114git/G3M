import base64
import json
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
from PyQt6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QColorDialog, QDialog, QMessageBox
from managers.localization_manager import localization_manager, tr
from models.game_modes import FullGameMode, DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode
from config.constants import UI_COLORS, SOCIAL_LINKS, ONLINE_UPDATE_INTERVAL, INITIALIZATION_TIMEOUT, THREAD_WAIT_TIMEOUT, SLOT_ID_UNIVERSAL
from utils.game_utils import is_game_running
from utils.ui_utils import safe_stop_thread, DebounceTimer
from utils.path_utils import get_user_data_root, resource_path, get_launcher_dir, get_user_plugins_dir
from workers.background_workers import PresenceWorker, FetchChangelogWorker
from controllers.mod_operations_controller import ModOperationsController
from controllers.library_display_controller import LibraryDisplayController
from controllers.search_display_controller import SearchDisplayController
from controllers.settings_ui_controller import SettingsUiController
from controllers.theme_controller import ThemeController
from controllers.game_launch_controller import GameLaunchController
from ui.common.feedback import FeedbackManager
from core.startup import SingleInstanceServer, ShortcutLaunchError
from core.app_state import AppState
from managers.mod_manager import ModManager
from managers.launch_manager import GameLauncher
from managers.updatecheck_manager import UpdateChecker
from managers.settings_manager import SettingsManager
from ui.main_window.search_tab_builder import SearchTabBuilder
from ui.main_window.library_tab_builder import LibraryTabBuilder
from ui.main_window.plugin_tab_builder import PluginTabBuilder
from ui.main_window.settings_view_builder import SettingsViewBuilder
from managers.plugin_manager import PluginManager
from managers.customization_manager import CustomizationManager
from managers.used_mods_manager import UsedModsManager
from managers.shortcut_manager import ShortcutManager
from ui.dialogs.chat_window import ChatWindow
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
        self.is_shortcut_launch = args and args.shortcut_launch
        self.app_state.config_dir = os.path.join(get_user_data_root(), 'settings')
        self.app_state.cache_dir = os.path.join(get_user_data_root(), 'cache')
        self.launcher_dir = get_launcher_dir()
        from utils.path_utils import get_user_mods_dir
        self.app_state.mods_dir = get_user_mods_dir()
        self.app_state.plugins_dir = get_user_plugins_dir()
        self.app_state.mods_metadata_path = os.path.join(self.app_state.mods_dir, 'metadata.json')
        self.app_state.plugins_metadata_path = os.path.join(self.app_state.plugins_dir, 'metadata.json')
        os.makedirs(self.app_state.config_dir, exist_ok=True)
        os.makedirs(self.app_state.cache_dir, exist_ok=True)
        os.makedirs(self.app_state.mods_dir, exist_ok=True)
        os.makedirs(self.app_state.plugins_dir, exist_ok=True)
        self.lang_manager = localization_manager
        self.app_state.config_path = os.path.join(self.app_state.config_dir, 'settings.json')
        self._migrate_settings_config_file()
        self.feedback_manager = FeedbackManager(self)
        self.feedback_manager.app_state = self.app_state
        self.settings_manager = SettingsManager(self.app_state, self.feedback_manager, self.lang_manager, parent=self)
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
        QTimer.singleShot(0, self.presence_worker.run)
        self.setWindowTitle('DELTAHUB')
        self._supports_volume = platform.system() == 'Windows'
        self._initial_size = None
        self.app_state.local_config = self.settings_manager.read_json(self.app_state.config_path) or {}
        self._init_localization()
        self._splash_was_shown = False
        self.settings_manager.migrate_config_if_needed()
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
        self.feedback_manager.status_updated.connect(self.update_status_signal.emit)
        self.settings_manager.language_changed.connect(lambda _: self._retranslate_ui())
        self.settings_manager.restart_required.connect(lambda msg: self.feedback_manager.show_message('info', 'dialogs.restart_required', msg))
        self.settings_manager.status_changed.connect(self.update_status_signal.emit)
        self.mod_manager = ModManager(self.app_state, self.feedback_manager, self.settings_manager, self)
        self.mod_manager.progress_updated.connect(self.set_progress_signal.emit)
        self.mod_manager.status_changed.connect(self.update_status_signal.emit)
        self.mod_manager.url_prompt_required.connect(self._handle_url_install_prompt)
        self.game_launcher = GameLauncher(self.app_state, self.feedback_manager, self.mod_manager, self)
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
        self.update_checker.update_error.connect(lambda msg: self.feedback_manager.show_message('error', 'errors.error', msg))
        self.update_checker.quit_requested.connect(QApplication.quit)
        self.plugin_manager = PluginManager(self.app_state, self.settings_manager, self)
        self.plugin_manager.app_window = self
        self.customization_manager = CustomizationManager(self.app_state, self)
        self.slot_manager = UsedModsManager(self.app_state, self.mod_manager, self.feedback_manager, self.settings_manager, self)
        self.slot_manager.used_mods_updated.connect(self._on_slot_manager_used_mods_updated)
        self._load_used_mods_debounce = DebounceTimer(delay_ms=200)
        self.shortcut_manager = ShortcutManager(self.app_state, self.feedback_manager, self.mod_manager, self)
        self.shortcut_manager.shortcut_created.connect(lambda path: self.feedback_manager.update_status(tr('status.shortcut_created', path=path), UI_COLORS['status_success']))
        self.shortcut_manager.status_changed.connect(self.feedback_manager.update_status)
        self.mod_ops = ModOperationsController(self.app_state, self.feedback_manager, self.mod_manager, self)
        self.library_display = LibraryDisplayController(self.app_state, self.feedback_manager, self.mod_manager, self.slot_manager, self)
        self.search_display = SearchDisplayController(self.app_state, self.feedback_manager, self.mod_manager, self.mod_ops, self)
        self.search_display.ui_button_text_update.connect(self._on_search_ui_button_text_update)
        self.search_display.ui_button_tooltip_update.connect(self._on_search_ui_button_tooltip_update)
        self.search_display.ui_button_enabled_update.connect(self._on_search_ui_button_enabled_update)
        self.search_display.ui_label_text_update.connect(self._on_search_ui_label_text_update)
        self.search_display.ui_widget_updates_enabled.connect(self._on_search_ui_widget_updates_enabled)
        self.settings_ui = SettingsUiController(self.app_state, self.feedback_manager, self.settings_manager, self.slot_manager, self.customization_manager, self)
        self.theme = ThemeController(self.app_state, self.feedback_manager, self.settings_manager, self.customization_manager, self)
        self.game_launch = GameLaunchController(self.app_state, self.feedback_manager, self.mod_manager, self.slot_manager, self.settings_manager, self.game_launcher, self.customization_manager, self.plugin_manager, self)
        from controllers.refresh_controller import RefreshController
        self.refresh_controller = RefreshController(self.app_state, self.feedback_manager, self.mod_manager, self.slot_manager, self.game_launch, self.update_checker, self.settings_manager, app_window=self)
        self.mod_manager.mod_list_updated.connect(self.library_display.update_display)
        self.mod_manager.mod_list_updated.connect(self.slot_manager._retry_load_missing_mods)
        self.mod_manager.mod_list_updated.connect(lambda: self._load_used_mods_debounce.call(self.slot_manager.load_used_mods_state))
        self.slot_manager.used_mod_changed.connect(lambda chapter_id: self.game_launch.update_button_state())
        self.slot_manager.used_mod_changed.connect(lambda chapter_id: self.library_display._update_priority_button_visibility(chapter_id) if hasattr(self.library_display, '_update_priority_button_visibility') else None)
        self.slot_manager.action_button_update_needed.connect(self.game_launch.update_button_state)
        self.slot_manager.mod_widgets_update_needed.connect(self.library_display.update_mod_widgets_slot_status)
        self.game_launch.window_hide_requested.connect(self.hide)
        self.game_launch.window_restore_requested.connect(self._on_window_restore_requested)
        self.game_launch.library_display_update_requested.connect(lambda: self.library_display.update_display())
        self.game_launch.search_display_update_requested.connect(lambda: self.search_display.update_display())
        self.game_launch.update_geometry_requested.connect(self.updateGeometry)
        self.game_launch.show_pending_dialogs_requested.connect(self._show_pending_dialogs)
        self.game_launch.pending_updates_changed.connect(lambda updates: setattr(self, 'pending_updates', updates))
        self.settings_manager.theme_changed.connect(self.theme.apply_theme)
        self.settings_manager.theme_changed.connect(self._on_theme_changed_by_manager)
        self.initialization_finished.connect(self.game_launch.update_button_state)
        self.initialization_finished.connect(self._try_start_background_music)
        if is_first_launch:
            self.initialization_finished.connect(self._handle_first_launch_settings)
        if self.is_shortcut_launch:
            self._shortcut_launch(args)
            return
        self.init_ui()
        self.custom_font_family = localization_manager.load_font()
        QTimer.singleShot(0, lambda: self.ui_ready.emit())
        self.update_status_signal.connect(self._update_status)
        self.hide_window_signal.connect(self.game_launch.hide_window)
        self.restore_window_signal.connect(self.game_launch.restore_window)
        self.set_progress_signal.connect(self._on_progress_update)
        self.show_update_prompt.connect(self._prompt_for_update)
        self.mods_loaded_signal.connect(self._on_mods_loaded)
        self.url_received_signal.connect(self.handle_one_click_install)
        self.install_from_gb_signal.connect(lambda mod: self._install_single_mod(mod, force=True))
        self.initialization_finished.connect(self._handle_pending_install)
        self.app_state.all_mods_updated.connect(lambda mods: setattr(self.app_state, 'all_mods', mods))
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(INITIALIZATION_TIMEOUT)
        self.settings_manager.load_window_geometry(self)

    def _handle_first_launch_settings(self):
        if self.app_state.local_config.get('first_launch_splash_shown', False):
            try:
                self.initialization_finished.disconnect(self._handle_first_launch_settings)
            except TypeError:
                pass
            return
        self.app_state.local_config['first_launch_splash_shown'] = True
        if 'disable_splash' not in self.app_state.local_config or self.app_state.local_config.get('disable_splash') is False:
            self.app_state.local_config['disable_splash'] = True
        self.settings_manager.write_local_config()
        try:
            self.initialization_finished.disconnect(self._handle_first_launch_settings)
        except TypeError:
            pass

    def _handle_pending_install(self):
        if self._pending_install_url:
            self.handle_one_click_install(self._pending_install_url)
            self._pending_install_url = None

    def _on_window_restore_requested(self):
        geometry_restored = self.settings_manager.load_window_geometry(self)
        if geometry_restored:
            self.show()
        else:
            self.showNormal()
        self.activateWindow()
        self.raise_()

    def handle_one_click_install(self, url: str):
        if is_game_running():
            return
        self.activateWindow()
        self.raise_()
        if self.app_state.is_installing:
            self.feedback_manager.show_message('warning', 'dialogs.install_in_progress_title', tr('dialogs.install_in_progress_body'))
            return
        if url.startswith('deltahub://'):
            from workers.background_workers import UrlInstallThread
            worker = UrlInstallThread(self, url)
            worker.status.connect(lambda msg, color: self.feedback_manager.update_status(msg, color))
            worker.progress.connect(lambda p: setattr(self.app_state, 'progress_bar_value', p))

            def on_manual_install_required(prepared_path, archive_path, temp_dir):
                self.app_state.is_installing = False
                self.app_state.progress_bar_visible = False
                self.app_state.progress_bar_value = 0
                self.app_state.clear_current_task()
                try:
                    from ui.dialogs.manual_mod_install_dialog import ManualModInstallDialog
                    from utils.game_utils import get_game_type_string
                    initial_game_type = None
                    if self.app_state and hasattr(self.app_state, 'game_mode'):
                        initial_game_type = get_game_type_string(self.app_state.game_mode)
                    dialog = ManualModInstallDialog(self, prepared_path, gamebanana_metadata=None, source_file_path=archive_path, initial_game_type=initial_game_type)
                    dialog.temp_dir_to_cleanup = temp_dir
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        if self.plugin_manager:
                            self.plugin_manager.convert_plugin_archives()
                            self.plugin_manager.load_plugins()
                        if hasattr(self, '_update_plugin_tabs'):
                            self._update_plugin_tabs()
                        if hasattr(self, 'plugin_display'):
                            self.plugin_display.update_display()
                        if self.mod_manager:
                            self.mod_manager.invalidate_mods_cache()
                            QTimer.singleShot(0, lambda: (self.mod_manager.load_local_mods(_skip_conversion=True), self.mod_manager.mod_list_updated.emit()))
                        if hasattr(self, 'library_display'):
                            self.library_display.update_display()
                        if hasattr(self, 'search_display'):
                            self.search_display.update_search_plaques()
                            self.search_display.update_filtered_mods(preserve_page=True)
                        if hasattr(self, 'settings_manager'):
                            self.settings_manager.theme_changed.emit()
                        self.feedback_manager.update_status(tr('dialogs.mod_created_successfully'), UI_COLORS['status_success'])
                        QMessageBox.information(self, tr('dialogs.success'), tr('dialogs.mod_created_successfully'))
                        QTimer.singleShot(1000, lambda: self._on_refresh_clicked(is_initial=False))
                except Exception as e:
                    logging.error(f'Failed to open manual install dialog: {e}', exc_info=True)
                    self.feedback_manager.show_message('error', tr('errors.error'), tr('errors.manual_install_failed', error=str(e)))
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass

            def on_finished(success, message):
                self.app_state.is_installing = False
                self.app_state.progress_bar_visible = False
                self.app_state.progress_bar_value = 0
                self.app_state.clear_current_task()
                if success:
                    if self.plugin_manager:
                        self.plugin_manager.convert_plugin_archives()
                        self.plugin_manager.load_plugins()
                    if hasattr(self, '_update_plugin_tabs'):
                        self._update_plugin_tabs()
                    if hasattr(self, 'plugin_display'):
                        self.plugin_display.update_display()
                    if self.mod_manager:
                        self.mod_manager.invalidate_mods_cache()
                        QTimer.singleShot(0, lambda: (self.mod_manager.load_local_mods(_skip_conversion=True), self.mod_manager.mod_list_updated.emit()))
                    if hasattr(self, 'library_display'):
                        self.library_display.update_display()
                    if hasattr(self, 'search_display'):
                        self.search_display.update_search_plaques()
                        self.search_display.update_filtered_mods(preserve_page=True)
                    if hasattr(self, 'settings_manager'):
                        self.settings_manager.theme_changed.emit()
                    self.feedback_manager.update_status(message, UI_COLORS['status_success'])
                    QTimer.singleShot(1000, lambda: self._on_refresh_clicked(is_initial=False))
                else:
                    logging.warning(f'Installation failed for deltahub:// URL: {message}')
                    self.feedback_manager.update_status(message or tr('errors.error'), UI_COLORS['status_error'])

            def on_unrar_needed():
                try:
                    from utils.archive_utils import prompt_for_unrar_install
                    if prompt_for_unrar_install(parent_widget=self):
                        logging.info('UnRAR installed successfully from app_window worker request')
                    else:
                        logging.info('User declined UnRAR installation from app_window worker request')
                except Exception as e:
                    logging.error(f'AppWindow: Error handling UnRAR installation request: {e}')
            worker.manual_install_required.connect(on_manual_install_required)
            worker.finished.connect(on_finished)
            worker.unrar_needed.connect(on_unrar_needed)
            self.app_state.is_installing = True
            self.app_state.progress_bar_visible = True
            self.app_state.progress_bar_value = 0
            self.app_state.current_task = worker
            worker.start()
        else:
            self.mod_manager.install_from_url(url)

    def _on_url_install_finished(self, success: bool, message: str):
        self.app_state.is_installing = False
        self.mod_ops.set_install_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        if success:
            self.library_display.update_display()
            if hasattr(self, 'search_display'):
                self.search_display.update_search_plaques()
                self.search_display.update_filtered_mods(preserve_page=True)
        status_color = UI_COLORS['status_success'] if success else UI_COLORS['status_error']
        self._update_status(message, status_color)

    def _handle_url_install_prompt(self, title, message):
        reply = self.feedback_manager.ask_question(title, message)
        self.mod_manager.handle_url_prompt_response(reply)

    def _shortcut_launch(self, args):
        try:
            settings_json = base64.b64decode(args.shortcut_launch).decode('utf-8')
            settings = json.loads(settings_json)
        except (UnicodeDecodeError, ValueError) as e:
            logging.error(f'Shortcut settings decode error: {e}')
            raise ShortcutLaunchError('Failed to decode shortcut settings')
        except (KeyError, TypeError) as e:
            logging.error(f'Shortcut settings parse error: {e}')
            raise ShortcutLaunchError('Failed to parse shortcut settings')
        except Exception as e:
            logging.error(f'Shortcut settings read error: {e}')
            raise ShortcutLaunchError('Failed to read shortcut settings')
        self._load_local_data()
        QTimer.singleShot(0, self.mod_manager.load_local_mods)
        try:
            if settings.get('is_undertaleyellow_mode', False):
                self.app_state.game_mode = UndertaleYellowGameMode()
            elif settings.get('is_undertale_mode', False):
                self.app_state.game_mode = UndertaleGameMode()
            elif settings.get('is_pizzatower_mode', False):
                self.app_state.game_mode = PizzaTowerGameMode()
            elif settings.get('is_sugaryspire_mode', False):
                self.app_state.game_mode = SugarySpireGameMode()
            else:
                self.app_state.game_mode = DemoGameMode() if settings.get('is_demo_mode', False) else FullGameMode()
            game_path = settings.get('game_path', '')
            demo_game_path = settings.get('demo_game_path', '')
            undertale_game_path = settings.get('undertale_game_path', '')
            undertaleyellow_game_path = settings.get('undertaleyellow_game_path', '')
            pizzatower_game_path = settings.get('pizzatower_game_path', '')
            sugaryspire_game_path = settings.get('sugaryspire_game_path', '')
            self.app_state.game_path = game_path
            self.app_state.demo_game_path = demo_game_path
            self.app_state.undertale_game_path = undertale_game_path
            if game_path:
                self.app_state.local_config['game_path'] = game_path
            if demo_game_path:
                self.app_state.local_config['demo_game_path'] = demo_game_path
            if undertale_game_path:
                self.app_state.local_config['undertale_game_path'] = undertale_game_path
            if undertaleyellow_game_path:
                self.app_state.local_config['undertaleyellow_game_path'] = undertaleyellow_game_path
            if pizzatower_game_path:
                self.app_state.local_config['pizzatower_game_path'] = pizzatower_game_path
            if sugaryspire_game_path:
                self.app_state.local_config['sugaryspire_game_path'] = sugaryspire_game_path
            launch_via_steam = settings.get('launch_via_steam', False)
            use_custom_executable = settings.get('use_custom_executable', False)
            custom_exec_path = settings.get('custom_executable_path', '')
            demo_custom_exec_path = settings.get('demo_custom_executable_path', '')
            undertale_custom_exec_path = settings.get('undertale_custom_executable_path', '')
            undertaleyellow_custom_exec_path = settings.get('undertaleyellow_custom_executable_path', '')
            pizzatower_custom_exec_path = settings.get('pizzatower_custom_executable_path', '')
            sugaryspire_custom_exec_path = settings.get('sugaryspire_custom_executable_path', '')
            direct_launch_slot_id = settings.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
            is_chapter_mode = settings.get('is_chapter_mode', False)
            if is_chapter_mode:
                self.app_state.current_mode = 'chapter'
            else:
                self.app_state.current_mode = 'normal'
            current_game_path = self._get_current_game_path()
            if not current_game_path or not os.path.exists(current_game_path):
                logging.error('Game files not found for launch')
                raise ShortcutLaunchError('Game files not found for launch')
            mods_settings = settings.get('mods', {})
            if not mods_settings:
                mods_settings = settings.get('selections', {})
            self.shortcut_manager.apply_shortcut_mods(mods_settings, is_chapter_mode=is_chapter_mode)
            self.shortcut_manager.launch_game_from_shortcut(launch_via_steam=launch_via_steam, use_custom_executable=use_custom_executable, custom_exec_path=custom_exec_path, demo_custom_exec_path=demo_custom_exec_path, undertale_custom_exec_path=undertale_custom_exec_path, undertaleyellow_custom_exec_path=undertaleyellow_custom_exec_path, pizzatower_custom_exec_path=pizzatower_custom_exec_path, sugaryspire_custom_exec_path=sugaryspire_custom_exec_path, direct_launch_slot_id=direct_launch_slot_id)
        except (OSError, FileNotFoundError) as e:
            logging.error(f'Launch error (file system): {e}')
            raise ShortcutLaunchError(f'File system error: {e}')
        except (KeyError, AttributeError) as e:
            logging.error(f'Launch error (missing data): {e}')
            raise ShortcutLaunchError(f'Missing required data: {e}')
        except Exception as e:
            logging.error(f'Launch error: {e}')
            raise ShortcutLaunchError(str(e) or 'Shortcut launch failed')

    def _handle_permission_error(self, path: str):
        self.feedback_manager.show_message('error', 'errors.access_denied', path=path)

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
        self.customization_manager.load_launcher_icon(self.launcher_icon_label)
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
        self.shortcut_button.clicked.connect(self.shortcut_manager.create_shortcut_flow)
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
        self.tag_textedit = search_widgets['tag_textedit']
        self.tag_customization = search_widgets['tag_customization']
        self.tag_gameplay = search_widgets['tag_gameplay']
        self.tag_other = search_widgets['tag_other']
        self.search_button = search_widgets['search_button']
        self.prev_page_btn = search_widgets['prev_page_btn']
        self.page_label = search_widgets['page_label']
        self.next_page_btn = search_widgets['next_page_btn']
        self.mods_per_page_spinbox = search_widgets['mods_per_page_spinbox']
        self.mods_per_page_label = search_widgets['mods_per_page_label']
        self.gb_sort_combo = search_widgets['gb_sort_combo']
        self.gb_sort_label = search_widgets['gb_sort_label']
        self.auto_sorting_checkbox = search_widgets['auto_sorting_checkbox']
        self.mods_per_page_spinbox.setValue(self.app_state.mods_per_page)
        self.mods_per_page_spinbox.valueChanged.connect(self._on_mods_per_page_changed)
        self.auto_sorting_checkbox.stateChanged.connect(self._on_auto_sorting_changed)
        self.app_state.auto_sorting = self.app_state.local_config.get('auto_sorting', False)
        self.auto_sorting_checkbox.setChecked(self.app_state.auto_sorting)
        self.gb_sort_combo.setCurrentIndex(0)
        self.gb_sort_combo.currentIndexChanged.connect(self._on_gamebanana_sort_changed)
        self.sort_combo.currentIndexChanged.connect(self._on_search_sort_changed)
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        if 'selected_search_game' not in self.app_state.local_config:
            default_game = self.modgame_combo.currentData() or 'deltarune'
            self.app_state.local_config['selected_search_game'] = default_game
            self.settings_manager.write_local_config()

        def on_modgame_changed():
            selected_game = self.modgame_combo.currentData() or 'deltarune'
            self.app_state.local_config['selected_search_game'] = selected_game
            self.settings_manager.write_local_config()
            self.app_state.current_page = 1
            self.search_display.load_mods_for_selected_game()
        self.modgame_combo.currentIndexChanged.connect(on_modgame_changed)
        self.tag_textedit.stateChanged.connect(lambda: (setattr(self.app_state, 'current_page', 1), self.search_display.update_filtered_mods()))
        self.tag_customization.stateChanged.connect(lambda: (setattr(self.app_state, 'current_page', 1), self.search_display.update_filtered_mods()))
        self.tag_gameplay.stateChanged.connect(lambda: (setattr(self.app_state, 'current_page', 1), self.search_display.update_filtered_mods()))
        self.tag_other.stateChanged.connect(lambda: (setattr(self.app_state, 'current_page', 1), self.search_display.update_filtered_mods()))
        self.search_button.clicked.connect(self.search_display.show_search_dialog)
        self.prev_page_btn.clicked.connect(self.search_display.prev_page)
        self.next_page_btn.clicked.connect(self.search_display.next_page)
        self.library_sort_ascending = False
        self.app_state.library_search_text = ''
        self._previous_mode = 'normal'
        library_builder = LibraryTabBuilder(self.app_state, self)
        self.library_tab_builder = library_builder
        self.library_tab = library_builder.build()
        library_widgets = library_builder.get_widgets()
        self.library_filters_widget = library_widgets['library_filters_widget']
        self.import_export_button = library_widgets.get('import_export_button')
        self.custom_executable_button = library_widgets.get('custom_executable_button')
        self.reset_custom_exe_button = library_widgets.get('reset_custom_exe_button')
        self.change_path_button = library_widgets.get('change_path_button')
        self.game_type_combo = library_widgets['game_type_combo']
        self.chapter_mode_checkbox = library_widgets['chapter_mode_checkbox']
        self.full_install_checkbox = library_widgets['full_install_checkbox']
        self.chapter_tabs_widget = library_widgets['chapter_tabs_widget']
        self.chapter_tabs_layout = library_widgets['chapter_tabs_layout']
        self.chapter_tab_buttons = library_widgets['chapter_tab_buttons']
        self.installed_mods_container = library_widgets['installed_mods_container']
        self.installed_mods_scroll = library_widgets['installed_mods_scroll']
        self.installed_mods_widget = library_widgets['installed_mods_widget']
        self.installed_mods_layout = library_widgets['installed_mods_layout']
        self.installed_mods_label = library_widgets.get('installed_mods_label')
        self.priority_button = library_widgets.get('priority_button')
        if self.priority_button:
            self.priority_button.clicked.connect(self.library_display.on_priority_button_click)
        self.create_modpack_button = library_widgets.get('create_modpack_button')
        if self.create_modpack_button:
            self.create_modpack_button.clicked.connect(self.library_display.on_create_modpack_button_click)
        self.fast_merging_checkbox = library_widgets.get('fast_merging_checkbox')
        self.fast_merging_label = library_widgets.get('fast_merging_label')
        if self.fast_merging_checkbox:
            fast_merging_enabled = self.app_state.local_config.get('fast_merging_enabled', False)
            self.fast_merging_checkbox.setChecked(fast_merging_enabled)
            self.fast_merging_checkbox.stateChanged.connect(self._on_fast_merging_changed)
        plugin_builder = PluginTabBuilder(self.app_state, self)
        self.plugin_tab_builder = plugin_builder
        self.plugins_tab = plugin_builder.build()
        plugin_widgets = plugin_builder.get_widgets()
        self.plugins_search_button = plugin_widgets['search_button']
        self.plugins_import_button = plugin_widgets['import_button']
        self.plugins_container = plugin_widgets['plugins_container']
        self.plugins_scroll = plugin_widgets['plugins_scroll']
        self.plugins_widget = plugin_widgets['plugins_widget']
        self.plugins_layout = plugin_widgets['plugins_layout']
        from controllers.plugin_display_controller import PluginDisplayController
        self.plugin_display = PluginDisplayController(self.app_state, self.feedback_manager, self.plugin_manager, self)
        self.plugins_search_button.clicked.connect(self.plugin_display.on_search_plugins)
        self.plugins_import_button.clicked.connect(self.plugin_display.on_import_plugin)
        self.library_sort_combo = library_widgets['library_sort_combo']
        self.library_sort_order_btn = library_widgets['library_sort_order_btn']
        self.library_tags_label = library_widgets['library_tags_label']
        self.library_tag_textedit = library_widgets['library_tag_textedit']
        self.library_tag_customization = library_widgets['library_tag_customization']
        self.library_tag_gameplay = library_widgets['library_tag_gameplay']
        self.library_tag_other = library_widgets['library_tag_other']
        self.library_tag_local = library_widgets['library_tag_local']
        self.library_tag_widgets = library_widgets['library_tag_widgets']
        self.library_search_button = library_widgets['library_search_button']
        if self.import_export_button:
            from controllers.mod_import_export_controller import ModImportExportController
            self.mod_import_export_controller = ModImportExportController(self.app_state, self.mod_manager, self)
            self.import_export_button.clicked.connect(self.mod_import_export_controller.show_import_export_dialog)
        self.game_type_combo.currentIndexChanged.connect(self.settings_ui.on_game_type_changed)
        self.chapter_mode_checkbox.stateChanged.connect(self.settings_ui.on_chapter_mode_changed)
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
        self._set_checkbox_checked_silently(self.chapter_mode_checkbox, saved_chapter_mode)
        self.game_type_combo.setEnabled(not saved_chapter_mode)
        self._set_checkbox_checked_silently(self.full_install_checkbox, saved_full_install)
        self.game_launch.set_full_install_checkbox_state(saved_full_install)
        self.app_state.is_installing_changed.connect(self.game_launch.update_button_state)
        self.app_state.is_installing_changed.connect(lambda v: self.mod_ops.set_install_buttons_enabled(not v))
        self.app_state.is_installing_changed.connect(lambda v: self._update_all_install_buttons())
        self.app_state.current_mode = 'chapter' if saved_chapter_mode else 'normal'
        self.game_launch.update_button_state()
        self._previous_mode = self.app_state.current_mode
        self.app_state.selected_chapter_id = None
        if saved_chapter_mode and hasattr(self, 'chapter_tabs_widget'):
            self.chapter_tabs_widget.setVisible(True)
        if saved_game_type == 'deltarunedemo':
            self.app_state.game_mode = DemoGameMode()
        elif saved_game_type == 'undertale':
            self.app_state.game_mode = UndertaleGameMode()
        elif saved_game_type == 'undertaleyellow':
            from models.game_modes import UndertaleYellowGameMode
            self.app_state.game_mode = UndertaleYellowGameMode()
        elif saved_game_type == 'pizzatower':
            from models.game_modes import PizzaTowerGameMode
            self.app_state.game_mode = PizzaTowerGameMode()
        elif saved_game_type == 'sugaryspire':
            from models.game_modes import SugarySpireGameMode
            self.app_state.game_mode = SugarySpireGameMode()
        else:
            self.app_state.game_mode = FullGameMode()
        self.app_state.game_mode_changed.connect(self._on_game_mode_updated_by_state)
        self._update_checkbox_visibility()
        self._update_change_path_button_text()
        self._setup_chapter_tabs()
        if saved_chapter_mode and hasattr(self, '_show_chapter_mode_instruction'):
            QTimer.singleShot(600, self._show_chapter_mode_instruction)

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
            QTimer.singleShot(800, update_priority_button)
        elif not saved_chapter_mode:
            QTimer.singleShot(500, self.library_display.update_display)

            def update_priority_button_normal():
                self.library_display._update_priority_button_visibility()
            QTimer.singleShot(800, update_priority_button_normal)
        QTimer.singleShot(700, self.library_display.update_mod_widgets_slot_status)
        self.main_tab_widget.addTab(self.search_mods_tab, tr('ui.search_tab'))
        self.main_tab_widget.addTab(self.library_tab, tr('ui.library_tab'))
        self.main_tab_widget.addTab(self.plugins_tab, tr('ui.plugins_tab'))
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
        self.settings_title_label = settings_widgets['settings_title_label']
        self.language_label = settings_widgets['language_label']
        self.language_combo = settings_widgets['language_combo']
        self.beta_updates_checkbox = settings_widgets['beta_updates_checkbox']
        self.clear_logs_checkbox = settings_widgets['clear_logs_checkbox']
        self.fullscreen_checkbox = settings_widgets['fullscreen_checkbox']
        self.hide_library_filters_checkbox = settings_widgets['hide_library_filters_checkbox']
        self.launch_via_steam_checkbox = settings_widgets['launch_via_steam_checkbox']
        self.use_portproton_checkbox = settings_widgets.get('use_portproton_checkbox')
        self.select_portproton_path_button = settings_widgets.get('select_portproton_path_button')
        self.portproton_path_label = settings_widgets.get('portproton_path_label')
        self.portproton_frame = settings_widgets.get('portproton_frame')
        self.hide_mods_without_files_checkbox = settings_widgets['hide_mods_without_files_checkbox']
        self.open_deltahub_folder_button = settings_widgets['open_deltahub_folder_button']
        self.customization_button = settings_widgets['customization_button']
        self.settings_customization_button = settings_widgets['settings_customization_button']
        self.reset_button = settings_widgets['reset_button']
        self.disable_background_checkbox = settings_widgets['disable_background_checkbox']
        self.disable_splash_checkbox = settings_widgets['disable_splash_checkbox']
        self.back_button_cust = settings_widgets['back_button_cust']
        self.change_background_button = settings_widgets['change_background_button']
        self.change_logo_button = settings_widgets['change_logo_button']
        self.background_music_button = settings_widgets['background_music_button']
        self.startup_sound_button = settings_widgets['startup_sound_button']
        self.custom_style_frame = settings_widgets['custom_style_frame']
        self.color_widgets = settings_widgets['color_widgets']
        self.color_labels = settings_widgets['color_labels']
        self.color_config = settings_widgets['color_config']
        self.theme_button = settings_widgets['theme_button']
        self.changelog_text_edit = settings_widgets['changelog_text_edit']
        self.changelog_button = settings_widgets['changelog_button']
        self.report_bug_button = settings_widgets['report_bug_button']
        self.language_combo.currentTextChanged.connect(lambda: self.settings_ui.on_language_changed(self.language_combo.currentData()))
        self.beta_updates_checkbox.stateChanged.connect(self.settings_ui.on_toggle_beta_updates)
        self.clear_logs_checkbox.stateChanged.connect(self.settings_ui.on_toggle_clear_logs)
        self.fullscreen_checkbox.stateChanged.connect(self.settings_ui.on_toggle_fullscreen)
        self.hide_library_filters_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_library_filters)
        self.launch_via_steam_checkbox.stateChanged.connect(self.settings_ui.on_toggle_steam_launch)
        if self.use_portproton_checkbox:
            self.use_portproton_checkbox.stateChanged.connect(self.settings_ui.on_toggle_portproton)
            self.use_portproton_checkbox.stateChanged.connect(self._update_portproton_ui)
        if self.select_portproton_path_button:
            self.select_portproton_path_button.clicked.connect(self._select_portproton_path)
        self.hide_mods_without_files_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_mods_without_files)
        if self.change_path_button:
            self.change_path_button.clicked.connect(self._prompt_for_game_path)
        if self.custom_executable_button:
            self.custom_executable_button.clicked.connect(self._select_custom_executable_file)
        if self.reset_custom_exe_button:
            self.reset_custom_exe_button.clicked.connect(self._reset_custom_executable)
        self.open_deltahub_folder_button.clicked.connect(self._open_deltahub_folder)
        self.customization_button.clicked.connect(lambda: self._switch_settings_page(self.settings_customization_page))
        self.reset_button.clicked.connect(self.settings_ui.reset_settings)
        self.disable_background_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_background)
        self.disable_splash_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_splash)
        self.back_button_cust.clicked.connect(self._go_back_to_settings_menu)
        self.change_background_button.clicked.connect(self.theme.on_background_button_click)
        self.change_logo_button.setText(self.customization_manager.get_logo_button_text())
        self.change_logo_button.clicked.connect(self.theme.on_logo_button_click)
        self.background_music_button.setText(self.customization_manager.get_background_music_button_text())
        self.background_music_button.clicked.connect(self.theme.on_background_music_button_click)
        self.startup_sound_button.setText(self.customization_manager.get_startup_sound_button_text())
        self.startup_sound_button.clicked.connect(self.theme.on_startup_sound_button_click)
        self.theme_button.clicked.connect(self.theme.on_theme_button_click)

        def pick_color_for_edit(target_edit):
            if (color := QColorDialog.getColor()).isValid():
                target_edit.setText(color.name())
                self.theme.on_custom_style_edited()
        for key in self.color_config.keys():
            line_edit = self.color_widgets[key]
            btn = settings_widgets[f'color_btn_{key}']
            reset_btn = settings_widgets[f'color_reset_{key}']
            line_edit.editingFinished.connect(self.theme.on_custom_style_edited)
            btn.clicked.connect(lambda _, le=line_edit: pick_color_for_edit(le))
            reset_btn.clicked.connect(lambda _, le=line_edit: (le.clear(), self.theme.on_custom_style_edited()))
        self.changelog_button.clicked.connect(lambda: self.settings_ui.toggle_settings_view(show_changelog=True))
        self.report_bug_button.clicked.connect(self.settings_ui.show_report_bug_dialog)
        self.search_display.update_filtered_mods()
        self.main_layout.addWidget(self.settings_widget)
        self.app_state.current_settings_page = self.settings_menu_page
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.setWindowIcon(QIcon(resource_path('assets/icons/icon.ico')))

    def _on_mods_loaded(self):
        if self.initialization_timer and self.initialization_timer.isActive():
            self.initialization_timer.stop()
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        if hasattr(self.app_state, 'pending_announce_check') and self.app_state.pending_announce_check and (not self.app_state.update_in_progress):
            QTimer.singleShot(500, self._check_and_show_announce)

    def _force_finish_initialization(self):
        if self.app_state.initialization_completed:
            return
        self.app_state.mods_loaded = True
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        if hasattr(self.app_state, 'pending_announce_check') and self.app_state.pending_announce_check and (not self.app_state.update_in_progress):
            QTimer.singleShot(500, self._check_and_show_announce)

    def _try_start_background_music(self):
        if getattr(self, 'is_shown_to_user', False) and self.isVisible():
            self.customization_manager.maybe_start_background_music(force=True)

    def _on_fast_merging_changed(self, state):
        fast_merging_enabled = state == Qt.CheckState.Checked or state == 2
        self.app_state.local_config['fast_merging_enabled'] = fast_merging_enabled
        self.settings_manager.write_local_config()
        logging.debug(f'Fast merging setting changed: {fast_merging_enabled}')

    def _on_library_filter_changed(self):
        self.library_display.update_display()

    def _on_search_sort_changed(self):
        if not hasattr(self, 'search_display'):
            return
        if hasattr(self, 'sort_combo'):
            sort_index = self.sort_combo.currentIndex()
            self.app_state.local_config['search_sort_index'] = sort_index
            self.settings_manager.write_local_config()
        self.search_display.update_filtered_mods()

    def _on_sort_refresh_complete(self):
        try:
            logging.debug('AppWindow: _on_sort_refresh_complete called (deprecated, sort is now non-blocking)')
            self.app_state.gamebanana_loading = False
            if hasattr(self, 'search_display'):
                if hasattr(self.search_display, '_update_display_in_progress'):
                    self.search_display._update_display_in_progress = False
        except Exception as e:
            logging.warning(f'Error in _on_sort_refresh_complete: {e}', exc_info=True)
            self.app_state.gamebanana_loading = False

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
        self.search_display.update_filtered_mods()

    def _on_mods_per_page_changed(self, value: int):
        try:
            self.app_state.mods_per_page = value
            self.app_state.local_config['mods_per_page'] = value
            self.settings_manager.write_local_config()
            self.app_state.current_page = 1
            self.search_display.update_filtered_mods()
            logging.info(f'Mods per page changed to {value}')
        except Exception as e:
            logging.error(f'Error in _on_mods_per_page_changed: {e}', exc_info=True)

    def _on_auto_sorting_changed(self, state: int):
        try:
            from PyQt6.QtCore import Qt
            is_checked = state == Qt.CheckState.Checked.value
            self.app_state.auto_sorting = is_checked
            self.app_state.local_config['auto_sorting'] = is_checked
            self.settings_manager.write_local_config()
            if is_checked:
                self.search_display.update_filtered_mods(preserve_page=True)
            logging.info(f'Auto-sorting changed to {is_checked}')
        except Exception as e:
            logging.error(f'Error in _on_auto_sorting_changed: {e}', exc_info=True)

    def _on_gamebanana_sort_changed(self, index: int):
        try:
            if not hasattr(self, 'gb_sort_combo'):
                return
            new_sort = self.gb_sort_combo.currentData()
            if not new_sort:
                return
            old_sort = getattr(self.app_state, 'gamebanana_sort', 'default')
            if old_sort == new_sort:
                return
            if hasattr(self, '_gamebanana_sort_timer') and self._gamebanana_sort_timer:
                try:
                    self._gamebanana_sort_timer.stop()
                    self._gamebanana_sort_timer.deleteLater()
                except (RuntimeError, ValueError):
                    pass
                self._gamebanana_sort_timer = None
            self._gamebanana_sort_change_in_progress = True
            self.app_state.gamebanana_sort = new_sort
            self.app_state.gamebanana_loaded_pages.clear()
            if hasattr(self, 'search_display'):
                if hasattr(self.search_display, '_update_display_in_progress'):
                    self.search_display._update_display_in_progress = False
                if hasattr(self.search_display, '_update_display_debounce'):
                    try:
                        self.search_display._update_display_debounce.cancel()
                    except Exception:
                        pass
                if hasattr(self.search_display, '_cleanup_details_threads'):
                    self.search_display._cleanup_details_threads()
                if hasattr(self.search_display, '_load_more_threads'):
                    for thread in list(self.search_display._load_more_threads):
                        if thread and thread.isRunning():
                            if hasattr(thread, 'cancel'):
                                thread.cancel()
                    self.search_display._load_more_threads.clear()
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                self.app_state.all_mods = [mod for mod in self.app_state.all_mods if not ((getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)) and (getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)).startswith('gb_'))]
            self.app_state.current_page = 1
            if hasattr(self.app_state, 'filtered_mods'):
                self.app_state.filtered_mods = []
            try:
                if hasattr(self, 'refresh_controller'):
                    if hasattr(self.refresh_controller, 'fetch_thread') and self.refresh_controller.fetch_thread and self.refresh_controller.fetch_thread.isRunning():
                        self.refresh_controller._stop_fetch_thread()
                    if hasattr(self.refresh_controller, 'metadata_thread') and self.refresh_controller.metadata_thread:
                        try:
                            if hasattr(self.refresh_controller.metadata_thread, 'cancel'):
                                self.refresh_controller.metadata_thread.cancel()
                            if self.refresh_controller.metadata_thread.isRunning():
                                try:
                                    self.refresh_controller.metadata_thread.mod_updated.disconnect()
                                    self.refresh_controller.metadata_thread.finished.disconnect()
                                except (TypeError, RuntimeError):
                                    pass
                                if self.refresh_controller.metadata_thread.isRunning():
                                    logging.debug('AppWindow: Metadata thread still running after sort change, will clean up via finished signal.')
                            self.refresh_controller.metadata_thread.deleteLater()
                            self.refresh_controller.metadata_thread = None
                        except Exception as e:
                            logging.warning(f'AppWindow: Error stopping metadata thread on sort change: {e}')
            except Exception:
                pass
            from PyQt6.QtCore import QTimer

            def trigger_refresh():
                try:
                    if not hasattr(self, '_gamebanana_sort_change_in_progress') or not self._gamebanana_sort_change_in_progress:
                        return
                    self.app_state.gamebanana_loading = False
                    if not hasattr(self.app_state, 'mods_loaded') or not self.app_state.mods_loaded:
                        self.app_state.mods_loaded = True
                    if hasattr(self, 'refresh_controller'):

                        def update_callback():
                            try:
                                if hasattr(self, '_gamebanana_sort_change_in_progress'):
                                    self._gamebanana_sort_change_in_progress = False
                                if hasattr(self, 'search_display'):

                                    def async_update():
                                        try:
                                            self.search_display.update_filtered_mods()
                                            self.app_state.current_page = 1
                                            QTimer.singleShot(50, lambda: self.search_display.update_display())
                                        except Exception as e:
                                            logging.error(f'AppWindow: Error in async_update after sort change: {e}', exc_info=True)
                                            if hasattr(self, '_gamebanana_sort_change_in_progress'):
                                                self._gamebanana_sort_change_in_progress = False
                                    QTimer.singleShot(0, async_update)
                            except Exception as e:
                                logging.error(f'AppWindow: Error in update_callback after sort change: {e}', exc_info=True)
                                if hasattr(self, '_gamebanana_sort_change_in_progress'):
                                    self._gamebanana_sort_change_in_progress = False
                        self.refresh_controller.refresh_mods_list(is_initial=False, on_fetch_finished_kwargs={'update_filtered_mods_callback': update_callback})
                    elif hasattr(self, 'search_display'):

                        def async_update():
                            try:
                                self.search_display.update_filtered_mods()
                                if hasattr(self, '_gamebanana_sort_change_in_progress'):
                                    self._gamebanana_sort_change_in_progress = False
                            except Exception as e:
                                logging.error(f'AppWindow: Error in async_update after sort change: {e}', exc_info=True)
                                if hasattr(self, '_gamebanana_sort_change_in_progress'):
                                    self._gamebanana_sort_change_in_progress = False
                        QTimer.singleShot(0, async_update)
                except Exception as e:
                    logging.error(f'AppWindow: Error in trigger_refresh after sort change: {e}', exc_info=True)
                    if hasattr(self, '_gamebanana_sort_change_in_progress'):
                        self._gamebanana_sort_change_in_progress = False
            self._gamebanana_sort_timer = QTimer()
            self._gamebanana_sort_timer.setSingleShot(True)
            self._gamebanana_sort_timer.timeout.connect(trigger_refresh)
            self._gamebanana_sort_timer.start(300)
        except Exception as e:
            logging.error(f'AppWindow: Error in _on_gamebanana_sort_changed: {e}', exc_info=True)
            if hasattr(self, '_gamebanana_sort_change_in_progress'):
                self._gamebanana_sort_change_in_progress = False

    def _update_checkbox_visibility(self):
        game_type = self.game_type_combo.currentData()
        if game_type == 'deltarune':
            self.chapter_mode_checkbox.setVisible(True)
            self.full_install_checkbox.setVisible(False)
        elif game_type == 'deltarunedemo' or game_type == 'undertaleyellow' or game_type == 'sugaryspire':
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
                self._set_checkbox_checked_silently(self.chapter_mode_checkbox, False)
                if getattr(self.app_state, 'current_mode', 'normal') != 'normal':
                    self.app_state.current_mode = 'normal'
                self.game_type_combo.setEnabled(True)
            self.slot_manager.load_used_mods_state()
            self.library_display.update_display()
            self._update_change_path_button_text()
        except Exception:
            pass

    def _update_pagination_controls(self):
        self.search_display.update_pagination()

    def _update_change_path_button_text(self):
        if self.change_path_button:
            self.change_path_button.setText(self.app_state.game_mode.path_change_button_text)

    def _full_install_tooltip(self) -> str:
        if platform.system() == 'Darwin':
            return tr('tooltips.macos_install_unavailable')
        from models.game_modes import UndertaleYellowGameMode, SugarySpireGameMode
        if isinstance(self.app_state.game_mode, SugarySpireGameMode):
            return tr('tooltips.full_spire_install_instructions')
        elif isinstance(self.app_state.game_mode, UndertaleYellowGameMode):
            return tr('tooltips.full_yellow_install_instructions')
        return tr('tooltips.full_install_instructions')

    def _safe_set_parent_none(self, obj):
        try:
            if obj:
                obj.setParent(None)
        except Exception:
            pass

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
                self.slot_manager.toggle_direct_launch_for_chapter(chapter_id)
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
                import logging
                logging.debug(f"Failed to parse color '{bg_color_str}': {e}")
                painter.fillRect(self.rect(), QColor('rgba(0, 0, 0, 200)'))
        super().paintEvent(event)

    def _initialize_mutual_exclusions(self):
        direct_launch_slot_id = self.app_state.local_config.get('direct_launch_slot_id', SLOT_ID_UNIVERSAL)
        is_chapter_mode = self.app_state.current_mode == 'chapter'
        is_deltarune = isinstance(self.app_state.game_mode, FullGameMode)
        should_block = is_deltarune and is_chapter_mode and (direct_launch_slot_id >= 0)
        if not hasattr(self, 'launch_via_steam_checkbox'):
            return
        self.launch_via_steam_checkbox.setEnabled(not should_block)
        self.theme.apply_theme()

    def _post_show_initialization(self):
        is_first_launch = not self.app_state.local_config.get('first_launch_splash_shown', False)
        if is_first_launch and getattr(self, '_splash_was_shown', False):
            self.app_state.local_config['first_launch_splash_shown'] = True
            self.app_state.local_config['disable_splash'] = True
            self.settings_manager.write_local_config()
        self.app_state.has_internet = check_internet_connection()
        if not self.app_state.has_internet:
            logging.info('No internet connection detected, running in offline mode')
            self.app_state.global_settings = {}
        else:
            self._init_session()
            try:
                import requests
                from config.constants import CLOUD_FUNCTIONS_BASE_URL
                from utils.network_utils import get_session
                response = get_session(self.app_state).get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
                if response.status_code == 200:
                    self.app_state.global_settings = response.json() or {}
            except requests.RequestException:
                self.feedback_manager.update_status(tr('status.global_settings_load_failed'), UI_COLORS['status_warning'])
                self.app_state.has_internet = False
        if not self.is_shortcut_launch and self.app_state.has_internet:
            self.app_state.pending_announce_check = True
        if localization_manager.get_current_language() == 'ru':
            changelog_url = self.app_state.global_settings.get('changelog_ru_url', self.app_state.global_settings.get('changelog_url'))
        else:
            changelog_url = self.app_state.global_settings.get('changelog_en_url', self.app_state.global_settings.get('changelog_url'))
        if changelog_url and self.app_state.has_internet:
            self.changelog_thread = QThread(self)
            self.changelog_worker = FetchChangelogWorker(changelog_url.strip())
            self.changelog_worker.moveToThread(self.changelog_thread)
            self.changelog_worker.finished.connect(self.changelog_text_edit.setMarkdown)
            self.changelog_thread.started.connect(self.changelog_worker.run)
            self.changelog_thread.start()
        else:
            self.changelog_text_edit.setMarkdown(tr('status.changelog_load_failed'))
        if is_game_running():
            self.feedback_manager.update_status(tr('status.deltarune_already_running'), UI_COLORS['status_error'])
            return
        self._load_local_data()
        self.app_state.game_path = self.app_state.local_config.get('game_path', '')
        self.app_state.demo_game_path = self.app_state.local_config.get('demo_game_path', '')
        self.app_state.undertale_game_path = self.app_state.local_config.get('undertale_game_path', '')
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
            self._set_checkbox_checked_silently(self.chapter_mode_checkbox, saved_chapter_mode)
        self._set_checkbox_checked_silently(self.disable_background_checkbox, self.app_state.local_config.get('background_disabled', False))
        self._set_checkbox_checked_silently(self.disable_splash_checkbox, self.app_state.local_config.get('disable_splash', False))
        self.beta_updates_checkbox.setChecked(self.app_state.local_config.get('beta_updates_enabled', False))
        self.clear_logs_checkbox.setChecked(self.app_state.local_config.get('clear_logs_on_startup', False))
        self.fullscreen_checkbox.setChecked(self.app_state.local_config.get('fullscreen_enabled', False))
        if hasattr(self, 'hide_library_filters_checkbox'):
            self.hide_library_filters_checkbox.setChecked(self.app_state.local_config.get('hide_library_filters', False))
        self._update_change_path_button_text()
        self.theme.update_background_button_state()
        self.hide_mods_without_files_checkbox.setChecked(self.app_state.local_config.get('hide_mods_without_files', False))
        self.launch_via_steam_checkbox.setChecked(self.app_state.local_config.get('launch_via_steam', False))
        if self.use_portproton_checkbox:
            self.use_portproton_checkbox.setChecked(self.app_state.local_config.get('use_portproton', False))
            self._update_portproton_ui()
        self._initialize_mutual_exclusions()
        self.settings_ui.on_toggle_steam_launch()
        self.theme.apply_theme()
        try:
            from workers.background_workers import ModScanThread
            from utils.path_utils import get_user_data_root
            cache_dir = os.path.join(get_user_data_root(), 'cache')
            self._mod_scan_thread = ModScanThread(self.app_state.mods_dir, self, cache_dir=cache_dir)
            self._mod_scan_thread.scan_completed.connect(self._on_mod_scan_finished)
            self._mod_scan_thread.start()
            self.status_label.setText(tr('status.scanning_mods'))
        except Exception as e:
            logging.error(f'AppWindow: Failed to start mod scan thread: {e}', exc_info=True)
            self.feedback_manager.update_status(tr('status.mod_scan_init_error', details=str(e)), UI_COLORS['status_error'])
            try:
                self._on_mod_scan_finished({})
            except Exception as scan_error:
                logging.error(f'AppWindow: Failed to handle mod scan error: {scan_error}', exc_info=True)
        if not self.game_launcher._find_and_validate_game_path(is_initial=True):
            self.action_button.setEnabled(False)

    def _on_mod_scan_finished(self, scan_cache: dict):
        try:
            if hasattr(self.mod_manager, '_mods_cache') and hasattr(self.mod_manager, '_cache_lock'):
                with self.mod_manager._cache_lock:
                    self.mod_manager._mods_cache = scan_cache
                    self.mod_manager._mods_cache_valid = True
            QTimer.singleShot(0, self.mod_manager.load_local_mods)
            saved_chapter_mode = self.app_state.local_config.get('chapter_mode_enabled', False)
            self.setEnabled(False)
            QTimer.singleShot(500, lambda: (self._load_mods_and_build_list_synchronously(saved_chapter_mode), self.setEnabled(True)))
            self._load_used_mods_debounce.call(self.slot_manager.load_used_mods_state)
        except Exception as e:
            logging.error(f'AppWindow: Error in _on_mod_scan_finished: {e}', exc_info=True)
            self.feedback_manager.update_status(tr('status.mod_scan_error', details=str(e)), UI_COLORS['status_error'])
            self.setEnabled(True)

    def _load_mods_and_build_list_synchronously(self, saved_chapter_mode=False):
        try:
            logging.info('AppWindow: Starting mods loading in background before window show')

            def update_installed_mods_callback():
                is_chapter_mode = self.app_state.current_mode == 'chapter'
                selected_id = self.app_state.selected_chapter_id
                if is_chapter_mode and selected_id is None:
                    if hasattr(self, '_show_chapter_mode_instruction'):
                        self._show_chapter_mode_instruction()
                else:
                    self.library_display.update_display()
                    if not saved_chapter_mode:
                        self.app_state.library_initialized = True

            def update_filtered_mods_callback():
                try:
                    logging.info('AppWindow: Building mods list after fetch (from callback)')
                    if hasattr(self, 'search_display'):
                        self.search_display.update_filtered_mods(preserve_page=False)
                    logging.info('AppWindow: Mods list built successfully (from callback)')
                except Exception as e:
                    logging.error(f'AppWindow: Error building mods list: {e}', exc_info=True)
            on_fetch_finished_kwargs = {'update_filtered_mods_callback': update_filtered_mods_callback, 'update_installed_mods_callback': update_installed_mods_callback, 'update_action_button_callback': lambda: self.game_launch.update_button_state(), 'update_plugin_tabs_callback': self._update_plugin_tabs, 'mods_loaded_signal': self.mods_loaded_signal}
            self.refresh_controller.refresh_mods_list(is_initial=True, language_combo=self.language_combo, retranslate_callback=self._retranslate_ui, on_fetch_finished_kwargs=on_fetch_finished_kwargs)
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
        max_retries = 15
        init_completed = self.app_state.initialization_completed
        is_shown = self.app_state.is_shown_to_user
        is_visible = self.isVisible() if hasattr(self, 'isVisible') else False
        logging.info(f'_handle_update_info: retry_count={retry_count}, initialization_completed={init_completed}, is_shown_to_user={is_shown}, is_visible={is_visible}')
        if init_completed and (is_shown or is_visible):
            logging.info(f"_handle_update_info: Conditions met, showing update prompt for version {update_info.get('version', 'unknown')}")
            if is_visible and (not is_shown):
                self.app_state.is_shown_to_user = True
                logging.info('_handle_update_info: Set app_state.is_shown_to_user=True because window is visible')
            self.show_update_prompt.emit(update_info)
        elif retry_count < max_retries:
            logging.debug(f'_handle_update_info: Conditions not met, retrying in 1 second (retry {retry_count + 1}/{max_retries})')
            QTimer.singleShot(1000, lambda: self._handle_update_info(update_info, retry_count + 1))
        else:
            logging.warning(f'Update dialog: conditions not met after max retries (init_completed={init_completed}, is_shown={is_shown}, is_visible={is_visible}), showing dialog anyway')
            self.show_update_prompt.emit(update_info)

    def _perform_update_ui_prep(self):
        widgets = [self.action_button, self.chat_button, self.shortcut_button, self.open_deltahub_folder_button, self.change_background_button]
        if self.change_path_button:
            widgets.append(self.change_path_button)
        for widget in widgets:
            if widget:
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
            widgets = [self.action_button, self.chat_button, self.shortcut_button, self.open_deltahub_folder_button, self.change_background_button]
            if self.change_path_button:
                widgets.append(self.change_path_button)
            for w in widgets:
                if w:
                    w.setEnabled(True)
            try:
                if hasattr(self, 'top_refresh_button') and self.top_refresh_button:
                    self.top_refresh_button.setEnabled(True)
            except Exception:
                pass
            self.settings_button.setEnabled(True)
            self.game_launch.update_button_state()
        except Exception:
            pass

    def _on_progress_update(self, value: int):
        self.progress_bar.setValue(value)
        if value > 0 and (not self.progress_bar.isVisible()):
            self.progress_bar.setVisible(True)

    def _update_status(self, message: str, color: str = 'white'):
        if not self.is_shortcut_launch:
            from config.constants import UI_COLORS
            actual_color = UI_COLORS.get(color, color)
            if not self.status_label.wordWrap():
                self.status_label.setWordWrap(True)
            self.status_label.setText(message)
            self.status_label.setStyleSheet(f'color: {actual_color};')

    def _update_online_label(self, count: int):
        if not self.is_shortcut_launch and hasattr(self, 'online_label') and (self.online_label is not None):
            self._last_online_count = count
            display_count = '?' if count < 0 else count
            self.online_label.setText(f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=display_count)}")

    def _select_custom_executable_file(self):
        dlg_title = tr('ui.select_launch_file')
        from PyQt6.QtWidgets import QFileDialog
        filepath, _ = QFileDialog.getOpenFileName(self, dlg_title)
        if filepath:
            config_key = self.app_state.game_mode.get_custom_exec_config_key()
            self.app_state.local_config[config_key] = filepath
            self.settings_manager.write_local_config()
            self.settings_manager.settings_changed.emit()
            self._update_custom_executable_ui()

    def _reset_custom_executable(self):
        config_key = self.app_state.game_mode.get_custom_exec_config_key()
        self.app_state.local_config[config_key] = ''
        self.settings_manager.write_local_config()
        self.settings_manager.settings_changed.emit()
        self._update_custom_executable_ui()

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
        filepath = self.settings_manager.select_portproton_path()
        if filepath:
            self._update_portproton_ui()

    def _update_portproton_ui(self):
        if not self.portproton_frame or not self.portproton_path_label:
            return
        use_portproton = self.app_state.local_config.get('use_portproton', False)
        path = self.app_state.local_config.get('portproton_path', '')
        self.portproton_frame.setVisible(use_portproton and (self.use_portproton_checkbox.isEnabled() if self.use_portproton_checkbox else False))
        if self.portproton_frame.isVisible():
            if path:
                self.portproton_path_label.setText(tr('ui.currently_selected', filename=os.path.basename(path)))
            else:
                self.portproton_path_label.setText(tr('ui.file_not_selected') + ' (using PATH)')

    def _on_slot_manager_used_mods_updated(self):
        import logging
        logging.debug('Used mods updated, refreshing UI')
        if hasattr(self, 'library_display'):
            self.library_display.update_mod_widgets_slot_status()
            self.library_display._update_priority_button_visibility()
        if self.app_state.current_mode == 'chapter':
            selected_chapter_id = getattr(self.app_state, 'selected_chapter_id', None)
            if selected_chapter_id is not None:
                self.library_display.update_for_chapter_mode(selected_chapter_id)

    def _setup_chapter_tabs(self):
        from config.constants import SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
        chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
        for i, chapter_id in enumerate(chapter_ids):
            if i < len(self.chapter_tab_buttons):
                btn = self.chapter_tab_buttons[i]
                btn.clicked.connect(lambda checked, cid=chapter_id: self._on_chapter_tab_clicked(cid) if checked else None)
                btn.installEventFilter(self)
                setattr(btn, '_chapter_id', chapter_id)
        self._update_chapter_tabs_style()

    def _on_chapter_tab_clicked(self, chapter_id):
        import logging
        logging.debug(f'Chapter tab clicked: {chapter_id}')
        from config.constants import SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
        chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
        for i, btn in enumerate(self.chapter_tab_buttons):
            btn.setChecked(chapter_ids[i] == chapter_id if i < len(chapter_ids) else False)
        self.app_state.selected_chapter_id = chapter_id
        self.library_display.update_display()
        if hasattr(self.library_display, '_update_priority_button_visibility'):
            self.library_display._update_priority_button_visibility(chapter_id)

    def _update_chapter_tabs_style(self):
        if not hasattr(self, 'chapter_tab_buttons'):
            return
        from config.constants import SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4
        from ui.common.styling import get_theme_color
        chapter_ids = [SLOT_ID_MENU, SLOT_ID_CHAPTER_1, SLOT_ID_CHAPTER_2, SLOT_ID_CHAPTER_3, SLOT_ID_CHAPTER_4]
        direct_launch_chapter_id = self.app_state.local_config.get('direct_launch_slot_id', -1)
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        for i, (chapter_id, btn) in enumerate(zip(chapter_ids, self.chapter_tab_buttons)):
            is_direct_launch = direct_launch_chapter_id == chapter_id
            border_style = 'dashed' if is_direct_launch else 'solid'
            text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
            btn.setStyleSheet(f'\n                QPushButton#chapter_tab_{i} {{\n                    background-color: {button_color};\n                    border: 2px {border_style} {border_color};\n                    color: {text_color};\n                    font-weight: bold;\n                    font-size: 13px;\n                    border-radius: 0px;\n                    padding: 5px;\n                }}\n                QPushButton#chapter_tab_{i}:checked {{\n                    background-color: {hover_color};\n                    border: 3px {border_style} {border_color};\n                }}\n                QPushButton#chapter_tab_{i}:hover {{\n                    background-color: {hover_color};\n                }}\n            ')

    def _retranslate_texts(self):
        self.color_config = {'background': tr('ui.background_color'), 'button': tr('ui.elements_color'), 'border': tr('ui.border_color'), 'button_hover': tr('ui.hover_color'), 'text': tr('ui.main_text_color'), 'version_text': tr('ui.secondary_text_color')}
        self.settings_button.setText(tr('ui.back_button') if self.app_state.is_settings_view else tr('ui.settings_title'))
        self.online_label.setToolTip(tr('tooltips.online_counter'))
        self.telegram_button.setText(tr('buttons.telegram'))
        self.beta_updates_checkbox.setToolTip(tr('tooltips.beta_updates'))
        self.discord_button.setText(tr('buttons.discord'))
        self.shortcut_button.setText(tr('buttons.shortcut'))
        self.chat_button.setText(tr('ui.chat_button'))
        self.main_tab_widget.setTabText(0, tr('ui.search_tab'))
        self.main_tab_widget.setTabText(1, tr('ui.library_tab'))
        if hasattr(self, 'plugins_tab') and self.main_tab_widget.count() > 2:
            self.main_tab_widget.setTabText(2, tr('ui.plugins_tab'))
        self.sort_combo.setItemText(0, tr('ui.sort_by_downloads'))
        self.sort_combo.setItemText(1, tr('ui.sort_by_update_date'))
        self.sort_combo.setItemText(2, tr('ui.sort_by_creation_date'))
        self.modgame_combo.setItemText(0, tr('dropdowns.all_mods'))
        self.modgame_combo.setItemText(1, tr('ui.deltarune'))
        self.modgame_combo.setItemText(2, tr('ui.deltarunedemo'))
        self.modgame_combo.setItemText(3, tr('ui.undertale'))
        self.tags_label.setText(tr('ui.tags_label'))
        self.tag_textedit.setText(tr('tags.textedit'))
        self.tag_customization.setText(tr('tags.customization'))
        self.tag_gameplay.setText(tr('tags.gameplay'))
        self.tag_other.setText(tr('tags.other'))
        self.search_button.setToolTip(tr('ui.search_placeholder'))
        if hasattr(self, 'fast_merging_label') and self.fast_merging_label:
            self.fast_merging_label.setText(tr('ui.fast_merging'))
            self.fast_merging_label.setToolTip(tr('ui.fast_merging_tooltip'))
        if hasattr(self, 'fast_merging_checkbox') and self.fast_merging_checkbox:
            self.fast_merging_checkbox.setToolTip(tr('ui.fast_merging_tooltip'))
        self.prev_page_btn.setText(tr('ui.prev_page'))
        self.next_page_btn.setText(tr('ui.next_page'))
        if hasattr(self, 'mods_per_page_label'):
            self.mods_per_page_label.setText(tr('ui.mods_per_page_label'))
            self.mods_per_page_spinbox.setToolTip(tr('ui.mods_per_page_tooltip'))
        if hasattr(self, 'gb_sort_label'):
            self.gb_sort_label.setText(tr('ui.gamebanana_sort_label'))
            self.gb_sort_combo.setItemText(0, tr('ui.gamebanana_sort_default'))
            self.gb_sort_combo.setItemText(1, tr('ui.gamebanana_sort_new'))
            self.gb_sort_combo.setItemText(2, tr('ui.gamebanana_sort_updated'))
            self.gb_sort_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
        if hasattr(self, 'custom_executable_button') and self.custom_executable_button:
            self.custom_executable_button.setText(tr('buttons.custom_executable'))
            self.custom_executable_button.setToolTip(tr('tooltips.custom_executable_library'))
        if hasattr(self, 'reset_custom_exe_button') and self.reset_custom_exe_button:
            self._update_custom_executable_ui()
        if hasattr(self, 'auto_sorting_checkbox') and self.auto_sorting_checkbox:
            self.auto_sorting_checkbox.setText(tr('ui.auto_sorting'))
            self.auto_sorting_checkbox.setToolTip(tr('ui.auto_sorting_tooltip'))
        self.chapter_mode_checkbox.setText(tr('ui.chapter_mode'))
        self.full_install_checkbox.setText(tr('ui.full_install'))
        self.full_install_checkbox.setToolTip(self._full_install_tooltip())
        self.settings_title_label.setText(f"<h1>{tr('ui.settings_title')}</h1>")
        self.language_label.setText(tr('ui.language_label'))
        self.beta_updates_checkbox.setText(tr('ui.beta_updates'))
        self.clear_logs_checkbox.setText(tr('ui.clear_logs_on_startup'))
        self.clear_logs_checkbox.setToolTip(tr('tooltips.clear_logs_on_startup'))
        self.fullscreen_checkbox.setText(tr('ui.fullscreen'))
        self.fullscreen_checkbox.setToolTip(tr('tooltips.fullscreen_tooltip'))
        self.launch_via_steam_checkbox.setText(tr('ui.steam_launch'))
        self.launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>')
        if self.use_portproton_checkbox:
            self.use_portproton_checkbox.setText(tr('ui.use_portproton'))
            self.use_portproton_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>')
        if self.select_portproton_path_button:
            self.select_portproton_path_button.setText(tr('buttons.select_portproton_path'))
        self.hide_mods_without_files_checkbox.setText(tr('ui.hide_mods_without_files'))
        self.hide_mods_without_files_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.hide_mods_without_files') + '</body></html>')
        self._update_change_path_button_text()
        self.open_deltahub_folder_button.setText(tr('buttons.open_deltahub_folder'))
        self.customization_button.setText(tr('tags.customization'))
        self.reset_button.setText(tr('buttons.reset_settings'))
        self.back_button_cust.setText(tr('ui.back_button'))
        self.theme.update_background_button_state()
        self.background_music_button.setText(self.customization_manager.get_background_music_button_text())
        self.startup_sound_button.setText(self.customization_manager.get_startup_sound_button_text())
        self.disable_background_checkbox.setText(tr('checkboxes.disable_background'))
        if hasattr(self, 'priority_button') and self.priority_button:
            self.priority_button.setText(tr('ui.priority'))
        if hasattr(self, 'create_modpack_button') and self.create_modpack_button:
            self.create_modpack_button.setText(tr('ui.create_modpack_button'))
        if hasattr(self, 'library_sort_combo') and self.library_sort_combo:
            self.library_sort_combo.setItemText(0, tr('ui.sort_by_name'))
            self.library_sort_combo.setItemText(1, tr('ui.sort_by_date'))
        if hasattr(self, 'library_sort_order_btn') and self.library_sort_order_btn:
            tooltip_text = tr('ui.ascending') if self.library_sort_ascending else tr('ui.descending')
            self.library_sort_order_btn.setToolTip(tooltip_text)
        if hasattr(self, 'library_tags_label') and self.library_tags_label:
            self.library_tags_label.setText(tr('ui.tags_label'))
        if hasattr(self, 'library_tag_textedit') and self.library_tag_textedit:
            self.library_tag_textedit.setText(tr('tags.textedit'))
        if hasattr(self, 'library_tag_customization') and self.library_tag_customization:
            self.library_tag_customization.setText(tr('tags.customization'))
        if hasattr(self, 'library_tag_gameplay') and self.library_tag_gameplay:
            self.library_tag_gameplay.setText(tr('tags.gameplay'))
        if hasattr(self, 'library_tag_other') and self.library_tag_other:
            self.library_tag_other.setText(tr('tags.other'))
        if hasattr(self, 'library_tag_local') and self.library_tag_local:
            self.library_tag_local.setText(tr('tags.local'))
        if hasattr(self, 'library_search_button') and self.library_search_button:
            self.library_search_button.setToolTip(tr('ui.search_placeholder'))
        if hasattr(self, 'chapter_tab_buttons') and self.chapter_tab_buttons:
            chapter_tab_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
            for i, btn in enumerate(self.chapter_tab_buttons):
                if i < len(chapter_tab_names):
                    btn.setText(chapter_tab_names[i])
        if hasattr(self, 'installed_mods_label') and self.installed_mods_label:
            self.installed_mods_label.setText(tr('ui.installed_mods_label'))
        if hasattr(self, 'import_export_button') and self.import_export_button:
            self.import_export_button.setText(tr('ui.import_export_mod'))
        self.disable_splash_checkbox.setText(tr('checkboxes.disable_splash'))
        for key in self.color_widgets.keys():
            if key in self.color_labels:
                self.color_labels[key].setText(self.color_config[key])
        self.changelog_button.setText(tr('buttons.close') if self.app_state.is_changelog_view else tr('buttons.changelog'))
        if hasattr(self, 'report_bug_button') and self.report_bug_button:
            self.report_bug_button.setText(tr('buttons.report_bug'))
        if hasattr(self, 'theme_button') and self.theme_button:
            self.theme_button.setText(tr('buttons.theme_management'))

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
                                plugin_api = current_plugin.get('api')
                                if plugin_api:
                                    setattr(self, 'plugin_api', plugin_api)
                                try:
                                    new_widget = handler(self) if callable(handler) else None
                                    if isinstance(new_widget, QWidget):
                                        self.main_tab_widget.removeTab(current_index)
                                        self.main_tab_widget.insertTab(current_index, new_widget, tr(current_plugin['name_key']))
                                        self.main_tab_widget.setCurrentIndex(current_index)
                                finally:
                                    if hasattr(self, 'plugin_api'):
                                        delattr(self, 'plugin_api')
                            except Exception:
                                if hasattr(self, 'plugin_api'):
                                    delattr(self, 'plugin_api')
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
            self.theme.apply_theme()
            if hasattr(self, '_update_chapter_tabs_style'):
                self._update_chapter_tabs_style()
            try:
                if hasattr(self, 'online_label'):
                    self._update_online_label(getattr(self, '_last_online_count', 0))
            except Exception:
                pass
            from ui.common.styling import get_theme_color
            text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
            if hasattr(self, 'plugin_tab_builder'):
                plugin_lbl = self.plugin_tab_builder.widgets.get('installed_plugins_label')
                if plugin_lbl:
                    plugin_lbl.setStyleSheet(f'font-weight: bold; font-size: 16px; color: {text_color};')
            if hasattr(self, 'installed_mods_label') and self.installed_mods_label:
                self.installed_mods_label.setStyleSheet(f'font-weight: bold; font-size: 16px; color: {text_color};')
            checkbox_style = f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: 12px;\n                spacing: 5px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        '
            if hasattr(self, 'library_tag_widgets'):
                for cb in self.library_tag_widgets:
                    cb.setStyleSheet(checkbox_style)
            if hasattr(self, 'chapter_mode_checkbox'):
                self.chapter_mode_checkbox.setStyleSheet(f'color: {text_color};')
            if hasattr(self, 'full_install_checkbox'):
                self.full_install_checkbox.setStyleSheet(f'color: {text_color};')
            if hasattr(self, 'tag_textedit'):
                search_checkboxes = [self.tag_textedit, self.tag_customization, self.tag_gameplay, self.tag_other]
                if hasattr(self, 'auto_sorting_checkbox'):
                    search_checkboxes.append(self.auto_sorting_checkbox)
                for cb in search_checkboxes:
                    if cb:
                        cb.setStyleSheet(checkbox_style)
            self.search_display.update_filtered_mods()
            self.search_display.update_all_plaques_labels()
            self.library_display.update_display()
            self._update_pagination_controls()
            self.game_launch.update_button_state()
            if hasattr(self, 'plugins_search_button'):
                self.plugins_search_button.setText(tr('plugins.search_plugins'))
            if hasattr(self, 'plugins_import_button'):
                self.plugins_import_button.setText(tr('plugins.import_plugins'))
            if hasattr(self, 'plugin_tab_builder') and hasattr(self.plugin_tab_builder, 'widgets'):
                widgets = self.plugin_tab_builder.widgets
                if 'installed_plugins_label' in widgets:
                    widgets['installed_plugins_label'].setText(tr('plugins.installed_plugins'))
            if hasattr(self, 'plugin_display'):
                self.plugin_display.retranslate_plugin_widgets()
            self.update()
        finally:
            self._suppress_tab_handlers = False

    def closeEvent(self, event):
        self.customization_manager.stop_background_music()
        self._online_timer.stop()
        if self.is_shortcut_launch:
            super().closeEvent(event)
            return
        try:
            threads_to_stop = []
            if self.game_launcher.monitor_thread:
                threads_to_stop.append(self.game_launcher.monitor_thread)
            for attr in ('install_thread', 'full_install_thread', 'current_install_thread', 'changelog_thread'):
                thread = getattr(self, attr, None)
                if thread:
                    threads_to_stop.append(thread)
            if hasattr(self.refresh_controller, 'fetch_thread') and self.refresh_controller.fetch_thread:
                threads_to_stop.append(self.refresh_controller.fetch_thread)
            if hasattr(self.refresh_controller, 'details_thread') and self.refresh_controller.details_thread:
                threads_to_stop.append(self.refresh_controller.details_thread)
            if hasattr(self.refresh_controller, 'metadata_thread') and self.refresh_controller.metadata_thread:
                threads_to_stop.append(self.refresh_controller.metadata_thread)
            bg_loader = getattr(self, '_bg_loader', None)
            if bg_loader:
                threads_to_stop.append(bg_loader)
            for thread in threads_to_stop:
                self._safe_set_parent_none(thread)
                safe_stop_thread(thread, timeout=THREAD_WAIT_TIMEOUT, blocking=False)
            if self.presence_thread:
                self._safe_set_parent_none(self.presence_thread)
                safe_stop_thread(self.presence_thread, timeout=2000, blocking=False)
            self.game_launcher._cleanup_direct_launch_files()
            if hasattr(self.game_launcher, 'multi_mod_merger'):
                self.game_launcher.multi_mod_merger.cleanup_processes_and_temp_files()
            try:
                import psutil
                current_process = psutil.Process(os.getpid())
                children = current_process.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                gone, alive = psutil.wait_procs(children, timeout=1)
                for proc in alive:
                    try:
                        proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception as e:
                logging.debug(f'Error cleaning up child processes: {e}')
            self.settings_manager.save_window_geometry(self)
            QApplication.processEvents()
            self.hide()
        except Exception as e:
            logging.error(f'closeEvent: error during cleanup: {e}', exc_info=True)
        finally:
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
        protected_first_launch_splash_shown = self.app_state.local_config.get('first_launch_splash_shown')
        protected_disable_splash = self.app_state.local_config.get('disable_splash')
        self.app_state.local_config = self.settings_manager.read_json(self.app_state.config_path) or {}
        if protected_first_launch_splash_shown is not None:
            self.app_state.local_config['first_launch_splash_shown'] = protected_first_launch_splash_shown
        if protected_disable_splash is not None:
            self.app_state.local_config['disable_splash'] = protected_disable_splash
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
        if not self.app_state.has_internet:
            return
        try:
            from utils.network_utils import get_session
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            get_session(self.app_state).post(f'{CLOUD_FUNCTIONS_BASE_URL}/presenceHeartbeat', json={'sessionId': self.session_id}, timeout=5)
        except Exception:
            self.app_state.has_internet = False

    def _on_theme_changed_by_manager(self):
        self.theme.on_theme_changed_by_manager()

    def _show_library_search_dialog(self):
        self.app_state.library_search_text = ''
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
            self.game_launch.update_button_state()
        if is_initial and (not result):
            self.customization_manager.start_background_music()
        return result

    def _open_deltahub_folder(self):
        deltahub_path = get_user_data_root()
        if os.path.exists(deltahub_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(deltahub_path))
        else:
            logging.warning(f'DELTAHUB folder not found: {deltahub_path}')

    def _install_single_mod(self, mod, force=False):
        self.mod_ops.install_mod(mod, force)

    def _on_single_mod_install_finished(self, success):
        was_installed_before = False
        if self.app_state.current_task:
            was_installed_before = getattr(self.app_state.current_task, 'was_installed_before', False)
        self.mod_ops._on_install_complete(success, '', was_installed_before)

    def _show_chapter_mode_instruction(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        from ui.common.styling import clear_layout_widgets
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        instruction_widget = QLabel(tr('ui.chapter_mode_instruction'))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from ui.common.styling import get_theme_color
        secondary_text_color = get_theme_color(self.app_state.local_config, 'version_text', '#CCCCCC')
        border_color = get_theme_color(self.app_state.local_config, 'border', '#666666')
        instruction_widget.setStyleSheet(f'\n            QLabel {{\n                color: {secondary_text_color};\n                font-size: 14px;\n                font-style: italic;\n                padding: 20px;\n                border: 2px dashed {border_color};\n                background-color: rgba(255, 255, 255, 0.1);\n            }}\n        ')
        instruction_widget.setWordWrap(True)
        instruction_widget.setMinimumHeight(80)
        self.installed_mods_layout.insertWidget(self.installed_mods_layout.count() - 1, instruction_widget)

    def _on_toggle_full_install(self, state):
        self.app_state.is_full_install = bool(state)
        if hasattr(self, 'game_launch'):
            self.game_launch.set_full_install_checkbox_state(bool(state))
        if platform.system() == 'Darwin' and self.app_state.is_full_install:
            self.feedback_manager.show_message('info', 'dialogs.unavailable', tr('dialogs.macos_install_unavailable'))
            self._set_checkbox_checked_silently(self.full_install_checkbox, False)
            return
        self.game_launch.update_button_state()

    def _update_all_install_buttons(self):
        if hasattr(self, 'search_display'):
            self.search_display.update_search_plaques()

    def _on_refresh_clicked(self, is_initial=False):
        if not is_initial and (not self.is_shortcut_launch) and self.app_state.has_internet:
            if self._reload_global_settings():
                QTimer.singleShot(500, lambda: self._check_and_show_announce(force_check=True))

        def update_installed_mods_callback():
            is_chapter_mode = self.app_state.current_mode == 'chapter'
            selected_id = self.app_state.selected_chapter_id
            if is_chapter_mode and selected_id is None:
                if hasattr(self, '_show_chapter_mode_instruction'):
                    self._show_chapter_mode_instruction()
            else:
                self.library_display.update_display()
        self.refresh_controller.refresh_mods_list(is_initial=is_initial, language_combo=self.language_combo, retranslate_callback=self._retranslate_ui, on_fetch_finished_kwargs={'update_filtered_mods_callback': lambda: self.search_display.update_filtered_mods(preserve_page=False), 'update_installed_mods_callback': update_installed_mods_callback, 'update_action_button_callback': lambda: self.game_launch.update_button_state(), 'update_plugin_tabs_callback': self._update_plugin_tabs, 'mods_loaded_signal': self.mods_loaded_signal})

    def _update_plugin_tabs(self):
        if not hasattr(self, 'plugin_manager') or not hasattr(self, 'main_tab_widget'):
            return
        if self._handling_plugin_tab:
            return
        self._handling_plugin_tab = True
        self.plugin_manager.load_plugins()
        self._plugin_tab_map = self.plugin_manager.update_plugin_tabs(self.main_tab_widget, num_original_tabs=3)
        if hasattr(self, 'plugin_display'):
            self.plugin_display.update_display()
        self._handling_plugin_tab = False

    def _on_tab_changed(self, index):
        num_original_tabs = 3
        if getattr(self, '_suppress_tab_handlers', False):
            self.previous_tab_index = index
            return
        if index == 2:
            if hasattr(self, 'plugin_display'):
                self.plugin_display.update_display()
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
                            plugin_api = plugin.get('api')
                            if plugin_api:
                                setattr(self, 'plugin_api', plugin_api)
                            try:
                                new_widget = handler(self)
                            finally:
                                if hasattr(self, 'plugin_api'):
                                    delattr(self, 'plugin_api')
                        if isinstance(new_widget, QWidget):
                            self.main_tab_widget.removeTab(index)
                            self.main_tab_widget.insertTab(index, new_widget, tr(plugin['name_key']))
                            self.main_tab_widget.setCurrentIndex(index)
                            self.previous_tab_index = index
                        else:
                            self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
                    except Exception as e:
                        logging.error(f"Error running plugin '{plugin['name_key']}': {e}")
                        self.feedback_manager.show_message('error', 'errors.error', f"Failed to run plugin '{tr(plugin['name_key'])}':\n{e}")
                        self.main_tab_widget.setCurrentIndex(self.previous_tab_index)
                        if hasattr(self, 'plugin_api'):
                            delattr(self, 'plugin_api')
                    finally:
                        self._handling_plugin_tab = False
                    return
                else:
                    on_tab_open_handler = plugin.get('on_tab_open')
                    if callable(on_tab_open_handler):
                        try:
                            plugin_api = plugin.get('api')
                            if plugin_api:
                                setattr(self, 'plugin_api', plugin_api)
                            try:
                                on_tab_open_handler(self)
                            finally:
                                if hasattr(self, 'plugin_api'):
                                    delattr(self, 'plugin_api')
                        except Exception as e:
                            logging.debug(f"Error calling on_tab_open for plugin '{plugin.get('name_key', 'unknown')}': {e}")
            self.previous_tab_index = index
            return
        if index == 1:
            if not getattr(self.app_state, 'library_initialized', False):
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self.library_display.update_display)
                self.app_state.library_initialized = True
            self.previous_tab_index = index
        else:
            self.previous_tab_index = index

    def _reload_global_settings(self):
        if not self.app_state.has_internet:
            return
        try:
            import requests
            from config.constants import CLOUD_FUNCTIONS_BASE_URL
            from utils.network_utils import get_session
            response = get_session(self.app_state).get(f'{CLOUD_FUNCTIONS_BASE_URL}/getGlobalSettings', timeout=5)
            if response.status_code == 200:
                self.app_state.global_settings = response.json() or {}
                logging.info('_reload_global_settings: Global settings reloaded successfully')
                return True
        except requests.RequestException as e:
            logging.warning(f'_reload_global_settings: Failed to reload global settings: {e}')
        return False

    def _check_and_show_announce(self, retry_count=0, force_check=False):
        max_retries = 15
        init_completed = self.app_state.initialization_completed
        is_shown = self.app_state.is_shown_to_user
        is_visible = self.isVisible() if hasattr(self, 'isVisible') else False
        logging.info(f'_check_and_show_announce: retry_count={retry_count}, initialization_completed={init_completed}, is_shown_to_user={is_shown}, is_visible={is_visible}, force_check={force_check}')
        if init_completed and (is_shown or is_visible or force_check):
            if not self.app_state.global_settings:
                return
            announce = self.app_state.global_settings.get('announce', {})
            announce_version = announce.get('version', 0)
            if announce_version == 0:
                logging.info('_check_and_show_announce: Announce version is 0, announcements disabled')
                return
            saved_version = self.app_state.local_config.get('announce_version', 0)
            if saved_version == -1:
                logging.info('_check_and_show_announce: User has disabled announcements (version -1)')
                return
            if announce_version != saved_version:
                if localization_manager.get_current_language() == 'ru':
                    announce_message = announce.get('message_ru', '')
                else:
                    announce_message = announce.get('message_en', '')
                if not announce_message:
                    logging.info('_check_and_show_announce: No message for current language')
                    self._save_announce(announce_version)
                    return
                announce_link = announce.get('link', '')
                logging.info(f'_check_and_show_announce: Conditions met, showing announce dialog (version {announce_version}, saved {saved_version})')
                if is_visible and (not is_shown):
                    self.app_state.is_shown_to_user = True
                    logging.info('_check_and_show_announce: Set app_state.is_shown_to_user=True because window is visible')
                from ui.dialogs.announce_dialog import AnnounceDialog
                dialog = AnnounceDialog(announce_message, announce_link, self)
                dialog.accepted_with_ok.connect(lambda: self._save_announce(announce_version))
                dialog.exec()
                self.app_state.pending_announce_check = False
            else:
                logging.info(f'_check_and_show_announce: Announce version {announce_version} matches saved version, skipping')
        elif retry_count < max_retries:
            logging.debug(f'_check_and_show_announce: Conditions not met, retrying in 1 second (retry {retry_count + 1}/{max_retries})')
            QTimer.singleShot(1000, lambda: self._check_and_show_announce(retry_count + 1, force_check))
        else:
            logging.warning(f'Announce dialog: conditions not met after max retries (init_completed={init_completed}, is_shown={is_shown}, is_visible={is_visible}), skipping announce')

    def _save_announce(self, version: int):
        self.app_state.local_config['announce_version'] = version
        self.settings_manager.write_local_config()
        logging.info(f'_save_announce: Saved announce version {version} to config')

    def _prompt_for_update(self, update_info):
        from config.constants import LAUNCHER_VERSION, UI_COLORS
        logging.info(f"_prompt_for_update called with version {update_info.get('version', 'unknown')}")
        if self.app_state.update_in_progress:
            logging.warning('_prompt_for_update: Update already in progress, ignoring')
            return
        if self.app_state.game_is_running:
            logging.info('_prompt_for_update: Game is running, adding to pending dialogs')
            self.app_state.pending_dialogs.append(('update', update_info))
            return
        logging.info('_prompt_for_update: Showing update dialog')
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
            logging.info('_prompt_for_update: User accepted update')
            if hasattr(self, '_perform_update_ui_prep'):
                self._perform_update_ui_prep()
            self.update_checker.perform_update(update_info)
        else:
            logging.info('_prompt_for_update: User rejected update')
            self.app_state.update_in_progress = False
            self.feedback_manager.update_status(tr('status.update_rejected'), UI_COLORS['status_info'])
            if hasattr(self.app_state, 'pending_announce_check') and self.app_state.pending_announce_check:
                QTimer.singleShot(500, self._check_and_show_announce)

    def _open_chat(self):
        if not check_internet_connection():
            self.feedback_manager.show_message('warning', 'chat.no_internet', tr('chat.no_internet'))
            return
        chat_window = ChatWindow(self.app_state, self)
        chat_window.exec()

    def _migrate_settings_config_file(self):
        old_config_path = os.path.join(self.app_state.config_dir, 'config.json')
        new_config_path = os.path.join(self.app_state.config_dir, 'settings.json')
        if os.path.exists(old_config_path) and (not os.path.exists(new_config_path)):
            shutil.move(old_config_path, new_config_path)
            logging.info('Migrated settings config.json to settings.json')

    def _on_search_ui_button_text_update(self, widget_name: str, text: str):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, 'setText'):
            widget.setText(text)

    def _on_search_ui_button_tooltip_update(self, widget_name: str, tooltip: str):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, 'setToolTip'):
            widget.setToolTip(tooltip)

    def _on_search_ui_button_enabled_update(self, widget_name: str, enabled: bool):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, 'setEnabled'):
            widget.setEnabled(enabled)

    def _on_search_ui_label_text_update(self, widget_name: str, text: str):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, 'setText'):
            widget.setText(text)

    def _on_search_ui_widget_updates_enabled(self, widget_name: str, enabled: bool):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, 'setUpdatesEnabled'):
            widget.setUpdatesEnabled(enabled)

    def _show_pending_dialogs(self):
        if not self.app_state.pending_dialogs:
            return
        pending = self.app_state.pending_dialogs.copy()
        self.app_state.pending_dialogs.clear()
        for dialog_type, dialog_data in pending:
            if dialog_type == 'update':
                self._prompt_for_update(dialog_data)
