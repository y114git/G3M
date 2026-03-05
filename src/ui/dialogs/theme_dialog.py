from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from services.localization_service import tr
from ui.common.styling import get_border_radius


class ThemeManagementDialog(QDialog):
    def __init__(self, parent_widget, theme_controller):
        super().__init__(parent_widget)
        self.theme_controller = theme_controller
        self.setWindowTitle(tr('buttons.theme_management'))
        self.setMinimumWidth(400)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        info_label = QLabel(tr('themes.current_settings') + ":")
        info_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(info_label)

        settings_text = self._build_settings_text()
        settings_label = QLabel(settings_text)
        layout.addWidget(settings_label)

        button_layout = QHBoxLayout()
        import_btn = QPushButton(tr('buttons.import'))
        import_btn.clicked.connect(self._on_import)
        export_btn = QPushButton(tr('buttons.export'))
        export_btn.clicked.connect(self._on_export)
        cancel_btn = QPushButton(tr('dialogs.cancel'))
        cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(import_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _build_settings_text(self):
        config = self.theme_controller.app_state.local_config
        cs = self.theme_controller.customization_service

        has_custom = False
        parts = []

        if config.get('custom_background_path'):
            parts.append("• " + tr('themes.custom_background'))
            has_custom = True

        if cs.get_background_music_path():
            parts.append("• " + tr('themes.background_music'))
            has_custom = True

        if cs.get_startup_sound_path():
            parts.append("• " + tr('themes.startup_sound'))
            has_custom = True

        if cs.get_custom_logo_path():
            parts.append("• " + tr('themes.custom_logo'))
            has_custom = True

        if cs.get_custom_font_path():
            parts.append("• " + tr('themes.custom_font'))
            has_custom = True

        color_map = {
            'custom_color_background': 'ui.background_color',
            'custom_color_button': 'ui.elements_color',
            'custom_color_border': 'ui.border_color',
            'custom_color_button_hover': 'ui.hover_color',
            'custom_color_text': 'ui.main_text_color',
            'custom_color_secondary_text': 'ui.secondary_text_color'
        }

        changed_colors = []
        for conf_key, lang_key in color_map.items():
            if config.get(conf_key):

                color_name = tr(lang_key).rstrip(':')
                changed_colors.append("  - " + color_name)

        if changed_colors:
            parts.append("• " + tr('themes.custom_colors') + ":\n" + "\n".join(changed_colors))
            has_custom = True

        border_radius = get_border_radius(config)
        if border_radius:
            parts.append("• " + tr('ui.border_radius_label') + f": {border_radius}px")
            has_custom = True

        if not has_custom:
            return tr('themes.no_customizations')

        return "\n".join(parts)

    def _on_import(self):
        self.accept()
        self.theme_controller.settings_service.import_theme()

    def _on_export(self):
        self.accept()
        self.theme_controller.settings_service.export_theme()
