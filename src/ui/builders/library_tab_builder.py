import logging
from typing import Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QScrollArea, QSizePolicy
from config.constants import BASE_TAG_NAMES, LIBRARY_GAME_OPTIONS, LIBRARY_IMPORT_ARCHIVE_EXTENSIONS
from services.localization_service import tr
from ui.widgets.shared.custom_controls import _ZeroHintWidget
from ui.common.styling import get_theme_colors, get_border_radius, clamp_border_radius, install_size_hint_height_sync, install_panel_style_handler, install_scroll_area_update_handlers, get_widget_border_radius, build_scrollbar_qss, build_button_style, apply_scroll_area_chrome
from ui.builders.shared_filters_builder import (
    create_modgame_combo, create_sort_controls, create_tag_checkboxes, create_search_button,
    create_filters_frame, apply_filters_frame_style
)

logger = logging.getLogger(__name__)


class _DropAreaWidget(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(LIBRARY_IMPORT_ARCHIVE_EXTENSIONS) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(LIBRARY_IMPORT_ARCHIVE_EXTENSIONS)]
            if paths:
                e.acceptProposedAction()
                self.files_dropped.emit(paths)


class LibraryTabBuilder(QObject):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def _get_colors(self):
        return get_theme_colors(
            self.app_state.local_config,
            border='#039d5b',
            button='#222222',
            button_hover='#616b78',
            text='#e8e9eb',
            background='#282828',
        )

    def build(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        f_scroll = QScrollArea(widget)
        f_scroll.setWidgetResizable(True)
        f_scroll.setFrameShape(QFrame.Shape.NoFrame)
        f_scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        f_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        f_scroll.setMinimumWidth(200)
        filters = self._create_library_filters_widget()
        f_scroll.setWidget(filters)
        install_size_hint_height_sync(filters, f_scroll, attr_name='_library_filters_scroll_height_filter')
        f_scroll.setVisible(not self.app_state.local_config.get('hide_library_filters', False))
        layout.addWidget(f_scroll)
        self.widgets['filters_scroll'] = f_scroll
        ctrl = QHBoxLayout()
        import_btn = QPushButton(tr('ui.import_export_mod'))
        import_btn.setObjectName('import_export_button')
        ctrl.addStretch()
        ctrl.addWidget(import_btn)
        ctrl.addSpacing(20)
        game_combo = create_modgame_combo(self.app_state, LIBRARY_GAME_OPTIONS, 'selected_game_type')
        ctrl.addWidget(game_combo)
        ctrl.addSpacing(20)
        ch_cb = QCheckBox(tr('ui.chapter_mode'))
        f_cb = QCheckBox(tr('ui.full_install'))
        ctrl.addWidget(ch_cb)
        ctrl.addWidget(f_cb)
        ctrl.addStretch()
        layout.addLayout(ctrl)
        colors = self._get_colors()
        ch_tabs = QWidget()
        ch_tabs.setObjectName('chapter_tabs_container')
        ch_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        t_layout = QHBoxLayout(ch_tabs)
        t_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t_layout.setContentsMargins(20, 10, 20, 10)
        t_layout.setSpacing(10)
        t_layout.addStretch()
        fs = max(1, int(14 * self.app_state.local_config.get('ui_scale', 1.0)))
        tab_btns = []
        for i, name in enumerate([tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setObjectName(f'chapter_tab_{i}')
            btn.setStyleSheet(build_button_style(btn.objectName(), colors['button'], colors['button_hover'], colors['text'], colors['border'], width=None, height=None, font_size=fs, border_radius=clamp_border_radius(get_border_radius(self.app_state.local_config), height=max(25, btn.sizeHint().height())), padding='5px', checked_bg_color=colors['button_hover'], checked_border_color=colors['border'], checked_border_width=3))
            t_layout.addWidget(btn)
            tab_btns.append(btn)
        t_layout.addStretch()
        ch_tabs.setVisible(False)
        layout.addWidget(ch_tabs)
        p_btn = QPushButton(tr('ui.priority'))
        m_btn = QPushButton(tr('ui.create_modpack_button'))
        for b, n in [(p_btn, 'priority_button'), (m_btn, 'create_modpack_button')]:
            b.setObjectName(n)
            b.setVisible(False)
            self._update_priority_button_style(b, colors['button'], colors['border'], colors['button_hover'])
        p_cont = QWidget()
        p_cont.setFixedHeight(0)
        p_cont.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        p_layout = QHBoxLayout(p_cont)
        p_layout.setContentsMargins(0, 0, 0, 0)
        p_layout.setSpacing(10)
        p_layout.addStretch()
        p_layout.addWidget(p_btn)
        p_layout.addWidget(m_btn)
        p_layout.addStretch()
        layout.addWidget(p_cont)
        p_cont.setObjectName('priority_button_container')
        mods_cont = _DropAreaWidget()
        mods_cont.setObjectName('mods_background')
        mods_cont.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        m_layout = QVBoxLayout(mods_cont)
        m_layout.setContentsMargins(15, 15, 15, 15)
        m_layout.setSpacing(10)
        mods_lbl = QLabel(tr('ui.installed_mods_label'))
        mods_lbl.setStyleSheet('font-weight: bold; font-size: 16px;')
        mods_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m_layout.addWidget(mods_lbl)
        scroll = QScrollArea(mods_cont)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        mods_w = _ZeroHintWidget(scroll)
        mw_layout = QVBoxLayout(mods_w)
        mw_layout.addStretch()
        mw_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(mods_w)
        m_layout.addWidget(scroll)
        container_padding = 15

        def _apply_inner_clip():
            container_radius = get_widget_border_radius(mods_cont, get_border_radius(self.app_state.local_config))
            content_padding = max(container_padding, (container_radius * 4 + 9) // 10)
            viewport_inset = max(2, min(10, container_radius // 5))
            scrollbar_corner_inset = max(6, min(18, container_radius // 2))
            scrollbar_qss = build_scrollbar_qss(colors["text"], get_border_radius(self.app_state.local_config), vertical_margin=(scrollbar_corner_inset, 2, scrollbar_corner_inset, 0), horizontal_margin=(0, scrollbar_corner_inset, scrollbar_corner_inset, scrollbar_corner_inset))
            m_layout.setContentsMargins(content_padding, content_padding, content_padding, content_padding)
            scroll.setStyleSheet(f'''QScrollArea {{ background-color: transparent; border: none; }}{scrollbar_qss}''')
            scrollbar_extent = apply_scroll_area_chrome(scroll, max(0, container_radius - viewport_inset), scrollbar_radius=get_border_radius(self.app_state.local_config), qss=scrollbar_qss)
            try:
                scroll.setViewportMargins(viewport_inset, viewport_inset, max(viewport_inset, scrollbar_extent + 2), viewport_inset)
            except (AttributeError, TypeError):
                logger.exception('LibraryTabBuilder: setViewportMargins failed for viewport_inset=%s', viewport_inset)

        mods_cont._inner_clip_callback = _apply_inner_clip
        install_scroll_area_update_handlers(scroll, _apply_inner_clip, 'library_viewport_clip')
        install_panel_style_handler(mods_cont, self.app_state.local_config, attr_name='_library_panel_style_filter')
        layout.addWidget(mods_cont)
        self.widgets.update({
            'library_filters_widget': filters,
            'import_export_button': import_btn,
            'game_type_combo': game_combo,
            'chapter_mode_checkbox': ch_cb,
            'full_install_checkbox': f_cb,
            'chapter_tabs_widget': ch_tabs,
            'chapter_tabs_layout': t_layout,
            'chapter_tab_buttons': tab_btns,
            'installed_mods_container': mods_cont,
            'installed_mods_scroll': scroll,
            'installed_mods_widget': mods_w,
            'installed_mods_layout': mw_layout,
            'priority_button': p_btn,
            'priority_button_container': p_cont,
            'priority_button_layout': p_layout,
            'create_modpack_button': m_btn,
            'installed_mods_label': mods_lbl
        })
        return widget

    def _create_library_filters_widget(self) -> QFrame:
        w, layout = create_filters_frame()
        apply_filters_frame_style(w, self.app_state)
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _vc = Qt.AlignmentFlag.AlignVCenter
        sort_combo, sort_btn = create_sort_controls(self.app_state, [tr('ui.sort_by_name'), tr('ui.sort_by_date')])
        layout.addWidget(sort_combo, 0, _vc)
        layout.addWidget(sort_btn, 0, _vc)
        layout.addSpacing(20)
        tags_lbl = QLabel(tr('ui.tags_label'))
        layout.addWidget(tags_lbl, 0, _vc)
        tags = create_tag_checkboxes(self.app_state, (*BASE_TAG_NAMES, 'gamebanana'))
        for t in tags.values():
            layout.addWidget(t, 0, _vc)
        layout.addStretch()
        search_btn = create_search_button()
        layout.addWidget(search_btn, 0, _vc)
        self.widgets.update({'library_sort_combo': sort_combo, 'library_sort_order_btn': sort_btn, 'library_tags_label': tags_lbl, 'library_search_button': search_btn, 'library_tag_widgets': list(tags.values())})
        self.widgets.update({f'library_tag_{k}': v for k, v in tags.items()})
        return w

    def _update_priority_button_style(self, btn, btn_clr, brd_clr, hvr_clr):
        n = btn.objectName()
        t = self._get_colors()['text']
        fs = max(1, int(14 * self.app_state.local_config.get('ui_scale', 1.0)))
        btn.setStyleSheet(build_button_style(n, btn_clr, hvr_clr, t, brd_clr, width=None, height=None, font_size=fs, border_radius=clamp_border_radius(get_border_radius(self.app_state.local_config), height=max(30, btn.sizeHint().height())), padding='5px'))

    def update_priority_button_style(self):
        colors = self._get_colors()
        for k in ('priority_button', 'create_modpack_button'):
            if k in self.widgets:
                self._update_priority_button_style(self.widgets[k], colors['button'], colors['border'], colors['button_hover'])
        tag_lbl = self.widgets.get('library_tags_label')
        if tag_lbl:
            tag_lbl.setStyleSheet(f'color: {colors["text"]};')

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
