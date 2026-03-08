import os
import platform
import shutil
import uuid
import webbrowser
import argparse
from typing import Optional
import logging
from PyQt6.QtCore import QTranslator, Qt, QEvent, QThread, QTimer, pyqtSignal, QPoint, QObject, QRectF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel, QLineEdit, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget, QHBoxLayout, QSizePolicy, QColorDialog, QSpinBox
from services.localization_service import localization_service, tr
from models.game_modes import DeltaruneGame, get_game
from config.constants import UI_COLORS, SOCIAL_LINKS, ONLINE_UPDATE_INTERVAL, INITIALIZATION_TIMEOUT, CLOUD_FUNCTIONS_BASE_URL
from ui.utils.ui_utils import DebounceTimer, UIAnimator
from ui.widgets.shared.custom_controls import AnimatedToolTip
from ui.dialogs.about_dialog import AboutDialog
from ui.dialogs.changelog_dialog import ChangelogDialog
from ui.widgets.shared.custom_title_bar import CustomTitleBar
from ui.common.styling import get_theme_color, get_border_radius, display_hex_to_qt_hex, clamp_border_radius, apply_rounded_mask
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
from adapters.gamebanana_adapter import GameBananaAPI
from services.mod_service import ModManager
from services.launch_service import GameLauncher
from services.updatecheck_service import UpdateChecker
from services.settings_service import SettingsManager
from ui.builders.search_tab_builder import ModsBrowserTabBuilder
from ui.builders.settings_view_builder import SettingsViewBuilder
from services.plugin_service import PluginManager
from services.customization_service import CustomizationManager
from services.used_mods_service import UsedModsManager
_translator = QTranslator()
_lock_file = None


def _is_pure_black_color(color: QColor) -> bool:
    return color.isValid() and color.red() == 0 and color.green() == 0 and color.blue() == 0


def _get_black_color_picker_seed(color: QColor) -> QColor:
    return QColor.fromHsv(0, 0, 255, color.alpha() if color.isValid() else 255)


class _BlackColorPickerEventFilter(QObject):

    def __init__(self, dialog: QColorDialog):
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and _is_pure_black_color(self._dialog.currentColor()):
            self._dialog.setCurrentColor(_get_black_color_picker_seed(self._dialog.currentColor()))
        return False


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
        is_first_launch = self._init_core_state(parent_for_dialogs, initial_url)
        self._init_runtime_state()
        self._init_services_and_controllers()
        self._connect_initialization_signals(is_first_launch)
        self._finalize_window_setup()

    def _init_core_state(self, parent_for_dialogs: Optional[QWidget], initial_url: str | None) -> bool:
        self._tooltip_widget = None
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._show_custom_tooltip)
        self._last_tooltip_text = ""
        self._last_tooltip_target = None
        self._last_tooltip_size_key = None
        self.app_state = AppState()
        GameBananaAPI.set_app_state(self.app_state)
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
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self.presence_worker, 'run', Qt.ConnectionType.QueuedConnection)
        self.setWindowTitle('DELTAHUB')
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self._supports_volume = platform.system() == 'Windows'
        self._initial_size = None
        self.app_state.local_config = self.settings_service.read_json(self.app_state.config_path) or {}
        self._init_localization()
        self._splash_was_shown = False
        self.settings_service.migrate_config_if_needed()
        return not self.app_state.local_config.get('first_launch_splash_shown', False)

    def _init_runtime_state(self):
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
        self._resize_margin = 6
        self._restoring_window_geometry = False
        self._window_layout_refresh_timer = QTimer(self)
        self._window_layout_refresh_timer.setSingleShot(True)
        self._window_layout_refresh_timer.timeout.connect(self._refresh_after_window_layout_change)
        self._last_resize_cursor_shape = None

    def _init_services_and_controllers(self):
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
        for signal_name, method_name in (
            ('ui_button_text_update', 'setText'),
            ('ui_button_tooltip_update', 'setToolTip'),
            ('ui_button_enabled_update', 'setEnabled'),
            ('ui_widget_updates_enabled', 'setUpdatesEnabled'),
        ):
            getattr(self.search_display, signal_name).connect(lambda w, v, method=method_name: self._set_widget_attr(w, method, v))
        self.settings_ui = SettingsUiController(self.app_state, self.feedback_service, self.settings_service, self.used_mods_service, self.customization_service, self)
        self.theme = ThemeController(self.app_state, self.feedback_service, self.settings_service, self.customization_service, self)
        self.game_launch = GameLaunchController(self.app_state, self.feedback_service, self.mod_service, self.used_mods_service, self.settings_service, self.game_launcher, self.customization_service, self.plugin_service, self)
        from controllers.refresh_controller import RefreshController
        self.refresh_controller = RefreshController(self.app_state, self.feedback_service, self.mod_service, self.used_mods_service, self.game_launch, self.update_checker, self.settings_service, app_window=self)
        self._connect_cross_service_signals()

    def _connect_initialization_signals(self, is_first_launch: bool):
        self.initialization_finished.connect(self.game_launch.update_button_state)
        self.initialization_finished.connect(self._try_start_background_music)
        if is_first_launch:
            self.initialization_finished.connect(self._handle_first_launch_settings)

    def _finalize_window_setup(self):
        self.init_ui()
        self._update_plugin_tabs()
        self.custom_font_family = localization_service.load_font()
        if (cfp := self.customization_service.get_custom_font_path()) and os.path.exists(cfp):
            from PyQt6.QtGui import QFontDatabase
            if families := QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(cfp)):
                self.custom_font_family = families[0]
        self.ui_ready.emit()
        self._connect_own_signals()
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(INITIALIZATION_TIMEOUT)
        self.settings_service.load_window_geometry(self)
        QApplication.instance().installEventFilter(self)

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
        self.app_state.gb_rate_limit_error.connect(self._on_gb_rate_limit_error)

    def _on_gb_rate_limit_error(self):
        if not self.app_state.local_config.get('gb_rate_limit_notified_this_session', False):
            self.app_state.local_config['gb_rate_limit_notified_this_session'] = True
            self.settings_service.write_local_config()
            self.feedback_service.show_message('warning', 'ui.gamebanana_rate_limit_title', 'ui.gamebanana_rate_limit_body')

    def _handle_pending_install(self):
        if self._pending_install_url:
            self.handle_one_click_install(self._pending_install_url)
            self._pending_install_url = None

    def _on_window_restore_requested(self):
        was_maximized = self.settings_service.was_window_maximized()
        self._restoring_window_geometry = True
        try:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized & ~Qt.WindowState.WindowMaximized)
        except Exception as e:
            logging.debug(f'Failed to clear window state: {e}')
        geometry_restored = self.settings_service.load_window_geometry(self, apply_maximized_state=False)
        if was_maximized:
            if geometry_restored:
                self.show()
            else:
                self.showNormal()
            QTimer.singleShot(0, self.showMaximized)
        elif geometry_restored:
            self.show()
        else:
            self.showNormal()
        QTimer.singleShot(250, self._finish_window_restore)
        self.activateWindow()
        self.raise_()

    def _finish_window_restore(self):
        self._restoring_window_geometry = False
        self._schedule_window_layout_refresh(220)

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

    def _show_about_dialog(self):
        dialog = AboutDialog(self, self.app_state, on_report_bug=self.settings_ui.show_report_bug_dialog if hasattr(self, 'settings_ui') else None)
        dialog.exec()

    def _show_changelog_dialog(self):
        changelog_url = self._localized_value(self.app_state.global_settings, 'changelog_ru_url', 'changelog_en_url', 'changelog_url')
        dialog = ChangelogDialog(self, changelog_url.strip() if changelog_url else '')
        dialog.exec()

    def _toggle_maximized_from_title_bar(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._schedule_window_layout_refresh(220)

    def _get_window_corner_radius(self) -> int:
        if self.isMaximized() or self.isFullScreen():
            return 0
        try:
            return max(0, int(get_border_radius(self.app_state.local_config, default=8)))
        except (TypeError, ValueError):
            return 8

    def _get_window_outline_width(self) -> int:
        return 0 if self.isMaximized() or self.isFullScreen() else 2

    def _get_window_outline_color(self) -> QColor:
        color = QColor(get_theme_color(self.app_state.local_config, 'border', '#039d5b'))
        return color if color.isValid() else QColor('#039d5b')

    def _apply_window_corner_mask(self):
        apply_rounded_mask(self, self._get_window_corner_radius())

    def _paint_window_outline(self, painter: QPainter):
        outline_width = self._get_window_outline_width()
        if outline_width <= 0:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._get_window_outline_color(), outline_width))
        inset = outline_width / 2
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        radius = clamp_border_radius(self._get_window_corner_radius(), width=rect.width(), height=rect.height(), border_width=outline_width)
        path = QPainterPath()
        if radius > 0:
            path.addRoundedRect(rect, radius, radius)
        else:
            path.addRect(rect)
        painter.drawPath(path)

    def _sync_title_bar_window_state(self):
        if hasattr(self, 'title_bar') and self.title_bar:
            self.title_bar.sync_window_state(self.isMaximized())
        if hasattr(self, 'main_layout') and self.main_layout:
            self.main_layout.setContentsMargins(*(0, 0, 0, 0) if self.isMaximized() else (10, 5, 10, 5))
        self._apply_window_corner_mask()

    def _schedule_window_layout_refresh(self, delay_ms: int = 160):
        timer = getattr(self, '_window_layout_refresh_timer', None)
        if timer is None:
            return
        timer.stop()
        timer.start(max(0, int(delay_ms)))

    def _window_resize_edges(self, pos):
        if self.isMaximized():
            return Qt.Edge(0)
        rect = self.rect()
        margin = max(4, int(self._resize_margin))
        left = pos.x() <= margin
        right = pos.x() >= rect.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= rect.height() - margin
        edges = Qt.Edge(0)
        if left:
            edges |= Qt.Edge.LeftEdge
        if right:
            edges |= Qt.Edge.RightEdge
        if top:
            edges |= Qt.Edge.TopEdge
        if bottom:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_resize_edges(edges):
        diagonal_a = Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        diagonal_b = Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        diagonal_c = Qt.Edge.TopEdge | Qt.Edge.RightEdge
        diagonal_d = Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if edges in (diagonal_a, diagonal_b):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (diagonal_c, diagonal_d):
            return Qt.CursorShape.SizeBDiagCursor
        if edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return None

    def _update_resize_cursor(self, pos):
        cursor_shape = self._cursor_for_resize_edges(self._window_resize_edges(pos))
        if cursor_shape is None:
            if self._last_resize_cursor_shape is not None:
                self.unsetCursor()
                self._last_resize_cursor_shape = None
            return
        if self._last_resize_cursor_shape == cursor_shape:
            return
        self.setCursor(cursor_shape)
        self._last_resize_cursor_shape = cursor_shape

    def _start_system_resize_if_needed(self, pos):
        edges = self._window_resize_edges(pos)
        if edges == Qt.Edge(0):
            return False
        handle = self.windowHandle()
        if handle is None:
            return False
        try:
            return bool(handle.startSystemResize(edges))
        except Exception:
            return False

    def init_ui(self):
        self.full_install_checkbox = QCheckBox(tr('ui.install_game_files_first'))
        self.full_install_checkbox.stateChanged.connect(self._on_toggle_full_install)
        self.full_install_checkbox.hide()
        self.setMinimumSize(960, 600)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 5, 10, 5)
        self.main_layout.setSpacing(6)
        self.setMouseTracking(True)
        self.title_bar = CustomTitleBar(self)
        self.title_bar.changelog_requested.connect(self._show_changelog_dialog)
        self.title_bar.about_requested.connect(self._show_about_dialog)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_restore_requested.connect(self._toggle_maximized_from_title_bar)
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.set_localized_texts(
            tr('ui.help_menu'),
            tr('buttons.changelog'),
            tr('ui.about_title'),
            tr('ui.minimize_window'),
            tr('ui.maximize_window'),
            tr('ui.restore_window'),
            tr('ui.close_window'),
        )
        self.main_layout.addWidget(self.title_bar)
        self.top_panel_widget = QFrame()
        self.top_panel_widget.setObjectName('topPanelWidget')
        self.top_frame = QHBoxLayout(self.top_panel_widget)
        self.top_frame.setContentsMargins(4, 0, 4, 0)
        self.top_frame.setSpacing(4)
        self.settings_button = QPushButton(tr('ui.settings_title'))
        self.settings_button.setObjectName('topPanelCompactButton')
        self.settings_button.clicked.connect(self.settings_ui.toggle_settings_view)
        self.online_label = QLabel(tr('status.online_count', count='?'))
        self.online_label.setStyleSheet('padding-left:8px;')
        self.online_label.setToolTip(tr('tooltips.online_counter'))
        self.top_frame.addWidget(self.settings_button)
        self.top_refresh_button = QPushButton('🔄️')
        self.top_refresh_button.setObjectName('topRefreshBtn')
        self.top_refresh_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.top_refresh_button.clicked.connect(self._on_refresh_clicked)
        self.top_frame.addWidget(self.top_refresh_button)
        self.top_frame.addWidget(self.online_label)
        self.top_frame.addStretch()
        self.logo_placeholder = QWidget()
        self.logo_placeholder.setFixedWidth(225)
        self.top_frame.addWidget(self.logo_placeholder)
        self.top_frame.addStretch()
        self.telegram_button = QPushButton(tr('buttons.telegram'))
        self.telegram_button.setObjectName('topPanelCompactButton')
        self.telegram_button.clicked.connect(lambda: webbrowser.open(self.app_state.global_settings.get('telegram_url', SOCIAL_LINKS['telegram'])))
        self.telegram_button.setStyleSheet(f"color: {UI_COLORS['link']};")
        self.top_frame.addWidget(self.telegram_button)
        self.discord_button = QPushButton(tr('buttons.discord'))
        self.discord_button.setObjectName('topPanelCompactButton')
        self.discord_button.clicked.connect(lambda: webbrowser.open(self.app_state.global_settings.get('discord_url', SOCIAL_LINKS['discord'])))
        self.discord_button.setStyleSheet(f"color: {UI_COLORS['social_discord']};")
        self.top_frame.addWidget(self.discord_button)
        self.main_layout.addWidget(self.top_panel_widget)
        self.launcher_icon_label = QLabel(self.top_panel_widget)
        self.launcher_icon_label.setFixedSize(250, 60)
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
        self.shortcut_button.clicked.connect(self._on_shortcut_button_click)
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
        self.main_layout.addSpacing(5)
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

        hide_mods_browser = self.app_state.local_config.get('hide_mods_browser_tab', False)
        hide_library = self.app_state.local_config.get('hide_library_tab', False)
        hide_plugins = self.app_state.local_config.get('hide_plugins_tab', False)

        self._num_main_tabs_visible = 0
        if not hide_mods_browser:
            self.main_tab_widget.addTab(self.search_mods_tab, tr('ui.search_tab'))
            self._num_main_tabs_visible += 1
        if not hide_library:
            self.main_tab_widget.addTab(self.library_tab, tr('ui.library_tab'))
            self._num_main_tabs_visible += 1
        if not hide_plugins:
            self.main_tab_widget.addTab(self.plugins_tab, tr('ui.plugins_tab'))
            self._num_main_tabs_visible += 1

        self.previous_tab_index = 0
        self.main_tab_widget.currentChanged.connect(self._on_tab_changed)
        self.main_tab_widget.setStyleSheet('\n            QTabWidget::tab-bar {\n                alignment: center;\n            }\n            QTabBar::tab {\n                min-width: 92px;\n                padding: 6px 10px;\n            }\n        ')
        self.main_layout.addWidget(self.main_tab_widget)
        self.main_layout.addWidget(self.bottom_widget)
        self._setup_settings_tab()
        self.search_display.update_filtered_mods()
        self.main_layout.addWidget(self.settings_widget)
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.setWindowIcon(QIcon(resource_path('assets/icons/icon.ico')))

    def _setup_search_tab(self):
        search_builder = ModsBrowserTabBuilder(self.app_state, self)
        self.search_tab_builder = search_builder
        self.search_mods_tab = search_builder.build()
        search_widgets = search_builder.get_widgets()
        self._bind_widgets(search_widgets, required=(
            'search_container', 'search_mods_scroll', 'mod_list_widget', 'mod_list_layout', 'mod_list_columns',
            'sort_combo', 'sort_order_btn', 'modgame_combo', 'tags_label', 'show_nsfw_checkbox', 'tag_textedit',
            'tag_customization', 'tag_gameplay', 'tag_other', 'search_button',
            'prev_page_btn', 'page_label', 'next_page_btn',
        ))
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

        def on_show_nsfw_changed(state):
            self.app_state.local_config['show_nsfw'] = bool(state)
            self.settings_service.write_local_config()
            self.app_state.current_page = 1
            self.search_display.update_filtered_mods()
        self.show_nsfw_checkbox.stateChanged.connect(on_show_nsfw_changed)
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
            'import_export_button', 'installed_mods_label', 'priority_button',
            'create_modpack_button',
        ))
        if self.priority_button:
            self.priority_button.clicked.connect(self.library_display.on_priority_button_click)
        if self.create_modpack_button:
            self.create_modpack_button.clicked.connect(self.library_display.on_create_modpack_button_click)
        from controllers.mod_import_export_controller import ModImportExportController
        self.mod_import_export_controller = ModImportExportController(self.app_state, self.mod_service, self)
        if self.import_export_button:
            self.import_export_button.clicked.connect(self.mod_import_export_controller.show_import_export_dialog)
        if hasattr(self.installed_mods_container, 'files_dropped'):
            self.installed_mods_container.files_dropped.connect(self.mod_import_export_controller.import_files_sequentially)
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
        if not self.app_state.game_mode.is_multi_tab and self.app_state.current_mode == 'chapter':
            self._set_checkbox_checked_silently(self.chapter_mode_checkbox, False)
            self.app_state.current_mode = 'normal'
            self.game_type_combo.setEnabled(True)
        self.app_state.game_mode_changed.connect(self._on_game_mode_updated_by_state)
        self._update_checkbox_visibility()
        self._update_change_path_button_text()
        self._setup_chapter_tabs()
        if self.app_state.current_mode == 'chapter' and hasattr(self, '_show_chapter_mode_instruction'):
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
        elif self.app_state.current_mode != 'chapter':
            self.library_display.update_display()
            self.library_display._update_priority_button_visibility()
            self.app_state.library_initialized = True
        self.library_display.update_mod_widgets_active_status()

    def _setup_plugins_tab(self):
        from ui.builders.plugin_tab_builder import PluginTabBuilder
        plugin_builder = PluginTabBuilder(self.app_state, self)
        self.plugin_tab_builder = plugin_builder
        self.plugins_tab = plugin_builder.build()
        for attr, key in (('plugins_search_button', 'search_button'), ('plugins_import_button', 'import_button'), ('plugins_container', 'plugins_container'), ('plugins_scroll', 'plugins_scroll'), ('plugins_widget', 'plugins_widget'), ('plugins_layout', 'plugins_layout')):
            setattr(self, attr, self.plugin_tab_builder.widgets[key])
        from controllers.plugin_display_controller import PluginDisplayController
        self.plugin_display = PluginDisplayController(self.app_state, self.feedback_service, self.plugin_service, self)
        self.plugins_search_button.clicked.connect(self.plugin_display.on_search_plugins)
        self.plugins_import_button.clicked.connect(self.plugin_display.on_import_plugin)

    def _setup_settings_tab(self):
        settings_builder = SettingsViewBuilder(self.app_state, self)
        self.settings_widget = settings_builder.build()
        settings_widgets = settings_builder.get_widgets()
        self._bind_widgets(settings_widgets, required=(
            'settings_tab_widget',
            'language_label', 'language_combo',
            'beta_updates_checkbox', 'reset_button',
            'fullscreen_checkbox', 'disable_animations_checkbox', 'disable_background_checkbox', 'disable_splash_checkbox',
            'change_background_button', 'change_logo_button', 'change_font_button', 'background_music_button',
            'startup_sound_button', 'custom_style_frame', 'color_widgets', 'color_labels',
            'color_config', 'theme_button', 'themes_list_widget', 'theme_apply_btn',
            'theme_save_btn', 'theme_delete_btn', 'do_not_save_theme_checkbox',
            'hide_wips_without_downloads_checkbox', 'auto_sorting_checkbox',
            'mods_per_page_label', 'mods_per_page_spinbox',
            'gb_sort_label', 'gb_sort_combo', 'blocklist_button',
            'hide_library_filters_checkbox', 'settings_game_combo',
            'settings_change_path_button', 'settings_custom_executable_button',
            'settings_reset_custom_exe_button',
            'skip_patching_warnings_checkbox', 'launch_via_steam_checkbox', 'dont_hide_window_checkbox',
            'hide_mods_browser_tab_checkbox', 'hide_library_tab_checkbox', 'hide_plugins_tab_checkbox',
            'merge_properties_checkbox', 'merge_code_checkbox', 'clear_cache_button',
            'ui_scale_label', 'ui_scale_spinbox',
            'border_radius_label', 'border_radius_spinbox',
        ), optional=(
            'use_portproton_checkbox', 'select_portproton_path_button',
            'portproton_path_label', 'portproton_frame',
        ))
        self._section_headers = settings_widgets.get('_section_headers', [])
        self._section_lines = settings_widgets.get('_section_lines', [])
        self.language_combo.currentTextChanged.connect(lambda: self.settings_ui.on_language_changed(self.language_combo.currentData()))
        self._connect_theme_setting_spinbox(self.ui_scale_spinbox, timer_attr='_ui_scale_timer', config_key='ui_scale', value_transform=lambda value: value / 100.0, after_change=self._refresh_scaled_card_displays)
        self._connect_theme_setting_spinbox(self.border_radius_spinbox, timer_attr='_border_radius_timer', config_key='custom_border_radius')

        self.beta_updates_checkbox.stateChanged.connect(self.settings_ui.on_toggle_beta_updates)
        self.reset_button.clicked.connect(self.settings_ui.reset_settings)
        self.fullscreen_checkbox.stateChanged.connect(self.settings_ui.on_toggle_fullscreen)
        self.disable_animations_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_animations)
        self.disable_background_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_background)
        self.disable_splash_checkbox.stateChanged.connect(self.settings_ui.on_toggle_disable_splash)
        self.change_background_button.clicked.connect(self.theme.on_background_button_click)
        self.theme.update_background_button_state()
        self.change_logo_button.setText(self.customization_service.get_logo_button_text())
        self.change_logo_button.clicked.connect(self.theme.on_logo_button_click)
        self.change_font_button.setText(self.customization_service.get_font_button_text())
        self.change_font_button.clicked.connect(self.settings_service.on_font_button_click)
        self.background_music_button.setText(self.customization_service.get_background_music_button_text())
        self.background_music_button.clicked.connect(self.theme.on_background_music_button_click)
        self.startup_sound_button.setText(self.customization_service.get_startup_sound_button_text())
        self.startup_sound_button.clicked.connect(self.theme.on_startup_sound_button_click)
        self.theme_button.clicked.connect(self.theme.on_theme_button_click)
        self.theme_apply_btn.clicked.connect(self.theme.on_theme_apply_clicked)
        self.theme_save_btn.clicked.connect(self.theme.on_theme_save_clicked)
        self.theme_delete_btn.clicked.connect(self.theme.on_theme_delete_clicked)

        self.theme.init_theme_list()

        def color_to_display_hex(color: QColor) -> str:
            if color.alpha() < 255:
                return f'#{color.red():02X}{color.green():02X}{color.blue():02X}{color.alpha():02X}'
            return color.name().upper()

        def sync_color_dialog_html_value(color_name_line_edit: QLineEdit, display_hex: str, html_edit_state: dict):
            html_edit_state['syncing'] = True
            html_edit_state['dirty'] = False
            was_blocked = color_name_line_edit.blockSignals(True)
            color_name_line_edit.setText(display_hex)
            color_name_line_edit.setCursorPosition(len(display_hex))
            color_name_line_edit.blockSignals(was_blocked)
            html_edit_state['syncing'] = False

        def on_color_dialog_html_text_edited(_text: str, html_edit_state: dict):
            if not html_edit_state.get('syncing'):
                html_edit_state['dirty'] = True

        def on_color_dialog_html_edited(dialog: QColorDialog, color_name_line_edit: QLineEdit, html_edit_state: dict):
            if html_edit_state.get('syncing') or not html_edit_state.get('dirty'):
                return
            html_edit_state['dirty'] = False
            updated_color = QColor(display_hex_to_qt_hex(color_name_line_edit.text().strip()))
            if updated_color.isValid():
                dialog.setCurrentColor(updated_color)

        def prepare_color_dialog(dialog: QColorDialog):
            zoom_factor = self.app_state.local_config.get('ui_scale', 1.0)
            dialog.setWindowTitle(tr('ui.select_color'))
            dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
            dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
            dialog.ensurePolished()
            dialog.setMinimumWidth(max(dialog.minimumWidth(), int(760 * zoom_factor)))
            spin_boxes = dialog.findChildren(QSpinBox)
            for spin_box in spin_boxes:
                spin_box.setMinimumWidth(max(spin_box.minimumWidth(), int(115 * zoom_factor)))
                if line_edit := spin_box.lineEdit():
                    line_edit.setMinimumWidth(max(line_edit.minimumWidth(), int(72 * zoom_factor)))
                    line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            color_name_line_edit = dialog.findChild(QLineEdit, 'qt_colorname_lineedit')
            if color_name_line_edit:
                color_name_line_edit.setMinimumWidth(max(color_name_line_edit.minimumWidth(), int(160 * zoom_factor)))
                color_name_line_edit.setMaxLength(9)
                color_name_line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            html_edit_state = {'dirty': False, 'syncing': False}
            preview_outer_radius = max(6, int(8 * zoom_factor))
            preview_inner_radius = max(4, preview_outer_radius - 2)
            preview_container = QWidget(dialog)
            preview_layout = QHBoxLayout(preview_container)
            preview_layout.setContentsMargins(0, int(8 * zoom_factor), 0, 0)
            preview_layout.setSpacing(int(12 * zoom_factor))
            preview_layout.addStretch()
            preview_frames = []
            for background_color in ('#FFFFFF', '#000000'):
                preview_base = QFrame(preview_container)
                preview_base.setFixedSize(int(92 * zoom_factor), int(56 * zoom_factor))
                preview_base.setStyleSheet(
                    f'background-color: {background_color}; border: 1px solid #808080; '
                    f'border-radius: {preview_outer_radius}px;'
                )
                preview_base_layout = QVBoxLayout(preview_base)
                preview_base_layout.setContentsMargins(1, 1, 1, 1)
                preview_base_layout.setSpacing(0)
                preview_fill = QFrame(preview_base)
                preview_base_layout.addWidget(preview_fill)
                preview_frames.append(preview_fill)
                preview_layout.addWidget(preview_base)
            preview_layout.addStretch()

            def sync_color_dialog_ui(color: QColor):
                if not color.isValid():
                    return
                for preview_frame in preview_frames:
                    preview_frame.setStyleSheet(
                        f'background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()}); '
                        f'border: none; border-radius: {preview_inner_radius}px;'
                    )
                if color_name_line_edit:
                    display_hex = color_to_display_hex(color)
                    QTimer.singleShot(0, lambda text=display_hex, line_edit=color_name_line_edit: sync_color_dialog_html_value(line_edit, text, html_edit_state))

            dialog.layout().insertWidget(max(0, dialog.layout().count() - 1), preview_container)
            color_picker_widget = next((widget for widget in dialog.findChildren(QWidget) if widget.metaObject().className().endswith('QColorPicker')), None)
            if color_picker_widget:
                dialog._black_color_picker_filter = _BlackColorPickerEventFilter(dialog)
                color_picker_widget.installEventFilter(dialog._black_color_picker_filter)
            if color_name_line_edit:
                color_name_line_edit.textEdited.connect(lambda text: on_color_dialog_html_text_edited(text, html_edit_state))
                color_name_line_edit.editingFinished.connect(lambda: on_color_dialog_html_edited(dialog, color_name_line_edit, html_edit_state))
            dialog.currentColorChanged.connect(sync_color_dialog_ui)
            sync_color_dialog_ui(dialog.currentColor())
            dialog.adjustSize()

        def pick_color_for_edit(target_edit):
            current_text = target_edit.text().strip()
            initial_text = current_text or target_edit.placeholderText().strip()
            initial_color = QColor(display_hex_to_qt_hex(initial_text)) if initial_text else QColor()
            dialog = QColorDialog(self)
            prepare_color_dialog(dialog)
            if initial_color.isValid():
                dialog.setCurrentColor(initial_color)
            if dialog.exec() == QColorDialog.DialogCode.Accepted:
                target_edit.setText(color_to_display_hex(dialog.currentColor()))
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
        self.hide_wips_without_downloads_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_wips_without_downloads)
        self.auto_sorting_checkbox.stateChanged.connect(self._on_auto_sorting_changed)
        self.mods_per_page_spinbox.setValue(self.app_state.mods_per_page)
        self.mods_per_page_spinbox.valueChanged.connect(self._on_mods_per_page_changed)
        self.app_state.auto_sorting = self.app_state.local_config.get('auto_sorting', False)
        self.auto_sorting_checkbox.setChecked(self.app_state.auto_sorting)
        self.gb_sort_combo.setCurrentIndex(0)
        self.gb_sort_combo.currentIndexChanged.connect(self._on_gamebanana_sort_changed)
        self.blocklist_button.clicked.connect(self.search_display.show_blocklist_dialog)
        self.hide_library_filters_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_library_filters)
        self.settings_game_combo.currentIndexChanged.connect(self._on_settings_game_combo_changed)
        self.settings_change_path_button.clicked.connect(self._prompt_for_game_path)
        self.settings_custom_executable_button.clicked.connect(self._select_custom_executable_file)
        self.settings_reset_custom_exe_button.clicked.connect(self._reset_custom_executable)
        self._update_settings_library_tab()
        self.skip_patching_warnings_checkbox.stateChanged.connect(self.settings_ui.on_toggle_skip_patching_warnings)
        self.launch_via_steam_checkbox.stateChanged.connect(self.settings_ui.on_toggle_steam_launch)
        self.dont_hide_window_checkbox.stateChanged.connect(self.settings_ui.on_toggle_dont_hide_window_on_launch)
        if self.use_portproton_checkbox:
            self.use_portproton_checkbox.stateChanged.connect(self.settings_ui.on_toggle_portproton)
            self.use_portproton_checkbox.stateChanged.connect(self._update_portproton_ui)
        if self.select_portproton_path_button:
            self.select_portproton_path_button.clicked.connect(self._select_portproton_path)

        self.hide_mods_browser_tab_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_mods_browser_tab)
        self.hide_library_tab_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_library_tab)
        self.hide_plugins_tab_checkbox.stateChanged.connect(self.settings_ui.on_toggle_hide_plugins_tab)
        self.merge_properties_checkbox.stateChanged.connect(self.settings_ui.on_toggle_merge_properties)
        self.merge_code_checkbox.stateChanged.connect(self.settings_ui.on_toggle_merge_code)
        self.clear_cache_button.clicked.connect(self.settings_ui.on_clear_cache_clicked)

        self.hide_mods_browser_tab_checkbox.setChecked(self.app_state.local_config.get('hide_mods_browser_tab', False))
        self.hide_library_tab_checkbox.setChecked(self.app_state.local_config.get('hide_library_tab', False))
        self.hide_plugins_tab_checkbox.setChecked(self.app_state.local_config.get('hide_plugins_tab', False))

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
            game_def = mode_obj or self.app_state.game_mode
            if not game_def.is_multi_tab:
                self._set_checkbox_checked_silently(self.chapter_mode_checkbox, False)
                if getattr(self.app_state, 'current_mode', 'normal') != 'normal':
                    self.app_state.current_mode = 'normal'
                self.app_state.selected_chapter_id = None
                self.game_type_combo.setEnabled(True)
            self._setup_chapter_tabs()
            self.used_mods_service.load_used_mods_state()
            self.library_display.update_display()
            self._update_change_path_button_text()
            self._update_settings_library_tab()
        except Exception:
            logging.debug('Error in _on_game_mode_updated_by_state', exc_info=True)

    def _update_change_path_button_text(self):
        if hasattr(self, 'settings_change_path_button') and self.settings_change_path_button:
            self.settings_change_path_button.setText(self.app_state.game_mode.path_change_button_text)

    def _on_settings_game_combo_changed(self, index):
        """When the game selector in Settings > Library changes, update the path button text."""
        game_id = self.settings_game_combo.itemData(index)
        if not game_id:
            return

        for i in range(self.game_type_combo.count()):
            if self.game_type_combo.itemData(i) == game_id:
                if self.game_type_combo.currentIndex() != i:
                    self.game_type_combo.setCurrentIndex(i)
                break

        game_def = get_game(game_id)
        if game_def and hasattr(self, 'settings_change_path_button'):
            self.settings_change_path_button.setText(game_def.path_change_button_text)
        self._update_custom_executable_ui(game_id)

    def _update_settings_library_tab(self):
        """Sync the settings Library tab with the current game mode."""
        current_game_id = self.app_state.game_mode.game_id
        combo = self.settings_game_combo
        for i in range(combo.count()):
            if combo.itemData(i) == current_game_id:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                break
        if hasattr(self, 'settings_change_path_button'):
            self.settings_change_path_button.setText(self.app_state.game_mode.path_change_button_text)
        self._update_custom_executable_ui(current_game_id)

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

    def _get_or_create_theme_timer(self, attr_name: str):
        timer = getattr(self, attr_name, None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self.theme.apply_theme)
            setattr(self, attr_name, timer)
        return timer

    def _connect_theme_setting_spinbox(self, spinbox, *, timer_attr: str, config_key: str, value_transform=None, after_change=None):
        timer = self._get_or_create_theme_timer(timer_attr)

        def _on_changed(value):
            self.app_state.local_config[config_key] = value_transform(value) if value_transform else value
            self.settings_service.write_local_config()
            timer.start()
            if after_change:
                after_change()

        spinbox.valueChanged.connect(_on_changed)

    def _refresh_scaled_card_displays(self):
        if hasattr(self, 'search_tab_builder') and hasattr(self.search_tab_builder, 'refresh_dynamic_styles'):
            self.search_tab_builder.refresh_dynamic_styles()
        if hasattr(self, 'search_display'):
            self.search_display.update_display()
        if hasattr(self, 'library_display'):
            self.library_display.update_display()
        if hasattr(self, 'plugin_display'):
            self.plugin_display.update_display()

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
        ev_type = ev.type()
        tooltip_timer = getattr(self, '_tooltip_timer', None)
        tooltip_widget = getattr(self, '_tooltip_widget', None)
        last_tooltip_target = getattr(self, '_last_tooltip_target', None)
        if ev_type == QEvent.Type.MouseButtonDblClick:
            chapter_id = getattr(obj, '_chapter_id', None)
            if chapter_id is not None:
                self.used_mods_service.toggle_direct_launch_for_chapter(chapter_id)
                return True
        elif ev_type == QEvent.Type.Wheel:
            if ev.modifiers() == Qt.KeyboardModifier.ControlModifier:
                delta = ev.angleDelta().y()
                if delta > 0:
                    self._zoom_ui(1)
                elif delta < 0:
                    self._zoom_ui(-1)
                return True
        elif ev_type == QEvent.Type.KeyPress:
            if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if ev.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                    self._zoom_ui(1)
                    return True
                elif ev.key() == Qt.Key.Key_Minus:
                    self._zoom_ui(-1)
                    return True
        elif ev_type == QEvent.Type.ToolTip:
            text = obj.toolTip() if hasattr(obj, 'toolTip') else ''
            if text:
                if last_tooltip_target == obj and tooltip_widget and tooltip_widget.isVisible():
                    return True
                if last_tooltip_target == obj and self._last_tooltip_text == text and tooltip_timer and tooltip_timer.isActive():
                    return True
                self._last_tooltip_text = text
                self._last_tooltip_target = obj
                if tooltip_timer:
                    tooltip_timer.start(250)
                return True
            self._hide_custom_tooltip()
            return super().eventFilter(obj, ev)
        elif ev_type in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Hide):
            if tooltip_timer:
                tooltip_timer.stop()
            self._hide_custom_tooltip()

        return super().eventFilter(obj, ev)

    def _refresh_after_window_layout_change(self):
        if not self.isVisible() or self.isMinimized():
            return
        self.updateGeometry()
        if hasattr(self, 'main_tab_widget') and self.main_tab_widget:
            self.main_tab_widget.updateGeometry()
        if hasattr(self, 'search_mods_scroll') and self.search_mods_scroll:
            self.search_mods_scroll.updateGeometry()
            try:
                viewport = self.search_mods_scroll.viewport()
            except Exception:
                viewport = None
            if viewport:
                viewport.updateGeometry()
        if hasattr(self, 'mod_list_widget') and self.mod_list_widget:
            self.mod_list_widget.updateGeometry()
        if hasattr(self, 'search_display'):
            current_tab = self.main_tab_widget.currentWidget() if hasattr(self, 'main_tab_widget') and self.main_tab_widget else None
            search_tab = getattr(self, 'search_mods_tab', None)
            if search_tab is None or current_tab is search_tab:
                refresh_visible_layout = getattr(self.search_display, 'refresh_visible_layout', None)
                if callable(refresh_visible_layout):
                    refresh_visible_layout()
                else:
                    if hasattr(self.search_display, '_last_grid_metrics_key'):
                        self.search_display._last_grid_metrics_key = None
                    self.search_display.update_display()

    def _show_custom_tooltip(self):
        last_tooltip_target = getattr(self, '_last_tooltip_target', None)
        last_tooltip_text = getattr(self, '_last_tooltip_text', '')
        if not last_tooltip_target or not last_tooltip_text:
            return

        from PyQt6.QtGui import QCursor

        tooltip_widget = getattr(self, '_tooltip_widget', None)
        if tooltip_widget is None:
            tooltip_widget = AnimatedToolTip(last_tooltip_text, None)
            tooltip_widget._preserve_fade_effect = True
            self._tooltip_widget = tooltip_widget
            self._last_tooltip_size_key = None
        UIAnimator._stop_existing_fade(tooltip_widget)
        tooltip_widget._is_fading_out = False
        if tooltip_widget.text() != last_tooltip_text:
            tooltip_widget.setText(last_tooltip_text)
        if self._last_tooltip_size_key != last_tooltip_text:
            tooltip_widget.adjustSize()
            self._last_tooltip_size_key = last_tooltip_text

        pos = QCursor.pos()
        pos += QPoint(10, 10)

        screen = QApplication.primaryScreen().availableGeometry()
        if pos.x() + tooltip_widget.width() > screen.right():
            pos.setX(screen.right() - tooltip_widget.width() - 5)
        if pos.y() + tooltip_widget.height() > screen.bottom():
            pos.setY(pos.y() - tooltip_widget.height() - 20)

        tooltip_widget.move(pos)
        if tooltip_widget.isVisible():
            tooltip_widget.show()
            tooltip_widget.raise_()
            effect = tooltip_widget.graphicsEffect() if hasattr(tooltip_widget, 'graphicsEffect') else None
            if effect is not None and hasattr(effect, 'setOpacity'):
                effect.setOpacity(1.0)
        else:
            UIAnimator.fade_in(tooltip_widget, 150, self.app_state)

    def _hide_custom_tooltip(self):
        tooltip_widget = getattr(self, '_tooltip_widget', None)
        if tooltip_widget and tooltip_widget.isVisible():
            if not getattr(tooltip_widget, '_is_fading_out', False):
                tooltip_widget._is_fading_out = True
                anim = UIAnimator.fade_out(tooltip_widget, 150, self.app_state)
                if anim:
                    anim.finished.connect(lambda tw=tooltip_widget: setattr(tw, '_is_fading_out', False))
                else:
                    tooltip_widget.hide()
                    tooltip_widget._is_fading_out = False
        self._last_tooltip_target = None
        self._last_tooltip_text = ''

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
        self._paint_window_outline(painter)
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
            self._trigger_initial_mods_refresh(saved_chapter_mode)
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

    def _trigger_initial_mods_refresh(self, saved_chapter_mode=False):
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
        return [self.action_button, self.chat_button, self.change_background_button]

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
        except Exception as e:
            logging.debug(f'Update cleanup - progress bar: {e}')
        self.app_state.update_in_progress = False
        try:
            if not self.app_state.is_settings_view:
                self.tab_widget.setEnabled(True)
            self._set_update_ui_enabled(True)
            self.game_launch.update_button_state()
        except Exception as e:
            logging.debug(f'Update cleanup - UI restore: {e}')

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

    def _update_custom_executable_ui(self, game_id=None):
        game_def = get_game(game_id) if game_id else self.app_state.game_mode
        if not game_def:
            return
        config_key = game_def.get_custom_exec_config_key()
        path = self.app_state.local_config.get(config_key, '')
        has_custom_exe = bool(path)
        if hasattr(self, 'settings_reset_custom_exe_button') and self.settings_reset_custom_exe_button:
            self.settings_reset_custom_exe_button.setVisible(has_custom_exe)

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

    def _sync_chapter_tab_buttons(self):
        if not hasattr(self, 'chapter_tab_buttons'):
            return []
        tabs = list(getattr(self.app_state.game_mode, 'tabs', ()) or ())
        for i, btn in enumerate(self.chapter_tab_buttons):
            try:
                btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            if i >= len(tabs):
                btn.setChecked(False)
                btn.setVisible(False)
                btn._chapter_id = None
                continue
            tab = tabs[i]
            btn.setVisible(True)
            btn.setText(tr(tab.name_key))
            btn.clicked.connect(lambda checked, tid=tab.tab_id: self._on_chapter_tab_clicked(tid) if checked else None)
            btn.installEventFilter(self)
            btn._chapter_id = tab.tab_id
        if hasattr(self, 'chapter_tabs_widget'):
            self.chapter_tabs_widget.setVisible(self.app_state.current_mode == 'chapter' and self.app_state.game_mode.is_multi_tab and bool(tabs))
        return tabs

    def _setup_chapter_tabs(self):
        self._sync_chapter_tab_buttons()
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
        border_color = get_theme_color(self.app_state.local_config, 'border', '#039d5b')
        button_color = get_theme_color(self.app_state.local_config, 'button', '#222222')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#616b78')
        text_color = get_theme_color(self.app_state.local_config, 'text', '#e8e9eb')
        fs = max(1, int(14 * self.app_state.local_config.get('ui_scale', 1.0)))
        for i, (tab, btn) in enumerate(zip(tabs, self.chapter_tab_buttons)):
            border_style = 'dashed' if direct_launch_chapter_id == tab.tab_id else 'solid'
            br = clamp_border_radius(get_border_radius(self.app_state.local_config), height=max(25, btn.sizeHint().height()))
            btn.setStyleSheet(f'\n                QPushButton#chapter_tab_{i} {{\n                    background-color: {button_color};\n                    border: 2px {border_style} {border_color};\n                    color: {text_color};\n                    font-weight: bold;\n                    font-size: {fs}px;\n                    border-radius: {br}px;\n                    padding: 5px;\n                }}\n                QPushButton#chapter_tab_{i}:checked {{\n                    background-color: {hover_color};\n                    border: 3px {border_style} {border_color};\n                }}\n                QPushButton#chapter_tab_{i}:hover {{\n                    background-color: {hover_color};\n                }}\n            ')

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
        app = QApplication.instance()
        if app:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        from core.app_cleanup import perform_close_cleanup
        perform_close_cleanup(self)
        super().closeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_title_bar_window_state()
            if not self.isMinimized():
                self._schedule_window_layout_refresh(220)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start_system_resize_if_needed(event.position().toPoint()):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._last_resize_cursor_shape is not None:
            self.unsetCursor()
            self._last_resize_cursor_shape = None
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_window_corner_mask()
        if hasattr(self, 'launcher_icon_label') and hasattr(self, 'top_panel_widget'):
            panel_width = self.top_panel_widget.width()
            logo_width = self.launcher_icon_label.width()
            logo_height = self.launcher_icon_label.height()
            panel_height = self.top_panel_widget.height()
            y = max(0, (panel_height - logo_height) // 2)
            self.launcher_icon_label.move((panel_width - logo_width) // 2, y)
        if not self._restoring_window_geometry:
            self.settings_service.schedule_geometry_save(self)
            self._schedule_window_layout_refresh()

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._restoring_window_geometry:
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
        from PyQt6.QtWidgets import QInputDialog
        if getattr(self, 'library_search_text', ''):
            self.library_search_text = ''
            self.app_state.library_search_text = ''
            self.library_search_button.setText('🔍')
            self.library_search_button.setToolTip(tr('ui.search_placeholder'))
            self.library_display.update_display()
        else:
            text, ok = QInputDialog.getText(self, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.library_search_text = text.strip()
                self.app_state.library_search_text = text.strip()
                self.library_search_button.setText('↻')
                self.library_search_button.setToolTip(tr('ui.clear_search_tooltip', text=text.strip()))
                self.library_display.update_display()

    def _prompt_for_game_path(self, is_initial=False):
        result = self.settings_service.prompt_for_game_path(is_initial)
        if result:
            self.game_launch.update_button_state()
        if is_initial and (not result):
            self.customization_service.start_background_music()
        return result

    def _show_chapter_mode_instruction(self):
        if not hasattr(self, 'installed_mods_layout'):
            return
        from ui.common.styling import clear_layout_widgets
        clear_layout_widgets(self.installed_mods_layout, keep_last_n=1)
        instruction_widget = QLabel(tr('ui.chapter_mode_instruction'))
        instruction_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        secondary_text_color = get_theme_color(self.app_state.local_config, 'secondary_text', '#CCCCCC')
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
        if hasattr(self, 'theme') and self.theme:
            self.theme.init_theme_list()
        if not is_initial and self.app_state.has_internet:
            self._reload_global_settings(callback=lambda success: self._check_and_show_announce(force_check=True) if success else None)
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(self.presence_worker, 'run', Qt.ConnectionType.QueuedConnection)

        def update_filtered_callback(): return self.search_display.update_filtered_mods(preserve_page=False) if hasattr(self, 'search_display') and self.search_display else None
        def update_installed_callback(): return self._update_installed_mods_display()
        def update_action_callback(): return self.game_launch.update_button_state()
        update_plugin_callback = self._update_plugin_tabs

        callbacks = {
            'update_filtered_mods_callback': update_filtered_callback,
            'update_installed_mods_callback': update_installed_callback,
            'update_action_button_callback': update_action_callback,
            'update_plugin_tabs_callback': update_plugin_callback,
            'mods_loaded_signal': self.mods_loaded_signal
        }

        self.refresh_controller.refresh_mods_list(is_initial=is_initial, language_combo=self.language_combo, localization_callback=self._relocalize_ui, on_fetch_finished_kwargs=callbacks)

    def _create_nobody_came_tab(self):
        """Create and add 'But nobody came.' placeholder tab when no tabs are visible."""
        from PyQt6.QtWidgets import QVBoxLayout, QLabel
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(tr('ui.nobody_came'))
        lbl.setStyleSheet('font-size: 18px; color: gray;')
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)
        self.main_tab_widget.addTab(w, '')

    def _remove_nobody_came_tab(self):
        """Remove 'But nobody came.' tab if it exists as the only tab."""
        from PyQt6.QtWidgets import QVBoxLayout, QLabel
        if self.main_tab_widget.count() != 1:
            return
        widget = self.main_tab_widget.widget(0)
        if isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout(), QVBoxLayout):
            if widget.layout().count() > 0:
                label = widget.layout().itemAt(0).widget()
                if isinstance(label, QLabel) and 'nobody' in label.text().lower():
                    self.main_tab_widget.removeTab(0)

    def _init_plugin_placeholder_tab(self, tab_index):
        """Initialize a plugin placeholder tab at the given index if needed."""
        current_widget = self.main_tab_widget.widget(tab_index)
        is_placeholder = type(current_widget) is QWidget and current_widget.layout() is None
        if not is_placeholder or tab_index not in self._plugin_tab_map:
            return
        plugin = self._plugin_tab_map[tab_index]
        try:
            handler = plugin.get('page_init') if callable(plugin.get('page_init')) else plugin.get('on_tab_open')
            if callable(handler):
                new_widget = self._run_with_plugin_api(plugin, handler)
                if isinstance(new_widget, QWidget):
                    try:
                        new_widget.setProperty('plugin_name_key', plugin.get('name_key'))
                        new_widget._plugin_info = plugin
                    except Exception:
                        pass
                    self.main_tab_widget.removeTab(tab_index)
                    self.main_tab_widget.insertTab(tab_index, new_widget, tr(plugin['name_key']))
                    self.main_tab_widget.setCurrentIndex(tab_index)
        except Exception as e:
            logging.exception(f"Error initializing plugin '{plugin.get('name_key', 'unknown')}: {e}'")

    def _update_nobody_came_state(self, num_main_tabs, plugin_count):
        """Show or remove 'But nobody came.' based on tab/plugin counts."""
        if num_main_tabs == 0 and plugin_count == 0:
            if self.main_tab_widget.count() == 0:
                self._create_nobody_came_tab()
        elif num_main_tabs == 0 and plugin_count > 0:
            self._remove_nobody_came_tab()
            if self.main_tab_widget.count() > 0:
                idx = max(self.main_tab_widget.currentIndex(), 0)
                self._init_plugin_placeholder_tab(idx)

    def _update_plugin_tabs(self):
        if not hasattr(self, 'plugin_service') or not hasattr(self, 'main_tab_widget'):
            return
        if self._handling_plugin_tab:
            return
        self._handling_plugin_tab = True
        self.plugin_service.load_plugins()
        num_main_tabs = getattr(self, '_num_main_tabs_visible', 3)
        self._plugin_tab_map = self.plugin_service.update_plugin_tabs(self.main_tab_widget, num_original_tabs=num_main_tabs)
        self._update_nobody_came_state(num_main_tabs, len(self._plugin_tab_map))
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
            self.plugin_api = plugin_api
        try:
            return handler(self)
        finally:
            if hasattr(self, 'plugin_api'):
                del self.plugin_api

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

    def _reload_global_settings(self, callback=None):
        from core.app_update_handler import reload_global_settings
        reload_global_settings(self, callback=callback)

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
        if not self.app_state.has_internet:
            self.feedback_service.show_message('warning', 'chat.no_internet', tr('chat.no_internet'))
            return
        from ui.dialogs.chat_dialog import ChatWindow
        chat_window = ChatWindow(self.app_state, self)
        chat_window.exec()

    def _on_shortcut_button_click(self):
        from controllers.shortcut_controller import on_shortcut_button_click
        on_shortcut_button_click(self.app_state, self.feedback_service, self.used_mods_service, self)

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

    def _zoom_ui(self, direction):
        current_zoom = self.app_state.local_config.get('ui_scale', 1.0)
        new_zoom = max(0.5, min(2.0, round(current_zoom + (0.1 * direction), 1)))
        if new_zoom != current_zoom:
            self.app_state.local_config['ui_scale'] = new_zoom
            if hasattr(self, 'ui_scale_spinbox'):
                self.ui_scale_spinbox.blockSignals(True)
                self.ui_scale_spinbox.setValue(int(new_zoom * 100))
                self.ui_scale_spinbox.blockSignals(False)
            self.settings_service.write_local_config()
            if hasattr(self, '_ui_scale_timer'):
                self._ui_scale_timer.start()
            self._refresh_scaled_card_displays()
