"""Dialog for theme management and import actions."""

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from config.settings_schema import DEFAULT_APP_SETTINGS
from services.localization_service import tr
from ui.common.styling import get_border_radius


class ThemeManagementDialog(QDialog):
    def __init__(self, parent_widget, theme_controller) -> None:
        super().__init__(parent_widget)
        self.theme_controller = theme_controller
        self.setWindowTitle(tr("buttons.theme_management"))
        self.setMinimumWidth(400)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        info_label = QLabel(tr("themes.current_settings") + ":")
        info_label.setStyleSheet("font-weight: bold;")
        info_label.setToolTip(tr("tooltips.theme_current_settings"))
        layout.addWidget(info_label)

        settings_text = self._build_settings_text()
        settings_label = QLabel(settings_text)
        settings_label.setToolTip(tr("tooltips.theme_current_settings"))
        layout.addWidget(settings_label)

        button_layout = QHBoxLayout()
        import_btn = QPushButton(tr("buttons.import"))
        import_btn.setToolTip(tr("tooltips.import_theme"))
        import_btn.clicked.connect(self._on_import)
        export_btn = QPushButton(tr("buttons.export"))
        export_btn.setToolTip(tr("tooltips.export_theme"))
        export_btn.clicked.connect(self._on_export)
        cancel_btn = QPushButton(tr("dialogs.cancel"))
        cancel_btn.setToolTip(tr("tooltips.cancel"))
        cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(import_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _build_settings_text(self):
        config = self.theme_controller.app_state.local_config
        cs = self.theme_controller.customization_service
        parts = [
            "• " + tr(label_key)
            for enabled, label_key in (
                (config.get("custom_background_path"), "themes.custom_background"),
                (cs.get_background_music_path(), "themes.background_music"),
                (cs.get_startup_sound_path(), "themes.startup_sound"),
                (cs.get_custom_logo_path(), "themes.custom_logo"),
                (cs.get_custom_font_path(), "themes.custom_font"),
            )
            if enabled
        ]

        color_map = {
            "custom_background_color": "ui.background_color",
            "custom_elements_color": "ui.elements_color",
            "custom_border_color": "ui.border_color",
            "custom_hover_color": "ui.custom_hover_color",
            "custom_select_color": "ui.custom_select_color",
            "custom_main_text_color": "ui.main_text_color",
            "custom_secondary_text_color": "ui.secondary_text_color",
        }

        changed_colors = [
            " - " + tr(lang_key).rstrip(":")
            for conf_key, lang_key in color_map.items()
            if config.get(conf_key)
        ]

        if changed_colors:
            parts.append(
                "• " + tr("themes.custom_colors") + ":\n" + "\n".join(changed_colors)
            )

        border_radius = get_border_radius(
            config, default=DEFAULT_APP_SETTINGS["custom_border_radius"]
        )
        if border_radius != DEFAULT_APP_SETTINGS["custom_border_radius"]:
            parts.append("• " + tr("ui.border_radius_label") + f": {border_radius}px")

        if not parts:
            return tr("themes.no_customizations")

        return "\n".join(parts)

    def _on_import(self):
        self.accept()
        self.theme_controller.settings_service.import_theme()

    def _on_export(self):
        self.accept()
        self.theme_controller.settings_service.export_theme()
