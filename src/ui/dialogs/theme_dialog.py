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

        self.info_label = QLabel()
        self.info_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.info_label)

        settings_text = self._build_settings_text()
        self.settings_label = QLabel(settings_text)
        layout.addWidget(self.settings_label)

        button_layout = QHBoxLayout()
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self._on_import)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._on_export)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.import_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("buttons.theme_management"))
        self.info_label.setText(tr("themes.current_settings") + ":")
        tooltip = tr("tooltips.theme_current_settings")
        self.info_label.setToolTip(tooltip)
        self.settings_label.setText(self._build_settings_text())
        self.settings_label.setToolTip(tooltip)
        for button, text_key, tooltip_key in (
            (self.import_button, "buttons.import", "tooltips.import_theme"),
            (self.export_button, "buttons.export", "tooltips.export_theme"),
            (self.cancel_button, "dialogs.cancel", "tooltips.cancel"),
        ):
            button.setText(tr(text_key))
            button.setToolTip(tr(tooltip_key))

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
