from typing import Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QComboBox, QScrollArea, QSizePolicy, QSpinBox
from managers.localization_manager import tr
from ui.widgets.common.custom_controls import NoScrollComboBox
from ui.common.styling import get_theme_color


class SearchTabBuilder:

    def __init__(self, app_state, parent=None):
        self.app_state = app_state
        self.parent = parent
        self.widgets = {}

    def build(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        filters_widget = self._create_filters_widget()
        layout.addWidget(filters_widget)
        search_container = QWidget()
        search_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        search_container.setObjectName('search_mods_background')
        search_container_layout = QVBoxLayout(search_container)
        search_container_layout.setContentsMargins(10, 10, 10, 10)
        search_container_layout.setSpacing(10)
        search_mods_scroll = QScrollArea()
        search_mods_scroll.setWidgetResizable(True)
        search_mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        search_mods_scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        mod_list_widget = QWidget()
        mod_list_layout = QVBoxLayout(mod_list_widget)
        mod_list_layout.setSpacing(15)
        mod_list_layout.addStretch()
        search_mods_scroll.setWidget(mod_list_widget)
        search_container_layout.addWidget(search_mods_scroll)
        pagination_widget = self._create_pagination_widget()
        search_container_layout.addWidget(pagination_widget)
        search_bg_color = get_theme_color(self.app_state.local_config, 'background', '#000000')
        r, g, b = (int(search_bg_color[1:3], 16), int(search_bg_color[3:5], 16), int(search_bg_color[5:7], 16)) if search_bg_color.startswith('#') else (0, 0, 0)
        search_bg_rgba = f'rgba({r}, {g}, {b}, 128)'
        search_container.setStyleSheet(f'\n            QWidget#search_mods_background {{\n                background-color: {search_bg_rgba};\n                border-radius: 10px;\n                margin: 5px;\n            }}\n        ')
        layout.addWidget(search_container)
        self.widgets['search_container'] = search_container
        self.widgets['search_mods_scroll'] = search_mods_scroll
        self.widgets['mod_list_widget'] = mod_list_widget
        self.widgets['mod_list_layout'] = mod_list_layout
        return widget

    def _create_filters_widget(self) -> QFrame:
        filters_widget = QFrame()
        filters_widget.setObjectName('filters')
        filters_widget.setFixedHeight(55)
        filters_layout = QHBoxLayout(filters_widget)
        filters_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        sort_combo = NoScrollComboBox()
        sort_combo.addItems([tr('ui.sort_by_downloads'), tr('ui.sort_by_update_date'), tr('ui.sort_by_creation_date')])
        saved_sort_index = self.app_state.local_config.get('search_sort_index', 1)
        if 0 <= saved_sort_index < sort_combo.count():
            sort_combo.setCurrentIndex(saved_sort_index)
        else:
            sort_combo.setCurrentIndex(1)
        filters_layout.addWidget(sort_combo)
        sort_order_btn = QPushButton('▼')
        sort_order_btn.setObjectName('sortOrderBtn')
        sort_order_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sort_order_btn.setToolTip(tr('ui.sort_direction_tooltip'))
        filters_layout.addWidget(sort_order_btn)
        filters_layout.addSpacing(20)
        modgame_combo = QComboBox()
        modgame_combo.addItem(tr('ui.deltarune'), 'deltarune')
        modgame_combo.addItem(tr('ui.deltarunedemo'), 'deltarunedemo')
        modgame_combo.addItem(tr('ui.undertale'), 'undertale')
        modgame_combo.addItem(tr('ui.undertaleyellow'), 'undertaleyellow')
        modgame_combo.addItem(tr('ui.pizzatower'), 'pizzatower')
        modgame_combo.addItem(tr('ui.sugaryspire'), 'sugaryspire')
        saved_game = self.app_state.local_config.get('selected_search_game', 'deltarune')
        game_index = modgame_combo.findData(saved_game)
        if game_index >= 0:
            modgame_combo.setCurrentIndex(game_index)
        else:
            modgame_combo.setCurrentIndex(0)
        filters_layout.addWidget(modgame_combo)
        filters_layout.addSpacing(20)
        tags_label = QLabel(tr('ui.tags_label'))
        filters_layout.addWidget(tags_label)
        tag_textedit = QCheckBox(tr('tags.textedit'))
        tag_customization = QCheckBox(tr('tags.customization'))
        tag_gameplay = QCheckBox(tr('tags.gameplay'))
        tag_other = QCheckBox(tr('tags.other'))
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        tag_style = f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: 12px;\n                spacing: 5px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        '
        for tag in [tag_textedit, tag_customization, tag_gameplay, tag_other]:
            tag.setStyleSheet(tag_style)
            filters_layout.addWidget(tag)
        filters_layout.addStretch()
        search_button = QPushButton('🔍')
        search_button.setObjectName('searchBtn')
        search_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        search_button.setFixedSize(35, 35)
        search_button.setToolTip(tr('ui.search_placeholder'))
        filters_layout.addWidget(search_button)
        self.widgets['sort_combo'] = sort_combo
        self.widgets['sort_order_btn'] = sort_order_btn
        self.widgets['modgame_combo'] = modgame_combo
        self.widgets['tags_label'] = tags_label
        self.widgets['tag_textedit'] = tag_textedit
        self.widgets['tag_customization'] = tag_customization
        self.widgets['tag_gameplay'] = tag_gameplay
        self.widgets['tag_other'] = tag_other
        self.widgets['search_button'] = search_button
        return filters_widget

    def _create_pagination_widget(self) -> QWidget:
        pagination_widget = QWidget()
        pagination_widget.setMinimumHeight(80)
        pagination_layout = QVBoxLayout(pagination_widget)
        pagination_layout.setContentsMargins(0, 0, 0, 0)
        pagination_layout.setSpacing(15)
        pagination_buttons_layout = QHBoxLayout()
        pagination_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_page_btn = QPushButton(tr('ui.prev_page'))
        prev_page_btn.setEnabled(False)
        prev_page_btn.setMaximumHeight(24)
        prev_page_btn.setStyleSheet('font-size: 12px; padding: 3px 8px;')
        pagination_buttons_layout.addWidget(prev_page_btn)
        page_label = QLabel(tr('ui.page_label', current=1, total=1))
        page_label.setStyleSheet('font-size: 14px; padding: 0px 10px;')
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pagination_buttons_layout.addWidget(page_label)
        next_page_btn = QPushButton(tr('ui.next_page'))
        next_page_btn.setEnabled(False)
        next_page_btn.setMaximumHeight(24)
        next_page_btn.setStyleSheet('font-size: 12px; padding: 3px 8px;')
        pagination_buttons_layout.addWidget(next_page_btn)
        pagination_layout.addLayout(pagination_buttons_layout)
        mods_per_page_layout = QHBoxLayout()
        mods_per_page_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mods_per_page_layout.setSpacing(10)
        gb_sort_label = QLabel(tr('ui.gamebanana_sort_label'))
        gb_sort_label.setStyleSheet('font-size: 12px; padding: 0px 5px;')
        mods_per_page_layout.addWidget(gb_sort_label)
        gb_sort_combo = QComboBox()
        gb_sort_combo.addItem(tr('ui.gamebanana_sort_default'), 'default')
        gb_sort_combo.addItem(tr('ui.gamebanana_sort_new'), 'new')
        gb_sort_combo.addItem(tr('ui.gamebanana_sort_updated'), 'updated')
        gb_sort_combo.setMaximumWidth(120)
        gb_sort_combo.setStyleSheet('font-size: 12px; padding: 2px 5px;')
        gb_sort_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
        current_sort = getattr(self.app_state, 'gamebanana_sort', 'default')
        if current_sort == 'default':
            gb_sort_combo.setCurrentIndex(0)
        elif current_sort == 'new':
            gb_sort_combo.setCurrentIndex(1)
        elif current_sort == 'updated':
            gb_sort_combo.setCurrentIndex(2)
        else:
            gb_sort_combo.setCurrentIndex(0)
        mods_per_page_layout.addWidget(gb_sort_combo)
        mods_per_page_label = QLabel(tr('ui.mods_per_page_label'))
        mods_per_page_label.setStyleSheet('font-size: 12px; padding: 0px 5px;')
        mods_per_page_layout.addWidget(mods_per_page_label)
        mods_per_page_spinbox = QSpinBox()
        mods_per_page_spinbox.setMinimum(5)
        mods_per_page_spinbox.setMaximum(1000)
        mods_per_page_spinbox.setValue(self.app_state.mods_per_page if hasattr(self.app_state, 'mods_per_page') else 20)
        mods_per_page_spinbox.setMaximumWidth(80)
        mods_per_page_spinbox.setStyleSheet('\n            QSpinBox {\n                font-size: 12px;\n                padding: 2px 5px;\n            }\n            QSpinBox::up-button, QSpinBox::down-button {\n                width: 0px;\n                border: none;\n            }\n        ')
        mods_per_page_spinbox.setToolTip(tr('ui.mods_per_page_tooltip'))
        mods_per_page_layout.addWidget(mods_per_page_spinbox)
        auto_sorting_checkbox = QCheckBox(tr('ui.auto_sorting'))
        auto_sorting_checkbox.setToolTip(tr('ui.auto_sorting_tooltip'))
        auto_sorting_checkbox.setChecked(self.app_state.local_config.get('auto_sorting', False))
        auto_sorting_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        text_color = get_theme_color(self.app_state.local_config, 'text', 'white')
        auto_sorting_style = f'\n            QCheckBox {{\n                color: {text_color};\n                font-size: 12px;\n                spacing: 5px;\n            }}\n            QCheckBox::indicator {{\n                width: 16px;\n                height: 16px;\n            }}\n        '
        auto_sorting_checkbox.setStyleSheet(auto_sorting_style)
        mods_per_page_layout.addWidget(auto_sorting_checkbox)
        pagination_layout.addLayout(mods_per_page_layout)
        self.widgets['prev_page_btn'] = prev_page_btn
        self.widgets['page_label'] = page_label
        self.widgets['next_page_btn'] = next_page_btn
        self.widgets['mods_per_page_spinbox'] = mods_per_page_spinbox
        self.widgets['mods_per_page_label'] = mods_per_page_label
        self.widgets['gb_sort_combo'] = gb_sort_combo
        self.widgets['gb_sort_label'] = gb_sort_label
        self.widgets['auto_sorting_checkbox'] = auto_sorting_checkbox
        return pagination_widget

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
