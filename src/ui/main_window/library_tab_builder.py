from typing import Dict, Any
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QComboBox, QScrollArea, QSizePolicy
from managers.localization_manager import tr
from ui.widgets.common.custom_controls import NoScrollComboBox
from ui.common.styling import get_theme_color


class _ZeroHintWidget(QWidget):

    def sizeHint(self) -> QSize:
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class LibraryTabBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        library_filters_widget = self._create_library_filters_widget()
        hide_filters = self.app_state.local_config.get('hide_library_filters', False)
        library_filters_widget.setVisible(not hide_filters)
        layout.addWidget(library_filters_widget)
        controls_layout = QHBoxLayout()
        controls_layout.addStretch()
        game_type_combo = QComboBox()
        game_type_combo.addItem('DELTARUNE', 'deltarune')
        game_type_combo.addItem('DELTARUNE DEMO', 'deltarunedemo')
        game_type_combo.addItem('UNDERTALE', 'undertale')
        controls_layout.addWidget(game_type_combo)
        controls_layout.addSpacing(20)
        chapter_mode_checkbox = QCheckBox(tr('ui.chapter_mode'))
        controls_layout.addWidget(chapter_mode_checkbox)
        full_install_checkbox = QCheckBox(tr('ui.full_install'))
        controls_layout.addWidget(full_install_checkbox)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        slots_container = QWidget()
        slots_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        slots_layout = QVBoxLayout(slots_container)
        active_slots_widget = QWidget()
        active_slots_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        active_slots_widget.setObjectName('slots_background')
        active_slots_layout = QHBoxLayout(active_slots_widget)
        active_slots_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        active_slots_layout.setContentsMargins(20, 15, 20, 15)
        active_slots_layout.setSpacing(0)
        slots_bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        if slots_bg_color.startswith('#'):
            r = int(slots_bg_color[1:3], 16)
            g = int(slots_bg_color[3:5], 16)
            b = int(slots_bg_color[5:7], 16)
            slots_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            slots_bg_rgba = 'rgba(0, 0, 0, 128)'
        active_slots_widget.setStyleSheet(f'\n            QWidget#slots_background {{\n                background-color: {slots_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        slots_layout.addWidget(active_slots_widget)
        layout.addWidget(slots_container)
        installed_mods_container = QWidget()
        installed_mods_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        installed_mods_container.setObjectName('mods_background')
        mods_container_layout = QVBoxLayout(installed_mods_container)
        mods_container_layout.setContentsMargins(15, 15, 15, 15)
        mods_container_layout.setSpacing(10)
        installed_mods_label = QLabel(tr('ui.installed_mods_label'))
        installed_mods_label.setStyleSheet('font-weight: bold; font-size: 16px;')
        installed_mods_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mods_container_layout.addWidget(installed_mods_label)
        installed_mods_scroll = QScrollArea()
        installed_mods_scroll.setWidgetResizable(True)
        installed_mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        installed_mods_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        from PyQt6.QtWidgets import QAbstractScrollArea
        installed_mods_scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        installed_mods_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        installed_mods_widget = _ZeroHintWidget()
        installed_mods_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        installed_mods_layout = QVBoxLayout(installed_mods_widget)
        installed_mods_layout.addStretch()
        installed_mods_layout.setContentsMargins(0, 0, 0, 0)
        installed_mods_scroll.setWidget(installed_mods_widget)
        mods_container_layout.addWidget(installed_mods_scroll)
        try:
            mods_container_layout.setStretch(0, 0)
            mods_container_layout.setStretch(1, 1)
        except Exception:
            pass
        mods_bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        if mods_bg_color.startswith('#'):
            r = int(mods_bg_color[1:3], 16)
            g = int(mods_bg_color[3:5], 16)
            b = int(mods_bg_color[5:7], 16)
            mods_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        else:
            mods_bg_rgba = 'rgba(0, 0, 0, 128)'
        installed_mods_container.setStyleSheet(f'\n            QWidget#mods_background {{\n                background-color: {mods_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        layout.addWidget(installed_mods_container)
        try:
            layout.setStretch(0, 0)
            layout.setStretch(1, 0)
            layout.setStretch(2, 0)
            layout.setStretch(3, 1)
        except Exception:
            pass
        self.widgets['library_filters_widget'] = library_filters_widget
        self.widgets['game_type_combo'] = game_type_combo
        self.widgets['chapter_mode_checkbox'] = chapter_mode_checkbox
        self.widgets['full_install_checkbox'] = full_install_checkbox
        self.widgets['slots_container'] = slots_container
        self.widgets['slots_layout'] = slots_layout
        self.widgets['active_slots_widget'] = active_slots_widget
        self.widgets['active_slots_layout'] = active_slots_layout
        self.widgets['installed_mods_container'] = installed_mods_container
        self.widgets['installed_mods_scroll'] = installed_mods_scroll
        self.widgets['installed_mods_widget'] = installed_mods_widget
        self.widgets['installed_mods_layout'] = installed_mods_layout
        return widget

    def _create_library_filters_widget(self) -> QFrame:
        filters_widget = QFrame()
        filters_widget.setObjectName('filters')
        filters_widget.setFixedHeight(55)
        filters_layout = QHBoxLayout(filters_widget)
        filters_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        library_sort_combo = NoScrollComboBox()
        library_sort_combo.addItems([tr('ui.sort_by_name'), tr('ui.sort_by_date')])
        filters_layout.addWidget(library_sort_combo)
        library_sort_order_btn = QPushButton('▼')
        library_sort_order_btn.setObjectName('sortOrderBtn')
        library_sort_order_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        library_sort_order_btn.setToolTip(tr('ui.sort_direction_tooltip'))
        filters_layout.addWidget(library_sort_order_btn)
        filters_layout.addSpacing(20)
        library_tags_label = QLabel(tr('ui.tags_label'))
        filters_layout.addWidget(library_tags_label)
        library_tag_translation = QCheckBox(tr('tags.translation'))
        library_tag_customization = QCheckBox(tr('tags.customization'))
        library_tag_gameplay = QCheckBox(tr('tags.gameplay'))
        library_tag_other = QCheckBox(tr('tags.other'))
        library_tag_local = QCheckBox(tr('tags.local'))
        tag_style = '\n            QCheckBox {\n                color: white;\n                font-size: 12px;\n                spacing: 5px;\n            }\n            QCheckBox::indicator {\n                width: 16px;\n                height: 16px;\n            }\n        '
        library_tag_widgets = [library_tag_translation, library_tag_customization, library_tag_gameplay, library_tag_other, library_tag_local]
        for tag in library_tag_widgets:
            tag.setStyleSheet(tag_style)
            filters_layout.addWidget(tag)
        filters_layout.addStretch()
        library_search_button = QPushButton('🔍')
        library_search_button.setObjectName('searchBtn')
        library_search_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        library_search_button.setFixedSize(35, 35)
        library_search_button.setToolTip(tr('ui.search_placeholder'))
        filters_layout.addWidget(library_search_button)
        self.widgets['library_sort_combo'] = library_sort_combo
        self.widgets['library_sort_order_btn'] = library_sort_order_btn
        self.widgets['library_tags_label'] = library_tags_label
        self.widgets['library_tag_translation'] = library_tag_translation
        self.widgets['library_tag_customization'] = library_tag_customization
        self.widgets['library_tag_gameplay'] = library_tag_gameplay
        self.widgets['library_tag_other'] = library_tag_other
        self.widgets['library_tag_local'] = library_tag_local
        self.widgets['library_tag_widgets'] = library_tag_widgets
        self.widgets['library_search_button'] = library_search_button
        return filters_widget

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
