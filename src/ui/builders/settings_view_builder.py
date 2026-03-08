from typing import Dict, Any
import platform
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QCheckBox, QLineEdit, QSizePolicy, QTabWidget,
    QScrollArea, QSpinBox, QComboBox,
)
from services.localization_service import localization_service, tr
from config.constants import SETTINGS_COLOR_CONFIG
from ui.widgets.shared.custom_controls import NoScrollComboBox
from ui.utils.ui_utils import UIAnimator
from ui.common.styling import get_border_radius


class SettingsViewBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QFrame:
        settings_widget = QFrame()
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
        tab_widget.addTab(self._build_mods_browser_tab(tab_widget), tr('ui.settings_tab_mods_browser'))
        tab_widget.addTab(self._build_library_tab(tab_widget), tr('ui.settings_tab_library'))
        tab_widget.addTab(self._build_launch_tab(tab_widget), tr('ui.settings_tab_launch'))
        tab_widget.addTab(self._build_plugins_tab(tab_widget), tr('ui.settings_tab_plugins'))
        settings_layout.addWidget(tab_widget, stretch=1)

        settings_widget.setVisible(False)

        self.widgets['settings_widget'] = settings_widget
        self.widgets['settings_tab_widget'] = tab_widget
        return settings_widget

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
        content.setVisible(not is_collapsed)

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

        return section, content_layout

    def _styled_checkbox(self, text: str, tooltip: str = '') -> QCheckBox:
        cb = QCheckBox(text)
        if tooltip:
            cb.setToolTip(tooltip)
        return cb

    def _styled_label(self, text: str, bold: bool = False) -> QLabel:
        lbl = QLabel(text)
        if bold:
            lbl.setStyleSheet('font-weight: bold;')
        return lbl

    def _styled_button(self, text: str, width: int = 80, tooltip: str = '') -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumWidth(width)
        btn.setMinimumHeight(32)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        if tooltip:
            btn.setToolTip(tooltip)
        return btn

    def _create_icon_btn(self, icon: str, obj_name: str = 'actionIconBtn') -> QPushButton:
        btn = QPushButton(icon)
        btn.setObjectName(obj_name)
        btn.setFixedSize(35, 35)
        return btn

    def _create_color_row(self, label_text: str, parent: QWidget = None):
        row = QHBoxLayout()
        row.setSpacing(15)
        label = QLabel(label_text, parent)
        label.setStyleSheet("padding-left: 5px;")
        disp = QLineEdit(parent)
        disp.setReadOnly(True)
        disp.setObjectName('color_display')
        disp.setMinimumWidth(180)
        disp.setMaximumWidth(230)
        disp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton(tr('ui.select_color'), parent)
        btn.setMinimumWidth(80)
        btn.setMinimumHeight(30)
        reset = self._create_icon_btn('⭯')
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
        available_languages = localization_service.get_available_languages()
        current_language = localization_service.get_current_language()
        for code, name in available_languages.items():
            language_combo.addItem(name, code)
            if code == current_language:
                language_combo.setCurrentIndex(language_combo.count() - 1)
        language_layout.addWidget(language_combo)
        cl.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignCenter)
        beta_updates_checkbox = self._styled_checkbox(tr('ui.beta_updates'), tr('tooltips.beta_updates'))
        cl.addWidget(beta_updates_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        fullscreen_checkbox = self._styled_checkbox(tr('ui.fullscreen'), tr('tooltips.fullscreen_tooltip'))
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
        ui_scale_layout.addWidget(ui_scale_spinbox)
        cl.addWidget(ui_scale_container, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_advanced'), 'general_advanced', 'ui.settings_section_advanced', parent=page)
        reset_button = self._styled_button(tr('buttons.reset_settings'), 80)
        cl.addWidget(reset_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['language_label'] = language_label
        self.widgets['language_combo'] = language_combo
        self.widgets['beta_updates_checkbox'] = beta_updates_checkbox
        self.widgets['fullscreen_checkbox'] = fullscreen_checkbox
        self.widgets['ui_scale_label'] = ui_scale_label
        self.widgets['ui_scale_spinbox'] = ui_scale_spinbox
        self.widgets['reset_button'] = reset_button
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
        theme_apply_btn, theme_save_btn, theme_delete_btn = self._create_icon_btn("✔"), self._create_icon_btn("🖫"), self._create_icon_btn("🗑")
        themes_row.addWidget(themes_list_widget)
        themes_row.addWidget(theme_apply_btn), themes_row.addWidget(theme_save_btn), themes_row.addWidget(theme_delete_btn)
        cl.addLayout(themes_row)

        do_not_save_theme_checkbox = self._styled_checkbox(tr('ui.do_not_save_theme_after_import'))
        cl.addWidget(do_not_save_theme_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_media'), 'appearance_general', 'ui.settings_section_media', parent=page)
        disable_animations_checkbox = self._styled_checkbox(tr('checkboxes.disable_animations'))
        disable_background_checkbox = self._styled_checkbox(tr('checkboxes.disable_background'))
        disable_splash_checkbox = self._styled_checkbox(tr('checkboxes.disable_splash'))
        background_buttons_layout = QHBoxLayout()
        background_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        background_buttons_layout.setSpacing(10)
        change_background_button = self._styled_button('', 140)
        background_buttons_layout.addWidget(change_background_button)
        change_logo_button = self._styled_button('', 140)
        background_buttons_layout.addWidget(change_logo_button)
        change_font_button = self._styled_button('', 140)
        background_buttons_layout.addWidget(change_font_button)
        cl.addLayout(background_buttons_layout)
        layout.addWidget(sec)

        sec_audio, cl_audio = self._collapsible_section(tr('ui.settings_section_audio'), 'appearance_audio', 'ui.settings_section_audio', parent=page)
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)
        background_music_button = self._styled_button('', 180)
        sound_buttons_layout.addWidget(background_music_button)
        startup_sound_button = self._styled_button('', 180)
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

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'mods_browser_general', 'ui.settings_section_general', parent=page)
        hide_mods_browser_tab_checkbox = self._styled_checkbox(tr('ui.hide_mods_browser_tab'))
        cl.addWidget(hide_mods_browser_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_display'), 'mods_display', 'ui.settings_section_display', parent=page)
        mpp_container = QWidget(page)
        mpp_layout = QHBoxLayout(mpp_container)
        mpp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mpp_layout.setSpacing(10)
        mods_per_page_label = self._styled_label(tr('ui.mods_per_page_label'))
        mpp_layout.addWidget(mods_per_page_label)
        mods_per_page_spinbox = QSpinBox()
        mods_per_page_spinbox.setMinimum(5)
        mods_per_page_spinbox.setMaximum(1000)
        mods_per_page_spinbox.setValue(getattr(self.app_state, 'mods_per_page', 20))
        mods_per_page_spinbox.setToolTip(tr('ui.mods_per_page_tooltip'))
        mpp_layout.addWidget(mods_per_page_spinbox)
        blocklist_button = self._styled_button(tr('ui.blocklist'), 100, tr('ui.blocklist_tooltip'))
        mpp_layout.addWidget(blocklist_button)
        cl.addWidget(mpp_container, alignment=Qt.AlignmentFlag.AlignCenter)
        hide_wips_without_downloads_checkbox = self._styled_checkbox(
            tr('ui.hide_wips_without_downloads'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.hide_wips_without_downloads') + '</body></html>'
        )
        cl.addWidget(hide_wips_without_downloads_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        auto_sorting_checkbox = self._styled_checkbox(tr('ui.auto_sorting'), tr('ui.auto_sorting_tooltip'))
        auto_sorting_checkbox.setChecked(self.app_state.local_config.get('auto_sorting', False))
        cl.addWidget(auto_sorting_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section('GameBanana', 'mods_gamebanana', parent=page)
        gb_container = QWidget(page)
        gb_layout = QHBoxLayout(gb_container)
        gb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gb_layout.setSpacing(10)
        gb_sort_label = self._styled_label(tr('ui.gamebanana_sort_label'))
        gb_layout.addWidget(gb_sort_label)
        gb_sort_combo = QComboBox()
        for label, data in [('default', 'default'), ('new', 'new'), ('updated', 'updated')]:
            gb_sort_combo.addItem(tr(f'ui.gamebanana_sort_{label}'), data)
        gb_sort_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
        gb_sort_combo.setCurrentIndex(
            {'default': 0, 'new': 1, 'updated': 2}.get(
                getattr(self.app_state, 'gamebanana_sort', 'default'), 0
            )
        )
        gb_layout.addWidget(gb_sort_combo)
        cl.addWidget(gb_container, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_advanced'), 'mods_advanced', 'ui.settings_section_advanced', parent=page)
        clear_cache_button = self._styled_button(tr('ui.clear_cache_button'), 120, tr('tooltips.clear_cache_button'))
        clear_cache_button.setObjectName('clear_cache_button')
        cl.addWidget(clear_cache_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_mods_browser_tab_checkbox'] = hide_mods_browser_tab_checkbox
        self.widgets['hide_wips_without_downloads_checkbox'] = hide_wips_without_downloads_checkbox
        self.widgets['auto_sorting_checkbox'] = auto_sorting_checkbox
        self.widgets['mods_per_page_label'] = mods_per_page_label
        self.widgets['mods_per_page_spinbox'] = mods_per_page_spinbox
        self.widgets['gb_sort_label'] = gb_sort_label
        self.widgets['gb_sort_combo'] = gb_sort_combo
        self.widgets['blocklist_button'] = blocklist_button
        self.widgets['clear_cache_button'] = clear_cache_button
        return self._wrap_in_scroll(page, parent)

    def _build_library_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'library_general', 'ui.settings_section_general', parent=page)
        hide_library_tab_checkbox = self._styled_checkbox(tr('ui.hide_library_tab'))
        cl.addWidget(hide_library_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_filters'), 'library_filters', 'ui.settings_section_filters', parent=page)
        hide_library_filters_checkbox = self._styled_checkbox(
            tr('ui.hide_library_filters'), tr('tooltips.hide_library_filters')
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
        hide_plugins_tab_checkbox = self._styled_checkbox(tr('ui.hide_plugins_tab'))
        cl.addWidget(hide_plugins_tab_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_plugins_tab_checkbox'] = hide_plugins_tab_checkbox
        return self._wrap_in_scroll(page, parent)

    def _build_launch_tab(self, parent: QWidget = None) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_paths'), 'launch_paths', 'ui.settings_section_paths', parent=page)
        game_selector_container = QWidget(page)
        gs_layout = QHBoxLayout(game_selector_container)
        gs_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gs_layout.setSpacing(10)
        game_selector_label = self._styled_label(tr('ui.mod_type_label'), bold=True)
        gs_layout.addWidget(game_selector_label)
        settings_game_combo = QComboBox()
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
        change_path_button = self._styled_button('', 140)
        change_path_button.setObjectName('settings_change_path_button')
        path_exe_layout.addWidget(change_path_button)
        custom_executable_button = self._styled_button(
            tr('buttons.custom_executable'), 120, tr('tooltips.custom_executable_library')
        )
        custom_executable_button.setObjectName('settings_custom_executable_button')
        path_exe_layout.addWidget(custom_executable_button)
        reset_custom_exe_button = QPushButton('⭯')
        reset_custom_exe_button.setObjectName('actionIconBtn')
        reset_custom_exe_button.setVisible(False)
        path_exe_layout.addWidget(reset_custom_exe_button)
        cl.addWidget(path_exe_row, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_launch'), 'launch_launch', 'ui.settings_section_launch', parent=page)
        launch_via_steam_checkbox = self._styled_checkbox(
            tr('ui.steam_launch'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>'
        )
        cl.addWidget(launch_via_steam_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        dont_hide_window_checkbox = self._styled_checkbox(
            tr('ui.dont_hide_window_on_launch'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.dont_hide_window_on_launch') + '</body></html>'
        )
        cl.addWidget(dont_hide_window_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        is_linux = platform.system() == 'Linux'
        use_portproton_checkbox = self._styled_checkbox(
            tr('ui.use_portproton'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>'
        )
        use_portproton_checkbox.setVisible(is_linux)
        cl.addWidget(use_portproton_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        select_portproton_path_button = self._styled_button(tr('buttons.select_portproton_path'), 200)
        select_portproton_path_button.setVisible(is_linux)
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
            tr('ui.skip_patching_warnings'), tr('tooltips.skip_patching_warnings')
        )
        cl.addWidget(skip_patching_warnings_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_merging'), 'launch_merging', 'ui.settings_section_merging', parent=page)
        cont = QWidget(page)
        mo_layout = QHBoxLayout(cont)
        mo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mo_layout.setSpacing(20)
        for key in ('merge_properties', 'merge_code'):
            cb = self._styled_checkbox(tr(f'checkboxes.{key}'), tr(f'tooltips.{key}'))
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
