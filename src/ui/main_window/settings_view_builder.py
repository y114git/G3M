from typing import Dict, Any
import platform
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QLineEdit, QTextBrowser, QSizePolicy
from managers.localization_manager import localization_manager, tr
from ui.widgets.common.custom_controls import NoScrollComboBox


class SettingsViewBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QFrame:
        settings_widget = QFrame()
        settings_widget.setObjectName('settings_widget')
        settings_layout = QVBoxLayout(settings_widget)
        settings_pages_container = QWidget()
        pages_layout = QVBoxLayout(settings_pages_container)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        settings_customization_page = QWidget()
        settings_menu_page = self._build_settings_menu_page()
        self._build_customization_page(settings_customization_page)
        pages_layout.addWidget(settings_menu_page)
        pages_layout.addWidget(settings_customization_page)
        settings_customization_page.setVisible(False)
        changelog_widget = self._build_changelog_widget()
        help_widget = self._build_help_widget()
        settings_layout.addWidget(settings_pages_container)
        changelog_widget.setVisible(False)
        settings_layout.addWidget(changelog_widget, stretch=1)
        help_widget.setVisible(False)
        settings_layout.addWidget(help_widget, stretch=1)
        button_bar_layout = QHBoxLayout()
        button_bar_layout.setSpacing(10)
        button_bar_layout.addStretch(1)
        button_bar_layout.addWidget(self.widgets['changelog_button'])
        button_bar_layout.addWidget(self.widgets['help_button'])
        button_bar_layout.addStretch(1)
        settings_layout.addLayout(button_bar_layout)
        settings_widget.setVisible(False)
        self.widgets['settings_widget'] = settings_widget
        self.widgets['settings_pages_container'] = settings_pages_container
        self.widgets['settings_menu_page'] = settings_menu_page
        self.widgets['settings_customization_page'] = settings_customization_page
        self.widgets['changelog_widget'] = changelog_widget
        self.widgets['help_widget'] = help_widget
        return settings_widget

    def _build_settings_menu_page(self) -> QWidget:
        settings_menu_page = QWidget()
        settings_menu_layout = QVBoxLayout(settings_menu_page)
        settings_menu_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_menu_layout.setSpacing(20)
        settings_title_label = QLabel(f"<h1>{tr('ui.settings_title')}</h1>")
        settings_title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        settings_menu_layout.addWidget(settings_title_label)
        settings_center_container = QVBoxLayout()
        settings_center_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_center_container.setSpacing(20)
        language_container = QWidget()
        language_layout = QHBoxLayout(language_container)
        language_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        language_layout.setSpacing(10)
        language_label = QLabel(tr('ui.language_label'))
        language_label.setStyleSheet('font-size: 20px; font-weight: bold;')
        language_layout.addWidget(language_label)
        language_combo = NoScrollComboBox()
        language_combo.setMinimumWidth(200)
        language_combo.setMaximumWidth(250)
        available_languages = localization_manager.get_available_languages()
        current_language = localization_manager.get_current_language()
        for code, name in available_languages.items():
            language_combo.addItem(name, code)
            if code == current_language:
                language_combo.setCurrentIndex(language_combo.count() - 1)
        language_layout.addWidget(language_combo)
        settings_center_container.addWidget(language_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        checkboxes_container = QWidget()
        checkboxes_layout = QHBoxLayout(checkboxes_container)
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        checkboxes_layout.setSpacing(40)
        left_column_widget = QWidget()
        left_column = QVBoxLayout(left_column_widget)
        left_column.setAlignment(Qt.AlignmentFlag.AlignLeft)
        left_column.setSpacing(20)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column_widget.setMinimumWidth(200)
        right_column_widget = QWidget()
        right_column = QVBoxLayout(right_column_widget)
        right_column.setAlignment(Qt.AlignmentFlag.AlignLeft)
        right_column.setSpacing(20)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column_widget.setMinimumWidth(200)
        beta_updates_checkbox = QCheckBox(tr('ui.beta_updates'))
        beta_updates_checkbox.setToolTip(tr('tooltips.beta_updates'))
        left_column.addWidget(beta_updates_checkbox)
        clear_logs_checkbox = QCheckBox(tr('ui.clear_logs_on_startup'))
        clear_logs_checkbox.setToolTip(tr('tooltips.clear_logs_on_startup'))
        right_column.addWidget(clear_logs_checkbox)
        fullscreen_checkbox = QCheckBox(tr('ui.fullscreen'))
        fullscreen_checkbox.setToolTip(tr('tooltips.fullscreen_tooltip'))
        left_column.addWidget(fullscreen_checkbox)
        hide_library_filters_checkbox = QCheckBox(tr('ui.hide_library_filters'))
        hide_library_filters_checkbox.setToolTip(tr('tooltips.hide_library_filters'))
        right_column.addWidget(hide_library_filters_checkbox)
        launch_via_steam_checkbox = QCheckBox(tr('ui.steam_launch'))
        launch_via_steam_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.steam') + '</body></html>')
        left_column.addWidget(launch_via_steam_checkbox)
        use_custom_executable_checkbox = QCheckBox(tr('ui.custom_executable'))
        use_custom_executable_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.custom_exe') + '</body></html>')
        right_column.addWidget(use_custom_executable_checkbox)
        checkboxes_layout.addWidget(left_column_widget)
        checkboxes_layout.addWidget(right_column_widget)
        settings_center_container.addWidget(checkboxes_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        use_portproton_checkbox = QCheckBox(tr('ui.use_portproton'))
        use_portproton_checkbox.setToolTip("<html><body style='white-space: normal;'>" + tr('tooltips.portproton') + '</body></html>')
        use_portproton_checkbox.setVisible(platform.system() == 'Linux')
        settings_center_container.addWidget(use_portproton_checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
        select_portproton_path_button = QPushButton(tr('buttons.select_portproton_path'))
        select_portproton_path_button.setVisible(platform.system() == 'Linux')
        select_portproton_path_button.setFixedWidth(153)
        portproton_path_label = QLabel(tr('ui.file_not_selected'))
        portproton_path_label.setFixedHeight(20)
        portproton_frame = QFrame()
        portproton_layout = QVBoxLayout(portproton_frame)
        portproton_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        portproton_layout.addWidget(select_portproton_path_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        portproton_layout.addWidget(portproton_path_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        portproton_frame.setVisible(False)
        if platform.system() != 'Linux':
            portproton_frame.setVisible(False)
            use_portproton_checkbox.setVisible(False)
        settings_center_container.addWidget(portproton_frame, alignment=Qt.AlignmentFlag.AlignHCenter)
        select_custom_executable_button = QPushButton(tr('buttons.select_file'))
        select_custom_executable_button.setFixedWidth(153)
        custom_executable_path_label = QLabel(tr('ui.file_not_selected'))
        custom_executable_path_label.setFixedHeight(20)
        custom_exe_frame = QFrame()
        custom_exe_layout = QVBoxLayout(custom_exe_frame)
        custom_exe_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        custom_exe_layout.addWidget(select_custom_executable_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        custom_exe_layout.addWidget(custom_executable_path_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        settings_center_container.addWidget(custom_exe_frame, alignment=Qt.AlignmentFlag.AlignHCenter)
        custom_exe_frame.setVisible(False)
        change_path_button = QPushButton()
        change_path_button.setFixedWidth(300)
        settings_center_container.addWidget(change_path_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        open_deltahub_folder_button = QPushButton(tr('buttons.open_deltahub_folder'))
        open_deltahub_folder_button.setFixedWidth(300)
        settings_center_container.addWidget(open_deltahub_folder_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        customization_button = QPushButton(tr('tags.customization'))
        customization_button.setFixedWidth(200)
        reset_button = QPushButton(tr('buttons.reset_settings'))
        reset_button.setFixedWidth(200)
        buttons_layout = QHBoxLayout()
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons_layout.setSpacing(10)
        buttons_layout.addWidget(customization_button)
        buttons_layout.addWidget(reset_button)
        settings_center_container.addLayout(buttons_layout)
        settings_menu_layout.addLayout(settings_center_container)
        settings_menu_layout.addStretch()
        self.widgets['settings_title_label'] = settings_title_label
        self.widgets['language_label'] = language_label
        self.widgets['language_combo'] = language_combo
        self.widgets['beta_updates_checkbox'] = beta_updates_checkbox
        self.widgets['clear_logs_checkbox'] = clear_logs_checkbox
        self.widgets['fullscreen_checkbox'] = fullscreen_checkbox
        self.widgets['hide_library_filters_checkbox'] = hide_library_filters_checkbox
        self.widgets['launch_via_steam_checkbox'] = launch_via_steam_checkbox
        self.widgets['use_portproton_checkbox'] = use_portproton_checkbox
        self.widgets['select_portproton_path_button'] = select_portproton_path_button
        self.widgets['portproton_path_label'] = portproton_path_label
        self.widgets['portproton_frame'] = portproton_frame
        self.widgets['use_custom_executable_checkbox'] = use_custom_executable_checkbox
        self.widgets['select_custom_executable_button'] = select_custom_executable_button
        self.widgets['custom_executable_path_label'] = custom_executable_path_label
        self.widgets['custom_exe_frame'] = custom_exe_frame
        self.widgets['change_path_button'] = change_path_button
        self.widgets['open_deltahub_folder_button'] = open_deltahub_folder_button
        self.widgets['customization_button'] = customization_button
        self.widgets['settings_customization_button'] = customization_button
        self.widgets['reset_button'] = reset_button
        return settings_menu_page

    def _build_customization_page(self, settings_customization_page: QWidget):
        disable_background_checkbox = QCheckBox(tr('checkboxes.disable_background'))
        disable_splash_checkbox = QCheckBox(tr('checkboxes.disable_splash'))
        settings_customization_layout = QVBoxLayout(settings_customization_page)
        back_button_cust = QPushButton(tr('ui.back_button'))
        settings_customization_layout.addWidget(back_button_cust, alignment=Qt.AlignmentFlag.AlignLeft)
        settings_customization_layout.addSpacing(15)
        change_background_button = QPushButton()
        change_background_button.setFixedWidth(400)
        change_background_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        settings_customization_layout.addWidget(change_background_button, 0, Qt.AlignmentFlag.AlignHCenter)
        settings_customization_layout.addSpacing(8)
        sound_buttons_layout = QHBoxLayout()
        sound_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sound_buttons_layout.setSpacing(10)
        background_music_button = QPushButton()
        background_music_button.setFixedWidth(275)
        background_music_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sound_buttons_layout.addWidget(background_music_button)
        startup_sound_button = QPushButton()
        startup_sound_button.setFixedWidth(275)
        startup_sound_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sound_buttons_layout.addWidget(startup_sound_button)
        settings_customization_layout.addLayout(sound_buttons_layout)
        settings_customization_layout.addSpacing(20)
        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkboxes_layout.setSpacing(20)
        checkboxes_layout.addWidget(disable_background_checkbox)
        checkboxes_layout.addWidget(disable_splash_checkbox)
        settings_customization_layout.addLayout(checkboxes_layout)
        settings_customization_layout.addSpacing(8)
        custom_style_frame = QFrame()
        custom_style_layout = QVBoxLayout(custom_style_frame)
        custom_style_layout.setContentsMargins(0, 15, 0, 0)
        custom_style_layout.setSpacing(8)
        color_widgets = {}
        color_labels = {}
        color_config = {'background': tr('ui.background_color'), 'button': tr('ui.elements_color'), 'border': tr('ui.border_color'), 'button_hover': tr('ui.hover_color'), 'text': tr('ui.main_text_color'), 'version_text': tr('ui.secondary_text_color')}

        def create_setting_row(label_text: str) -> tuple:
            layout = QHBoxLayout()
            label = QLabel(label_text)
            color_display = QLineEdit()
            color_display.setFixedWidth(95)
            color_display.setReadOnly(True)
            color_btn = QPushButton(tr('ui.select_color'))
            color_btn.setFixedWidth(150)
            reset_btn = QPushButton('⭯')
            reset_btn.setStyleSheet('min-width: 35px; max-width: 35px; padding-left: 0px; padding-right: 0px;')
            reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            layout.addWidget(label)
            layout.addStretch()
            for widget in [color_display, color_btn, reset_btn]:
                layout.addWidget(widget)
            return (layout, color_display, color_btn, reset_btn, label)
        for key, label_text in color_config.items():
            layout, line_edit, btn, reset_btn, label_widget = create_setting_row(label_text)
            color_widgets[key] = line_edit
            color_labels[key] = label_widget
            self.widgets[f'color_btn_{key}'] = btn
            self.widgets[f'color_reset_{key}'] = reset_btn
            custom_style_layout.addLayout(layout)
        settings_customization_layout.addWidget(custom_style_frame)
        settings_customization_layout.addStretch()
        theme_button = QPushButton(tr('buttons.theme_management'))
        theme_button.setFixedWidth(400)
        theme_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        settings_customization_layout.addWidget(theme_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.widgets['disable_background_checkbox'] = disable_background_checkbox
        self.widgets['disable_splash_checkbox'] = disable_splash_checkbox
        self.widgets['back_button_cust'] = back_button_cust
        self.widgets['change_background_button'] = change_background_button
        self.widgets['background_music_button'] = background_music_button
        self.widgets['startup_sound_button'] = startup_sound_button
        self.widgets['custom_style_frame'] = custom_style_frame
        self.widgets['color_widgets'] = color_widgets
        self.widgets['color_labels'] = color_labels
        self.widgets['color_config'] = color_config
        self.widgets['theme_button'] = theme_button

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
        changelog_text_edit.setOpenExternalLinks(True)
        changelog_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")
        changelog_layout.addWidget(changelog_text_edit)
        changelog_button = QPushButton(tr('buttons.changelog'))
        changelog_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        changelog_button.setStyleSheet('min-width: 220px; max-width: 220px;')
        self.widgets['changelog_text_edit'] = changelog_text_edit
        self.widgets['changelog_button'] = changelog_button
        return changelog_widget

    def _build_help_widget(self) -> QFrame:
        help_widget = QFrame()
        help_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        help_layout = QVBoxLayout(help_widget)
        help_text_edit = QTextBrowser()
        help_text_edit.setOpenExternalLinks(True)
        help_text_edit.setMinimumHeight(0)
        help_text_edit.setMaximumHeight(500)
        if self.parent:
            help_font = self.parent.font()
            help_text_edit.setFont(help_font)
            help_doc = help_text_edit.document()
            if help_doc is not None:
                help_doc.setDefaultFont(help_font)
                help_doc.setDefaultStyleSheet('p { margin-bottom: 0.75em; } ul, ol { margin-left: 1em; } li { margin-bottom: 0.25em; }')
        help_text_edit.setOpenExternalLinks(True)
        help_text_edit.setMarkdown(f"<i>{tr('status.loading')}</i>")
        help_layout.addWidget(help_text_edit)
        help_button = QPushButton(tr('buttons.help'))
        help_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        help_button.setStyleSheet('min-width: 220px; max-width: 220px;')
        self.widgets['help_text_edit'] = help_text_edit
        self.widgets['help_button'] = help_button
        return help_widget

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
