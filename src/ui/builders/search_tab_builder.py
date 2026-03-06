from typing import Dict, Any
from PyQt6.QtCore import Qt, QObject
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame, QScrollArea, QSizePolicy, QLabel
from services.localization_service import tr
from ui.common.styling import install_size_hint_height_sync, install_scroll_viewport_clip, apply_panel_style
from ui.builders.shared_filters_builder import (
    BASE_TAG_NAMES, SEARCH_GAME_OPTIONS, create_sort_controls, create_tag_checkboxes, create_search_button,
    create_filters_frame, create_modgame_combo, create_pagination_controls, apply_filters_frame_style
)


class ModsBrowserTabBuilder(QObject):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def build(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        f_scroll = QScrollArea(widget)
        f_scroll.setWidgetResizable(True)
        f_scroll.setFrameShape(QFrame.Shape.NoFrame)
        f_scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        f_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        f_scroll.setMinimumWidth(200)
        f_widget = self._create_filters_widget()
        f_scroll.setWidget(f_widget)
        install_size_hint_height_sync(f_widget, f_scroll, attr_name='_filters_scroll_height_filter')
        layout.addWidget(f_scroll)
        self.widgets.update({'filters_scroll': f_scroll, 'filters_widget': f_widget})
        container = QWidget(widget)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        container.setObjectName('search_mods_background')
        sc_layout = QVBoxLayout(container)
        sc_layout.setContentsMargins(10, 10, 10, 10)
        sc_layout.setSpacing(10)
        scroll = QScrollArea(container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        mod_list = QWidget(scroll)
        mod_list_layout = QVBoxLayout(mod_list)
        mod_list_layout.setSpacing(15)
        mod_list_layout.addStretch()
        scroll.setWidget(mod_list)
        pag_widget, prev_btn, page_lbl, next_btn = create_pagination_controls()
        sc_layout.addWidget(scroll)
        sc_layout.addWidget(pag_widget)
        container_padding = 10
        install_scroll_viewport_clip(scroll, container, self.app_state.local_config, inset=container_padding, attr_name='_search_viewport_clip_filter')
        apply_panel_style(container, self.app_state.local_config)
        layout.addWidget(container)
        self.widgets.update({'search_container': container, 'search_mods_scroll': scroll, 'mod_list_widget': mod_list, 'mod_list_layout': mod_list_layout, 'prev_page_btn': prev_btn, 'page_label': page_lbl, 'next_page_btn': next_btn})
        return widget

    def _create_filters_widget(self) -> QFrame:
        w, layout = create_filters_frame()
        apply_filters_frame_style(w, self.app_state)
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _vc = Qt.AlignmentFlag.AlignVCenter
        sort_combo, sort_btn = create_sort_controls(self.app_state, [tr('ui.sort_by_downloads'), tr('ui.sort_by_update_date'), tr('ui.sort_by_creation_date')], 'search_sort_index')
        layout.addWidget(sort_combo, 0, _vc)
        layout.addWidget(sort_btn, 0, _vc)
        layout.addSpacing(20)
        modgame_combo = create_modgame_combo(self.app_state, SEARCH_GAME_OPTIONS, 'selected_search_game')
        layout.addWidget(modgame_combo, 0, _vc)
        layout.addSpacing(20)
        tags_label = QLabel(tr('ui.tags_label'))
        layout.addWidget(tags_label, 0, _vc)
        tags = create_tag_checkboxes(self.app_state, BASE_TAG_NAMES)
        for t in tags.values():
            layout.addWidget(t, 0, _vc)
        layout.addStretch()
        search_btn = create_search_button()
        layout.addWidget(search_btn, 0, _vc)
        self.widgets.update({'sort_combo': sort_combo, 'sort_order_btn': sort_btn, 'modgame_combo': modgame_combo, 'tags_label': tags_label, 'search_button': search_btn})
        self.widgets.update({f'tag_{k}': v for k, v in tags.items()})
        return w

    def get_widgets(self) -> Dict[str, Any]: return self.widgets
