from typing import Dict, Any
from PyQt6.QtCore import Qt, QObject, QEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame, QScrollArea, QSizePolicy, QLabel
from services.localization_service import tr
from ui.common.styling import get_theme_color, rgba_from_color
from ui.builders.shared_filters_builder import (
    create_sort_controls, create_tag_checkboxes, create_search_button,
    create_filters_frame, create_modgame_combo, create_pagination_controls
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
        f_widget = self._create_filters_widget()
        f_scroll.setWidget(f_widget)
        f_widget.installEventFilter(self)
        layout.addWidget(f_scroll)
        self.widgets['filters_scroll'] = f_scroll
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
        bg = get_theme_color(self.app_state.local_config, 'background', '#000000')
        container.setStyleSheet(f'QWidget#search_mods_background {{ background-color: {rgba_from_color(bg)}; border-radius: 10px; margin: 5px; }}')
        layout.addWidget(container)
        self.widgets.update({'search_container': container, 'search_mods_scroll': scroll, 'mod_list_widget': mod_list, 'mod_list_layout': mod_list_layout, 'prev_page_btn': prev_btn, 'page_label': page_lbl, 'next_page_btn': next_btn})
        return widget

    def eventFilter(self, obj, event):
        if 'filters_scroll' in self.widgets and obj == self.widgets['filters_scroll'].widget() and event.type() == QEvent.Type.Resize:
            self.widgets['filters_scroll'].setFixedHeight(obj.sizeHint().height() + (15 if self.widgets['filters_scroll'].horizontalScrollBar().isVisible() else 0))
        return super().eventFilter(obj, event)

    def _create_filters_widget(self) -> QFrame:
        w, layout = create_filters_frame()
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _vc = Qt.AlignmentFlag.AlignVCenter
        sort_combo, sort_btn = create_sort_controls(self.app_state, [tr('ui.sort_by_downloads'), tr('ui.sort_by_update_date'), tr('ui.sort_by_creation_date')], 'search_sort_index')
        layout.addWidget(sort_combo, 0, _vc)
        layout.addWidget(sort_btn, 0, _vc)
        layout.addSpacing(20)
        modgame_combo = create_modgame_combo(self.app_state, [('deltarune', 'deltarune'), ('undertale', 'undertale'), ('undertaleyellow', 'undertaleyellow'), ('pizzatower', 'pizzatower'), ('sugaryspire', 'sugaryspire')], 'selected_search_game')
        layout.addWidget(modgame_combo, 0, _vc)
        layout.addSpacing(20)
        tags_label = QLabel(tr('ui.tags_label'))
        layout.addWidget(tags_label, 0, _vc)
        tags = create_tag_checkboxes(self.app_state, ('textedit', 'customization', 'gameplay', 'other'))
        for t in tags.values():
            layout.addWidget(t, 0, _vc)
        layout.addStretch()
        search_btn = create_search_button()
        layout.addWidget(search_btn, 0, _vc)
        self.widgets.update({'sort_combo': sort_combo, 'sort_order_btn': sort_btn, 'modgame_combo': modgame_combo, 'tags_label': tags_label, 'search_button': search_btn})
        self.widgets.update({f'tag_{k}': v for k, v in tags.items()})
        return w

    def get_widgets(self) -> Dict[str, Any]: return self.widgets
