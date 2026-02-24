from typing import Dict, Any
import platform
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QCheckBox, QLineEdit, QTextBrowser, QSizePolicy, QTabWidget,
    QScrollArea, QSpinBox, QComboBox,
)
from services.localization_service import localization_service, tr
from ui.widgets.shared.custom_controls import NoScrollComboBox


class SettingsViewBuilder:
    """Builds the settings view UI for application configuration."""

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
        tab_widget.addTab(self._build_general_tab(), tr('ui.settings_tab_general'))
        tab_widget.addTab(self._build_appearance_tab(), tr('ui.settings_tab_appearance'))
        tab_widget.addTab(self._build_mods_browser_tab(), tr('ui.settings_tab_mods_browser'))
        tab_widget.addTab(self._build_library_tab(), tr('ui.settings_tab_library'))
        tab_widget.addTab(self._build_launch_tab(), tr('ui.settings_tab_launch'))
        tab_widget.addTab(self._build_plugins_tab(), tr('ui.settings_tab_plugins'))
        settings_layout.addWidget(tab_widget, stretch=1)

        changelog_widget = self._build_changelog_widget()
        changelog_widget.setVisible(False)
        settings_layout.addWidget(changelog_widget, stretch=1)

        button_bar_layout = QHBoxLayout()
        button_bar_layout.setSpacing(10)
        button_bar_layout.addStretch(1)
        button_bar_layout.addWidget(self.widgets['changelog_button'])
        button_bar_layout.addWidget(self.widgets['report_bug_button'])
        button_bar_layout.addStretch(1)
        settings_layout.addLayout(button_bar_layout)

        settings_widget.setVisible(False)

        self.widgets['settings_widget'] = settings_widget
        self.widgets['settings_tab_widget'] = tab_widget
        self.widgets['changelog_widget'] = changelog_widget
        return settings_widget

    def _wrap_in_scroll(self, content_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content_widget)
        return scroll

    def _get_section_line_color(self) -> str:
        from ui.common.styling import get_section_line_color
        return get_section_line_color(self.app_state.local_config)

    def _build_simple_tab_page(self) -> tuple:
        """Create a simple settings tab page with standard layout. Returns (page, layout)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(4)
        layout.setContentsMargins(20, 12, 20, 20)
        return page, layout

    def _collapsible_section(self, title: str, section_key: str, lang_key: str = '') -> tuple:
        """Create a collapsible section. Returns (section_widget, content_layout)."""
        collapsed_map = self.app_state.local_config.get('settings_collapsed_sections', {})
        is_collapsed = collapsed_map.get(section_key, False)

        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 8, 0, 4)
        section_layout.setSpacing(6)

        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        line_color = self._get_section_line_color()
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

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 6, 0, 2)
        content_layout.setSpacing(8)
        content.setVisible(not is_collapsed)

        def toggle_section(event=None):
            vis = not content.isVisible()
            content.setVisible(vis)
            arrow.setText('\u25BC' if vis else '\u25B6')
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

    def _styled_button(self, text: str, width: int = 250, tooltip: str = '') -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedWidth(width)
        if tooltip:
            btn.setToolTip(tooltip)
        return btn

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(4)
        layout.setContentsMargins(20, 12, 20, 20)

        sec, cl = self._collapsible_section(tr('ui.settings_section_app'), 'general_app', 'ui.settings_section_app')
        language_container = QWidget()
        language_layout = QHBoxLayout(language_container)
        language_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        language_layout.setSpacing(10)
        language_label = self._styled_label(tr('ui.language_label'), bold=True)
        language_layout.addWidget(language_label)
        language_combo = NoScrollComboBox()
        language_combo.setMinimumWidth(200)
        language_combo.setMaximumWidth(250)
        available_languages = localization_service.get_available_languages()
        current_language = localization_service.get_current_language()
        for code, name in available_languages.items():
            language_combo.addItem(name, code)
            if code == current_language:
                language_combo.setCurrentIndex(language_combo.count() - 1)
        language_layout.addWidget(language_combo)
        cl.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        beta_updates_checkbox = self._styled_checkbox(tr('ui.beta_updates'), tr('tooltips.beta_updates'))
        cl.addWidget(beta_updates_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        fullscreen_checkbox = self._styled_checkbox(tr('ui.fullscreen'), tr('tooltips.fullscreen_tooltip'))
        cl.addWidget(fullscreen_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_advanced'), 'general_advanced', 'ui.settings_section_advanced')
        open_deltahub_folder_button = self._styled_button(tr('buttons.open_deltahub_folder'), 300)
        cl.addWidget(open_deltahub_folder_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        reset_button = self._styled_button(tr('buttons.reset_settings'), 200)
        cl.addWidget(reset_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['language_label'] = language_label
        self.widgets['language_combo'] = language_combo
        self.widgets['beta_updates_checkbox'] = beta_updates_checkbox
        self.widgets['fullscreen_checkbox'] = fullscreen_checkbox
        self.widgets['open_deltahub_folder_button'] = open_deltahub_folder_button
        self.widgets['reset_button'] = reset_button
        return self._wrap_in_scroll(page)

    def _build_appearance_tab(self) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'appearance_general', 'ui.settings_section_general')
        disable_background_checkbox = self._styled_checkbox(tr('checkboxes.disable_background'))
        disable_splash_checkbox = self._styled_checkbox(tr('checkboxes.disable_splash'))
        background_buttons_layout = QHBoxLayout()
        background_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        background_buttons_layout.setSpacing(10)
        change_background_button = self._styled_button('', 275)
        change_background_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        background_buttons_layout.addWidget(change_background_button)
        change_logo_button = self._styled_button('', 275)
        change_logo_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        background_buttons_layout.addWidget(change_logo_button)
        cl.addLayout(background_buttons_layout)
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)
        background_music_button = self._styled_button('', 275)
        background_music_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sound_buttons_layout.addWidget(background_music_button)
        startup_sound_button = self._styled_button('', 275)
        startup_sound_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sound_buttons_layout.addWidget(startup_sound_button)
        cl.addLayout(sound_buttons_layout)
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkboxes_layout.setSpacing(20)
        checkboxes_layout.addWidget(disable_background_checkbox)
        checkboxes_layout.addWidget(disable_splash_checkbox)
        cl.addLayout(checkboxes_layout)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_colors'), 'appearance_colors', 'ui.settings_section_colors')
        custom_style_frame = QFrame()
        custom_style_layout = QVBoxLayout(custom_style_frame)
        custom_style_layout.setContentsMargins(0, 4, 0, 0)
        custom_style_layout.setSpacing(8)
        color_widgets = {}
        color_labels = {}
        color_config = {
            'background': tr('ui.background_color'),
            'button': tr('ui.elements_color'),
            'border': tr('ui.border_color'),
            'button_hover': tr('ui.hover_color'),
            'text': tr('ui.main_text_color'),
            'version_text': tr('ui.secondary_text_color'),
        }

        def create_setting_row(label_text: str):
            row = QHBoxLayout()
            label = QLabel(label_text)
            color_display = QLineEdit()
            color_display.setFixedWidth(95)
            color_display.setReadOnly(True)
            color_btn = QPushButton(tr('ui.select_color'))
            color_btn.setFixedWidth(150)
            reset_btn = QPushButton('⭯')
            reset_btn.setStyleSheet('min-width: 35px; max-width: 35px; padding-left: 0px; padding-right: 0px;')
            reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(label)
            row.addStretch()
            for w in [color_display, color_btn, reset_btn]:
                row.addWidget(w)
            return (row, color_display, color_btn, reset_btn, label)

        for key, label_text in color_config.items():
            row_layout, line_edit, btn, reset_btn, label_widget = create_setting_row(label_text)
            color_widgets[key] = line_edit
            color_labels[key] = label_widget
            self.widgets[f'color_btn_{key}'] = btn
            self.widgets[f'color_reset_{key}'] = reset_btn
            custom_style_layout.addLayout(row_layout)
        cl.addWidget(custom_style_frame)
        theme_button = self._styled_button(tr('buttons.theme_management'), 400)
        theme_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        cl.addWidget(theme_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['disable_background_checkbox'] = disable_background_checkbox
        self.widgets['disable_splash_checkbox'] = disable_splash_checkbox
        self.widgets['change_background_button'] = change_background_button
        self.widgets['change_logo_button'] = change_logo_button
        self.widgets['background_music_button'] = background_music_button
        self.widgets['startup_sound_button'] = startup_sound_button
        self.widgets['custom_style_frame'] = custom_style_frame
        self.widgets['color_widgets'] = color_widgets
        self.widgets['color_labels'] = color_labels
        self.widgets['color_config'] = color_config
        self.widgets['theme_button'] = theme_button
        return self._wrap_in_scroll(page)

    def _build_mods_browser_tab(self) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'mods_browser_general', 'ui.settings_section_general')
        hide_mods_browser_tab_checkbox = self._styled_checkbox(tr('ui.hide_mods_browser_tab'))
        cl.addWidget(hide_mods_browser_tab_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_display'), 'mods_display', 'ui.settings_section_display')
        mpp_container = QWidget()
        mpp_layout = QHBoxLayout(mpp_container)
        mpp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mpp_layout.setSpacing(10)
        mods_per_page_label = self._styled_label(tr('ui.mods_per_page_label'))
        mpp_layout.addWidget(mods_per_page_label)
        mods_per_page_spinbox = QSpinBox()
        mods_per_page_spinbox.setMinimum(5)
        mods_per_page_spinbox.setMaximum(1000)
        mods_per_page_spinbox.setMaximumWidth(80)
        mods_per_page_spinbox.setValue(getattr(self.app_state, 'mods_per_page', 20))
        mods_per_page_spinbox.setToolTip(tr('ui.mods_per_page_tooltip'))
        mods_per_page_spinbox.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        mpp_layout.addWidget(mods_per_page_spinbox)
        blocklist_button = self._styled_button(tr('ui.blocklist'), 200, tr('ui.blocklist_tooltip'))
        mpp_layout.addWidget(blocklist_button)
        cl.addWidget(mpp_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        hide_mods_without_files_checkbox = self._styled_checkbox(
            tr('ui.hide_mods_without_files'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.hide_mods_without_files') + '</body></html>'
        )
        cl.addWidget(hide_mods_without_files_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        auto_sorting_checkbox = self._styled_checkbox(tr('ui.auto_sorting'), tr('ui.auto_sorting_tooltip'))
        auto_sorting_checkbox.setChecked(self.app_state.local_config.get('auto_sorting', False))
        cl.addWidget(auto_sorting_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section('GameBanana', 'mods_gamebanana')
        gb_container = QWidget()
        gb_layout = QHBoxLayout(gb_container)
        gb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gb_layout.setSpacing(10)
        gb_sort_label = self._styled_label(tr('ui.gamebanana_sort_label'))
        gb_layout.addWidget(gb_sort_label)
        gb_sort_combo = QComboBox()
        for label, data in [('default', 'default'), ('new', 'new'), ('updated', 'updated')]:
            gb_sort_combo.addItem(tr(f'ui.gamebanana_sort_{label}'), data)
        gb_sort_combo.setMaximumWidth(150)
        gb_sort_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
        gb_sort_combo.setCurrentIndex(
            {'default': 0, 'new': 1, 'updated': 2}.get(
                getattr(self.app_state, 'gamebanana_sort', 'default'), 0
            )
        )
        gb_layout.addWidget(gb_sort_combo)
        cl.addWidget(gb_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_advanced'), 'mods_advanced', 'ui.settings_section_advanced')
        clear_cache_button = self._styled_button(tr('ui.clear_cache_button'), 250, tr('tooltips.clear_cache_button'))
        clear_cache_button.setObjectName('clear_cache_button')
        cl.addWidget(clear_cache_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_mods_browser_tab_checkbox'] = hide_mods_browser_tab_checkbox
        self.widgets['hide_mods_without_files_checkbox'] = hide_mods_without_files_checkbox
        self.widgets['auto_sorting_checkbox'] = auto_sorting_checkbox
        self.widgets['mods_per_page_label'] = mods_per_page_label
        self.widgets['mods_per_page_spinbox'] = mods_per_page_spinbox
        self.widgets['gb_sort_label'] = gb_sort_label
        self.widgets['gb_sort_combo'] = gb_sort_combo
        self.widgets['blocklist_button'] = blocklist_button
        self.widgets['clear_cache_button'] = clear_cache_button
        return self._wrap_in_scroll(page)

    def _build_library_tab(self) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'library_general', 'ui.settings_section_general')
        hide_library_tab_checkbox = self._styled_checkbox(tr('ui.hide_library_tab'))
        cl.addWidget(hide_library_tab_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_filters'), 'library_filters', 'ui.settings_section_filters')
        hide_library_filters_checkbox = self._styled_checkbox(
            tr('ui.hide_library_filters'), tr('tooltips.hide_library_filters')
        )
        cl.addWidget(hide_library_filters_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_library_tab_checkbox'] = hide_library_tab_checkbox
        self.widgets['hide_library_filters_checkbox'] = hide_library_filters_checkbox
        return self._wrap_in_scroll(page)

    def _build_plugins_tab(self) -> QWidget:
        page, layout = self._build_simple_tab_page()

        sec, cl = self._collapsible_section(tr('ui.settings_section_general'), 'plugins_general', 'ui.settings_section_general')
        hide_plugins_tab_checkbox = self._styled_checkbox(tr('ui.hide_plugins_tab'))
        cl.addWidget(hide_plugins_tab_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['hide_plugins_tab_checkbox'] = hide_plugins_tab_checkbox
        return self._wrap_in_scroll(page)

    def _build_launch_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(4)
        layout.setContentsMargins(20, 12, 20, 20)

        sec, cl = self._collapsible_section(tr('ui.settings_section_paths'), 'launch_paths', 'ui.settings_section_paths')
        game_selector_container = QWidget()
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
        settings_game_combo.setMinimumWidth(200)
        gs_layout.addWidget(settings_game_combo)
        cl.addWidget(game_selector_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        path_exe_row = QWidget()
        path_exe_layout = QHBoxLayout(path_exe_row)
        path_exe_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path_exe_layout.setSpacing(10)
        change_path_button = self._styled_button('', 300)
        change_path_button.setObjectName('settings_change_path_button')
        path_exe_layout.addWidget(change_path_button)
        custom_executable_button = self._styled_button(
            tr('buttons.custom_executable'), 250, tr('tooltips.custom_executable_library')
        )
        custom_executable_button.setObjectName('settings_custom_executable_button')
        path_exe_layout.addWidget(custom_executable_button)
        reset_custom_exe_button = QPushButton('⭯')
        reset_custom_exe_button.setObjectName('settings_reset_custom_exe_button')
        reset_custom_exe_button.setStyleSheet('min-width: 35px; max-width: 35px; padding-left: 0px; padding-right: 0px;')
        reset_custom_exe_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        reset_custom_exe_button.setVisible(False)
        path_exe_layout.addWidget(reset_custom_exe_button)
        cl.addWidget(path_exe_row, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_launch'), 'launch_launch', 'ui.settings_section_launch')
        launch_via_steam_checkbox = self._styled_checkbox(
            tr('ui.steam_launch'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>'
        )
        cl.addWidget(launch_via_steam_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        is_linux = platform.system() == 'Linux'
        use_portproton_checkbox = self._styled_checkbox(
            tr('ui.use_portproton'),
            "<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>'
        )
        use_portproton_checkbox.setVisible(is_linux)
        cl.addWidget(use_portproton_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        select_portproton_path_button = self._styled_button(tr('buttons.select_portproton_path'), 200)
        select_portproton_path_button.setVisible(is_linux)
        portproton_path_label = QLabel(tr('ui.file_not_selected'))
        portproton_path_label.setFixedHeight(20)
        portproton_frame = QFrame()
        portproton_layout = QVBoxLayout(portproton_frame)
        portproton_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        portproton_layout.addWidget(select_portproton_path_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        portproton_layout.addWidget(portproton_path_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        portproton_frame.setVisible(False)
        cl.addWidget(portproton_frame, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_patching'), 'launch_patching', 'ui.settings_section_patching')
        skip_patching_warnings_checkbox = self._styled_checkbox(
            tr('ui.skip_patching_warnings'), tr('tooltips.skip_patching_warnings')
        )
        cl.addWidget(skip_patching_warnings_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        sec, cl = self._collapsible_section(tr('ui.settings_section_merging'), 'launch_merging', 'ui.settings_section_merging')
        cont = QWidget()
        mo_layout = QHBoxLayout(cont)
        mo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mo_layout.setSpacing(20)
        for key in ('merge_properties', 'merge_code'):
            cb = self._styled_checkbox(tr(f'checkboxes.{key}'), tr(f'tooltips.{key}'))
            mo_layout.addWidget(cb)
            self.widgets[f'{key}_checkbox'] = cb
        cl.addWidget(cont, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sec)

        layout.addStretch()

        self.widgets['settings_game_combo'] = settings_game_combo
        self.widgets['settings_game_selector_label'] = game_selector_label
        self.widgets['settings_change_path_button'] = change_path_button
        self.widgets['skip_patching_warnings_checkbox'] = skip_patching_warnings_checkbox
        self.widgets['launch_via_steam_checkbox'] = launch_via_steam_checkbox
        self.widgets['use_portproton_checkbox'] = use_portproton_checkbox
        self.widgets['select_portproton_path_button'] = select_portproton_path_button
        self.widgets['portproton_path_label'] = portproton_path_label
        self.widgets['portproton_frame'] = portproton_frame
        self.widgets['settings_custom_executable_button'] = custom_executable_button
        self.widgets['settings_reset_custom_exe_button'] = reset_custom_exe_button
        return self._wrap_in_scroll(page)

    def _build_changelog_widget(self) -> QFrame:
        changelog_widget = QFrame()
        changelog_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        changelog_layout = QVBoxLayout(changelog_widget)
        changelog_text_edit = QTextBrowser()
        changelog_text_edit.setOpenExternalLinks(True)
        changelog_text_edit.setMinimumHeight(0)
        changelog_text_edit.setMaximumHeight(500)
        if self.parent:
            current_font = self.parent.font()
            changelog_text_edit.setFont(current_font)
            doc = changelog_text_edit.document()
            if doc is not None:
                doc.setDefaultFont(current_font)
                doc.setDefaultStyleSheet('p { margin-bottom: 0.75em; } ul, ol { margin-left: 1em; } li { margin-bottom: 0.25em; }')
        changelog_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")
        changelog_layout.addWidget(changelog_text_edit)
        changelog_button = QPushButton(tr('buttons.changelog'))
        changelog_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        changelog_button.setStyleSheet('min-width: 220px; max-width: 220px;')
        report_bug_button = QPushButton(tr('buttons.report_bug'))
        report_bug_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        report_bug_button.setStyleSheet('min-width: 220px; max-width: 220px;')
        self.widgets['changelog_text_edit'] = changelog_text_edit
        self.widgets['changelog_button'] = changelog_button
        self.widgets['report_bug_button'] = report_bug_button
        return changelog_widget

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
