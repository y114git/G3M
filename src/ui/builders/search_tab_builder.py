from typing import Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QComboBox, QScrollArea, QSizePolicy, QSpinBox
from services.localization_service import tr
from ui.widgets.shared.custom_controls import NoScrollComboBox
from ui.common.styling import get_theme_color, rgba_from_color, build_tag_checkbox_style


class SearchTabBuilder:
    """Builds the search tab UI for browsing and searching mods."""

    def __init__(self, app_state, parent=None):
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def build(self) -> QWidget:
        widget, layout = QWidget(), None
        layout = QVBoxLayout(widget)
        layout.addWidget(self._create_filters_widget())
        search_container = QWidget()
        search_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        search_container.setObjectName('search_mods_background')
        sc_layout = QVBoxLayout(search_container)
        sc_layout.setContentsMargins(10, 10, 10, 10), sc_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True), scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        mod_list_widget, mod_list_layout = QWidget(), None
        mod_list_layout = QVBoxLayout(mod_list_widget)
        mod_list_layout.setSpacing(15), mod_list_layout.addStretch()
        scroll.setWidget(mod_list_widget)
        sc_layout.addWidget(scroll), sc_layout.addWidget(self._create_pagination_widget())
        bg = get_theme_color(self.app_state.local_config, 'background', '#000000')
        search_container.setStyleSheet(f'QWidget#search_mods_background {{ background-color: {rgba_from_color(bg)}; border-radius: 10px; margin: 5px; }}')
        layout.addWidget(search_container)
        self.widgets.update({'search_container': search_container, 'search_mods_scroll': scroll, 'mod_list_widget': mod_list_widget, 'mod_list_layout': mod_list_layout})
        return widget

    def _create_filters_widget(self) -> QFrame:
        w = QFrame()
        w.setObjectName('filters'), w.setFixedHeight(55)
        layout = QHBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter), layout.setContentsMargins(0, 0, 0, 0)
        sort_combo = NoScrollComboBox()
        sort_combo.addItems([tr('ui.sort_by_downloads'), tr('ui.sort_by_update_date'), tr('ui.sort_by_creation_date')])
        idx = self.app_state.local_config.get('search_sort_index', 1)
        sort_combo.setCurrentIndex(idx if 0 <= idx < sort_combo.count() else 1)
        layout.addWidget(sort_combo)
        sort_btn = QPushButton('▼')
        sort_btn.setObjectName('sortOrderBtn'), sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed), sort_btn.setToolTip(tr('ui.sort_direction_tooltip'))
        layout.addWidget(sort_btn), layout.addSpacing(20)
        modgame_combo = QComboBox()
        for name, data in [('deltarune', 'deltarune'), ('undertale', 'undertale'), ('undertaleyellow', 'undertaleyellow'), ('pizzatower', 'pizzatower'), ('sugaryspire', 'sugaryspire')]:
            modgame_combo.addItem(tr(f'ui.{name}'), data)
        game_idx = modgame_combo.findData(self.app_state.local_config.get('selected_search_game', 'deltarune'))
        modgame_combo.setCurrentIndex(max(game_idx, 0))
        layout.addWidget(modgame_combo), layout.addSpacing(20)
        tags_label = QLabel(tr('ui.tags_label'))
        layout.addWidget(tags_label)
        tags = {n: QCheckBox(tr(f'tags.{n}')) for n in ('textedit', 'customization', 'gameplay', 'other')}
        style = build_tag_checkbox_style(get_theme_color(self.app_state.local_config, 'text', 'white'))
        for t in tags.values():
            t.setStyleSheet(style), layout.addWidget(t)
        layout.addStretch()
        search_btn = QPushButton('🔍')
        search_btn.setObjectName('searchBtn'), search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        search_btn.setFixedSize(35, 35), search_btn.setToolTip(tr('ui.search_placeholder'))
        layout.addWidget(search_btn)
        self.widgets.update({'sort_combo': sort_combo, 'sort_order_btn': sort_btn, 'modgame_combo': modgame_combo, 'tags_label': tags_label, 'search_button': search_btn})
        self.widgets.update({f'tag_{k}': v for k, v in tags.items()})
        return w

    def _create_pagination_widget(self) -> QWidget:
        w = QWidget()
        w.setMinimumHeight(80)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0), layout.setSpacing(15)
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_btn = QPushButton(tr('ui.prev_page'))
        prev_btn.setEnabled(False), prev_btn.setMaximumHeight(24), prev_btn.setStyleSheet('font-size: 12px; padding: 3px 8px;')
        btn_layout.addWidget(prev_btn)
        page_lbl = QLabel(tr('ui.page_label', current=1, total=1))
        page_lbl.setStyleSheet('font-size: 14px; padding: 0px 10px;'), page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(page_lbl)
        next_btn = QPushButton(tr('ui.next_page'))
        next_btn.setEnabled(False), next_btn.setMaximumHeight(24), next_btn.setStyleSheet('font-size: 12px; padding: 3px 8px;')
        btn_layout.addWidget(next_btn)
        layout.addLayout(btn_layout)
        mods_layout = QHBoxLayout()
        mods_layout.setAlignment(Qt.AlignmentFlag.AlignCenter), mods_layout.setSpacing(10)
        gb_lbl = QLabel(tr('ui.gamebanana_sort_label'))
        gb_lbl.setStyleSheet('font-size: 12px; padding: 0px 5px;')
        mods_layout.addWidget(gb_lbl)
        gb_combo = QComboBox()
        for label, data in [('default', 'default'), ('new', 'new'), ('updated', 'updated')]:
            gb_combo.addItem(tr(f'ui.gamebanana_sort_{label}'), data)
        gb_combo.setMaximumWidth(120), gb_combo.setStyleSheet('font-size: 12px; padding: 2px 5px;'), gb_combo.setToolTip(tr('ui.gamebanana_sort_tooltip'))
        gb_combo.setCurrentIndex({'default': 0, 'new': 1, 'updated': 2}.get(getattr(self.app_state, 'gamebanana_sort', 'default'), 0))
        mods_layout.addWidget(gb_combo)
        mpp_lbl = QLabel(tr('ui.mods_per_page_label'))
        mpp_lbl.setStyleSheet('font-size: 12px; padding: 0px 5px;')
        mods_layout.addWidget(mpp_lbl)
        mpp_spin = QSpinBox()
        mpp_spin.setMinimum(5), mpp_spin.setMaximum(1000), mpp_spin.setMaximumWidth(80)
        mpp_spin.setValue(getattr(self.app_state, 'mods_per_page', 20))
        mpp_spin.setStyleSheet('QSpinBox { font-size: 12px; padding: 2px 5px; } QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }')
        mpp_spin.setToolTip(tr('ui.mods_per_page_tooltip'))
        mods_layout.addWidget(mpp_spin)
        auto_cb = QCheckBox(tr('ui.auto_sorting'))
        auto_cb.setToolTip(tr('ui.auto_sorting_tooltip')), auto_cb.setChecked(self.app_state.local_config.get('auto_sorting', False))
        auto_cb.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        auto_cb.setStyleSheet(build_tag_checkbox_style(get_theme_color(self.app_state.local_config, 'text', 'white')))
        mods_layout.addWidget(auto_cb), mods_layout.addSpacing(10)
        blocklist_btn = QPushButton(tr('ui.blocklist'))
        blocklist_btn.setObjectName('blocklistBtn'), blocklist_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        blocklist_btn.setMinimumWidth(80), blocklist_btn.setToolTip(tr('ui.blocklist_tooltip'))
        mods_layout.addWidget(blocklist_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(mods_layout)
        self.widgets.update({'prev_page_btn': prev_btn, 'page_label': page_lbl, 'next_page_btn': next_btn, 'mods_per_page_spinbox': mpp_spin, 'mods_per_page_label': mpp_lbl, 'gb_sort_combo': gb_combo, 'gb_sort_label': gb_lbl, 'auto_sorting_checkbox': auto_cb, 'blocklist_button': blocklist_btn})
        return w

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
