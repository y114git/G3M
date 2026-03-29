"""Plugins settings-tab controller."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models.download_models import SourceKind, TargetKind
from models.plugin_models import PLUGIN_API_VERSION
from services.localization_service import localization_service, tr
from services.plugin_support import is_version_compatible, resolve_plugin_path
from ui.common.styling import (
    clear_layout_widgets,
    get_border_radius,
    get_card_button_metrics,
    get_card_layout_scale,
    get_theme_color,
    load_mod_icon_universal,
    show_empty_message_in_layout,
    update_mod_widget_style,
)
from ui.dialogs.plugin_details_dialog import PluginDetailsDialog

logger = logging.getLogger(__name__)

_TAG_TO_ATTR = {
    "interface": "plugins_tag_interface_checkbox",
    "game_experience": "plugins_tag_game_experience_checkbox",
    "tool": "plugins_tag_tool_checkbox",
    "other": "plugins_tag_other_checkbox",
}


def _resolve_text(value: str) -> str:
    if not value:
        return ""
    translated = localization_service.get_text(value)
    return value if translated == f"[{value}]" else translated


class _PluginCatalogWorker(QThread):
    loaded = pyqtSignal()

    def __init__(self, plugin_catalog_service) -> None:
        super().__init__()
        self.plugin_catalog_service = plugin_catalog_service

    def run(self) -> None:
        try:
            self.plugin_catalog_service.refresh_catalog()
        except Exception:
            logger.exception("PluginsController: catalog refresh failed in _PluginCatalogWorker")
        finally:
            self.loaded.emit()


class PluginsController:
    """Owns the settings plugins tab, filters, and plugin actions."""

    def __init__(
        self,
        app_state,
        feedback_service,
        downloads_manager,
        plugin_catalog_service,
        plugin_state_service,
        plugin_runtime_service,
        plugin_install_service,
        app_window,
    ) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.downloads_manager = downloads_manager
        self.plugin_catalog_service = plugin_catalog_service
        self.plugin_state_service = plugin_state_service
        self.plugin_runtime_service = plugin_runtime_service
        self.plugin_install_service = plugin_install_service
        self.app = app_window
        self._loaded = False
        self._filtering = False
        self._catalog_worker: _PluginCatalogWorker | None = None
        self._plugin_tab_ids: list[str] = []
        self._download_buttons: dict[str, QPushButton] = {}
        self.downloads_manager.record_updated.connect(self._on_download_record_updated)
        self.downloads_manager.record_removed.connect(self._on_download_record_removed)

    def restore_filter_state(self) -> None:
        if not hasattr(self.app, "plugins_installed_only_checkbox"):
            return
        filters = self.plugin_state_service.get_filters()
        self._filtering = True
        try:
            self.app.plugins_installed_only_checkbox.setChecked(filters["installed_only"])
            for tag, attr in _TAG_TO_ATTR.items():
                checkbox = getattr(self.app, attr, None)
                if checkbox:
                    checkbox.setChecked(tag in filters["tags"])
        finally:
            self._filtering = False

    def on_tab_changed(self, index: int) -> None:
        if not hasattr(self.app, "settings_tab_widget"):
            return
        if (
            hasattr(self.app, "plugins_tab")
            and self.app.settings_tab_widget.currentWidget() is self.app.plugins_tab
        ):
            self.ensure_loaded()

    def ensure_loaded(self, force_refresh: bool = False) -> None:
        if self._loaded and not force_refresh and self.plugin_catalog_service.is_loaded():
            return
        self.plugin_runtime_service.scan_installed_plugins(resolve_catalog=False)
        self._loaded = True
        self.refresh_main_tabs()
        self.render()
        if force_refresh or self._catalog_worker is None:
            self._start_catalog_load()

    def on_filters_changed(self) -> None:
        if self._filtering:
            return
        self.plugin_state_service.set_filters(
            installed_only=bool(self.app.plugins_installed_only_checkbox.isChecked()),
            tags=[
                tag
                for tag, attr in _TAG_TO_ATTR.items()
                if getattr(self.app, attr, None) and getattr(self.app, attr).isChecked()
            ],
        )
        if self._loaded:
            self.render()

    def render(self) -> None:
        if not hasattr(self.app, "plugins_layout"):
            return
        self._apply_list_style()
        self._download_buttons.clear()
        clear_layout_widgets(self.app.plugins_layout)
        installed = {
            plugin.plugin_id: plugin
            for plugin in self.plugin_runtime_service.list_installed_plugins()
        }
        catalog_entries = self.plugin_catalog_service.list_entries(load_if_needed=False)
        filters = self.plugin_state_service.get_filters()
        tag_filter = set(filters["tags"])
        items: list[QWidget] = []

        for plugin in installed.values():
            if tag_filter and not (
                tag_filter & set(plugin.manifest.tags if plugin.manifest else [])
            ):
                continue
            items.append(self._build_installed_card(plugin))
        if not filters["installed_only"]:
            for entry in catalog_entries:
                if entry.id in installed:
                    continue
                if tag_filter and not (tag_filter & set(entry.tags)):
                    continue
                items.append(self._build_catalog_card(entry))
        if not items:
            show_empty_message_in_layout(
                self.app.plugins_layout,
                tr("plugins.empty"),
                self.app_state.local_config,
                font_size=15,
            )
            return
        for widget in items:
            self.app.plugins_layout.insertWidget(self.app.plugins_layout.count() - 1, widget)

    def relocalize_ui(self) -> None:
        self.restore_filter_state()
        self.refresh_main_tabs()
        if self._loaded:
            self.render()

    def _on_download_record_updated(self, record) -> None:
        if getattr(record, "target_kind", None) != TargetKind.PLUGIN:
            return
        plugin_id = (
            str((record.metadata or {}).get("plugin_id", "")).strip()
            if getattr(record, "metadata", None)
            else ""
        )
        effective_status = getattr(record, "effective_status_key", "")
        if plugin_id and effective_status in {"downloading", "installing", "ready"}:
            self._refresh_download_button_state(plugin_id)
            return
        self.plugin_runtime_service.scan_installed_plugins(
            resolve_catalog=self.plugin_catalog_service.is_loaded()
        )
        self.refresh_main_tabs()
        if self._loaded:
            self.render()

    def _on_download_record_removed(self, record) -> None:
        if getattr(record, "target_kind", None) != TargetKind.PLUGIN:
            return
        self.plugin_runtime_service.scan_installed_plugins(
            resolve_catalog=self.plugin_catalog_service.is_loaded()
        )
        self.refresh_main_tabs()

    def handle_external_refresh(self) -> None:
        self.plugin_runtime_service.scan_installed_plugins(
            resolve_catalog=self.plugin_catalog_service.is_loaded()
        )
        self.refresh_main_tabs()
        if self._loaded:
            self.render()

    def handle_theme_refresh(self) -> None:
        if self._loaded:
            self.render()

    def _build_card_shell(self) -> tuple[QFrame, QLabel, QVBoxLayout, QVBoxLayout]:
        parent = (
            getattr(self.app, "plugins_widget", None)
            or getattr(self.app, "plugins_container", None)
            or self.app
        )
        card = QFrame(parent)
        card.setObjectName("pluginCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        icon_label = QLabel(card)
        icon_label.setObjectName("modIcon")
        icon_label.setFixedSize(80, 80)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        body = QVBoxLayout()
        body.setSpacing(2)
        body.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(body, 1)
        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(actions, 0)
        card.main_layout = layout
        card.icon_label = icon_label
        update_mod_widget_style(card, "pluginCard", self.app)
        button_width, button_height, button_font_size = get_card_button_metrics(
            self.app_state.local_config
        )
        border = get_theme_color(self.app_state.local_config, "border")
        button = get_theme_color(self.app_state.local_config, "elements")
        hover = get_theme_color(self.app_state.local_config, "hover")
        text = get_theme_color(self.app_state.local_config, "main_text")
        radius = get_border_radius(self.app_state.local_config)
        card.setStyleSheet(
            card.styleSheet()
            + f"""
QPushButton#cardButton {{
    background-color: {button};
    color: {text};
    border: 2px solid {border};
    border-radius: {radius}px;
    min-width: {button_width}px;
    min-height: {button_height}px;
    font-size: {button_font_size}px;
}}
QPushButton#cardButton:hover {{
    background-color: {hover};
}}
QPushButton#cardButtonDownload {{
    background-color: #4CAF50;
    color: {text};
    border: 2px solid {border};
    border-radius: {radius}px;
    min-width: {button_width}px;
    min-height: {button_height}px;
    font-size: {button_font_size}px;
}}
QPushButton#cardButtonDownload:hover {{
    background-color: #5cb85c;
}}
QPushButton#cardButtonUninstall {{
    background-color: #d68b2a;
}}
QPushButton#cardButtonUninstall:hover {{
    background-color: #e29c3f;
}}
QPushButton#cardButtonDownload:disabled,
QPushButton#cardButton:disabled,
QPushButton#cardButtonUninstall:disabled {{
    background-color: #3b3b3b;
    color: #808080;
    border-color: #808080;
}}
"""
        )
        scale = get_card_layout_scale(self.app_state.local_config)
        margin = max(8, round(10 * scale))
        spacing = max(10, round(15 * scale))
        icon_size = max(64, round(80 * scale))
        card_height = max(120, round(120 * scale))

        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(spacing)
        icon_label.setFixedSize(icon_size, icon_size)
        card.setMinimumHeight(card_height)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        icon_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        card.mouseDoubleClickEvent = lambda event, widget=card: (
            self.show_plugin_details(widget.property("plugin_id"))
            if event.button() == Qt.MouseButton.LeftButton
            and widget.property("plugin_id")
            else None
        )
        return card, icon_label, body, actions

    @staticmethod
    def _entry_api_compatible(entry) -> bool:
        return bool(entry and is_version_compatible(PLUGIN_API_VERSION, entry.api_version))

    def _action_button(self, text: str, role: str, callback, enabled: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(role)
        button.clicked.connect(callback)
        button.setEnabled(enabled)
        return button

    def _card_header(
        self,
        title: str,
        version: str,
        author: str,
        badge: str = "",
        badge_tooltip: str = "",
        badge_color: str = "",
    ):
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        text_layout = QVBoxLayout()
        name_label = QLabel(title)
        name_label.setObjectName("primaryText")
        name_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        meta = QLabel(f"{author}  |  {version}".strip(" |"))
        meta.setObjectName("secondaryText")
        meta_color = get_theme_color(self.app_state.local_config, "secondary_text")
        meta.setStyleSheet(f"font-size: 13px; color: {meta_color};")
        text_layout.addWidget(name_label)
        text_layout.addWidget(meta)
        layout.addLayout(text_layout, 1)
        if badge:
            badge_label = QLabel(badge)
            badge_label.setObjectName("secondaryText")
            badge_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            badge_label.setStyleSheet(f"font-size: 13px; color: {meta_color};")
            if badge_tooltip:
                badge_label.setToolTip(badge_tooltip)
            if badge_color:
                badge_label.setStyleSheet(f"color: {badge_color}; font-size: 13px;")
            layout.addWidget(badge_label)
        return header

    def _set_local_icon(self, icon_label: QLabel, path: str) -> None:
        if path and path.strip():
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                icon_size = icon_label.width()
                icon_label.setPixmap(
                    pixmap.scaled(
                        icon_size,
                        icon_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def _build_catalog_card(self, entry):
        card, icon_label, body, actions = self._build_card_shell()
        card.setProperty("plugin_id", entry.id)
        if entry.icon:
            load_mod_icon_universal(icon_label, entry, size=icon_label.width())
        body.addWidget(self._card_header(entry.name, entry.version, entry.author))
        description = QLabel(entry.description)
        description.setObjectName("secondaryText")
        secondary_color = get_theme_color(self.app_state.local_config, "secondary_text")
        description.setStyleSheet(
            f"color: {secondary_color}; font-size: 12px;"
        )
        description.setWordWrap(True)
        description.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        body.addWidget(description)

        is_compatible = self._entry_api_compatible(entry)

        if not is_compatible:
            warning = QLabel(
                tr(
                    "plugins.incompatible_api_warning",
                    required_version=entry.api_version,
                    current_version=PLUGIN_API_VERSION,
                )
            )
            warning.setObjectName("warningText")
            warning_color = get_theme_color(self.app_state.local_config, "warning")
            warning.setStyleSheet(
                f"color: {warning_color}; font-size: 11px; font-style: italic;"
            )
            warning.setWordWrap(True)
            warning.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            body.addWidget(warning)

        download_button = self._action_button(
            tr("plugins.action_download"),
            "cardButtonDownload",
            lambda: self.download_plugin(entry),
            enabled=bool(entry.download_link and is_compatible),
        )
        self._download_buttons[entry.id] = download_button
        self._apply_download_button_state(download_button, entry, is_compatible)
        actions.addWidget(download_button)
        if entry.homepage:
            actions.addWidget(
                self._action_button(
                    tr("plugins.action_details"),
                    "cardButton",
                    lambda: QDesktopServices.openUrl(QUrl(entry.homepage)),
                )
            )
        return card

    def _build_installed_card(self, plugin):
        card, icon_label, body, actions = self._build_card_shell()
        card.setProperty("plugin_id", plugin.plugin_id)
        body.addWidget(
            self._card_header(
                _resolve_text(
                    plugin.manifest.name if plugin.manifest else plugin.plugin_id
                ),
                plugin.manifest.version if plugin.manifest else "",
                plugin.manifest.author if plugin.manifest else "",
                "",
                "",
                "",
            )
        )
        if plugin.manifest and plugin.manifest.icon:
            try:
                self._set_local_icon(
                    icon_label, resolve_plugin_path(plugin.path, plugin.manifest.icon)
                )
            except Exception as exc:
                logger.debug(
                    "PluginsController: failed to load icon for %s: %s",
                    plugin.plugin_id,
                    exc,
                    exc_info=True,
                )
        description = QLabel(
            _resolve_text(plugin.manifest.description if plugin.manifest else plugin.error)
        )
        description.setObjectName("secondaryText")
        secondary_color = get_theme_color(self.app_state.local_config, "secondary_text")
        description.setStyleSheet(
            f"color: {secondary_color}; font-size: 12px;"
        )
        description.setWordWrap(True)
        description.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        body.addWidget(description)

        if plugin.is_local:
            badge_text = tr("plugins.badge_local")
            badge_label = QLabel(badge_text)
            badge_label.setObjectName("secondaryText")
            badge_label.setStyleSheet(
                f"color: {secondary_color}; font-size: 12px;"
            )
            badge_label.setToolTip(tr("plugins.badge_local_tooltip"))
            body.addWidget(badge_label)

        actions.addWidget(
            self._action_button(
                tr("plugins.action_disable" if plugin.enabled else "plugins.action_enable"),
                "cardButtonUninstall" if plugin.enabled else "cardButtonDownload",
                lambda: self.toggle_plugin(plugin.plugin_id),
            )
        )
        actions.addWidget(
            self._action_button(
                tr("plugins.action_details"),
                "cardButton",
                lambda: self.show_plugin_details(plugin.plugin_id),
            )
        )
        return card

    def download_plugin(self, entry) -> None:
        if not entry.download_link:
            return
        self.downloads_manager.enqueue_with_feedback(
            self.feedback_service,
            display_name=entry.name,
            source_kind=SourceKind.EXTERNAL_URL,
            target_kind=TargetKind.PLUGIN,
            source_url=entry.download_link,
            canonical_key=f"plugin:{entry.id}:{entry.version}",
            metadata={
                "plugin_id": entry.id,
                "catalog_plugin_version": entry.version,
                "source": "catalog",
                "homepage": entry.homepage,
                "file_name": f"{entry.id}.zip",
            },
        )
        self._refresh_download_button_state(entry.id)

    def import_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        imported = False
        for path in paths:
            try:
                self.plugin_install_service.install_path(path, source="manual")
                imported = True
            except Exception as e:
                logger.error("PluginsController: import failed for %s: %s", path, e, exc_info=True)
                self.feedback_service.show_message("error", "errors.error", str(e))
        if imported:
            self.refresh_main_tabs()
            self.render()

    def toggle_plugin(self, plugin_id: str) -> None:
        plugin = self.plugin_runtime_service.get_plugin(plugin_id)
        if not plugin:
            return
        if plugin.enabled:
            self.plugin_runtime_service.disable_plugin(plugin_id)
        else:
            success, error = self.plugin_runtime_service.enable_plugin(plugin_id)
            if not success:
                self.feedback_service.show_message(
                    "error",
                    "errors.error",
                    error or tr("plugins.enable_failed"),
                )
        self.refresh_main_tabs()
        self.render()

    def show_plugin_details(self, plugin_id: str) -> None:
        plugin = self.plugin_runtime_service.get_plugin(plugin_id)
        if not plugin:
            return
        dialog = PluginDetailsDialog(
            plugin,
            self.plugin_runtime_service,
            self.plugin_state_service,
            self.app_state,
            can_update=bool(
                plugin.update_available
                and plugin.catalog_entry
                and self._entry_api_compatible(plugin.catalog_entry)
                and not plugin.is_local
            ),
            on_update=self.update_plugin,
            on_delete=self.delete_plugin,
            parent=self.app,
        )
        dialog.exec()
        self.render()

    def update_plugin(self, plugin_id: str) -> None:
        plugin = self.plugin_runtime_service.get_plugin(plugin_id)
        entry = plugin.catalog_entry if plugin else None
        if not entry or not self._entry_api_compatible(entry):
            return
        self.download_plugin(entry)

    def delete_plugin(self, plugin_id: str) -> None:
        try:
            self.plugin_install_service.delete_plugin(plugin_id)
        except Exception as e:
            logger.error("PluginsController: delete failed for %s: %s", plugin_id, e, exc_info=True)
            self.feedback_service.show_message("error", "errors.error", str(e))
        self.refresh_main_tabs()
        self.render()

    def _apply_list_style(self) -> None:
        if not hasattr(self.app, "plugins_container"):
            return
        border = get_theme_color(self.app_state.local_config, "border")
        background = get_theme_color(self.app_state.local_config, "background")
        radius = get_border_radius(self.app_state.local_config)
        self.app.plugins_container.setStyleSheet(
            f"QFrame#plugins_settings_container {{"
            f"background-color: {background};"
            f"border: 2px solid {border};"
            f"border-radius: {radius}px;"
            f"}}"
            "QScrollArea { background: transparent; }"
            "QWidget { background: transparent; }"
        )

    def _get_plugin_download_record(self, plugin_id: str):
        for record in reversed(list(getattr(self.downloads_manager, "records", []))):
            if getattr(record, "target_kind", None) != TargetKind.PLUGIN:
                continue
            metadata = getattr(record, "metadata", None) or {}
            if str(metadata.get("plugin_id", "")).strip() == plugin_id:
                return record
        return None

    @staticmethod
    def _is_plugin_download_busy(record) -> bool:
        if not record:
            return False
        return getattr(record, "effective_status_key", "") in {
            "downloading",
            "installing",
        }

    def _download_button_text(self, record) -> str:
        if not record:
            return tr("plugins.action_download")
        effective_status = getattr(record, "effective_status_key", "")
        if effective_status == "downloading":
            progress = max(0, min(100, int(getattr(record, "progress", 0) or 0)))
            return tr("downloads.status_downloading", progress=progress)
        if effective_status == "installing":
            return tr("downloads.status_installing")
        return tr("plugins.action_download")

    def _apply_download_button_state(
        self, button: QPushButton, entry, is_compatible: bool
    ) -> None:
        record = self._get_plugin_download_record(entry.id)
        button.setText(self._download_button_text(record))
        button.setEnabled(
            bool(
                entry.download_link
                and is_compatible
                and not self._is_plugin_download_busy(record)
            )
        )

    def _refresh_download_button_state(self, plugin_id: str) -> None:
        button = self._download_buttons.get(plugin_id)
        if not button:
            return
        entry = self.plugin_catalog_service.get_entry(plugin_id, load_if_needed=False)
        if not entry:
            return
        self._apply_download_button_state(
            button, entry, self._entry_api_compatible(entry)
        )

    def _start_catalog_load(self) -> None:
        if self._catalog_worker and self._catalog_worker.isRunning():
            return
        self._catalog_worker = _PluginCatalogWorker(self.plugin_catalog_service)
        self._catalog_worker.loaded.connect(self._on_catalog_loaded)
        self._catalog_worker.finished.connect(self._clear_catalog_worker)
        self._catalog_worker.start()

    def _on_catalog_loaded(self) -> None:
        self.plugin_runtime_service.scan_installed_plugins(resolve_catalog=True)
        if self._loaded:
            self.render()

    def _clear_catalog_worker(self) -> None:
        """Clean up the catalog worker safely."""
        if self._catalog_worker is not None:
            try:
                self._catalog_worker.loaded.disconnect()
                self._catalog_worker.finished.disconnect()
            except (TypeError, RuntimeError):
                pass

            worker = self._catalog_worker
            self._catalog_worker = None

            if worker.isRunning():
                worker.quit()
                worker.wait(1000)

            worker.deleteLater()

    def shutdown(self) -> None:
        """Explicit cleanup method for deterministic shutdown."""
        self._clear_catalog_worker()

    def refresh_main_tabs(self) -> None:
        if not hasattr(self.app, "main_tab_widget"):
            return
        tab_widget = self.app.main_tab_widget
        for plugin_id in list(self._plugin_tab_ids):
            widget = getattr(self.app, f"_plugin_tab_{plugin_id}", None)
            if widget is None:
                continue
            index = tab_widget.indexOf(widget)
            if index >= 0:
                tab_widget.removeTab(index)
            widget.deleteLater()
            delattr(self.app, f"_plugin_tab_{plugin_id}")
        self._plugin_tab_ids.clear()
        for plugin in self.plugin_runtime_service.list_installed_plugins():
            if (
                not plugin.enabled
                or not plugin.manifest
                or "main_view" not in plugin.manifest.hooks
            ):
                continue
            widget = self.plugin_runtime_service.get_main_widget(
                plugin.plugin_id, tab_widget
            )
            if widget is None:
                continue
            setattr(self.app, f"_plugin_tab_{plugin.plugin_id}", widget)
            tab_widget.addTab(widget, _resolve_text(plugin.manifest.name))
            self._plugin_tab_ids.append(plugin.plugin_id)
