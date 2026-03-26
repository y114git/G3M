import contextlib
import logging
import os
import webbrowser

from PyQt6 import sip
from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.game_ui import (
    on_toggle_full_install,
    show_chapter_mode_instruction,
    update_games_manager_button_style,
)
from app.localization_utils import relocalize_ui
from app_context.application_context import (
    ApplicationContext,
    build_application_context,
)
from bootstrap.bootstrap_coordinator import BootstrapCoordinator
from config.config import (
    DEFAULT_COLORS,
    FALLBACK_WINDOW_BG,
    INITIALIZATION_TIMEOUT,
    QSS_PADDING_LEFT_8,
    SOCIAL_LINKS,
    UI_COLORS,
)
from presentation.update_presenter import (
    check_and_show_announce,
    prompt_for_update,
    reload_global_settings,
)
from presentation.window_composition import WindowComposition
from presentation.window_state import initialize_window_runtime
from services.localization_service import localization_service, tr
from ui.common.styling import (
    apply_rounded_mask,
    clamp_border_radius,
    get_border_radius,
    get_theme_color,
)
from ui.dialogs.about_dialog import AboutDialog
from ui.dialogs.changelog_dialog import ChangelogDialog
from ui.utils.ui_utils import UIAnimator
from ui.widgets.shared.custom_controls import AnimatedToolTip
from ui.widgets.shared.custom_title_bar import CustomTitleBar
from utils.path_utils import colored_icon, resource_path


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

    def __init__(
        self,
        parent_for_dialogs: QWidget | None = None,
        initial_url: str | None = None,
        context: ApplicationContext | None = None,
    ) -> None:
        super().__init__()
        self._bind_application_context(
            context or build_application_context(parent=self),
            parent_for_dialogs,
            initial_url,
        )
        self._init_runtime_state()
        self._init_presentation_controllers()
        self._connect_initialization_signals()
        self._finalize_window_setup()

    def _bind_application_context(
        self,
        context: ApplicationContext,
        parent_for_dialogs: QWidget | None,
        initial_url: str | None,
    ) -> None:
        context.attach_window(
            self,
            parent_for_dialogs=parent_for_dialogs,
            initial_url=initial_url,
        )
        self.setWindowTitle("DELTAHUB")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )

    def _init_runtime_state(self):
        initialize_window_runtime(self)

    def _init_presentation_controllers(self):
        WindowComposition(self).compose()

    def _connect_initialization_signals(self):
        self.initialization_finished.connect(self.game_launch.update_button_state)
        self.initialization_finished.connect(self._try_start_background_music)

    def _finalize_window_setup(self):
        self.init_ui()
        self.custom_font_family = localization_service.load_font()
        if (
            cfp := self.customization_service.get_custom_font_path()
        ) and os.path.exists(cfp):
            from PyQt6.QtGui import QFontDatabase

            if families := QFontDatabase.applicationFontFamilies(
                QFontDatabase.addApplicationFont(cfp)
            ):
                self.custom_font_family = families[0]
        self.ui_ready.emit()
        self._connect_own_signals()
        self.initialization_timer = QTimer()
        self.initialization_timer.setSingleShot(True)
        self.initialization_timer.timeout.connect(self._force_finish_initialization)
        self.initialization_timer.start(INITIALIZATION_TIMEOUT)
        self.settings_service.load_window_geometry(self)
        QApplication.instance().installEventFilter(self)

    def _connect_own_signals(self):
        """Connect AppWindow's own pyqtSignals to their handlers."""
        self.update_status_signal.connect(self._update_status)
        self.hide_window_signal.connect(self.game_launch.hide_window)
        self.restore_window_signal.connect(self.game_launch.restore_window)
        self.set_progress_signal.connect(self._on_progress_update)
        self.show_update_prompt.connect(lambda info: prompt_for_update(self, info))
        self.mods_loaded_signal.connect(self._on_mods_loaded)
        self.url_received_signal.connect(self.handle_one_click_install)
        self.install_from_gb_signal.connect(
            lambda mod: self.mod_ops.install_mod(mod, force=True)
        )
        self.initialization_finished.connect(self._handle_pending_install)
        self.app_state.all_mods_updated.connect(
            lambda mods: setattr(self.app_state, "all_mods", mods)
        )
        self.app_state.gb_rate_limit_error.connect(self._on_gb_rate_limit_error)

    def _on_gb_rate_limit_error(self):
        if not self.app_state.local_config.get(
            "gb_rate_limit_notified_this_session", False
        ):
            self.app_state.local_config["gb_rate_limit_notified_this_session"] = True
            self.settings_service.write_local_config()
            self.feedback_service.show_message(
                "warning",
                "ui.gamebanana_rate_limit_title",
                "ui.gamebanana_rate_limit_body",
            )

    def _handle_pending_install(self):
        if self.context.pending_install_url:
            self.handle_one_click_install(self.context.pending_install_url)
            self.context.pending_install_url = None

    def _on_window_restore_requested(self):
        was_maximized = self.settings_service.was_window_maximized()
        self._restoring_window_geometry = True
        try:
            self.setWindowState(
                self.windowState()
                & ~Qt.WindowState.WindowMinimized
                & ~Qt.WindowState.WindowMaximized
            )
        except Exception as e:
            logging.debug(f"Failed to clear window state: {e}")
        geometry_restored = self.settings_service.load_window_geometry(
            self, apply_maximized_state=False
        )
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

    def refresh(self, is_initial: bool = False) -> None:
        """Public method to refresh the mods list and UI."""
        self._on_refresh_clicked(is_initial=is_initial)

    def _refresh_after_install(self) -> None:
        if self.mod_service:
            self.mod_service.invalidate_mods_cache()
            self.mod_service.load_local_mods(_skip_conversion=True)
            self.mod_service.mod_list_updated.emit()
        if hasattr(self, "library_display"):
            self.library_display.update_display()
        if hasattr(self, "search_display"):
            self.search_display.update_search_cards()
            self.search_display.update_filtered_mods(preserve_page=True)
        if hasattr(self, "settings_service"):
            self.settings_service.theme_changed.emit()

    def handle_one_click_install(self, url: str):
        from app.protocol_handler import handle_one_click_install

        handle_one_click_install(self, url)

    def _handle_url_install_prompt(self, title, message):
        reply = self.feedback_service.ask_question(title, message)
        self.mod_service.handle_url_prompt_response(reply)

    def _handle_permission_error(self, path: str):
        self.feedback_service.show_message("error", "errors.access_denied", path=path)

    def _get_current_game_path(self) -> str:
        return self.app_state.game_mode.get_game_path(self.app_state.local_config) or ""

    def _show_about_dialog(self):
        dialog = AboutDialog(
            self,
            self.app_state,
            on_report_bug=self.settings_ui.show_report_bug_dialog
            if hasattr(self, "settings_ui")
            else None,
        )
        dialog.exec()

    def _show_changelog_dialog(self):
        changelog_url = self._localized_value(
            self.app_state.global_settings,
            "changelog_ru_url",
            "changelog_en_url",
            "changelog_url",
        )
        dialog = ChangelogDialog(self, changelog_url.strip() if changelog_url else "")
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
            return max(
                0, int(get_border_radius(self.app_state.local_config, default=8))
            )
        except (TypeError, ValueError):
            return 8

    def _get_window_outline_width(self) -> int:
        return 0 if self.isMaximized() or self.isFullScreen() else 2

    def _get_window_outline_color(self) -> QColor:
        color = QColor(
            get_theme_color(self.app_state.local_config, "border")
        )
        return color if color.isValid() else QColor(DEFAULT_COLORS["border"])

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
        radius = clamp_border_radius(
            self._get_window_corner_radius(),
            width=rect.width(),
            height=rect.height(),
            border_width=outline_width,
        )
        path = QPainterPath()
        if radius > 0:
            path.addRoundedRect(rect, radius, radius)
        else:
            path.addRect(rect)
        painter.drawPath(path)

    def _sync_title_bar_window_state(self):
        if hasattr(self, "title_bar") and self.title_bar:
            self.title_bar.sync_window_state(self.isMaximized())
        if hasattr(self, "main_layout") and self.main_layout:
            self.main_layout.setContentsMargins(
                *(0, 0, 0, 0) if self.isMaximized() else (10, 5, 10, 5)
            )
        self._apply_window_corner_mask()

    def _schedule_window_layout_refresh(self, delay_ms: int = 160):
        timer = getattr(self, "_window_layout_refresh_timer", None)
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
    def _cursor_for_resize_edges(edges) -> Qt.CursorShape | None:
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
        self.full_install_checkbox = QCheckBox(tr("ui.install_game_files_first"))
        self.full_install_checkbox.stateChanged.connect(
            lambda state: on_toggle_full_install(self, state)
        )
        self.full_install_checkbox.hide()
        self.setMinimumSize(960, 600)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 5, 10, 5)
        self.main_layout.setSpacing(6)
        self.setMouseTracking(True)
        self.title_bar = CustomTitleBar(self, app_state=self.app_state)
        self.title_bar.changelog_requested.connect(self._show_changelog_dialog)
        self.title_bar.about_requested.connect(self._show_about_dialog)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_restore_requested.connect(
            self._toggle_maximized_from_title_bar
        )
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.set_localized_texts(
            tr("ui.help_menu"),
            tr("buttons.changelog"),
            tr("ui.about_title"),
            tr("ui.minimize_window"),
            tr("ui.maximize_window"),
            tr("ui.restore_window"),
            tr("ui.close_window"),
        )
        self.main_layout.addWidget(self.title_bar)
        self.top_panel_widget = QFrame()
        self.top_panel_widget.setObjectName("topPanelWidget")
        self.top_frame = QHBoxLayout(self.top_panel_widget)
        self.top_frame.setContentsMargins(4, 0, 4, 0)
        self.top_frame.setSpacing(4)
        self.settings_button = QPushButton(tr("ui.settings_title"))
        self.settings_button.setObjectName("topPanelCompactButton")
        self.settings_button.clicked.connect(self.settings_ui.toggle_settings_view)
        self.online_label = QLabel(tr("status.online_count", count="?"))
        self.online_label.setStyleSheet(QSS_PADDING_LEFT_8)
        self.online_label.setToolTip(tr("tooltips.online_counter"))
        self.top_frame.addWidget(self.settings_button)
        self.top_refresh_button = QPushButton()
        self.top_refresh_button.setObjectName("topRefreshBtn")
        self.top_refresh_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.top_refresh_button.clicked.connect(self._on_refresh_clicked)
        main_text_color = get_theme_color(
            self.app_state.local_config, "main_text")
        self.top_refresh_button.setIcon(colored_icon("refresh", main_text_color))
        self.top_refresh_button.setIconSize(QSize(20, 20))
        self.top_refresh_button.setFixedSize(30, 30)
        self.top_frame.addWidget(self.top_refresh_button)
        self.top_frame.addWidget(self.online_label)
        self.top_frame.addStretch()
        self.logo_placeholder = QWidget()
        self.logo_placeholder.setFixedWidth(225)
        self.top_frame.addWidget(self.logo_placeholder)
        self.top_frame.addStretch()
        social_style = "padding: 4px; min-width: 40px; min-height: 40px; max-width: 40px; max-height: 40px;"
        for attr, icon_svg, url_key, lang_key in (
            ("telegram_button", "telegram_logo.svg", "telegram", "buttons.telegram"),
            ("discord_button", "discord_logo.svg", "discord", "buttons.discord"),
        ):
            btn = QPushButton()
            btn.setObjectName("topPanelCompactButton")
            btn.clicked.connect(
                lambda _=False, k=url_key: webbrowser.open(
                    self.app_state.global_settings.get(f"{k}_url", SOCIAL_LINKS[k])
                )
            )
            btn.setIcon(QIcon(resource_path(f"assets/icons/{icon_svg}")))
            btn.setIconSize(QSize(32, 32))
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(social_style)
            btn.setToolTip(tr(lang_key))
            setattr(self, attr, btn)
            self.top_frame.addWidget(btn)
        self.main_layout.addWidget(self.top_panel_widget)
        self.launcher_icon_label = QLabel(self.top_panel_widget)
        self.launcher_icon_label.setFixedSize(250, 60)
        self.launcher_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.customization_service.load_launcher_icon(self.launcher_icon_label)
        self.bottom_widget = QFrame()
        self.bottom_widget.setObjectName("bottom_widget")
        self.bottom_frame = QVBoxLayout(self.bottom_widget)
        self.status_label = QLabel(tr("ui.initialization"))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.action_frame = QHBoxLayout()
        self.shortcut_button = QPushButton(tr("buttons.shortcut"))
        self.action_button = QPushButton(tr("status.please_wait"))
        self.action_button.setEnabled(False)
        self.action_button.setMinimumWidth(200)
        self.action_button.clicked.connect(self.game_launch.on_action_button_click)
        self.app_state.is_installing = False
        self.pending_updates = []
        self.chat_button = QPushButton(tr("ui.chat_button"))
        from app.dialogs import open_chat

        self.chat_button.clicked.connect(lambda: open_chat(self))
        self.shortcut_button.clicked.connect(self._on_shortcut_button_click)
        self.action_frame.addWidget(self.shortcut_button)
        self.action_frame.addWidget(self.action_button)
        self.action_frame.addWidget(self.chat_button)
        self.app_state.action_button_text_changed.connect(self.action_button.setText)
        self.app_state.action_button_enabled_changed.connect(
            self.action_button.setEnabled
        )
        self.app_state.progress_bar_visible_changed.connect(
            self.progress_bar.setVisible
        )
        self.app_state.progress_bar_value_changed.connect(self.progress_bar.setValue)
        self.bottom_frame.addWidget(self.status_label)
        self.bottom_frame.addWidget(self.progress_bar)
        self.bottom_frame.addLayout(self.action_frame)
        self.main_layout.addSpacing(5)
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.app_state.current_page = 1
        self.app_state.filtered_mods = []
        self.sort_ascending = False
        self.app_state.search_text = ""
        from app.tab_setup import setup_library_tab, setup_search_tab

        setup_search_tab(self)
        self.library_sort_ascending = self.app_state.local_config.get(
            "library_sort_ascending", True
        )
        self.app_state.library_search_text = ""
        self._previous_mode = "normal"
        setup_library_tab(self)

        self._num_main_tabs_visible = 0
        if not self.app_state.local_config.get("hide_mods_browser_tab", False):
            self.main_tab_widget.addTab(self.mods_browser_tab, tr("ui.search_tab"))
            self._num_main_tabs_visible += 1
        if not self.app_state.local_config.get("hide_library_tab", False):
            self.main_tab_widget.addTab(self.library_tab, tr("ui.library_tab"))
            self._num_main_tabs_visible += 1

        self.previous_tab_index = 0
        from app.tab_handler import handle_tab_changed

        self.main_tab_widget.currentChanged.connect(
            lambda index: handle_tab_changed(self, index)
        )
        self.main_tab_widget.setStyleSheet(
            "\n            QTabWidget::tab-bar {\n                alignment: center;\n            }\n            QTabBar::tab {\n                min-width: 92px;\n                padding: 6px 10px;\n            }\n        "
        )
        self.main_layout.addWidget(self.main_tab_widget)
        self.main_layout.addWidget(self.bottom_widget)
        from app.settings_setup import setup_settings_tab

        setup_settings_tab(self)
        if hasattr(self, "plugins_ui") and self.plugins_ui:
            self.plugins_ui.refresh_main_tabs()
        self.search_display.update_filtered_mods()
        self.tab_widget = self.main_tab_widget
        self.tabs = {}
        self.setWindowIcon(QIcon(resource_path("assets/icons/icon.ico")))

    def _finish_initialization(self):
        self.app_state.initialization_completed = True
        self.initialization_finished.emit()
        if (
            hasattr(self.app_state, "pending_announce_check")
            and self.app_state.pending_announce_check
            and (not self.app_state.update_in_progress)
        ):
            check_and_show_announce(self)

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
        if getattr(self, "is_shown_to_user", False) and self.isVisible():
            self.customization_service.maybe_start_background_music(force=True)

    def _on_search_sort_changed(self):
        if not hasattr(self, "search_display"):
            return
        if hasattr(self, "sort_combo"):
            sort_index = self.sort_combo.currentIndex()
            self.app_state.local_config["search_sort_index"] = sort_index
            self.settings_service.write_local_config()
        self.search_display.load_mods_for_selected_game()

    def _on_library_sort_changed(self):
        self.app_state.local_config["library_sort_index"] = (
            self.library_sort_combo.currentIndex()
        )
        self.settings_service.write_local_config()
        self.library_display.update_display()

    def _toggle_library_sort_order(self):
        self.library_sort_ascending = not self.library_sort_ascending
        self.app_state.local_config["library_sort_ascending"] = (
            self.library_sort_ascending
        )
        self.settings_service.write_local_config()
        self._apply_sort_order(self.library_sort_ascending, self.library_sort_order_btn)
        self.library_display.update_display()

    def _apply_sort_order(self, is_ascending: bool, sort_button):
        """Apply sort order to button with icon and tooltip update."""
        if sort_button:
            sort_button.setToolTip(
                tr("ui.ascending") if is_ascending else tr("ui.descending")
            )
            tc = get_theme_color(self.app_state.local_config, "main_text")
            sort_button.setIcon(
                colored_icon("arrow_up" if is_ascending else "arrow_down", tc)
            )
            sort_button.setIconSize(QSize(12, 12))

    def _update_section_reset_buttons_visibility(self):
        show_reset_buttons = self.app_state.local_config.get(
            "show_reset_buttons", False
        )
        for reset_btn, *_ in getattr(self, "_section_reset_buttons", []):
            if reset_btn:
                reset_btn.setVisible(show_reset_buttons)

    def _safe_set_parent_none(self, obj):
        try:
            if obj:
                obj.setParent(None)
        except Exception as e:
            logging.debug(
                f"Failed to clear parent for widget/object: {e}", exc_info=True
            )

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

    def _connect_theme_setting_spinbox(
        self,
        spinbox,
        *,
        timer_attr: str,
        config_key: str,
        value_transform=None,
        after_change=None,
    ):
        timer = self._get_or_create_theme_timer(timer_attr)

        def _on_changed(value):
            self.app_state.local_config[config_key] = (
                value_transform(value) if value_transform else value
            )
            self.settings_service.write_local_config()
            timer.start()
            if after_change:
                after_change()

        spinbox.valueChanged.connect(_on_changed)

    def _refresh_scaled_card_displays(self):
        if hasattr(self, "search_tab_builder") and hasattr(
            self.search_tab_builder, "refresh_dynamic_styles"
        ):
            self.search_tab_builder.refresh_dynamic_styles()
        if hasattr(self, "search_display"):
            self.search_display.update_display()
        if hasattr(self, "library_display"):
            self.library_display.update_display()

    @staticmethod
    def _localized_value(data, ru_key, en_key, fallback_key=None) -> str:
        return data.get(
            ru_key if localization_service.get_current_language() == "ru" else en_key,
            "",
        ) or (data.get(fallback_key, "") if fallback_key else "")

    def _set_checkbox_checked_silently(self, checkbox, checked):
        checkbox.blockSignals(True)
        try:
            checkbox.setChecked(checked)
        finally:
            checkbox.blockSignals(False)

    def eventFilter(self, obj, ev):
        ev_type = ev.type()
        tooltip_timer = getattr(self, "_tooltip_timer", None)
        tooltip_widget = getattr(self, "_tooltip_widget", None)
        last_tooltip_target = getattr(self, "_last_tooltip_target", None)
        if ev_type == QEvent.Type.MouseButtonDblClick:
            chapter_id = getattr(obj, "_chapter_id", None)
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
            with contextlib.suppress(RuntimeError, AttributeError):
                if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if ev.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                        self._zoom_ui(1)
                        return True
                    if ev.key() == Qt.Key.Key_Minus:
                        self._zoom_ui(-1)
                        return True
        elif ev_type == QEvent.Type.ToolTip:
            is_deleted = True
            if obj is None:
                is_deleted = True
            else:
                with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                    is_deleted = sip.isdeleted(obj)
            if is_deleted:
                self._hide_custom_tooltip()
                return super().eventFilter(obj, ev)
            text = ""
            with contextlib.suppress(RuntimeError, AttributeError):
                text = obj.toolTip() if hasattr(obj, "toolTip") else ""
            if text:
                if (
                    last_tooltip_target == obj
                    and tooltip_widget
                    and tooltip_widget.isVisible()
                ):
                    return True
                if (
                    last_tooltip_target == obj
                    and self._last_tooltip_text == text
                    and tooltip_timer
                    and tooltip_timer.isActive()
                ):
                    return True
                self._last_tooltip_text = text
                self._last_tooltip_target = obj
                if tooltip_timer:
                    tooltip_timer.start(50)
                return True
            self._hide_custom_tooltip()
            return super().eventFilter(obj, ev)
        elif ev_type in (
            QEvent.Type.Leave,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Hide,
        ):
            if tooltip_timer:
                tooltip_timer.stop()
            self._hide_custom_tooltip()

        return super().eventFilter(obj, ev)

    def _refresh_after_window_layout_change(self):
        if not self.isVisible() or self.isMinimized():
            return
        self.updateGeometry()
        if hasattr(self, "main_tab_widget") and self.main_tab_widget:
            self.main_tab_widget.updateGeometry()
        if hasattr(self, "mods_browser_scroll") and self.mods_browser_scroll:
            self.mods_browser_scroll.updateGeometry()
            try:
                viewport = self.mods_browser_scroll.viewport()
            except Exception:
                viewport = None
            if viewport:
                viewport.updateGeometry()
        if hasattr(self, "mod_list_widget") and self.mod_list_widget:
            self.mod_list_widget.updateGeometry()
        update_games_manager_button_style(self)
        if hasattr(self, "search_display"):
            current_tab = (
                self.main_tab_widget.currentWidget()
                if hasattr(self, "main_tab_widget") and self.main_tab_widget
                else None
            )
            mods_browser_tab = getattr(self, "mods_browser_tab", None)
            if mods_browser_tab is None or current_tab is mods_browser_tab:
                refresh_visible_layout = getattr(
                    self.search_display, "refresh_visible_layout", None
                )
                if callable(refresh_visible_layout):
                    if hasattr(self.search_display, "_last_grid_metrics_key"):
                        self.search_display._last_grid_metrics_key = None
                    refresh_visible_layout()
                    QTimer.singleShot(
                        0,
                        lambda: (
                            hasattr(self, "search_display")
                            and not sip.isdeleted(self)
                            and refresh_visible_layout()
                        ),
                    )
                else:
                    if hasattr(self.search_display, "_last_grid_metrics_key"):
                        self.search_display._last_grid_metrics_key = None
                    self.search_display.update_display()

    def _show_custom_tooltip(self):
        last_tooltip_target = getattr(self, "_last_tooltip_target", None)
        last_tooltip_text = getattr(self, "_last_tooltip_text", "")
        if not last_tooltip_target or not last_tooltip_text:
            return

        from PyQt6.QtGui import QCursor

        tooltip_widget = getattr(self, "_tooltip_widget", None)
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
            effect = (
                tooltip_widget.graphicsEffect()
                if hasattr(tooltip_widget, "graphicsEffect")
                else None
            )
            if effect is not None and hasattr(effect, "setOpacity"):
                effect.setOpacity(1.0)
        else:
            UIAnimator.fade_in(tooltip_widget, 150, self.app_state)

    def _hide_custom_tooltip(self):
        tooltip_widget = getattr(self, "_tooltip_widget", None)
        if (
            tooltip_widget
            and tooltip_widget.isVisible()
            and not getattr(tooltip_widget, "_is_fading_out", False)
        ):
            tooltip_widget._is_fading_out = True
            anim = UIAnimator.fade_out(tooltip_widget, 150, self.app_state)
            if anim:
                anim.finished.connect(
                    lambda tw=tooltip_widget: setattr(tw, "_is_fading_out", False)
                )
            else:
                tooltip_widget.hide()
                tooltip_widget._is_fading_out = False
        self._last_tooltip_target = None
        self._last_tooltip_text = ""

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.background_movie is not None:
            painter.drawPixmap(self.rect(), self.background_movie.currentPixmap())
        elif self.background_pixmap:
            painter.drawPixmap(self.rect(), self.background_pixmap)
        else:
            bg_color_str = (
                self.app_state.local_config.get("custom_background_color")
                or FALLBACK_WINDOW_BG
            )
            try:
                painter.fillRect(self.rect(), QColor(bg_color_str))
            except (ValueError, TypeError) as e:
                logging.debug(f"Failed to parse color '{bg_color_str}': {e}")
                painter.fillRect(self.rect(), QColor(FALLBACK_WINDOW_BG))
        self._paint_window_outline(painter)
        super().paintEvent(event)

    def _post_show_initialization(self):
        if hasattr(self, "_post_show_initialized") and self._post_show_initialized:
            return
        self._post_show_initialized = True
        BootstrapCoordinator.post_show_initialization(self)

    def _on_mod_scan_finished(self, scan_cache: dict):
        try:
            if hasattr(self.mod_service, "_mods_cache") and hasattr(
                self.mod_service, "_cache_lock"
            ):
                with self.mod_service._cache_lock:
                    self.mod_service._mods_cache = scan_cache
                    self.mod_service._mods_cache_valid = True
            self.mod_service.load_local_mods()
            saved_chapter_mode = self.app_state.local_config.get(
                "chapter_mode_enabled", False
            )
            self._trigger_initial_mods_refresh(saved_chapter_mode)
            self._load_used_mods_debounce.call(
                self.used_mods_service.load_used_mods_state
            )
        except Exception as e:
            logging.error(
                f"AppWindow: Error in _on_mod_scan_finished: {e}", exc_info=True
            )
            self.feedback_service.update_status(
                tr("status.mod_scan_error", details=str(e)), UI_COLORS["status_error"]
            )
            self.setEnabled(True)

    def _update_installed_mods_display(self, set_library_initialized=False):
        is_chapter_mode = self.app_state.current_mode == "chapter"
        selected_id = self.app_state.selected_chapter_id
        if is_chapter_mode and selected_id is None:
            show_chapter_mode_instruction(self)
        else:
            self.library_display.update_display()
            if set_library_initialized:
                self.app_state.library_initialized = True

    def _trigger_initial_mods_refresh(self, saved_chapter_mode=False):
        try:

            def update_filtered_mods_callback():
                try:
                    if hasattr(self, "search_display"):
                        self.search_display.update_filtered_mods(preserve_page=False)
                except Exception as e:
                    logging.error(
                        f"AppWindow: Error building mods list: {e}", exc_info=True
                    )

            on_fetch_finished_kwargs = {
                "update_filtered_mods_callback": update_filtered_mods_callback,
                "update_installed_mods_callback": lambda: (
                    self._update_installed_mods_display(
                        set_library_initialized=not saved_chapter_mode
                    )
                ),
                "update_action_button_callback": lambda: (
                    self.game_launch.update_button_state()
                ),
                "mods_loaded_signal": self.mods_loaded_signal,
            }
            self.refresh_controller.refresh_mods_list(
                is_initial=True,
                language_combo=self.language_combo,
                localization_callback=lambda: relocalize_ui(self),
                on_fetch_finished_kwargs=on_fetch_finished_kwargs,
            )
            try:
                if (
                    hasattr(self, "search_display")
                    and hasattr(self.app_state, "all_mods")
                    and self.app_state.all_mods
                ):
                    self.search_display.update_filtered_mods(preserve_page=False)
            except Exception as e:
                logging.error(
                    f"AppWindow: Error building initial mods list: {e}", exc_info=True
                )
        except Exception as e:
            logging.error(
                f"AppWindow: Error in _load_mods_and_build_list_synchronously: {e}",
                exc_info=True,
            )

    def _get_update_widgets(self):
        return [self.action_button, self.chat_button, self.change_background_button]

    def _set_update_ui_enabled(self, enabled: bool):
        for w in self._get_update_widgets():
            if w:
                w.setEnabled(enabled)
        if getattr(self, "top_refresh_button", None):
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
            logging.debug(f"Update cleanup - progress bar: {e}")
        self.app_state.update_in_progress = False
        try:
            if not self.app_state.is_settings_view:
                self.tab_widget.setEnabled(True)
            self._set_update_ui_enabled(True)
            self.game_launch.update_button_state()
        except Exception as e:
            logging.debug(f"Update cleanup - UI restore: {e}")

    def _on_progress_update(self, value: int):
        self.progress_bar.setValue(value)
        if value > 0 and (not self.progress_bar.isVisible()):
            self.progress_bar.setVisible(True)

    def _update_status(self, message: str, color: str = "white"):
        actual_color = UI_COLORS.get(color, color)
        if not self.status_label.wordWrap():
            self.status_label.setWordWrap(True)
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {actual_color};")

    def _update_online_label(self, count: int):
        if hasattr(self, "online_label") and (self.online_label is not None):
            self._last_online_count = count
            display_count = "?" if count < 0 else count
            self.online_label.setText(
                f"<span style='color:{UI_COLORS['status_ready']};'>●</span> {tr('status.online_count', count=display_count)}"
            )

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

    def closeEvent(self, event):
        app = QApplication.instance()
        if app:
            with contextlib.suppress(Exception):
                app.removeEventFilter(self)
        if hasattr(self, 'plugins_ui') and self.plugins_ui:
            self.plugins_ui.shutdown()
        from app.cleanup import perform_close_cleanup

        perform_close_cleanup(self)
        super().closeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_title_bar_window_state()
            if not self.isMinimized():
                self._schedule_window_layout_refresh(220)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._start_system_resize_if_needed(event.position().toPoint())
        ):
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
        if hasattr(self, "launcher_icon_label") and hasattr(self, "top_panel_widget"):
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
        last_selected_profile = self.app_state.local_config.get("last_selected_profile")
        active_profile = (
            self.profile_service.active_name
            if hasattr(self, "profile_service")
            else None
        )
        self.app_state.local_config = (
            self.settings_service.read_json(self.app_state.config_path) or {}
        )
        if active_profile:
            self.app_state.local_config["active_profile"] = active_profile
        self.app_state.local_config["last_selected_profile"] = last_selected_profile
        try:
            self.mod_service.migrate_metadata_from_local_configs()
        except Exception as e:
            logging.warning(f"Metadata migration failed: {e}")
        self.app_state.local_config["metadata_migrated_v2"] = True
        self.settings_service.write_local_config()

    def _update_qt_locale(self, language_code):
        self.context.update_qt_locale(language_code)

    def _set_lib_search_icon(self, is_searching: bool):
        tc = get_theme_color(self.app_state.local_config, "main_text")
        self.library_search_button.setIcon(
            colored_icon("reset", tc) if is_searching else colored_icon("search", tc)
        )
        self.library_search_button.setIconSize(QSize(16, 16))

    def _refresh_themed_icons(self):
        """Re-read theme color and regenerate all SVG-based button icons."""
        tc = get_theme_color(self.app_state.local_config, "main_text")
        if hasattr(self, "top_refresh_button"):
            self.top_refresh_button.setIcon(colored_icon("refresh", tc))
            self.top_refresh_button.setIconSize(QSize(20, 20))
        if hasattr(self, "library_search_button"):
            is_searching = bool(getattr(self, "library_search_text", ""))
            self.library_search_button.setIcon(
                colored_icon("reset", tc)
                if is_searching
                else colored_icon("search", tc)
            )
            self.library_search_button.setIconSize(QSize(16, 16))
        if hasattr(self, "library_sort_order_btn") and self.library_sort_order_btn:
            is_asc = getattr(self, "library_sort_ascending", False)
            self.library_sort_order_btn.setIcon(
                colored_icon("arrow_up" if is_asc else "arrow_down", tc)
            )
            self.library_sort_order_btn.setIconSize(QSize(12, 12))
        if hasattr(self, "title_bar") and self.title_bar:
            self.title_bar._update_window_icons()

    def _show_library_search_dialog(self):
        from PyQt6.QtWidgets import QInputDialog

        if getattr(self, "library_search_text", ""):
            self.library_search_text = ""
            self.app_state.library_search_text = ""
            self._set_lib_search_icon(False)
            self.library_search_button.setToolTip(tr("ui.search_placeholder"))
            self.library_display.update_display()
        else:
            text, ok = QInputDialog.getText(
                self, tr("ui.search_tab"), tr("ui.search_in_name_description")
            )
            if ok and text.strip():
                self.library_search_text = text.strip()
                self.app_state.library_search_text = text.strip()
                self._set_lib_search_icon(True)
                self.library_search_button.setToolTip(
                    tr("ui.clear_search_tooltip", text=text.strip())
                )
                self.library_display.update_display()

    def _prompt_for_game_path(self, is_initial=False):
        result = self.settings_service.prompt_for_game_path(is_initial)
        if result:
            self.game_launch.update_button_state()
        if is_initial and (not result):
            self.customization_service.start_background_music()
        return result

    def _update_all_action_buttons(self):
        if hasattr(self, "search_display"):
            self.search_display.update_search_cards()

    def _on_refresh_clicked(self, is_initial=False):
        if (
            hasattr(self, "plugins_ui")
            and self.plugins_ui
            and getattr(self.app_state, "is_settings_view", False)
            and hasattr(self, "settings_tab_widget")
            and hasattr(self, "plugins_tab")
            and self.settings_tab_widget.currentWidget() is self.plugins_tab
        ):
            self.plugins_ui.ensure_loaded(force_refresh=True)
        if hasattr(self, "theme") and self.theme:
            self.theme.init_theme_list()
        if not is_initial and self.app_state.has_internet:
            reload_global_settings(
                self,
                callback=lambda success: (
                    check_and_show_announce(self, force_check=True) if success else None
                ),
            )
            self.session_manager.request_presence_refresh()

        def update_filtered_callback():
            return (
                self.search_display.update_filtered_mods(preserve_page=False)
                if hasattr(self, "search_display") and self.search_display
                else None
            )

        def update_installed_callback():
            return self._update_installed_mods_display()

        def update_action_callback():
            return self.game_launch.update_button_state()

        callbacks = {
            "update_filtered_mods_callback": update_filtered_callback,
            "update_installed_mods_callback": update_installed_callback,
            "update_action_button_callback": update_action_callback,
            "mods_loaded_signal": self.mods_loaded_signal,
        }

        self.refresh_controller.refresh_mods_list(
            is_initial=is_initial,
            language_combo=self.language_combo,
            localization_callback=lambda: relocalize_ui(self),
            on_fetch_finished_kwargs=callbacks,
        )

    def _on_shortcut_button_click(self):
        from controllers.shortcut_controller import on_shortcut_button_click

        on_shortcut_button_click(
            self.app_state, self.feedback_service, self.used_mods_service, self
        )

    def _set_widget_attr(self, widget_name: str, method: str, value):
        widget = getattr(self, widget_name, None)
        if widget and hasattr(widget, method):
            getattr(widget, method)(value)
            if method == "setIcon" and hasattr(widget, "setText"):
                widget.setText("")

    def _show_pending_dialogs(self):
        if not self.app_state.pending_dialogs:
            return
        pending = self.app_state.pending_dialogs.copy()
        self.app_state.pending_dialogs.clear()
        for dialog_type, dialog_data in pending:
            if dialog_type == "update":
                prompt_for_update(self, dialog_data)

    def _zoom_ui(self, direction):
        current_zoom = self.app_state.local_config.get("ui_scale", 1.0)
        new_zoom = max(0.5, min(2.0, round(current_zoom + (0.1 * direction), 1)))
        if new_zoom != current_zoom:
            self.app_state.local_config["ui_scale"] = new_zoom
            if hasattr(self, "ui_scale_spinbox"):
                self.ui_scale_spinbox.blockSignals(True)
                self.ui_scale_spinbox.setValue(int(new_zoom * 100))
                self.ui_scale_spinbox.blockSignals(False)
            self.settings_service.write_local_config()
            if hasattr(self, "_ui_scale_timer"):
                self._ui_scale_timer.start()
            self._refresh_scaled_card_displays()
