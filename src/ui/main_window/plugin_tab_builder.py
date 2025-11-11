from typing import Dict, Any
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QScrollArea, QSizePolicy
from managers.localization_manager import tr
from ui.common.styling import get_theme_color


class _ZeroHintWidget(QWidget):

    def sizeHint(self) -> QSize:
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class PluginTabBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        controls_layout = QHBoxLayout()
        controls_layout.addStretch()
        search_button = QPushButton(tr('plugins.search_plugins'))
        search_button.setObjectName('searchPluginsButton')
        controls_layout.addWidget(search_button)
        controls_layout.addSpacing(20)
        import_button = QPushButton(tr('plugins.import_plugins'))
        import_button.setObjectName('importPluginsButton')
        controls_layout.addWidget(import_button)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        plugins_container = QWidget()
        plugins_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        plugins_container.setObjectName('plugins_background')
        plugins_container_layout = QVBoxLayout(plugins_container)
        plugins_container_layout.setContentsMargins(15, 15, 15, 15)
        plugins_container_layout.setSpacing(10)
        installed_plugins_label = QLabel(tr('plugins.installed_plugins'))
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        installed_plugins_label.setStyleSheet(f'font-weight: bold; font-size: 16px; color: {text_color};')
        installed_plugins_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plugins_container_layout.addWidget(installed_plugins_label)
        plugins_scroll = QScrollArea()
        plugins_scroll.setWidgetResizable(True)
        plugins_scroll.setFrameShape(QFrame.Shape.NoFrame)
        plugins_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        from PyQt6.QtWidgets import QAbstractScrollArea
        plugins_scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        plugins_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        plugins_widget = _ZeroHintWidget()
        plugins_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        plugins_layout = QVBoxLayout(plugins_widget)
        plugins_layout.addStretch()
        plugins_layout.setContentsMargins(0, 0, 0, 0)
        plugins_scroll.setWidget(plugins_widget)
        plugins_container_layout.addWidget(plugins_scroll)
        try:
            plugins_container_layout.setStretch(0, 0)
            plugins_container_layout.setStretch(1, 1)
        except Exception:
            pass
        plugins_bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        if plugins_bg_color.startswith('#'):
            r = int(plugins_bg_color[1:3], 16)
            g = int(plugins_bg_color[3:5], 16)
            b = int(plugins_bg_color[5:7], 16)
            plugins_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            plugins_bg_rgba = 'rgba(0, 0, 0, 128)'
        plugins_container.setStyleSheet(f'\n            QWidget#plugins_background {{\n                background-color: {plugins_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        layout.addWidget(plugins_container)
        try:
            layout.setStretch(0, 0)
            layout.setStretch(1, 1)
        except Exception:
            pass
        self.widgets['search_button'] = search_button
        self.widgets['import_button'] = import_button
        self.widgets['plugins_container'] = plugins_container
        self.widgets['plugins_scroll'] = plugins_scroll
        self.widgets['plugins_widget'] = plugins_widget
        self.widgets['plugins_layout'] = plugins_layout
        self.widgets['installed_plugins_label'] = installed_plugins_label
        return widget

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
