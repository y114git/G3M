import platform
from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.config import (
    QSS_ARROW_LABEL,
    QSS_BOLD_LABEL,
    QSS_BOLD_TRANSPARENT,
    QSS_PADDING_LEFT_5,
    QSS_SETTINGS_TAB_ALIGNMENT,
    SETTINGS_COLOR_CONFIG,
)
from config.settings_schema import get_theme_color_key
from models.game_modes import get_visible_game_entries
from services.localization_service import (
    get_settings_library_tab_title,
    localization_service,
    tr,
)
from ui.common.styling import (
    get_border_radius,
    get_theme_color,
    get_ui_scale_factor,
    install_widget_update_handler,
)
from ui.utils.ui_utils import UIAnimator
from ui.widgets.shared.custom_controls import NoScrollComboBox
from utils.path_utils import colored_icon


class _FilesDropWidget(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            u.isLocalFile() for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and any(
            u.isLocalFile() for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [
                u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()
            ]
            if paths:
                event.acceptProposedAction()
                self.files_dropped.emit(paths)


class _ElidedPathLineEdit(QLineEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.textEdited.connect(self._on_text_edited)

    def _on_text_edited(self, text: str) -> None:
        self._full_text = text

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        if self.hasFocus():
            self._show_full_text()
        else:
            self._apply_elided_text()

    def full_text(self) -> str:
        if self.hasFocus():
            return self.text().strip()
        return self._full_text.strip()

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._show_full_text()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._full_text = self.text()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        super().focusOutEvent(event)
        self._apply_elided_text()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self.hasFocus():
            self._apply_elided_text()

    def _show_full_text(self) -> None:
        was_blocked = self.blockSignals(True)
        self.setText(self._full_text)
        self.setCursorPosition(len(self._full_text))
        self.blockSignals(was_blocked)

    def _apply_elided_text(self) -> None:
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            self._full_text,
            Qt.TextElideMode.ElideMiddle,
            max(0, self.contentsRect().width() - 12),
        )
        was_blocked = self.blockSignals(True)
        self.setText(elided)
        self.blockSignals(was_blocked)


class SettingsViewBuilder:
    def __init__(self, app_state, parent=None) -> None:
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}
        self._dynamic_style_signal_connected = False

    def build(self) -> QFrame:
        settings_widget = QFrame(self.parent)
        settings_widget.setObjectName("settings_widget")
        settings_layout = QVBoxLayout(settings_widget)

        tab_widget = QTabWidget()
        tab_widget.setObjectName("settings_tab_widget")
        tab_widget.setStyleSheet(QSS_SETTINGS_TAB_ALIGNMENT)
        tab_widget.addTab(
            self._build_general_tab(tab_widget), tr("ui.settings_tab_general")
        )
        tab_widget.addTab(
            self._build_appearance_tab(tab_widget), tr("ui.settings_tab_appearance")
        )
        tab_widget.addTab(self._build_game_tab(tab_widget), tr("ui.settings_tab_game"))
        tab_widget.addTab(
            self._build_mods_browser_tab(tab_widget), tr("ui.settings_tab_mods_browser")
        )
        tab_widget.addTab(
            self._build_library_tab(tab_widget),
            get_settings_library_tab_title(self.app_state),
        )
        plugins_tab = self._build_plugins_tab(tab_widget)
        tab_widget.addTab(plugins_tab, tr("ui.settings_tab_plugins"))
        self.widgets["plugins_tab"] = plugins_tab
        settings_layout.addWidget(tab_widget, stretch=1)

        settings_layout.addStretch()

        settings_widget.setVisible(False)

        self._connect_dynamic_style_refresh()

        self.widgets["settings_widget"] = settings_widget
        self.widgets["settings_tab_widget"] = tab_widget
        return settings_widget

    def refresh_dynamic_styles(self) -> None:
        tc = get_theme_color(self.app_state.local_config, "main_text")
        icon_size = self._scaled_icon_size()
        button_size = self._scaled_icon_button_size()
        seen = set()
        section_reset_buttons = [
            btn for btn, *_ in self.widgets.get("_section_reset_buttons", [])
        ]
        for btn in [*self.widgets.values(), *section_reset_buttons]:
            icon_name = getattr(btn, "_themed_icon_name", None) if btn else None
            if not btn or not icon_name or id(btn) in seen:
                continue
            seen.add(id(btn))
            btn.setIcon(colored_icon(icon_name, tc))
            btn.setIconSize(QSize(icon_size, icon_size))
            if getattr(btn, "_scaled_icon_button", False):
                btn.setFixedSize(button_size, button_size)
        if self.parent and getattr(self.parent, "games_manager_button", None):
            from app.game_ui import update_games_manager_button_style

            update_games_manager_button_style(self.parent)

    def _scaled_icon_button_size(self) -> int:
        scale = get_ui_scale_factor(self.app_state.local_config)
        return max(32, round(35 * scale))

    def _scaled_icon_size(self) -> int:
        scale = get_ui_scale_factor(self.app_state.local_config)
        return max(16, round(20 * scale))

    def _connect_dynamic_style_refresh(self) -> None:
        if self._dynamic_style_signal_connected:
            return
        settings_service = getattr(self.parent, "settings_service", None)
        if settings_service is None:
            return
        settings_service.theme_changed.connect(self.refresh_dynamic_styles)
        self._dynamic_style_signal_connected = True

    def _wrap_in_scroll(
        self, content_widget: QWidget, parent: QWidget = None
    ) -> QScrollArea:
        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content_widget)
        return scroll

    def _build_simple_tab_page(self) -> tuple:
        """Create a simple settings tab page with standard layout. Returns (page, layout)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(4)
        layout.setContentsMargins(20, 12, 20, 20)
        return page, layout

    @staticmethod
    def _mark_reset(
        widget: QWidget,
        *,
        config_key: str = "",
        reset_action: str = "",
        reset_value=None,
    ) -> QWidget:
        if config_key:
            widget.setProperty("reset_config_key", config_key)
        if reset_action:
            widget.setProperty("reset_action", reset_action)
        if reset_value is not None:
            widget.setProperty("reset_value", reset_value)
        return widget

    def _collapsible_section(
        self, title: str, section_key: str, lang_key: str = "", parent: QWidget = None
    ) -> tuple:
        """Create a collapsible section. Returns (section_widget, content_layout)."""
        collapsed_map = self.app_state.local_config.get(
            "settings_collapsed_sections", {}
        )
        is_collapsed = collapsed_map.get(section_key, False)

        section = QWidget(parent)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 8, 0, 4)
        section_layout.setSpacing(6)

        header = QWidget(section)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        from ui.common.styling import get_section_line_color

        line_color = get_section_line_color(self.app_state.local_config)
        line_style = f"color: {line_color};"

        line_left = QFrame()
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_left.setFrameShadow(QFrame.Shadow.Sunken)
        line_left.setStyleSheet(line_style)
        header_layout.addWidget(line_left, 1)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(QSS_BOLD_TRANSPARENT)
        header_layout.addWidget(title_lbl)

        reset_btn = self._create_icon_btn("⭯", app_state=self.app_state)
        reset_btn.setToolTip(tr("buttons.reset_settings"))
        if not self.app_state.local_config.get("show_reset_buttons", False):
            reset_btn.setVisible(False)
        header_layout.addWidget(reset_btn)

        arrow = QLabel("\u25b6" if is_collapsed else "\u25bc")
        arrow.setStyleSheet(QSS_ARROW_LABEL)
        header_layout.addWidget(arrow)

        line_right = QFrame()
        line_right.setFrameShape(QFrame.Shape.HLine)
        line_right.setFrameShadow(QFrame.Shadow.Sunken)
        line_right.setStyleSheet(line_style)
        header_layout.addWidget(line_right, 1)

        if "_section_lines" not in self.widgets:
            self.widgets["_section_lines"] = []
        self.widgets["_section_lines"].append(line_left)
        self.widgets["_section_lines"].append(line_right)

        content = QWidget(section)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 10, 30, 10)
        content_layout.setSpacing(12)
        if is_collapsed:
            content.setVisible(False)

        def toggle_section(event=None):
            vis = not content.isVisible()
            arrow.setText("\u25bc" if vis else "\u25b6")
            UIAnimator.collapse_expand(content, vis, 200, self.app_state)
            cm = self.app_state.local_config.get("settings_collapsed_sections", {})
            cm[section_key] = not vis
            self.app_state.local_config["settings_collapsed_sections"] = cm

        header.mousePressEvent = toggle_section

        section_layout.addWidget(header)
        section_layout.addWidget(content)

        if lang_key:
            if "_section_headers" not in self.widgets:
                self.widgets["_section_headers"] = []
            self.widgets["_section_headers"].append((title_lbl, lang_key))

        if "_collapsible_toggles" not in self.widgets:
            self.widgets["_collapsible_toggles"] = []
        self.widgets["_collapsible_toggles"].append(toggle_section)

        if "_section_reset_buttons" not in self.widgets:
            self.widgets["_section_reset_buttons"] = []
        self.widgets["_section_reset_buttons"].append(
            (reset_btn, section_key, lang_key, content)
        )

        return section, content_layout

    def _styled_checkbox(
        self, text: str, tooltip: str = "", config_key: str = "", reset_value=None
    ) -> QCheckBox:
        cb = QCheckBox(text)
        if tooltip:
            cb.setToolTip(tooltip)
        return self._mark_reset(cb, config_key=config_key, reset_value=reset_value)

    def _styled_label(self, text: str, bold: bool = False) -> QLabel:
        lbl = QLabel(text)
        if bold:
            lbl.setStyleSheet(QSS_BOLD_LABEL)
        return lbl

    def _styled_button(
        self, text: str, width: int = 80, tooltip: str = "", reset_action: str = ""
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumWidth(width)
        btn.setMinimumHeight(32)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        if tooltip:
            btn.setToolTip(tooltip)
        return self._mark_reset(btn, reset_action=reset_action)

    _EMOJI_TO_ICON = {"⭯": "reset", "✔": "checkmark", "🖫": "save", "🗑": "delete"}

    def _create_icon_btn(
        self, icon_text: str, obj_name: str = "actionIconBtn", app_state=None
    ) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName(obj_name)
        btn._scaled_icon_button = True
        button_size = self._scaled_icon_button_size()
        btn.setFixedSize(button_size, button_size)
        icon_name = self._EMOJI_TO_ICON.get(icon_text)
        if icon_name and app_state:
            btn._themed_icon_name = icon_name

            def _apply_icon(b=btn, i=icon_name, s=app_state, builder=self):
                b.setIcon(colored_icon(i, get_theme_color(s.local_config, "main_text")))
                b.setIconSize(
                    QSize(builder._scaled_icon_size(), builder._scaled_icon_size())
                )
                b.setFixedSize(
                    builder._scaled_icon_button_size(),
                    builder._scaled_icon_button_size(),
                )

            install_widget_update_handler(
                btn, _apply_icon, attr_name="_themed_icon_update_filter"
            )
        else:
            btn.setText(icon_text)
        return btn

    def _create_color_row(self, label_text: str, parent: QWidget = None):
        row = QHBoxLayout()
        row.setSpacing(15)
        label = QLabel(label_text, parent)
        label.setStyleSheet(QSS_PADDING_LEFT_5)
        disp = QLineEdit(parent)
        disp.setObjectName("color_display")
        disp.setMinimumWidth(180)
        disp.setMaximumWidth(230)
        disp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton(tr("ui.select_color"), parent)
        btn.setMinimumWidth(80)
        btn.setMinimumHeight(30)
        reset = self._create_icon_btn("⭯", app_state=self.app_state)
        row.addWidget(label)
        row.addStretch()
        row.addWidget(disp)
        row.addWidget(btn)
        row.addWidget(reset)
        return row, disp, btn, reset, label

    def _create_path_input_row(
        self,
        *,
        object_prefix: str,
        label_text: str,
        browse_tooltip: str,
        reset_action: str = "",
        reset_config_key: str = "",
    ) -> tuple[QWidget, QLabel, _ElidedPathLineEdit, QPushButton, QPushButton]:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.setSpacing(8)

        row_label = self._styled_label(label_text, bold=True)
        row_label.setMinimumWidth(150)
        row_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(row_label)

        path_edit = _ElidedPathLineEdit(row_widget)
        path_edit.setObjectName(f"{object_prefix}_edit")
        path_edit.setMinimumWidth(480)
        path_edit.setMaximumWidth(720)
        path_edit.setPlaceholderText(tr("ui.path_field_placeholder"))
        path_edit.setToolTip("")
        row_layout.addWidget(path_edit)

        browse_button = self._styled_button("", 44, browse_tooltip)
        browse_button.setObjectName(f"{object_prefix}_browse_button")
        browse_button.setText("...")
        browse_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row_layout.addWidget(browse_button)

        reset_button = self._create_icon_btn("⭯", app_state=self.app_state)
        reset_button.setObjectName(f"{object_prefix}_reset_button")
        reset_button.setToolTip(tr("buttons.reset_settings"))
        reset_button.setVisible(False)
        reset_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if reset_config_key:
            self._mark_reset(reset_button, config_key=reset_config_key)
        elif reset_action:
            self._mark_reset(reset_button, reset_action=reset_action)
        row_layout.addWidget(reset_button)
        return row_widget, row_label, path_edit, browse_button, reset_button

    def _build_general_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_app"),
            "general_app",
            "ui.settings_section_app",
            parent=page,
        )
        language_container = QWidget(page)
        language_layout = QHBoxLayout(language_container)
        language_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        language_layout.setSpacing(10)
        language_label = self._styled_label(tr("ui.language_label"), bold=True)
        language_layout.addWidget(language_label)
        language_combo = NoScrollComboBox()
        language_combo.setMinimumWidth(120)
        language_combo.setToolTip(tr("tooltips.language"))
        language_combo = self._mark_reset(language_combo, config_key="language")
        available_languages = localization_service.get_available_languages()
        current_language = localization_service.get_current_language()
        for code, name in available_languages.items():
            language_combo.addItem(name, code)
            if code == current_language:
                language_combo.setCurrentIndex(language_combo.count() - 1)
        language_layout.addWidget(language_combo)
        cl.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignCenter)
        beta_updates_checkbox = self._styled_checkbox(
            tr("ui.beta_updates"), tr("tooltips.beta_updates"), "beta_updates_enabled"
        )
        cl.addWidget(beta_updates_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        fullscreen_checkbox = self._styled_checkbox(
            tr("ui.fullscreen"), tr("tooltips.fullscreen_tooltip"), "fullscreen_enabled"
        )
        cl.addWidget(fullscreen_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        ui_scale_container = QWidget(page)
        ui_scale_layout = QHBoxLayout(ui_scale_container)
        ui_scale_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ui_scale_layout.setSpacing(10)
        ui_scale_label = self._styled_label(tr("ui.scale_label"), bold=True)
        ui_scale_layout.addWidget(ui_scale_label)
        ui_scale_spinbox = QSpinBox()
        ui_scale_spinbox.setMinimum(50)
        ui_scale_spinbox.setMaximum(200)
        ui_scale_spinbox.setSingleStep(10)
        ui_scale_spinbox.setSuffix("%")
        ui_scale_spinbox.setValue(
            int(self.app_state.local_config.get("ui_scale", 1.0) * 100)
        )
        ui_scale_spinbox.setMinimumWidth(140)
        ui_scale_spinbox.setToolTip(tr("tooltips.ui_scale"))
        ui_scale_spinbox = self._mark_reset(ui_scale_spinbox, config_key="ui_scale")
        ui_scale_layout.addWidget(ui_scale_spinbox)
        cl.addWidget(ui_scale_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(sec)

        sec_adv, cl_adv = self._collapsible_section(
            tr("ui.settings_section_advanced"),
            "general_advanced",
            "ui.settings_section_advanced",
            parent=page,
        )
        show_reset_buttons_checkbox = self._styled_checkbox(
            tr("ui.show_reset_buttons"),
            config_key="show_reset_buttons",
            reset_value=False,
        )
        analytics_opt_in_checkbox = self._styled_checkbox(
            tr("ui.analytics_opt_in"),
            tr("tooltips.analytics_opt_in"),
            "analytics_opt_in_enabled",
            reset_value=False,
        )
        cl_adv.addWidget(
            show_reset_buttons_checkbox, alignment=Qt.AlignmentFlag.AlignCenter
        )
        cl_adv.addWidget(
            analytics_opt_in_checkbox, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec_adv)

        layout.addStretch()

        self.widgets["language_label"] = language_label
        self.widgets["language_combo"] = language_combo
        self.widgets["beta_updates_checkbox"] = beta_updates_checkbox
        self.widgets["fullscreen_checkbox"] = fullscreen_checkbox
        self.widgets["show_reset_buttons_checkbox"] = show_reset_buttons_checkbox
        self.widgets["analytics_opt_in_checkbox"] = analytics_opt_in_checkbox
        self.widgets["ui_scale_label"] = ui_scale_label
        self.widgets["ui_scale_spinbox"] = ui_scale_spinbox
        return self._wrap_in_scroll(page, parent)

    def _build_appearance_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_themes"),
            "appearance_themes",
            "ui.settings_section_themes",
            parent=page,
        )

        theme_button = self._styled_button(tr("buttons.import_export_themes"), 140)
        cl.addWidget(theme_button, alignment=Qt.AlignmentFlag.AlignCenter)

        themes_row = QHBoxLayout()
        themes_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        themes_list_widget = QComboBox()
        themes_list_widget.setMinimumWidth(150)
        theme_apply_btn = self._create_icon_btn("✔", app_state=self.app_state)
        theme_save_btn = self._create_icon_btn("🖫", app_state=self.app_state)
        theme_delete_btn = self._create_icon_btn("🗑", app_state=self.app_state)
        themes_row.addWidget(themes_list_widget)
        themes_row.addWidget(theme_apply_btn)
        themes_row.addWidget(theme_save_btn)
        themes_row.addWidget(theme_delete_btn)
        cl.addLayout(themes_row)

        do_not_save_theme_checkbox = self._styled_checkbox(
            tr("ui.do_not_save_theme_after_import")
        )
        self._mark_reset(do_not_save_theme_checkbox, reset_value=False)
        cl.addWidget(do_not_save_theme_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_media"),
            "appearance_general",
            "ui.settings_section_media",
            parent=page,
        )
        disable_animations_checkbox = self._styled_checkbox(
            tr("checkboxes.disable_animations"), config_key="disable_animations"
        )
        disable_background_checkbox = self._styled_checkbox(
            tr("checkboxes.disable_background"), config_key="background_disabled"
        )
        disable_startup_sound_checkbox = self._styled_checkbox(
            tr("checkboxes.disable_startup_sound"),
            config_key="disable_startup_sound",
        )
        pause_background_music_unfocused_checkbox = self._styled_checkbox(
            tr("checkboxes.pause_background_music_unfocused"),
            tr("tooltips.pause_background_music_unfocused"),
            config_key="pause_background_music_unfocused",
        )
        background_buttons_layout = QHBoxLayout()
        background_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        background_buttons_layout.setSpacing(10)
        change_background_button = self._styled_button(
            "", 140, reset_action="background"
        )
        background_buttons_layout.addWidget(change_background_button)
        change_logo_button = self._styled_button("", 140, reset_action="logo")
        background_buttons_layout.addWidget(change_logo_button)
        change_font_button = self._styled_button("", 140, reset_action="font")
        background_buttons_layout.addWidget(change_font_button)
        cl.addLayout(background_buttons_layout)
        layout.addWidget(sec)

        sec_audio, cl_audio = self._collapsible_section(
            tr("ui.settings_section_audio"),
            "appearance_audio",
            "ui.settings_section_audio",
            parent=page,
        )
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)
        background_music_button = self._styled_button(
            "", 180, reset_action="background_music"
        )
        sound_buttons_layout.addWidget(background_music_button)
        startup_sound_button = self._styled_button(
            "", 180, reset_action="startup_sound"
        )
        sound_buttons_layout.addWidget(startup_sound_button)
        cl_audio.addLayout(sound_buttons_layout)
        layout.addWidget(sec_audio)

        sec_styling, cl_styling = self._collapsible_section(
            tr("ui.settings_section_styling"),
            "appearance_styling",
            "ui.settings_section_styling",
            parent=page,
        )
        border_radius_container = QWidget(page)
        border_radius_layout = QHBoxLayout(border_radius_container)
        border_radius_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        border_radius_layout.setSpacing(10)
        border_radius_label = self._styled_label(
            tr("ui.border_radius_label"), bold=True
        )
        border_radius_layout.addWidget(border_radius_label)
        border_radius_spinbox = QSpinBox()
        border_radius_spinbox.setMinimum(0)
        border_radius_spinbox.setMaximum(999)
        border_radius_spinbox.setSingleStep(1)
        border_radius_spinbox.setSuffix("px")
        border_radius_spinbox.setValue(
            int(get_border_radius(self.app_state.local_config))
        )
        border_radius_spinbox.setMinimumWidth(100)
        self._mark_reset(border_radius_spinbox, config_key="custom_border_radius")
        border_radius_layout.addWidget(border_radius_spinbox)
        cl_styling.addWidget(
            border_radius_container, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec_styling)

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_colors"),
            "appearance_colors",
            "ui.settings_section_colors",
            parent=page,
        )
        custom_style_frame = QFrame(page)
        custom_style_layout = QVBoxLayout(custom_style_frame)
        custom_style_layout.setContentsMargins(0, 4, 0, 0)
        custom_style_layout.setSpacing(8)
        color_widgets, color_labels = {}, {}
        for key, lang_key in SETTINGS_COLOR_CONFIG.items():
            row_layout, line_edit, btn, reset_btn, label_widget = (
                self._create_color_row(tr(lang_key))
            )
            self._mark_reset(line_edit, config_key=get_theme_color_key(key))
            color_widgets[key], color_labels[key] = line_edit, label_widget
            self.widgets[f"color_btn_{key}"], self.widgets[f"color_reset_{key}"] = (
                btn,
                reset_btn,
            )
            custom_style_layout.addLayout(row_layout)
        cl.addWidget(custom_style_frame)
        layout.addWidget(sec)

        sec_adv, cl_adv = self._collapsible_section(
            tr("ui.settings_section_advanced"),
            "appearance_advanced",
            "ui.settings_section_advanced",
            parent=page,
        )
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkboxes_layout.setSpacing(20)
        checkboxes_layout.addWidget(disable_animations_checkbox)
        checkboxes_layout.addWidget(disable_background_checkbox)
        checkboxes_layout.addWidget(disable_startup_sound_checkbox)
        cl_adv.addLayout(checkboxes_layout)
        cl_adv.addWidget(
            pause_background_music_unfocused_checkbox,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(sec_adv)

        layout.addStretch()

        self.widgets["disable_animations_checkbox"] = disable_animations_checkbox
        self.widgets["disable_background_checkbox"] = disable_background_checkbox
        self.widgets["disable_startup_sound_checkbox"] = disable_startup_sound_checkbox
        self.widgets["pause_background_music_unfocused_checkbox"] = (
            pause_background_music_unfocused_checkbox
        )
        self.widgets["change_background_button"] = change_background_button
        self.widgets["change_logo_button"] = change_logo_button
        self.widgets["change_font_button"] = change_font_button
        self.widgets["background_music_button"] = background_music_button
        self.widgets["startup_sound_button"] = startup_sound_button
        self.widgets["custom_style_frame"] = custom_style_frame
        self.widgets["color_widgets"] = color_widgets
        self.widgets["color_labels"] = color_labels
        self.widgets["color_config"] = {
            k: tr(v) for k, v in SETTINGS_COLOR_CONFIG.items()
        }
        self.widgets["theme_button"] = theme_button
        self.widgets["themes_list_widget"] = themes_list_widget
        self.widgets["theme_apply_btn"] = theme_apply_btn
        self.widgets["theme_save_btn"] = theme_save_btn
        self.widgets["theme_delete_btn"] = theme_delete_btn
        self.widgets["do_not_save_theme_checkbox"] = do_not_save_theme_checkbox
        self.widgets["border_radius_label"] = border_radius_label
        self.widgets["border_radius_spinbox"] = border_radius_spinbox
        return self._wrap_in_scroll(page, parent)

    def _build_mods_browser_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_general"),
            "mods_general",
            "ui.settings_section_general",
            parent=page,
        )
        hide_mods_browser_tab_checkbox = self._styled_checkbox(
            tr("ui.hide_mods_browser_tab"), config_key="hide_mods_browser_tab"
        )
        cl.addWidget(
            hide_mods_browser_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(
            tr("downloads.title"), "mods_downloads", "downloads.title", parent=page
        )
        downloads_no_auto_use_cb = self._styled_checkbox(
            tr("downloads.settings_no_auto_use"), config_key="downloads_no_auto_use"
        )
        cl.addWidget(downloads_no_auto_use_cb, alignment=Qt.AlignmentFlag.AlignCenter)
        downloads_delete_after_use_cb = self._styled_checkbox(
            tr("downloads.settings_delete_after_use"),
            config_key="downloads_delete_after_use",
        )
        cl.addWidget(
            downloads_delete_after_use_cb, alignment=Qt.AlignmentFlag.AlignCenter
        )
        downloads_save_local_imports_cb = self._styled_checkbox(
            tr("downloads.settings_save_local_imports"),
            config_key="downloads_save_local_imports",
        )
        cl.addWidget(
            downloads_save_local_imports_cb, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets["hide_mods_browser_tab_checkbox"] = hide_mods_browser_tab_checkbox
        self.widgets["downloads_no_auto_use_checkbox"] = downloads_no_auto_use_cb
        self.widgets["downloads_delete_after_use_checkbox"] = (
            downloads_delete_after_use_cb
        )
        self.widgets["downloads_save_local_imports_checkbox"] = (
            downloads_save_local_imports_cb
        )
        return self._wrap_in_scroll(page, parent)

    def _build_library_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_general"),
            "library_general",
            "ui.settings_section_general",
            parent=page,
        )
        hide_library_tab_checkbox = self._styled_checkbox(
            tr("ui.hide_library_tab"), config_key="hide_library_tab"
        )
        cl.addWidget(hide_library_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_filters"),
            "library_filters",
            "ui.settings_section_filters",
            parent=page,
        )
        hide_library_filters_checkbox = self._styled_checkbox(
            tr("ui.hide_library_filters"),
            tr("tooltips.hide_library_filters"),
            "hide_library_filters",
        )
        cl.addWidget(
            hide_library_filters_checkbox, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(
            tr("game_versions.title"),
            "library_game_versions",
            "game_versions.title",
            parent=page,
        )
        game_versions_full_replace_cb = self._styled_checkbox(
            tr("game_versions.settings_full_replace"),
            tr("game_versions.settings_full_replace_tooltip"),
            "versions_full_replace_files",
        )
        cl.addWidget(
            game_versions_full_replace_cb, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets["hide_library_tab_checkbox"] = hide_library_tab_checkbox
        self.widgets["hide_library_filters_checkbox"] = hide_library_filters_checkbox
        self.widgets["game_versions_full_replace_checkbox"] = (
            game_versions_full_replace_cb
        )
        return self._wrap_in_scroll(page, parent)

    def _build_game_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_paths"),
            "launch_paths",
            "ui.settings_section_paths",
            parent=page,
        )
        game_selector_container = QWidget(page)
        gs_layout = QHBoxLayout(game_selector_container)
        gs_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gs_layout.setSpacing(10)
        game_selector_label = self._styled_label(tr("ui.mod_type_label"), bold=True)
        gs_layout.addWidget(game_selector_label)
        settings_game_combo = QComboBox()
        self._mark_reset(settings_game_combo, config_key="selected_game_type")
        for entry in get_visible_game_entries():
            settings_game_combo.addItem(entry.display_name, entry.id)
        settings_game_combo.setMinimumWidth(150)
        gs_layout.addWidget(settings_game_combo)
        games_manager_button = QPushButton()
        games_manager_button.setObjectName("games_manager_button")
        games_manager_button._themed_icon_name = "settings"
        games_manager_button._themed_icon_app_state = self.app_state
        games_manager_button._scaled_icon_button = True
        games_manager_button._themed_icon_size = QSize(
            self._scaled_icon_size(), self._scaled_icon_size()
        )
        games_manager_button.setIconSize(games_manager_button._themed_icon_size)
        games_manager_button.setFixedSize(
            self._scaled_icon_button_size(), self._scaled_icon_button_size()
        )
        games_manager_button.setToolTip(tr("games.manager_title"))
        games_manager_button.setContentsMargins(0, 0, 0, 0)
        games_manager_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        gs_layout.addWidget(games_manager_button)
        cl.addWidget(game_selector_container, alignment=Qt.AlignmentFlag.AlignCenter)
        game_path_row, game_path_label, game_path_edit, game_path_browse_button, game_path_reset_button = (
            self._create_path_input_row(
                object_prefix="settings_game_path",
                label_text=tr("ui.settings_game_path_label"),
                browse_tooltip=tr("tooltips.select_game"),
                reset_action="game_paths",
            )
        )
        cl.addWidget(game_path_row, alignment=Qt.AlignmentFlag.AlignCenter)

        (
            custom_executable_row,
            custom_executable_label,
            custom_executable_edit,
            custom_executable_button,
            reset_custom_exe_button,
        ) = self._create_path_input_row(
            object_prefix="settings_custom_executable",
            label_text=tr("ui.settings_custom_executable_path_label"),
            browse_tooltip=tr("tooltips.custom_executable_library"),
            reset_action="custom_executables",
        )
        cl.addWidget(custom_executable_row, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_launch"),
            "launch_launch",
            "ui.settings_section_launch",
            parent=page,
        )
        launch_via_steam_checkbox = self._styled_checkbox(
            tr("ui.steam_launch"),
            "<html><body style='white-space: normal;'>"
            + tr("tooltips.steam")
            + "</body></html>",
            "launch_via_steam",
        )
        cl.addWidget(launch_via_steam_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        dont_hide_window_checkbox = self._styled_checkbox(
            tr("ui.dont_hide_window_on_launch"),
            "<html><body style='white-space: normal;'>"
            + tr("tooltips.dont_hide_window_on_launch")
            + "</body></html>",
            "dont_hide_window_on_launch",
        )
        cl.addWidget(dont_hide_window_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        is_linux = platform.system() == "Linux"
        use_portproton_checkbox = self._styled_checkbox(
            tr("ui.use_portproton"),
            "<html><body style='white-space: normal;'>"
            + tr("tooltips.portproton")
            + "</body></html>",
            "use_portproton",
        )
        if not is_linux:
            use_portproton_checkbox.setVisible(False)
        cl.addWidget(use_portproton_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        (
            portproton_row,
            portproton_label,
            portproton_path_edit,
            select_portproton_path_button,
            portproton_reset_button,
        ) = self._create_path_input_row(
            object_prefix="settings_portproton_path",
            label_text=tr("ui.settings_portproton_path_label"),
            browse_tooltip=tr("buttons.select_portproton_path"),
            reset_action="portproton_path",
        )
        if not is_linux:
            portproton_row.setVisible(False)
        portproton_frame = QFrame(page)
        portproton_layout = QVBoxLayout(portproton_frame)
        portproton_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        portproton_layout.addWidget(portproton_row, alignment=Qt.AlignmentFlag.AlignCenter)
        portproton_frame.setVisible(False)
        cl.addWidget(portproton_frame, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(
            tr("ui.settings_section_patching"),
            "launch_patching",
            "ui.settings_section_patching",
            parent=page,
        )
        manage_warnings_button = self._styled_button(
            tr("buttons.manage_warnings"),
            210,
            tr("tooltips.manage_warnings"),
        )
        cont = QWidget(page)
        mo_layout = QHBoxLayout(cont)
        mo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mo_layout.setSpacing(20)
        for key in ("merge_properties", "merge_code"):
            cb = self._styled_checkbox(
                tr(f"checkboxes.{key}"), tr(f"tooltips.{key}"), key
            )
            mo_layout.addWidget(cb)
            self.widgets[f"{key}_checkbox"] = cb
        cl.addWidget(cont, alignment=Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(
            manage_warnings_button, alignment=Qt.AlignmentFlag.AlignCenter
        )
        clear_g3mtool_cache_button = self._styled_button(
            tr("buttons.clear_g3mtool_cache"),
            180,
            tr("tooltips.clear_g3mtool_cache"),
        )
        cl.addWidget(
            clear_g3mtool_cache_button, alignment=Qt.AlignmentFlag.AlignCenter
        )
        layout.addWidget(sec)

        sec_adv, cl_adv = self._collapsible_section(
            tr("ui.settings_section_advanced"),
            "launch_advanced",
            "ui.settings_section_advanced",
            parent=page,
        )

        (
            g3mtool_row,
            g3mtool_label,
            g3mtool_path_edit,
            custom_g3mtool_button,
            reset_g3mtool_button,
        ) = self._create_path_input_row(
            object_prefix="settings_custom_g3mtool",
            label_text=tr("ui.settings_custom_g3mtool_path_label"),
            browse_tooltip=tr("tooltips.custom_g3mtool_binary"),
            reset_config_key="custom_g3mtool_path",
        )
        cl_adv.addWidget(g3mtool_row, alignment=Qt.AlignmentFlag.AlignCenter)

        (
            xdelta_row,
            xdelta_label,
            xdelta_path_edit,
            custom_xdelta_button,
            reset_xdelta_button,
        ) = self._create_path_input_row(
            object_prefix="settings_custom_xdelta",
            label_text=tr("ui.settings_custom_xdelta_path_label"),
            browse_tooltip=tr("tooltips.custom_xdelta_binary"),
            reset_config_key="custom_xdelta_path",
        )
        cl_adv.addWidget(xdelta_row, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec_adv)

        layout.addStretch()

        self.widgets["settings_game_combo"] = settings_game_combo
        self.widgets["games_manager_button"] = games_manager_button
        self.widgets["settings_game_selector_label"] = game_selector_label
        self.widgets["settings_game_path_label"] = game_path_label
        self.widgets["settings_game_path_edit"] = game_path_edit
        self.widgets["settings_game_path_browse_button"] = game_path_browse_button
        self.widgets["settings_game_path_reset_button"] = game_path_reset_button
        self.widgets["dont_hide_window_checkbox"] = dont_hide_window_checkbox
        self.widgets["manage_warnings_button"] = manage_warnings_button
        self.widgets["clear_g3mtool_cache_button"] = clear_g3mtool_cache_button
        self.widgets["launch_via_steam_checkbox"] = launch_via_steam_checkbox
        self.widgets["use_portproton_checkbox"] = use_portproton_checkbox
        self.widgets["select_portproton_path_button"] = select_portproton_path_button
        self.widgets["settings_portproton_path_label"] = portproton_label
        self.widgets["portproton_path_edit"] = portproton_path_edit
        self.widgets["settings_portproton_path_reset_button"] = portproton_reset_button
        self.widgets["portproton_frame"] = portproton_frame
        self.widgets["settings_custom_executable_label"] = custom_executable_label
        self.widgets["settings_custom_executable_edit"] = custom_executable_edit
        self.widgets["settings_custom_executable_button"] = custom_executable_button
        self.widgets["settings_reset_custom_exe_button"] = reset_custom_exe_button
        self.widgets["settings_custom_g3mtool_label"] = g3mtool_label
        self.widgets["settings_custom_g3mtool_edit"] = g3mtool_path_edit
        self.widgets["settings_custom_g3mtool_button"] = custom_g3mtool_button
        self.widgets["settings_reset_g3mtool_button"] = reset_g3mtool_button
        self.widgets["settings_custom_xdelta_label"] = xdelta_label
        self.widgets["settings_custom_xdelta_edit"] = xdelta_path_edit
        self.widgets["settings_custom_xdelta_button"] = custom_xdelta_button
        self.widgets["settings_reset_xdelta_button"] = reset_xdelta_button
        return self._wrap_in_scroll(page, parent)

    def _build_plugins_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        filters = QWidget(page)
        filters_layout = QHBoxLayout(filters)
        filters_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filters_layout.setSpacing(12)
        installed_only_checkbox = self._styled_checkbox(
            tr("plugins.filters_installed_only")
        )
        plugins_tag_interface = self._styled_checkbox(tr("plugins.tag_interface"))
        plugins_tag_game_experience = self._styled_checkbox(
            tr("plugins.tag_game_experience")
        )
        plugins_tag_tool = self._styled_checkbox(tr("plugins.tag_tool"))
        plugins_tag_other = self._styled_checkbox(tr("plugins.tag_other"))
        for checkbox in (
            installed_only_checkbox,
            plugins_tag_interface,
            plugins_tag_game_experience,
            plugins_tag_tool,
            plugins_tag_other,
        ):
            filters_layout.addWidget(checkbox)
        layout.addWidget(filters)

        plugins_container = QFrame(page)
        plugins_container.setObjectName("plugins_settings_container")
        plugins_container.setMinimumHeight(600)
        plugins_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        plugins_container_layout = QVBoxLayout(plugins_container)
        plugins_container_layout.setContentsMargins(12, 12, 12, 12)
        plugins_scroll = QScrollArea(plugins_container)
        plugins_scroll.setWidgetResizable(True)
        plugins_scroll.setFrameShape(QFrame.Shape.NoFrame)
        plugins_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plugins_widget = _FilesDropWidget(plugins_scroll)
        plugins_layout = QVBoxLayout(plugins_widget)
        plugins_layout.setContentsMargins(8, 8, 8, 8)
        plugins_layout.setSpacing(12)
        plugins_layout.addStretch()
        plugins_scroll.setWidget(plugins_widget)
        plugins_scroll.viewport().setAcceptDrops(True)
        plugins_container_layout.addWidget(plugins_scroll)
        layout.addWidget(plugins_container)
        layout.addStretch()

        self.widgets["plugins_installed_only_checkbox"] = installed_only_checkbox
        self.widgets["plugins_tag_interface_checkbox"] = plugins_tag_interface
        self.widgets["plugins_tag_game_experience_checkbox"] = (
            plugins_tag_game_experience
        )
        self.widgets["plugins_tag_tool_checkbox"] = plugins_tag_tool
        self.widgets["plugins_tag_other_checkbox"] = plugins_tag_other
        self.widgets["plugins_scroll"] = plugins_scroll
        self.widgets["plugins_widget"] = plugins_widget
        self.widgets["plugins_layout"] = plugins_layout
        self.widgets["plugins_container"] = plugins_container
        return self._wrap_in_scroll(page, parent)

    def get_widgets(self) -> dict[str, Any]:
        return self.widgets
