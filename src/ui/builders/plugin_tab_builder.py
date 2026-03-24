from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.localization_service import tr
from ui.common.styling import (
    get_theme_color,
    install_panel_style_handler,
    install_scroll_viewport_clip,
    set_layout_stretch_factors,
)


class PluginTabBuilder:
    """Builds the plugin tab UI for displaying installed plugins."""

    def __init__(self, app_state, parent=None) -> None:
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def build(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        controls_layout = QHBoxLayout()
        controls_layout.addStretch()
        search_button = QPushButton(tr("plugins.search_plugins"))
        search_button.setObjectName("searchPluginsButton")
        controls_layout.addWidget(search_button)
        controls_layout.addSpacing(20)
        import_button = QPushButton(tr("plugins.import_plugins"))
        import_button.setObjectName("importPluginsButton")
        controls_layout.addWidget(import_button)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        plugins_container = QWidget(widget)
        plugins_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        plugins_container.setObjectName("plugins_background")
        plugins_container_layout = QVBoxLayout(plugins_container)
        plugins_container_layout.setContentsMargins(15, 15, 15, 15)
        plugins_container_layout.setSpacing(10)
        text_color = get_theme_color(self.app_state.local_config, "text")
        installed_plugins_label = QLabel(tr("plugins.installed_plugins"))
        installed_plugins_label.setStyleSheet(
            f"font-weight: bold; font-size: 16px; color: {text_color};"
        )
        installed_plugins_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plugins_container_layout.addWidget(installed_plugins_label)
        plugins_scroll = QScrollArea(plugins_container)
        plugins_scroll.setWidgetResizable(True)
        plugins_scroll.setFrameShape(QFrame.Shape.NoFrame)
        plugins_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plugins_scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        plugins_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        plugins_widget = QWidget(plugins_scroll)
        plugins_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        plugins_layout = QVBoxLayout(plugins_widget)
        plugins_layout.addStretch()
        plugins_layout.setContentsMargins(0, 0, 0, 0)
        plugins_scroll.setWidget(plugins_widget)
        plugins_container_layout.addWidget(plugins_scroll)
        container_padding = 15
        install_scroll_viewport_clip(
            plugins_scroll,
            plugins_container,
            self.app_state.local_config,
            inset=container_padding,
            attr_name="_plugins_viewport_clip_filter",
        )
        set_layout_stretch_factors(plugins_container_layout, 0, 1)
        install_panel_style_handler(
            plugins_container,
            self.app_state.local_config,
            attr_name="_plugins_panel_style_filter",
        )
        layout.addWidget(plugins_container)
        set_layout_stretch_factors(layout, 0, 1)
        self.widgets = {
            "search_button": search_button,
            "import_button": import_button,
            "plugins_container": plugins_container,
            "plugins_scroll": plugins_scroll,
            "plugins_widget": plugins_widget,
            "plugins_layout": plugins_layout,
            "installed_plugins_label": installed_plugins_label,
        }
        return widget

    def get_widgets(self) -> dict[str, Any]:
        return self.widgets
