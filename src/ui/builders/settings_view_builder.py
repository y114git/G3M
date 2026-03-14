from typing import Dict, Any
import platform
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QCheckBox, QLineEdit, QSizePolicy, QTabWidget,
    QScrollArea, QSpinBox, QComboBox,
)
from PyQt6.QtGui import QIcon  # noqa: F401
from services.localization_service import localization_service, tr
from config.constants import SETTINGS_COLOR_CONFIG
from ui.widgets.shared.custom_controls import NoScrollComboBox
from ui.utils.ui_utils import UIAnimator
from ui.common.styling import get_border_radius, get_theme_color, install_widget_update_handler
from utils.path_utils import colored_icon


class SettingsViewBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}
        self._dynamic_style_signal_connected = False

    def build(self) -> QFrame:
        settings_widget = QFrame(self.parent)
        settings_widget.setObjectName('settings_widget')
        settings_layout = QVBoxLayout(settings_widget)

        tab_widget = QTabWidget()
        tab_widget.setObjectName('settings_tab_widget')
        tab_widget.setStyleSheet("""
            QTabWidget::tab-bar { alignment: center; }
            QTabBar::tab { min-width: 110px; padding: 6px 14px; }
        """)
        tab_widget.addTab(self._build_general_tab(tab_widget), tr('ui.settings_tab_general'))
        tab_widget.addTab(self._build_appearance_tab(tab_widget), tr('ui.settings_tab_appearance'))
        tab_widget.addTab(self._build_game_tab(tab_widget), tr('ui.settings_tab_game'))
        tab_widget.addTab(self._build_mods_browser_tab(tab_widget), tr('ui.settings_tab_mods_browser'))
        tab_widget.addTab(self._build_library_tab(tab_widget), tr('ui.settings_tab_library'))
        tab_widget.addTab(self._build_plugins_tab(tab_widget), tr('ui.settings_tab_plugins'))
        settings_layout.addWidget(tab_widget, stretch=1)

        settings_layout.addStretch()

        settings_widget.setVisible(False)

        self._connect_dynamic_style_refresh()

        self.widgets['settings_widget'] = settings_widget
        self.widgets['settings_tab_widget'] = tab_widget
        return settings_widget

    def refresh_dynamic_styles(self) -> None:
        tc = get_theme_color(self.app_state.local_config, 'text', '#ffffff')
        seen = set()
        for btn in self.widgets.values():
            icon_name = getattr(btn, '_themed_icon_name', None) if btn else None
            if btn and icon_name and id(btn) not in seen:
                seen.add(id(btn))
                btn.setIcon(colored_icon(icon_name, tc))
                btn.setIconSize(QSize(20, 20))
        for btn, *_ in self.widgets.get('_section_reset_buttons', []):
            icon_name = getattr(btn, '_themed_icon_name', None) if btn else None
            if btn and icon_name and id(btn) not in seen:
                seen.add(id(btn))
                btn.setIcon(colored_icon(icon_name, tc))
                btn.setIconSize(QSize(20, 20))

    def _connect_dynamic_style_refresh(self) -> None:
        if self._dynamic_style_signal_connected:
            return
        settings_service = getattr(self.parent, 'settings_service', None)
        if settings_service is None:
            return
        settings_service.theme_changed.connect(self.refresh_dynamic_styles)
        self._dynamic_style_signal_connected = True

    def _wrap_in_scroll(self, content_widget: QWidget, parent: QWidget = None) -> QScrollArea:
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
    def _mark_reset(widget: QWidget, *, config_key: str = '', reset_action: str = '', reset_value=None):
        if config_key:
            widget.setProperty('reset_config_key', config_key)
        if reset_action:
            widget.setProperty('reset_action', reset_action)
        if reset_value is not None:
            widget.setProperty('reset_value', reset_value)
        return widget

    def _collapsible_section(self, title: str, section_key: str, lang_key: str = '', parent: QWidget = None) -> tuple:
        """Create a collapsible section. Returns (section_widget, content_layout)."""
        collapsed_map = self.app_state.local_config.get('settings_collapsed_sections', {})
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
        line_style = f'color: {line_color};'

        line_left = QFrame()
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_left.setFrameShadow(QFrame.Shadow.Sunken)
        line_left.setStyleSheet(line_style)
        header_layout.addWidget(line_left, 1)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet('font-weight: bold; background: transparent;')
        header_layout.addWidget(title_lbl)

        reset_btn = self._create_icon_btn('⭯', app_state=self.app_state)
        reset_btn.setToolTip(tr('buttons.reset_settings'))
        if not self.app_state.local_config.get('show_reset_buttons', False):
            reset_btn.setVisible(False)
        header_layout.addWidget(reset_btn)

        arrow = QLabel('\u25B6' if is_collapsed else '\u25BC')
        arrow.setStyleSheet('font-size: 10px; background: transparent;')
        header_layout.addWidget(arrow)

        line_right = QFrame()
        line_right.setFrameShape(QFrame.Shape.HLine)
        line_right.setFrameShadow(QFrame.Shadow.Sunken)
        line_right.setStyleSheet(line_style)
        header_layout.addWidget(line_right, 1)

        if '_section_lines' not in self.widgets:
            self.widgets['_section_lines'] = []
        self.widgets['_section_lines'].append(line_left)
        self.widgets['_section_lines'].append(line_right)

        content = QWidget(section)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 10, 30, 10)
        content_layout.setSpacing(12)
        if is_collapsed:
            content.setVisible(False)

        def toggle_section(event=None):
            vis = not content.isVisible()
            arrow.setText('\u25BC' if vis else '\u25B6')
            UIAnimator.collapse_expand(content, vis, 200, self.app_state)
            cm = self.app_state.local_config.get('settings_collapsed_sections', {})
            cm[section_key] = not vis
            self.app_state.local_config['settings_collapsed_sections'] = cm

        header.mousePressEvent = toggle_section

        section_layout.addWidget(header)
        section_layout.addWidget(content)

        if lang_key:
            if '_section_headers' not in self.widgets:
                self.widgets['_section_headers'] = []
            self.widgets['_section_headers'].append((title_lbl, lang_key))

        if '_collapsible_toggles' not in self.widgets:
            self.widgets['_collapsible_toggles'] = []
        self.widgets['_collapsible_toggles'].append(toggle_section)

        if '_section_reset_buttons' not in self.widgets:
            self.widgets['_section_reset_buttons'] = []
        self.widgets['_section_reset_buttons'].append((reset_btn, section_key, lang_key, content))

        return section, content_layout

    def _styled_checkbox(self, text: str, tooltip: str = '', config_key: str = '', reset_value=None) -> QCheckBox:
        cb = QCheckBox(text)
        if tooltip:
            cb.setToolTip(tooltip)
        return self._mark_reset(cb, config_key=config_key, reset_value=reset_value)

    def _styled_label(self, text: str, bold: bool = False) -> QLabel:
        lbl = QLabel(text)
        if bold:
            lbl.setStyleSheet('font-weight: bold;')
        return lbl

    def _styled_button(self, text: str, width: int = 80, tooltip: str = '', reset_action: str = '') -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumWidth(width)
        btn.setMinimumHeight(32)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        if tooltip:
            btn.setToolTip(tooltip)
        return self._mark_reset(btn, reset_action=reset_action)

    _EMOJI_TO_ICON = {'⭯': 'reset', '✔': 'checkmark', '🖫': 'save', '🗑': 'delete'}

    def _create_icon_btn(self, icon_text: str, obj_name: str = 'actionIconBtn', app_state=None) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName(obj_name)
        btn.setFixedSize(35, 35)
        icon_name = self._EMOJI_TO_ICON.get(icon_text)
        if icon_name and app_state:
            btn._themed_icon_name = icon_name
            def _apply_icon(b=btn, i=icon_name, s=app_state):
                b.setIcon(colored_icon(i, get_theme_color(s.local_config, 'text', '#ffffff')))
                b.setIconSize(QSize(20, 20))
            install_widget_update_handler(btn, _apply_icon, attr_name='_themed_icon_update_filter')
        else:
            btn.setText(icon_text)
        return btn

    def _create_color_row(self, label_text: str, parent: QWidget = None):
        row = QHBoxLayout()
        row.setSpacing(15)
        label = QLabel(label_text, parent)
        label.setStyleSheet("padding-left: 5px;")
        disp = QLineEdit(parent)
        disp.setObjectName('color_display')
        disp.setMinimumWidth(180)
        disp.setMaximumWidth(230)
        disp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton(tr('ui.select_color'), parent)
        btn.setMinimumWidth(80)
        btn.setMinimumHeight(30)
        reset = self._create_icon_btn('⭯', app_state=self.app_state)
        row.addWidget(label)
        row.addStretch()
        row.addWidget(disp)
        row.addWidget(btn)
        row.addWidget(reset)
        return row, disp, btn, reset, label

    def _build_general_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_app'), 'general_app', 'ui.settings_section_app', parent=page)
        language_container = QWidget(page)
        language_layout = QHBoxLayout(language_container)
        language_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        language_layout.setSpacing(10)
        language_label = self._styled_label(tr('ui.language_label'), bold=True)
        language_layout.addWidget(language_label)
        language_combo = NoScrollComboBox()
        language_combo.setMinimumWidth(120)
        language_combo = self._mark_reset(language_combo, config_key='language')
        available_languages = localization_service.get_available_languages()
        current_language = localization_service.get_current_language()
        for code, name in available_languages.items():
            language_combo.addItem(name, code)
            if code == current_language:
                language_combo.setCurrentIndex(language_combo.count() - 1)
        language_layout.addWidget(language_combo)
        cl.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignCenter)
        beta_updates_checkbox = self._styled_checkbox(tr('ui.beta_updates'), tr('tooltips.beta_updates'), 'beta_updates_enabled')
        cl.addWidget(beta_updates_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        fullscreen_checkbox = self._styled_checkbox(tr('ui.fullscreen'), tr('tooltips.fullscreen_tooltip'), 'fullscreen_enabled')
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
        ui_scale_spinbox.setValue(int(self.app_state.local_config.get('ui_scale', 1.0) * 100))
        ui_scale_spinbox.setMinimumWidth(140)
        ui_scale_spinbox = self._mark_reset(ui_scale_spinbox, config_key='ui_scale')
        ui_scale_layout.addWidget(ui_scale_spinbox)
        cl.addWidget(ui_scale_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(sec)

        sec_adv, cl_adv = self._collapsible_section(tr('ui.settings_section_advanced'), 'general_advanced', 'ui.settings_section_advanced', parent=page)
        show_reset_buttons_checkbox = self._styled_checkbox(tr('ui.show_reset_buttons'), config_key='show_reset_buttons', reset_value=False)
        cl_adv.addWidget(show_reset_buttons_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec_adv)

        layout.addStretch()

        self.widgets['language_label'] = language_label
        self.widgets['language_combo'] = language_combo
        self.widgets['beta_updates_checkbox'] = beta_updates_checkbox
        self.widgets['fullscreen_checkbox'] = fullscreen_checkbox
        self.widgets['show_reset_buttons_checkbox'] = show_reset_buttons_checkbox
        self.widgets['ui_scale_label'] = ui_scale_label
        self.widgets['ui_scale_spinbox'] = ui_scale_spinbox
        return self._wrap_in_scroll(page, parent)

    def _build_appearance_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_themes'), 'appearance_themes', 'ui.settings_section_themes', parent=page)

        theme_button = self._styled_button(tr('buttons.import_export_themes'), 140)
        cl.addWidget(theme_button, alignment=Qt.AlignmentFlag.AlignCenter)

        themes_row = QHBoxLayout()
        themes_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        themes_list_widget = QComboBox()
        themes_list_widget.setMinimumWidth(150)
        theme_apply_btn = self._create_icon_btn("✔", app_state=self.app_state)
        theme_save_btn = self._create_icon_btn("🖫", app_state=self.app_state)
        theme_delete_btn = self._create_icon_btn("🗑", app_state=self.app_state)
        themes_row.addWidget(themes_list_widget)
        themes_row.addWidget(theme_apply_btn), themes_row.addWidget(theme_save_btn), themes_row.addWidget(theme_delete_btn)
        cl.addLayout(themes_row)

        do_not_save_theme_checkbox = self._styled_checkbox(tr('ui.do_not_save_theme_after_import'))
        self._mark_reset(do_not_save_theme_checkbox, reset_value=False)
        cl.addWidget(do_not_save_theme_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_media'), 'appearance_general', 'ui.settings_section_media', parent=page)
        disable_animations_checkbox = self._styled_checkbox(tr('checkboxes.disable_animations'), config_key='disable_animations')
        disable_background_checkbox = self._styled_checkbox(tr('checkboxes.disable_background'), config_key='background_disabled')
        disable_splash_checkbox = self._styled_checkbox(tr('checkboxes.disable_splash'), config_key='disable_splash')
        background_buttons_layout = QHBoxLayout()
        background_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        background_buttons_layout.setSpacing(10)
        change_background_button = self._styled_button('', 140, reset_action='background')
        background_buttons_layout.addWidget(change_background_button)
        change_logo_button = self._styled_button('', 140, reset_action='logo')
        background_buttons_layout.addWidget(change_logo_button)
        change_font_button = self._styled_button('', 140, reset_action='font')
        background_buttons_layout.addWidget(change_font_button)
        cl.addLayout(background_buttons_layout)
        layout.addWidget(sec)

        sec_audio, cl_audio = self._collapsible_section(tr('ui.settings_section_audio'), 'appearance_audio', 'ui.settings_section_audio', parent=page)
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)
        background_music_button = self._styled_button('', 180, reset_action='background_music')
        sound_buttons_layout.addWidget(background_music_button)
        startup_sound_button = self._styled_button('', 180, reset_action='startup_sound')
        sound_buttons_layout.addWidget(startup_sound_button)
        cl_audio.addLayout(sound_buttons_layout)
        layout.addWidget(sec_audio)

        sec_styling, cl_styling = self._collapsible_section(tr('ui.settings_section_styling'), 'appearance_styling', 'ui.settings_section_styling', parent=page)
        border_radius_container = QWidget(page)
        border_radius_layout = QHBoxLayout(border_radius_container)
        border_radius_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        border_radius_layout.setSpacing(10)
        border_radius_label = self._styled_label(tr('ui.border_radius_label'), bold=True)
        border_radius_layout.addWidget(border_radius_label)
        border_radius_spinbox = QSpinBox()
        border_radius_spinbox.setMinimum(0)
        border_radius_spinbox.setMaximum(999)
        border_radius_spinbox.setSingleStep(1)
        border_radius_spinbox.setSuffix("px")
        border_radius_spinbox.setValue(int(get_border_radius(self.app_state.local_config)))
        border_radius_spinbox.setMinimumWidth(100)
        self._mark_reset(border_radius_spinbox, config_key='custom_border_radius')
        border_radius_layout.addWidget(border_radius_spinbox)
        cl_styling.addWidget(border_radius_container, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec_styling)

        sec, cl = self._collapsible_section(tr('ui.settings_section_colors'), 'appearance_colors', 'ui.settings_section_colors', parent=page)
        custom_style_frame = QFrame(page)
        custom_style_layout = QVBoxLayout(custom_style_frame)
        custom_style_layout.setContentsMargins(0, 4, 0, 0)
        custom_style_layout.setSpacing(8)
        color_widgets, color_labels = {}, {}
        for key, lang_key in SETTINGS_COLOR_CONFIG.items():
            row_layout, line_edit, btn, reset_btn, label_widget = self._create_color_row(tr(lang_key))
            self._mark_reset(line_edit, config_key=f'custom_color_{key}')
            color_widgets[key], color_labels[key] = line_edit, label_widget
            self.widgets[f'color_btn_{key}'], self.widgets[f'color_reset_{key}'] = btn, reset_btn
            custom_style_layout.addLayout(row_layout)
        cl.addWidget(custom_style_frame)
        layout.addWidget(sec)

        sec_adv, cl_adv = self._collapsible_section(tr('ui.settings_section_advanced'), 'appearance_advanced', 'ui.settings_section_advanced', parent=page)
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkboxes_layout.setSpacing(20)
        checkboxes_layout.addWidget(disable_animations_checkbox)
        checkboxes_layout.addWidget(disable_background_checkbox)
        checkboxes_layout.addWidget(disable_splash_checkbox)
        cl_adv.addLayout(checkboxes_layout)
        layout.addWidget(sec_adv)

        layout.addStretch()

        self.widgets['disable_animations_checkbox'] = disable_animations_checkbox
        self.widgets['disable_background_checkbox'] = disable_background_checkbox
        self.widgets['disable_splash_checkbox'] = disable_splash_checkbox
        self.widgets['change_background_button'] = change_background_button
        self.widgets['change_logo_button'] = change_logo_button
        self.widgets['change_font_button'] = change_font_button
        self.widgets['background_music_button'] = background_music_button
        self.widgets['startup_sound_button'] = startup_sound_button
        self.widgets['custom_style_frame'] = custom_style_frame
        self.widgets['color_widgets'] = color_widgets
        self.widgets['color_labels'] = color_labels
        self.widgets['color_config'] = {k: tr(v) for k, v in SETTINGS_COLOR_CONFIG.items()}
        self.widgets['theme_button'] = theme_button
        self.widgets['themes_list_widget'] = themes_list_widget
        self.widgets['theme_apply_btn'] = theme_apply_btn
        self.widgets['theme_save_btn'] = theme_save_btn
        self.widgets['theme_delete_btn'] = theme_delete_btn
        self.widgets['do_not_save_theme_checkbox'] = do_not_save_theme_checkbox
        self.widgets['border_radius_label'] = border_radius_label
        self.widgets['border_radius_spinbox'] = border_radius_spinbox
        return self._wrap_in_scroll(page, parent)

    def _build_mods_browser_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'mods_general', 'ui.settings_section_general', parent=page)
        hide_mods_browser_tab_checkbox = self._styled_checkbox(tr('ui.hide_mods_browser_tab'), config_key='hide_mods_browser_tab')
        cl.addWidget(hide_mods_browser_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_filters'), 'mods_filters', 'ui.settings_section_filters', parent=page)
        blocklist_button = self._styled_button(tr('ui.blocklist'), 100, tr('ui.blocklist_tooltip'))
        cl.addWidget(blocklist_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('downloads.title'), 'mods_downloads', 'downloads.title', parent=page)
        downloads_no_auto_use_cb = self._styled_checkbox(tr('downloads.settings_no_auto_use'), config_key='downloads_no_auto_use')
        cl.addWidget(downloads_no_auto_use_cb, alignment=Qt.AlignmentFlag.AlignCenter)
        downloads_delete_after_use_cb = self._styled_checkbox(tr('downloads.settings_delete_after_use'), config_key='downloads_delete_after_use')
        cl.addWidget(downloads_delete_after_use_cb, alignment=Qt.AlignmentFlag.AlignCenter)
        downloads_save_local_imports_cb = self._styled_checkbox(tr('downloads.settings_save_local_imports'), config_key='downloads_save_local_imports')
        cl.addWidget(downloads_save_local_imports_cb, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_mods_browser_tab_checkbox'] = hide_mods_browser_tab_checkbox
        self.widgets['blocklist_button'] = blocklist_button
        self.widgets['downloads_no_auto_use_checkbox'] = downloads_no_auto_use_cb
        self.widgets['downloads_delete_after_use_checkbox'] = downloads_delete_after_use_cb
        self.widgets['downloads_save_local_imports_checkbox'] = downloads_save_local_imports_cb
        return self._wrap_in_scroll(page, parent)

    def _build_library_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'library_general', 'ui.settings_section_general', parent=page)
        hide_library_tab_checkbox = self._styled_checkbox(tr('ui.hide_library_tab'), config_key='hide_library_tab')
        cl.addWidget(hide_library_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_filters'), 'library_filters', 'ui.settings_section_filters', parent=page)
        hide_library_filters_checkbox = self._styled_checkbox(
            tr('ui.hide_library_filters'), tr('tooltips.hide_library_filters'), 'hide_library_filters'
        )
        cl.addWidget(hide_library_filters_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_library_tab_checkbox'] = hide_library_tab_checkbox
        self.widgets['hide_library_filters_checkbox'] = hide_library_filters_checkbox
        return self._wrap_in_scroll(page, parent)

    def _build_plugins_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'plugins_general', 'ui.settings_section_general', parent=page)
        hide_plugins_tab_checkbox = self._styled_checkbox(tr('ui.hide_plugins_tab'), config_key='hide_plugins_tab')
        cl.addWidget(hide_plugins_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_plugins_tab_checkbox'] = hide_plugins_tab_checkbox
        return self._wrap_in_scroll(page, parent)

    def _build_game_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_paths'), 'launch_paths', 'ui.settings_section_paths', parent=page)
        game_selector_container = QWidget(page)
        gs_layout = QHBoxLayout(game_selector_container)
        gs_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gs_layout.setSpacing(10)
        game_selector_label = self._styled_label(tr('ui.mod_type_label'), bold=True)
        gs_layout.addWidget(game_selector_label)
        settings_game_combo = QComboBox()
        self._mark_reset(settings_game_combo, config_key='selected_game_type')
        for label, data in [
            ('DELTARUNE', 'deltarune'), ('DELTARUNE DEMO', 'deltarunedemo'),
            ('UNDERTALE', 'undertale'), ('UNDERTALE Yellow', 'undertaleyellow'),
            ('Pizza Tower', 'pizzatower'), ('Sugary Spire', 'sugaryspire'),
        ]:
            settings_game_combo.addItem(label, data)
        settings_game_combo.setMinimumWidth(150)
        gs_layout.addWidget(settings_game_combo)
        cl.addWidget(game_selector_container, alignment=Qt.AlignmentFlag.AlignCenter)
        path_exe_row = QWidget(page)
        path_exe_layout = QHBoxLayout(path_exe_row)
        path_exe_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path_exe_layout.setSpacing(10)
        change_path_button = self._styled_button('', 140, reset_action='game_paths')
        change_path_button.setObjectName('settings_change_path_button')
        path_exe_layout.addWidget(change_path_button)
        custom_executable_button = self._styled_button(
            tr('buttons.custom_executable'), 120, tr('tooltips.custom_executable_library')
        )
        custom_executable_button.setObjectName('settings_custom_executable_button')
        path_exe_layout.addWidget(custom_executable_button)
        reset_custom_exe_button = self._create_icon_btn('⭯', app_state=self.app_state)
        reset_custom_exe_button.setToolTip(tr('buttons.reset_settings'))
        reset_custom_exe_button.setVisible(False)
        self._mark_reset(reset_custom_exe_button, reset_action='custom_executables')
        path_exe_layout.addWidget(reset_custom_exe_button)
        cl.addWidget(path_exe_row, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_launch'), 'launch_launch', 'ui.settings_section_launch', parent=page)
        launch_via_steam_checkbox = self._styled_checkbox(
            tr('ui.steam_launch'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>', 'launch_via_steam'
        )
        cl.addWidget(launch_via_steam_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        dont_hide_window_checkbox = self._styled_checkbox(
            tr('ui.dont_hide_window_on_launch'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.dont_hide_window_on_launch') + '</body></html>', 'dont_hide_window_on_launch'
        )
        cl.addWidget(dont_hide_window_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        is_linux = platform.system() == 'Linux'
        use_portproton_checkbox = self._styled_checkbox(
            tr('ui.use_portproton'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>', 'use_portproton'
        )
        if not is_linux:
            use_portproton_checkbox.setVisible(False)
        cl.addWidget(use_portproton_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        select_portproton_path_button = self._styled_button(tr('buttons.select_portproton_path'), 200, reset_action='portproton_path')
        if not is_linux:
            select_portproton_path_button.setVisible(False)
        portproton_path_label = QLabel(tr('ui.file_not_selected'))
        portproton_path_label.setMinimumHeight(20)
        portproton_frame = QFrame(page)
        portproton_layout = QVBoxLayout(portproton_frame)
        portproton_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        portproton_layout.addWidget(select_portproton_path_button, alignment=Qt.AlignmentFlag.AlignCenter)
        portproton_layout.addWidget(portproton_path_label, alignment=Qt.AlignmentFlag.AlignCenter)
        portproton_frame.setVisible(False)
        cl.addWidget(portproton_frame, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_patching'), 'launch_patching', 'ui.settings_section_patching', parent=page)
        skip_patching_warnings_checkbox = self._styled_checkbox(
            tr('ui.skip_patching_warnings'), tr('tooltips.skip_patching_warnings'), 'skip_patching_warnings'
        )
        cl.addWidget(skip_patching_warnings_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_merging'), 'launch_merging', 'ui.settings_section_merging', parent=page)
        cont = QWidget(page)
        mo_layout = QHBoxLayout(cont)
        mo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mo_layout.setSpacing(20)
        for key in ('merge_properties', 'merge_code'):
            cb = self._styled_checkbox(tr(f'checkboxes.{key}'), tr(f'tooltips.{key}'), key)
            mo_layout.addWidget(cb)
            self.widgets[f'{key}_checkbox'] = cb
        cl.addWidget(cont, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['settings_game_combo'] = settings_game_combo
        self.widgets['settings_game_selector_label'] = game_selector_label
        self.widgets['settings_change_path_button'] = change_path_button
        self.widgets['dont_hide_window_checkbox'] = dont_hide_window_checkbox
        self.widgets['skip_patching_warnings_checkbox'] = skip_patching_warnings_checkbox
        self.widgets['launch_via_steam_checkbox'] = launch_via_steam_checkbox
        self.widgets['use_portproton_checkbox'] = use_portproton_checkbox
        self.widgets['select_portproton_path_button'] = select_portproton_path_button
        self.widgets['portproton_path_label'] = portproton_path_label
        self.widgets['portproton_frame'] = portproton_frame
        self.widgets['settings_custom_executable_button'] = custom_executable_button
        self.widgets['settings_reset_custom_exe_button'] = reset_custom_exe_button
        return self._wrap_in_scroll(page, parent)

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
