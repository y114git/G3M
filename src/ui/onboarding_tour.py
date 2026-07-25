"""Interactive first-run tour over the real main window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import get_library_tab_title, tr
from ui.common.styling import get_border_radius, get_theme_color


@dataclass(frozen=True)
class _TourStep:
    key: str
    target: str = ""
    view: Literal["current", "main", "settings", "browser", "library"] = "current"
    settings_tab: int = -1


_STEPS = (
    _TourStep("welcome"),
    _TourStep("settings", "settings_button", "main"),
    _TourStep("app_settings", "settings_tabs", "settings", 0),
    _TourStep("appearance", "settings_tabs", "settings", 1),
    _TourStep("game_setup", "settings_game_path_edit", "settings", 2),
    _TourStep("browser_settings", "settings_tabs", "settings", 3),
    _TourStep("library_settings", "settings_tabs", "settings", 4),
    _TourStep("plugins", "settings_tabs", "settings", 5),
    _TourStep("browser", "modgame_combo", "browser"),
    _TourStep("browser_filters", "mods_browser_tab", "browser"),
    _TourStep("downloads", "downloads_button", "browser"),
    _TourStep("library", "library_tab", "library"),
    _TourStep("add_mod", "add_mod_button", "library"),
    _TourStep("profiles", "profile_combo", "library"),
    _TourStep("game_versions", "library_game_versions_button", "library"),
    _TourStep("priority", "priority_button", "library"),
    _TourStep("modpack", "create_modpack_button", "library"),
    _TourStep("diagnostics", "diagnostics_button", "library"),
    _TourStep("common_problems", "diagnostics_button", "library"),
    _TourStep("modding_tools", "library_modding_tools_button", "library"),
    _TourStep("shortcut", "shortcut_button", "main"),
    _TourStep("community", "community_button", "main"),
    _TourStep("game_extras", "main_tab_widget", "main"),
    _TourStep("launch", "action_button", "main"),
    _TourStep("finish"),
)


class OnboardingTour(QWidget):
    """Spotlight tour which navigates without activating highlighted actions."""

    completed = pyqtSignal(bool)

    def __init__(self, window) -> None:
        super().__init__(window)
        self.host = window
        self._index = 0
        self._target_rect = QRect()
        self._restore_settings = bool(window.app_state.is_settings_view)
        self._restore_main_tab = window.main_tab_widget.currentIndex()
        self._restore_settings_tab = window.settings_tab_widget.currentIndex()
        self._temporary_tabs: list[QWidget] = []
        self.setObjectName("onboardingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        window.installEventFilter(self)
        self._build_card()
        self.apply_theme()
        self.setGeometry(window.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._show_step(0)

    def _build_card(self) -> None:
        self.card = QFrame(self)
        self.card.setObjectName("onboardingCoachCard")
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        self.counter = QLabel(self.card)
        self.counter.setObjectName("onboardingCounter")
        layout.addWidget(self.counter)

        self.title = QLabel(self.card)
        font = QFont(self.font())
        font.setPointSize(max(14, font.pointSize() + 3))
        font.setBold(True)
        self.title.setFont(font)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.body = QLabel(self.card)
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.body)

        buttons = QHBoxLayout()
        self.skip_button = QPushButton(self.card)
        self.skip_button.clicked.connect(lambda: self._complete(False))
        self.configure_button = QPushButton(self.card)
        self.configure_button.clicked.connect(lambda: self._complete(True))
        layout.addWidget(self.configure_button)
        self.back_button = QPushButton(self.card)
        self.back_button.clicked.connect(lambda: self._show_step(self._index - 1))
        self.next_button = QPushButton(self.card)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

    def _prepare_view(self, step: _TourStep) -> None:
        if step.view in {"main", "browser", "library"}:
            if self.host.app_state.is_settings_view:
                self.host.settings_ui.toggle_settings_view()
            if step.view in {"browser", "library"}:
                tab_name = (
                    "mods_browser_tab" if step.view == "browser" else "library_tab"
                )
                tab = getattr(self.host, tab_name, None)
                index = self.host.main_tab_widget.indexOf(tab)
                if isinstance(tab, QWidget) and index < 0:
                    title = (
                        tr("ui.search_tab")
                        if step.view == "browser"
                        else get_library_tab_title(self.host.app_state)
                    )
                    index = self.host.main_tab_widget.addTab(tab, title)
                    self._temporary_tabs.append(tab)
                if index >= 0:
                    self.host.main_tab_widget.setCurrentIndex(index)
        elif step.view == "settings":
            if not self.host.app_state.is_settings_view:
                self.host.settings_ui.toggle_settings_view()
            if step.settings_tab >= 0:
                self.host.settings_tab_widget.setCurrentIndex(step.settings_tab)

    def _find_target(self, name: str) -> QWidget | None:
        target = (
            self.host.settings_tab_widget.tabBar()
            if name == "settings_tabs"
            else getattr(self.host, name, None)
        )
        if not isinstance(target, QWidget) or sip.isdeleted(target):
            return None
        parent = target.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(target, 24, 24)
                break
            parent = parent.parentWidget()
        return target if target.isVisibleTo(self.host) else None

    def _show_step(self, index: int) -> None:
        self._index = max(0, min(index, len(_STEPS) - 1))
        step = _STEPS[self._index]
        self._prepare_view(step)
        self.counter.setText(
            tr("onboarding.tour.progress", current=self._index + 1, total=len(_STEPS))
        )
        self.title.setText(tr(f"onboarding.tour.steps.{step.key}.title"))
        self.body.setText(tr(f"onboarding.tour.steps.{step.key}.body"))
        self.skip_button.setText(tr("onboarding.skip_button"))
        self.back_button.setText(tr("onboarding.back_button"))
        self.next_button.setText(
            tr("onboarding.finish_button")
            if self._index == len(_STEPS) - 1
            else tr("onboarding.next_button")
        )
        self.configure_button.setText(
            tr("onboarding.configure_button").replace("&", "&&")
        )
        self.configure_button.setVisible(self._index == len(_STEPS) - 1)
        self.back_button.setEnabled(self._index > 0)
        QTimer.singleShot(0, self._reposition)

    def _reposition(self) -> None:
        if sip.isdeleted(self):
            return
        step = _STEPS[self._index]
        target = self._find_target(step.target) if step.target else None
        if target is None:
            self._target_rect = QRect()
        else:
            origin = self.mapFromGlobal(target.mapToGlobal(target.rect().topLeft()))
            self._target_rect = QRect(origin, target.size()).adjusted(-7, -7, 7, 7)

        card_width = min(460, max(320, self.width() - 40))
        self.card.setFixedWidth(card_width)
        self.body.setMaximumWidth(card_width - 36)
        self.card.adjustSize()
        margin = 18
        if self._target_rect.isEmpty():
            x = (self.width() - self.card.width()) // 2
            y = (self.height() - self.card.height()) // 2
        else:
            below = self._target_rect.bottom() + margin
            above = self._target_rect.top() - self.card.height() - margin
            y = below if below + self.card.height() <= self.height() - margin else above
            if y < margin:
                y = max(margin, (self.height() - self.card.height()) // 2)
            x = self._target_rect.center().x() - self.card.width() // 2
            x = max(margin, min(x, self.width() - self.card.width() - margin))
        self.card.move(x, y)
        self.card.raise_()
        self.update()

    def _next(self) -> None:
        if self._index == len(_STEPS) - 1:
            self._complete(False)
        else:
            self._show_step(self._index + 1)

    def _restore_view(self) -> None:
        for tab in self._temporary_tabs:
            index = self.host.main_tab_widget.indexOf(tab)
            if index >= 0:
                self.host.main_tab_widget.removeTab(index)
        self._temporary_tabs.clear()
        self.host.main_tab_widget.setCurrentIndex(self._restore_main_tab)
        if self._restore_settings != self.host.app_state.is_settings_view:
            self.host.settings_ui.toggle_settings_view()
        if self._restore_settings:
            self.host.settings_tab_widget.setCurrentIndex(self._restore_settings_tab)

    def _complete(self, open_settings: bool) -> None:
        self._restore_view()
        self.completed.emit(open_settings)
        self.close()

    def relocalize_ui(self) -> None:
        self._show_step(self._index)

    def apply_theme(self) -> None:
        config = self.host.app_state.local_config
        background = get_theme_color(config, "elements")
        border = get_theme_color(config, "border")
        text = get_theme_color(config, "main_text")
        secondary = get_theme_color(config, "secondary_text")
        radius = get_border_radius(config)
        self.card.setStyleSheet(
            f"#onboardingCoachCard {{ background: {background}; border: 2px solid "
            f"{border}; border-radius: {radius}px; }} "
            f"#onboardingCoachCard QLabel {{ color: {text}; }} "
            f"#onboardingCounter {{ color: {secondary}; }}"
        )
        self._reposition()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not self._target_rect.isEmpty():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._target_rect), 8, 8)
            shade = shade.subtracted(hole)
        painter.fillPath(shade, QColor(0, 0, 0, 175))
        if not self._target_rect.isEmpty():
            painter.setPen(QPen(QColor(get_theme_color(
                self.host.app_state.local_config, "border"
            )), 3))
            painter.drawRoundedRect(self._target_rect, 8, 8)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
            self._reposition()
        return False

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right):
            self._next()
        elif event.key() == Qt.Key.Key_Left:
            self._show_step(self._index - 1)
        elif event.key() == Qt.Key.Key_Escape:
            self._complete(False)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.host.removeEventFilter(self)
        super().closeEvent(event)
