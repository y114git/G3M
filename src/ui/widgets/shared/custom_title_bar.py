"""Custom title bar widgets for the main window."""

import logging

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ui.common.styling import get_theme_color
from utils.path_utils import colored_icon

logger = logging.getLogger(__name__)


class CustomTitleBar(QWidget):
    log_viewer_requested = pyqtSignal()
    support_packager_requested = pyqtSignal()
    changelog_requested = pyqtSignal()
    onboarding_requested = pyqtSignal()
    about_requested = pyqtSignal()
    minimize_requested = pyqtSignal()
    maximize_restore_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, parent=None, app_state=None) -> None:
        super().__init__(parent)
        self.setObjectName("customTitleBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.app_state = app_state

        self._maximize_tooltip = ""
        self._restore_tooltip = ""
        self._menu_popup_gap = 6

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.left_widget = QWidget(self)
        self.left_widget.setObjectName("titleBarLeftWidget")
        left_layout = QHBoxLayout(self.left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        self._left_layout = left_layout

        self.windows_button, self.windows_menu = self.add_menu_button()
        self.log_viewer_action = QAction(self.windows_menu)
        self.log_viewer_action.triggered.connect(self.log_viewer_requested.emit)
        self.windows_menu.addAction(self.log_viewer_action)
        self.support_packager_action = QAction(self.windows_menu)
        self.support_packager_action.triggered.connect(
            self.support_packager_requested.emit
        )
        self.windows_menu.addAction(self.support_packager_action)

        self.help_button, self.help_menu = self.add_menu_button()
        self.changelog_action = QAction(self.help_menu)
        self.changelog_action.triggered.connect(self.changelog_requested.emit)
        self.help_menu.addAction(self.changelog_action)
        self.onboarding_action = QAction(self.help_menu)
        self.onboarding_action.triggered.connect(self.onboarding_requested.emit)
        self.help_menu.addAction(self.onboarding_action)
        self.about_action = QAction(self.help_menu)
        self.about_action.triggered.connect(self.about_requested.emit)
        self.help_menu.addAction(self.about_action)
        left_layout.addStretch(1)

        self.right_widget = QWidget(self)
        self.right_widget.setObjectName("titleBarRightWidget")
        right_layout = QHBoxLayout(self.right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self._right_layout = right_layout

        self.minimize_button = QPushButton(self.right_widget)
        self.minimize_button.setObjectName("titleBarMinimizeButton")
        self.minimize_button.clicked.connect(self.minimize_requested.emit)

        self.maximize_button = QPushButton(self.right_widget)
        self.maximize_button.setObjectName("titleBarMaximizeButton")
        self.maximize_button.clicked.connect(self.maximize_restore_requested.emit)

        self.close_button = QPushButton(self.right_widget)
        self.close_button.setObjectName("titleBarCloseButton")
        self.close_button.clicked.connect(self.close_requested.emit)

        self._update_window_icons()

        right_layout.addStretch(1)
        right_layout.addWidget(self.minimize_button)
        right_layout.addWidget(self.maximize_button)
        right_layout.addWidget(self.close_button)

        layout.addWidget(self.left_widget, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        layout.addWidget(self.right_widget, 0, Qt.AlignmentFlag.AlignRight)

        for widget in (self.left_widget, self.right_widget):
            widget.installEventFilter(self)

        self.apply_metrics()

    def add_menu_button(self, text: str = ""):
        button = QToolButton(self.left_widget)
        button.setObjectName("titleBarMenuButton")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setText(text)
        menu = QMenu(button)
        menu.setObjectName("titleBarPopupMenu")
        button.clicked.connect(
            lambda _checked=False, b=button, m=menu: self._show_menu_popup(b, m)
        )
        menu.aboutToHide.connect(lambda b=button: self._reset_menu_button_state(b))
        self._left_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        button.installEventFilter(self)
        return button, menu

    def _show_menu_popup(self, button: QToolButton, menu: QMenu):
        if not menu.actions():
            return
        if menu.isVisible():
            menu.close()
            return
        button.setDown(True)
        button.update()
        menu.popup(
            button.mapToGlobal(QPoint(0, button.height() + self._menu_popup_gap))
        )

    @staticmethod
    def _reset_menu_button_state(button: QToolButton) -> None:
        if not button or sip.isdeleted(button):
            return
        try:
            button.setDown(False)
            button.clearFocus()
            button.update()
        except RuntimeError:
            return

    def set_localized_texts(
        self,
        windows_text: str,
        log_viewer_text: str,
        support_packager_text: str,
        help_text: str,
        changelog_text: str,
        onboarding_text: str,
        about_text: str,
        minimize_tooltip: str,
        maximize_tooltip: str,
        restore_tooltip: str,
        close_tooltip: str,
    ):
        self.windows_button.setText(windows_text)
        self.log_viewer_action.setText(log_viewer_text)
        self.log_viewer_action.setToolTip(log_viewer_text)
        self.support_packager_action.setText(support_packager_text)
        self.support_packager_action.setToolTip(support_packager_text)
        self.help_button.setText(help_text)
        self.changelog_action.setText(changelog_text)
        self.changelog_action.setToolTip(changelog_text)
        self.onboarding_action.setText(onboarding_text)
        self.onboarding_action.setToolTip(onboarding_text)
        self.about_action.setText(about_text)
        self.about_action.setToolTip(about_text)
        self.minimize_button.setToolTip(minimize_tooltip)
        self._maximize_tooltip = maximize_tooltip
        self._restore_tooltip = restore_tooltip
        self.close_button.setToolTip(close_tooltip)
        self.sync_window_state(self.window().isMaximized() if self.window() else False)

    def _tc(self):
        return (
            get_theme_color(self.app_state.local_config, "main_text")
            if self.app_state
            else "#ffffff"
        )

    def _update_window_icons(self):
        """Update window control buttons with colored icons."""
        tc = self._tc()
        for btn, name in (
            (self.minimize_button, "minimize"),
            (self.close_button, "cross"),
        ):
            btn.setIcon(colored_icon(name, tc))
            btn.setIconSize(QSize(12, 12))
        self.sync_window_state(self.window().isMaximized() if self.window() else False)

    def sync_window_state(self, is_maximized: bool):
        """Sync window state and update maximize/restore icon."""
        tc = self._tc()
        self.maximize_button.setIcon(
            colored_icon("restore" if is_maximized else "maximize", tc)
        )
        self.maximize_button.setIconSize(QSize(12, 12))
        self.maximize_button.setToolTip(
            self._restore_tooltip if is_maximized else self._maximize_tooltip
        )

    def apply_metrics(self, scale: float = 1.0):
        scale_value = max(1, round(scale * 100)) / 100.0

        def scaled(value: int) -> int:
            return max(1, round(value * scale_value))

        self.layout().setContentsMargins(scaled(8), scaled(4), scaled(8), scaled(4))
        self.layout().setSpacing(scaled(6))
        self._right_layout.setSpacing(scaled(4))
        self.setFixedHeight(scaled(38))
        self._menu_popup_gap = scaled(5)
        button_size = scaled(26)
        for button in self.left_widget.findChildren(QToolButton):
            button.setMinimumHeight(scaled(20))
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.setFixedSize(button_size, button_size)
            if self.app_state:
                icon_size = scaled(12)
                button.setIconSize(QSize(icon_size, icon_size))

    def _can_start_window_action(self, pos) -> bool:
        child = self.childAt(pos)
        return not isinstance(child, (QPushButton, QToolButton))

    def _start_system_move(self):
        window = self.window()
        handle = window.windowHandle() if window else None
        if handle is None or window.isMaximized():
            return False
        try:
            return bool(handle.startSystemMove())
        except Exception as e:
            logger.debug("startSystemMove failed: %s", e)
            return False

    def eventFilter(self, watched, event):
        if watched in (self.left_widget, self.right_widget):
            pos = (
                watched.mapTo(self, event.position().toPoint())
                if hasattr(event, "position")
                else None
            )
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and pos is not None
                and self._can_start_window_action(pos)
                and self._start_system_move()
            ):
                event.accept()
                return True
            if (
                event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
                and pos is not None
                and self._can_start_window_action(pos)
            ):
                self.maximize_restore_requested.emit()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._can_start_window_action(event.position().toPoint())
            and self._start_system_move()
        ):
            event.accept()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._can_start_window_action(event.position().toPoint())
        ):
            self.maximize_restore_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
