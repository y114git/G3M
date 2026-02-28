from typing import Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QComboBox, QScrollArea, QSizePolicy
from services.localization_service import tr
from ui.widgets.shared.custom_controls import _ZeroHintWidget
from ui.common.styling import get_theme_color, rgba_from_color
from ui.builders.shared_filters_builder import (
    create_sort_controls, create_tag_checkboxes, create_search_button,
    create_filters_frame
)

_ARCHIVE_EXTENSIONS = ('.zip', '.7z', '.rar', '.tar.gz', '.lzma', '.gz')


class _DropAreaWidget(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(_ARCHIVE_EXTENSIONS) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(_ARCHIVE_EXTENSIONS)]
            if paths:
                e.acceptProposedAction()
                self.files_dropped.emit(paths)


class LibraryTabBuilder(QObject):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def _get_colors(self):
        cfg = self.app_state.local_config
        bg = get_theme_color(cfg, 'background', '#000000')
        return {
            'border': get_theme_color(cfg, 'border', 'white'),
            'button': get_theme_color(cfg, 'button', 'black'),
            'button_hover': get_theme_color(cfg, 'button_hover', '#333'),
            'text': get_theme_color(cfg, 'text', 'white'),
            'background': bg
        }

    def build(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        f_scroll = QScrollArea(widget)
        f_scroll.setWidgetResizable(True)
        f_scroll.setFrameShape(QFrame.Shape.NoFrame)
        f_scroll.setStyleSheet('QScrollArea { background-color: transparent; }')
        f_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filters = self._create_library_filters_widget()
        f_scroll.setWidget(filters)
        filters.installEventFilter(self)
        f_scroll.setVisible(not self.app_state.local_config.get('hide_library_filters', False))
        layout.addWidget(f_scroll)
        self.widgets['filters_scroll'] = f_scroll
        ctrl = QHBoxLayout()
        import_btn = QPushButton(tr('ui.import_export_mod'))
        import_btn.setObjectName('import_export_button')
        ctrl.addStretch()
        ctrl.addWidget(import_btn)
        ctrl.addSpacing(20)
        game_combo = QComboBox()
        for label_key, data in [('deltarune', 'deltarune'), ('deltarunedemo', 'deltarunedemo'), ('undertale', 'undertale'), ('undertaleyellow', 'undertaleyellow'), ('pizzatower', 'pizzatower'), ('sugaryspire', 'sugaryspire')]:
            game_combo.addItem(tr(f'ui.{label_key}'), data)
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
        tab_btns = []
        for i, name in enumerate([tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setObjectName(f'chapter_tab_{i}')
            btn.setStyleSheet(f'QPushButton#chapter_tab_{i} {{ background-color: {colors["button"]}; border: 2px solid {colors["border"]}; color: {colors["text"]}; font-weight: bold; font-size: 13px; border-radius: 0px; padding: 5px; }} QPushButton#chapter_tab_{i}:checked {{ background-color: {colors["button_hover"]}; border: 3px solid {colors["border"]}; }} QPushButton#chapter_tab_{i}:hover {{ background-color: {colors["button_hover"]}; }}')
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
        mods_cont.setStyleSheet(f'QWidget#mods_background {{ background-color: {rgba_from_color(colors["background"])}; border-radius: 10px; margin: 5px; }}')
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

    def eventFilter(self, obj, event):
        if 'filters_scroll' in self.widgets:
            fs = self.widgets['filters_scroll']
            if obj == fs.widget() and event.type() == QEvent.Type.Resize:
                fs.setFixedHeight(obj.sizeHint().height() + (15 if fs.horizontalScrollBar().isVisible() else 0))
        return False

    def _create_library_filters_widget(self) -> QFrame:
        w, layout = create_filters_frame()
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        _vc = Qt.AlignmentFlag.AlignVCenter
        sort_combo, sort_btn = create_sort_controls(self.app_state, [tr('ui.sort_by_name'), tr('ui.sort_by_date')])
        layout.addWidget(sort_combo, 0, _vc)
        layout.addWidget(sort_btn, 0, _vc)
        layout.addSpacing(20)
        tags_lbl = QLabel(tr('ui.tags_label'))
        layout.addWidget(tags_lbl, 0, _vc)
        tags = create_tag_checkboxes(self.app_state, ('textedit', 'customization', 'gameplay', 'other', 'gamebanana'))
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
        t = get_theme_color(self.app_state.local_config, 'text', 'white')
        btn.setStyleSheet(f'QPushButton#{n} {{ background-color: {btn_clr}; border: 2px solid {brd_clr}; color: {t}; font-weight: bold; font-size: 13px; border-radius: 0px; padding: 5px; }} QPushButton#{n}:hover {{ background-color: {hvr_clr}; }}')

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
