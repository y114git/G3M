from typing import Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QComboBox, QScrollArea, QSizePolicy
from managers.localization_manager import tr
from ui.widgets.common.custom_controls import NoScrollComboBox, _ZeroHintWidget
from ui.common.styling import get_theme_color


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
        import_export_button = QPushButton(tr('ui.import_export_mod'))
        import_export_button.setObjectName('import_export_button')
        controls_layout.addWidget(import_export_button)
        controls_layout.addSpacing(20)
        game_type_combo = QComboBox()
        game_type_combo.addItem('DELTARUNE', 'deltarune')
        game_type_combo.addItem('DELTARUNE DEMO', 'deltarunedemo')
        game_type_combo.addItem('UNDERTALE', 'undertale')
        game_type_combo.addItem('UNDERTALE Yellow', 'undertaleyellow')
        controls_layout.addWidget(game_type_combo)
        controls_layout.addSpacing(20)
        chapter_mode_checkbox = QCheckBox(tr('ui.chapter_mode'))
        controls_layout.addWidget(chapter_mode_checkbox)
        full_install_checkbox = QCheckBox(tr('ui.full_install'))
        controls_layout.addWidget(full_install_checkbox)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        chapter_tabs_widget = QWidget()
        chapter_tabs_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        chapter_tabs_layout = QHBoxLayout(chapter_tabs_widget)
        chapter_tabs_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chapter_tabs_layout.setContentsMargins(20, 10, 20, 10)
        chapter_tabs_layout.setSpacing(10)
        chapter_tabs_layout.addStretch()
        chapter_tabs_widget.setObjectName('chapter_tabs_container')
        chapter_tab_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
        chapter_tab_buttons = []
        for i, chapter_name in enumerate(chapter_tab_names):
            chapter_btn = QPushButton(chapter_name)
            chapter_btn.setCheckable(True)
            chapter_btn.setObjectName(f'chapter_tab_{i}')
            chapter_btn.setFixedHeight(40)
            chapter_btn.setMinimumWidth(100)
            text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
            chapter_btn.setStyleSheet(f'\n                QPushButton#chapter_tab_{i} {{\n                    background-color: {button_color};\n                    border: 2px solid {border_color};\n                    color: {text_color};\n                    font-weight: bold;\n                    font-size: 13px;\n                    border-radius: 0px;\n                    padding: 5px;\n                }}\n                QPushButton#chapter_tab_{i}:checked {{\n                    background-color: {hover_color};\n                    border: 3px solid {border_color};\n                }}\n                QPushButton#chapter_tab_{i}:hover {{\n                    background-color: {hover_color};\n                }}\n            ')
            chapter_tabs_layout.addWidget(chapter_btn)
            chapter_tab_buttons.append(chapter_btn)
        chapter_tabs_layout.addStretch()
        chapter_tabs_widget.setVisible(False)
        layout.addWidget(chapter_tabs_widget)
        priority_button = QPushButton(tr('ui.priority'))
        priority_button.setObjectName('priority_button')
        priority_button.setVisible(False)
        priority_button.setFixedSize(175, 35)
        self._update_priority_button_style(priority_button, button_color, border_color, hover_color)
        create_modpack_button = QPushButton(tr('ui.create_modpack_button'))
        create_modpack_button.setObjectName('create_modpack_button')
        create_modpack_button.setVisible(False)
        create_modpack_button.setFixedSize(175, 35)
        self._update_priority_button_style(create_modpack_button, button_color, border_color, hover_color)
        priority_button_container = QWidget()
        priority_button_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        priority_button_layout = QHBoxLayout(priority_button_container)
        priority_button_layout.setContentsMargins(0, 0, 0, 0)
        priority_button_layout.setSpacing(10)
        priority_button_layout.addStretch()
        priority_button_layout.addWidget(priority_button)
        priority_button_layout.addWidget(create_modpack_button)
        fast_merging_label = QLabel(tr('ui.fast_merging'))
        fast_merging_label.setToolTip(tr('ui.fast_merging_tooltip'))
        fast_merging_checkbox = QCheckBox()
        fast_merging_checkbox.setObjectName('fast_merging_checkbox')
        fast_merging_checkbox.setToolTip(tr('ui.fast_merging_tooltip'))
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        fast_merging_label.setStyleSheet(f'color: {text_color};')
        fast_merging_checkbox.setStyleSheet(f'\n            QCheckBox {{\n                spacing: 0px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        ')
        priority_button_layout.addWidget(fast_merging_label)
        priority_button_layout.addWidget(fast_merging_checkbox)
        priority_button_layout.addStretch()
        priority_button_container.setFixedHeight(0)
        layout.addWidget(priority_button_container)
        self.widgets['priority_button_layout'] = priority_button_layout
        self.widgets['priority_button_container'] = priority_button_container
        self.widgets['create_modpack_button'] = create_modpack_button
        self.widgets['fast_merging_checkbox'] = fast_merging_checkbox
        self.widgets['fast_merging_label'] = fast_merging_label
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
        self.widgets['installed_mods_label'] = installed_mods_label
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
        self.widgets['import_export_button'] = import_export_button
        self.widgets['game_type_combo'] = game_type_combo
        self.widgets['chapter_mode_checkbox'] = chapter_mode_checkbox
        self.widgets['full_install_checkbox'] = full_install_checkbox
        self.widgets['chapter_tabs_widget'] = chapter_tabs_widget
        self.widgets['chapter_tabs_layout'] = chapter_tabs_layout
        self.widgets['chapter_tab_buttons'] = chapter_tab_buttons
        self.widgets['installed_mods_container'] = installed_mods_container
        self.widgets['installed_mods_scroll'] = installed_mods_scroll
        self.widgets['installed_mods_widget'] = installed_mods_widget
        self.widgets['installed_mods_layout'] = installed_mods_layout
        self.widgets['priority_button'] = priority_button
        self.widgets['priority_button_layout'] = priority_button_layout
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
        library_tag_textedit = QCheckBox(tr('tags.textedit'))
        library_tag_customization = QCheckBox(tr('tags.customization'))
        library_tag_gameplay = QCheckBox(tr('tags.gameplay'))
        library_tag_other = QCheckBox(tr('tags.other'))
        library_tag_local = QCheckBox(tr('tags.local'))
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        tag_style = f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: 12px;\n                spacing: 5px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        '
        library_tag_widgets = [library_tag_textedit, library_tag_customization, library_tag_gameplay, library_tag_other, library_tag_local]
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
        self.widgets['library_tag_textedit'] = library_tag_textedit
        self.widgets['library_tag_customization'] = library_tag_customization
        self.widgets['library_tag_gameplay'] = library_tag_gameplay
        self.widgets['library_tag_other'] = library_tag_other
        self.widgets['library_tag_local'] = library_tag_local
        self.widgets['library_tag_widgets'] = library_tag_widgets
        self.widgets['library_search_button'] = library_search_button
        return filters_widget

    def _update_priority_button_style(self, button, button_color, border_color, hover_color):
        button_obj_name = button.objectName()
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        button.setStyleSheet(f'\n            QPushButton#{button_obj_name} {{\n                background-color: {button_color};\n                border: 2px solid {border_color};\n                color: {text_color};\n                font-weight: bold;\n                font-size: 13px;\n                border-radius: 0px;\n                padding: 5px;\n            }}\n            QPushButton#{button_obj_name}:hover {{\n                background-color: {hover_color};\n            }}\n        ')

    def update_priority_button_style(self):
        border_color = get_theme_color(self.app_state.local_config, 'border', 'white')
        button_color = get_theme_color(self.app_state.local_config, 'button', 'black')
        hover_color = get_theme_color(self.app_state.local_config, 'button_hover', '#333')
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        if 'priority_button' in self.widgets:
            button = self.widgets['priority_button']
            self._update_priority_button_style(button, button_color, border_color, hover_color)
        if 'create_modpack_button' in self.widgets:
            button = self.widgets['create_modpack_button']
            self._update_priority_button_style(button, button_color, border_color, hover_color)
        if 'fast_merging_label' in self.widgets:
            fast_merging_label = self.widgets['fast_merging_label']
            fast_merging_label.setStyleSheet(f'color: {text_color};')
        if 'library_tags_label' in self.widgets:
            library_tags_label = self.widgets['library_tags_label']
            library_tags_label.setStyleSheet(f'color: {text_color};')

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
