"""Details dialog for installed plugins."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from models.plugin_models import InstalledPluginRecord
from services.localization_service import localization_service, tr
from services.plugin_support import resolve_plugin_path
from ui.common.styling import get_theme_color


def _resolve_text(value: str) -> str:
    if not value:
        return ""
    translated = localization_service.get_text(value)
    return value if translated == f"[{value}]" else translated


class PluginDetailsDialog(QDialog):
    """Shows installed plugin metadata, settings, and destructive actions."""

    def __init__(
        self,
        plugin: InstalledPluginRecord,
        runtime_service,
        state_service,
        app_state,
        *,
        can_update: bool,
        on_update,
        on_delete,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.runtime_service = runtime_service
        self.state_service = state_service
        self.app_state = app_state
        self._on_update = on_update
        self._on_delete = on_delete
        self._can_update = can_update
        self.setWindowTitle(_resolve_text(plugin.manifest.name if plugin.manifest else plugin.plugin_id))
        self.setMinimumWidth(620)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        summary = QFrame(self)
        summary_layout = QHBoxLayout(summary)
        summary_layout.setSpacing(14)
        icon_frame = QFrame(summary)
        icon_frame.setStyleSheet(f"border: 2px solid {get_theme_color(self.app_state.local_config, 'border')}; border-radius: 12px;")
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel(icon_frame)
        icon_label.setFixedSize(112, 112)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.plugin.manifest and self.plugin.manifest.icon:
            pixmap = QPixmap(resolve_plugin_path(self.plugin.path, self.plugin.manifest.icon))
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(
                        112,
                        112,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        icon_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(icon_frame, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_layout = QVBoxLayout()
        title = QLabel(
            _resolve_text(
                self.plugin.manifest.name if self.plugin.manifest else self.plugin.plugin_id
            )
        )
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {get_theme_color(self.app_state.local_config, 'main_text')};")
        meta_layout.addWidget(title)
        description = QLabel(
            _resolve_text(
                self.plugin.manifest.description if self.plugin.manifest else self.plugin.error
            )
        )
        description.setWordWrap(True)
        description.setStyleSheet(f"font-size: 12px; color: {get_theme_color(self.app_state.local_config, 'secondary_text')};")
        meta_layout.addWidget(description)
        for label_key, value in (
            ("plugins.meta_author", self.plugin.manifest.author if self.plugin.manifest else ""),
            ("plugins.meta_version", self.plugin.manifest.version if self.plugin.manifest else ""),
            ("plugins.meta_api_version", self.plugin.manifest.api_version if self.plugin.manifest else ""),
        ):
            row = QHBoxLayout()
            meta_label = QLabel(f"{tr(label_key)}:")
            meta_label.setStyleSheet(f"font-size: 15px; color: {get_theme_color(self.app_state.local_config, 'main_text')};")
            row.addWidget(meta_label)
            meta_value = QLabel(value)
            meta_value.setStyleSheet(f"font-size: 15px; color: {get_theme_color(self.app_state.local_config, 'secondary_text')};")
            row.addWidget(meta_value, 1)
            meta_layout.addLayout(row)
        summary_layout.addLayout(meta_layout, 1)
        layout.addWidget(summary)

        actions_layout = QHBoxLayout()
        if self.plugin.manifest and self.plugin.manifest.external_link:
            external_button = QPushButton(tr("plugins.details_external"))
            external_button.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(self.plugin.manifest.external_link))
            )
            actions_layout.addWidget(external_button)
        if self.plugin.manifest and self._can_update:
            update_button = QPushButton(tr("plugins.details_update"))
            update_button.clicked.connect(lambda: self._on_update(self.plugin.plugin_id))
            actions_layout.addWidget(update_button)
        actions_layout.addStretch(1)
        if actions_layout.count():
            layout.addLayout(actions_layout)

        settings_title = QLabel(tr("plugins.details_settings"))
        settings_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        settings_title.setStyleSheet(f"font-weight: bold; color: {get_theme_color(self.app_state.local_config, 'main_text')};")
        layout.addWidget(settings_title)
        settings_container = self._build_settings_container()
        layout.addWidget(settings_container, 1)

        delete_button = QPushButton(tr("plugins.details_delete"))
        from ui.common.styling import get_border_radius
        dr = get_border_radius(self.app_state.local_config)
        tc = get_theme_color(self.app_state.local_config, "main_text", "#e8e9eb")
        delete_button.setStyleSheet(
            f"background-color: darkred; color: {tc}; border-radius: {dr}px;"
        )
        delete_button.clicked.connect(self._confirm_delete_plugin)
        layout.addWidget(delete_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _build_settings_container(self):
        custom_widget = self.runtime_service.get_settings_widget(self.plugin.plugin_id, self)
        if custom_widget is not None:
            return custom_widget
        schema = self.plugin.manifest.settings_schema if self.plugin.manifest else {}
        if not schema:
            label = QLabel(tr("plugins.no_settings"))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return label
        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)
        fields = schema.get("fields", [])
        for field in fields:
            widget = self._build_schema_field(field)
            if widget:
                content_layout.addWidget(widget)
        content_layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_schema_field(self, field: dict[str, Any]):
        key = str(field.get("key", "")).strip()
        field_type = str(field.get("type", "string")).strip()
        if not key:
            return None
        container = QWidget(self)
        layout = QHBoxLayout(container)
        label = QLabel(_resolve_text(str(field.get("label", key))))
        layout.addWidget(label)
        current_value = self.state_service.get_plugin_setting(
            self.plugin.plugin_id,
            key,
            field.get("default"),
        )
        if field_type == "bool":
            widget = QCheckBox(container)
            widget.setChecked(bool(current_value))
            widget.stateChanged.connect(
                lambda state, plugin_id=self.plugin.plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, bool(state))
            )
        elif field_type == "int":
            widget = QSpinBox(container)
            try:
                min_val = int(field.get("min", 0))
            except (ValueError, TypeError):
                min_val = 0
            try:
                max_val = int(field.get("max", 999999))
            except (ValueError, TypeError):
                max_val = 999999
            try:
                cur_val = int(current_value or 0)
            except (ValueError, TypeError):
                cur_val = 0
            widget.setMinimum(min_val)
            widget.setMaximum(max_val)
            widget.setValue(cur_val)
            widget.valueChanged.connect(
                lambda value, plugin_id=self.plugin.plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, int(value))
            )
        elif field_type == "choice":
            widget = QComboBox(container)
            options = field.get("options", [])
            for option in options:
                value = option.get("value", option)
                text = _resolve_text(str(option.get("label", value))) if isinstance(option, dict) else str(option)
                widget.addItem(text, value)
            for index in range(widget.count()):
                if widget.itemData(index) == current_value:
                    widget.setCurrentIndex(index)
                    break
            widget.currentIndexChanged.connect(
                lambda index, combo=widget, plugin_id=self.plugin.plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, combo.itemData(index))
            )
        elif field_type in {"action", "button"}:
            widget = QPushButton(_resolve_text(str(field.get("button_text", field.get("label", key)))))
            widget.clicked.connect(
                lambda _=False, plugin_id=self.plugin.plugin_id, setting_key=key: self.runtime_service.run_settings_action(plugin_id, setting_key, self)
            )
        else:
            widget = QLineEdit(container)
            widget.setText("" if current_value is None else str(current_value))
            widget.editingFinished.connect(
                lambda edit=widget, plugin_id=self.plugin.plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, edit.text())
            )
        layout.addWidget(widget, 1 if field_type not in {"action", "button"} else 0)
        return container

    def _confirm_delete_plugin(self):
        """Show confirmation dialog before deleting plugin."""
        from PyQt6.QtWidgets import QMessageBox
        if (
            QMessageBox.question(
                self,
                tr("dialogs.are_you_sure"),
                tr("dialogs.plugin_deletion_confirmation"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._on_delete(self.plugin.plugin_id)
        self.accept()
