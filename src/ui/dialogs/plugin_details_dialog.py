"""Details dialog for installed plugins."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
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

from models.plugin_models import CatalogPluginEntry, InstalledPluginRecord
from services.localization_service import localization_service, tr
from services.plugins.support import resolve_plugin_path
from ui.common.styling import (
    get_border_radius,
    get_theme_color,
    load_mod_icon_universal,
)
from utils.native_integration import open_url_native


def _resolve_text(value: str) -> str:
    if not value:
        return ""
    translated = localization_service.get_text(value)
    return value if translated == f"[{value}]" else translated


class PluginDetailsDialog(QDialog):
    """Shows installed plugin metadata, settings, and destructive actions."""

    def __init__(
        self,
        plugin: InstalledPluginRecord | None,
        runtime_service,
        state_service,
        app_state,
        *,
        can_update: bool = False,
        on_update=None,
        catalog_entry: CatalogPluginEntry | None = None,
        can_download: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.catalog_entry = catalog_entry
        self.runtime_service = runtime_service
        self.state_service = state_service
        self.app_state = app_state
        self._on_update = on_update
        self._can_update = can_update
        self._can_download = can_download
        self.delete_requested = False
        self.download_requested = False
        self.setWindowTitle(self._display_name())
        self.setMinimumWidth(620)
        self._init_ui()

    def _plugin_id(self) -> str:
        if self.plugin:
            return self.plugin.plugin_id
        return self.catalog_entry.id if self.catalog_entry else ""

    def _manifest(self):
        return self.plugin.manifest if self.plugin and self.plugin.manifest else None

    def _display_name(self) -> str:
        manifest = self._manifest()
        if manifest:
            return _resolve_text(manifest.name)
        if self.plugin:
            return self.plugin.plugin_id
        return self.catalog_entry.name if self.catalog_entry else ""

    def _description(self) -> str:
        manifest = self._manifest()
        if manifest:
            return _resolve_text(manifest.description)
        if self.plugin:
            return self.plugin.error
        return self.catalog_entry.description if self.catalog_entry else ""

    def _author(self) -> str:
        manifest = self._manifest()
        if manifest:
            return manifest.author
        return self.catalog_entry.author if self.catalog_entry else ""

    def _version(self) -> str:
        manifest = self._manifest()
        if manifest:
            return manifest.version
        return self.catalog_entry.version if self.catalog_entry else ""

    def _api_version(self) -> str:
        manifest = self._manifest()
        if manifest:
            return manifest.api_version
        return self.catalog_entry.api_version if self.catalog_entry else ""

    def _homepage(self) -> str:
        manifest = self._manifest()
        if manifest:
            return manifest.homepage
        return self.catalog_entry.homepage if self.catalog_entry else ""

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        summary = QFrame(self)
        summary_layout = QHBoxLayout(summary)
        summary_layout.setSpacing(14)
        icon_column = QWidget(summary)
        icon_column_layout = QVBoxLayout(icon_column)
        icon_column_layout.setContentsMargins(0, 0, 0, 0)
        icon_column_layout.setSpacing(8)
        if homepage := self._homepage():
            external_button = QPushButton(tr("plugins.details_homepage"), icon_column)
            external_button.setToolTip(tr("tooltips.open_homepage"))
            external_button.clicked.connect(
                lambda: open_url_native(homepage)
            )
            icon_column_layout.addWidget(external_button)

        icon_label = QLabel(icon_column)
        icon_label.setFixedSize(112, 112)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(
            f"border: 2px solid {get_theme_color(self.app_state.local_config, 'border')}; "
            f"border-radius: {get_border_radius(self.app_state.local_config)}px;"
        )
        manifest = self._manifest()
        if self.plugin and manifest and manifest.icon:
            pixmap = QPixmap(resolve_plugin_path(self.plugin.path, manifest.icon))
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(
                        96,
                        96,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        elif self.catalog_entry and self.catalog_entry.icon:
            load_mod_icon_universal(icon_label, self.catalog_entry, size=96)
        icon_column_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        icon_column_layout.addStretch(1)
        summary_layout.addWidget(icon_column, 0, Qt.AlignmentFlag.AlignTop)
        meta_layout = QVBoxLayout()
        title = QLabel(self._display_name())
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {get_theme_color(self.app_state.local_config, 'main_text')};")
        meta_layout.addWidget(title)
        description = QLabel(self._description())
        description.setWordWrap(True)
        description.setStyleSheet(f"font-size: 12px; color: {get_theme_color(self.app_state.local_config, 'secondary_text')};")
        meta_layout.addWidget(description)
        for label_key, value in (
            ("plugins.meta_author", self._author()),
            ("plugins.meta_version", self._version()),
            ("plugins.meta_api_version", self._api_version()),
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
        has_actions = False
        if manifest and self._can_update:
            update_button = QPushButton(tr("plugins.details_update"))
            update_button.setToolTip(tr("tooltips.plugin_update"))
            update_button.clicked.connect(lambda: self._on_update(self._plugin_id()))
            actions_layout.addWidget(update_button)
            has_actions = True
        actions_layout.addStretch(1)
        if has_actions:
            layout.addLayout(actions_layout)

        if self.plugin is not None:
            settings_title = QLabel(tr("plugins.details_settings"))
            settings_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            settings_title.setStyleSheet(f"font-weight: bold; color: {get_theme_color(self.app_state.local_config, 'main_text')};")
            layout.addWidget(settings_title)
            settings_container = self._build_settings_container()
            layout.addWidget(settings_container, 1)

        dr = get_border_radius(self.app_state.local_config)
        tc = get_theme_color(self.app_state.local_config, "main_text", "#e8e9eb")
        if self.plugin is not None:
            delete_button = QPushButton(tr("plugins.details_delete"))
            delete_button.setStyleSheet(
                f"background-color: darkred; color: {tc}; border-radius: {dr}px;"
            )
            delete_button.setToolTip(tr("tooltips.plugin_delete"))
            delete_button.clicked.connect(self._confirm_delete_plugin)
            layout.addWidget(delete_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        else:
            download_button = QPushButton(tr("plugins.action_download"))
            download_button.setEnabled(self._can_download)
            download_button.setStyleSheet(
                f"color: {tc}; border-radius: {dr}px;"
            )
            download_button.clicked.connect(self._request_download)
            layout.addWidget(download_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _build_settings_container(self):
        custom_widget = self.runtime_service.get_settings_widget(self._plugin_id(), self)
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
        plugin_id = self._plugin_id()
        container = QWidget(self)
        layout = QHBoxLayout(container)
        label = QLabel(_resolve_text(str(field.get("label", key))))
        if field.get("description"):
            label.setToolTip(_resolve_text(str(field.get("description", ""))))
        layout.addWidget(label)
        current_value = self.state_service.get_plugin_setting(
            self._plugin_id(),
            key,
            field.get("default"),
        )
        if field_type == "bool":
            widget = QCheckBox(container)
            widget.setChecked(bool(current_value))
            if field.get("description"):
                widget.setToolTip(_resolve_text(str(field.get("description", ""))))
            widget.stateChanged.connect(
                lambda state, plugin_id=plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, bool(state))
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
            if field.get("description"):
                widget.setToolTip(_resolve_text(str(field.get("description", ""))))
            widget.valueChanged.connect(
                lambda value, plugin_id=plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, int(value))
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
            if field.get("description"):
                widget.setToolTip(_resolve_text(str(field.get("description", ""))))
            widget.currentIndexChanged.connect(
                lambda index, combo=widget, plugin_id=plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, combo.itemData(index))
            )
        elif field_type in {"action", "button"}:
            widget = QPushButton(_resolve_text(str(field.get("button_text", field.get("label", key)))))
            if field.get("description"):
                widget.setToolTip(_resolve_text(str(field.get("description", ""))))
            widget.clicked.connect(
                lambda _=False, plugin_id=plugin_id, setting_key=key: self.runtime_service.run_settings_action(plugin_id, setting_key, self)
            )
        else:
            widget = QLineEdit(container)
            widget.setText("" if current_value is None else str(current_value))
            if field.get("description"):
                widget.setToolTip(_resolve_text(str(field.get("description", ""))))
            widget.editingFinished.connect(
                lambda edit=widget, plugin_id=plugin_id, setting_key=key: self.state_service.set_plugin_setting(plugin_id, setting_key, edit.text())
            )
        if field.get("description"):
            widget.setToolTip(_resolve_text(str(field["description"])))
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
        self.delete_requested = True
        self.accept()

    def _request_download(self):
        self.download_requested = True
        self.accept()
