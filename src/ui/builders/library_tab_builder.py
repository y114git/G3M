from typing import Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QCheckBox, QComboBox, QScrollArea, QSizePolicy
from services.localization_service import tr
from ui.widgets.shared.custom_controls import NoScrollComboBox, _ZeroHintWidget
from ui.common.styling import get_theme_color, rgba_from_color, build_tag_checkbox_style


class LibraryTabBuilder:
    """Builds the library tab UI for displaying installed mods."""

    def __init__(self, app_state, parent=None):
        self.app_state, self.parent, self.widgets = app_state, parent, {}

    def _get_colors(self):
        cfg = self.app_state.local_config
        return {k: get_theme_color(cfg, k, d) for k, d in [('border', 'white'), ('button', 'black'), ('button_hover', '#333'), ('text', 'white'), ('background', '#000000')]}

    def build(self) -> QWidget:
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        filters = self._create_library_filters_widget()
        filters.setVisible(not self.app_state.local_config.get('hide_library_filters', False))
        layout.addWidget(filters)
        ctrl = QHBoxLayout()
        ctrl.addStretch()
        import_btn = QPushButton(tr('ui.import_export_mod'))
        import_btn.setObjectName('import_export_button')
        ctrl.addWidget(import_btn), ctrl.addSpacing(20)
        exe_btn = QPushButton(tr('buttons.custom_executable'))
        exe_btn.setObjectName('custom_executable_button'), exe_btn.setToolTip(tr('tooltips.custom_executable_library'))
        ctrl.addWidget(exe_btn)
        reset_btn = QPushButton('⭯')
        reset_btn.setObjectName('reset_custom_exe_button'), reset_btn.setStyleSheet('min-width: 35px; max-width: 35px; padding-left: 0px; padding-right: 0px;')
        reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed), reset_btn.setVisible(False)
        ctrl.addWidget(reset_btn), ctrl.addSpacing(10)
        path_btn = QPushButton()
        path_btn.setObjectName('change_path_button')
        ctrl.addWidget(path_btn), ctrl.addSpacing(20)
        game_combo = QComboBox()
        for label, data in [('DELTARUNE', 'deltarune'), ('DELTARUNE DEMO', 'deltarunedemo'), ('UNDERTALE', 'undertale'), ('UNDERTALE Yellow', 'undertaleyellow'), ('Pizza Tower', 'pizzatower'), ('Sugary Spire', 'sugaryspire')]:
            game_combo.addItem(label, data)
        ctrl.addWidget(game_combo), ctrl.addSpacing(20)
        chapter_cb = QCheckBox(tr('ui.chapter_mode'))
        full_cb = QCheckBox(tr('ui.full_install'))
        ctrl.addWidget(chapter_cb), ctrl.addWidget(full_cb), ctrl.addStretch()
        layout.addLayout(ctrl)
        colors = self._get_colors()
        chapter_tabs = QWidget()
        chapter_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        tabs_layout = QHBoxLayout(chapter_tabs)
        tabs_layout.setAlignment(Qt.AlignmentFlag.AlignCenter), tabs_layout.setContentsMargins(20, 10, 20, 10), tabs_layout.setSpacing(10), tabs_layout.addStretch()
        chapter_tabs.setObjectName('chapter_tabs_container')
        tab_names = [tr('chapters.menu'), tr('tabs.chapter_1'), tr('tabs.chapter_2'), tr('tabs.chapter_3'), tr('tabs.chapter_4')]
        tab_btns = []
        for i, name in enumerate(tab_names):
            btn = QPushButton(name)
            btn.setCheckable(True), btn.setObjectName(f'chapter_tab_{i}'), btn.setFixedHeight(40), btn.setMinimumWidth(100)
            btn.setStyleSheet(f'QPushButton#chapter_tab_{i} {{ background-color: {colors["button"]}; border: 2px solid {colors["border"]}; color: {colors["text"]}; font-weight: bold; font-size: 13px; border-radius: 0px; padding: 5px; }} QPushButton#chapter_tab_{i}:checked {{ background-color: {colors["button_hover"]}; border: 3px solid {colors["border"]}; }} QPushButton#chapter_tab_{i}:hover {{ background-color: {colors["button_hover"]}; }}')
            tabs_layout.addWidget(btn), tab_btns.append(btn)
        tabs_layout.addStretch()
        chapter_tabs.setVisible(False)
        layout.addWidget(chapter_tabs)
        priority_btn = QPushButton(tr('ui.priority'))
        priority_btn.setObjectName('priority_button'), priority_btn.setVisible(False), priority_btn.setFixedSize(175, 35)
        self._update_priority_button_style(priority_btn, colors['button'], colors['border'], colors['button_hover'])
        modpack_btn = QPushButton(tr('ui.create_modpack_button'))
        modpack_btn.setObjectName('create_modpack_button'), modpack_btn.setVisible(False), modpack_btn.setFixedSize(175, 35)
        self._update_priority_button_style(modpack_btn, colors['button'], colors['border'], colors['button_hover'])
        priority_container = QWidget()
        priority_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        priority_layout = QHBoxLayout(priority_container)
        priority_layout.setContentsMargins(0, 0, 0, 0), priority_layout.setSpacing(10), priority_layout.addStretch()
        priority_layout.addWidget(priority_btn), priority_layout.addWidget(modpack_btn)
        fast_lbl = QLabel(tr('ui.fast_merging'))
        fast_lbl.setToolTip(tr('ui.fast_merging_tooltip')), fast_lbl.setStyleSheet(f'color: {colors["text"]};')
        fast_cb = QCheckBox()
        fast_cb.setObjectName('fast_merging_checkbox'), fast_cb.setToolTip(tr('ui.fast_merging_tooltip'))
        fast_cb.setStyleSheet('QCheckBox { spacing: 0px; } QCheckBox::indicator { width: 16px; height: 16px; }')
        priority_layout.addWidget(fast_lbl), priority_layout.addWidget(fast_cb), priority_layout.addStretch()
        priority_container.setFixedHeight(0)
        layout.addWidget(priority_container)
        mods_container = QWidget()
        mods_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        mods_container.setObjectName('mods_background')
        mods_layout = QVBoxLayout(mods_container)
        mods_layout.setContentsMargins(15, 15, 15, 15), mods_layout.setSpacing(10)
        mods_lbl = QLabel(tr('ui.installed_mods_label'))
        mods_lbl.setStyleSheet('font-weight: bold; font-size: 16px;'), mods_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mods_layout.addWidget(mods_lbl)
        from PyQt6.QtWidgets import QAbstractScrollArea
        mods_scroll = QScrollArea()
        mods_scroll.setWidgetResizable(True), mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        mods_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        mods_scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        mods_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        mods_widget = _ZeroHintWidget()
        mods_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        mods_widget_layout = QVBoxLayout(mods_widget)
        mods_widget_layout.addStretch(), mods_widget_layout.setContentsMargins(0, 0, 0, 0)
        mods_scroll.setWidget(mods_widget)
        mods_layout.addWidget(mods_scroll)
        try:
            mods_layout.setStretch(0, 0), mods_layout.setStretch(1, 1)
        except BaseException:
            pass
        mods_container.setStyleSheet(f'QWidget#mods_background {{ background-color: {rgba_from_color(colors["background"])}; border-radius: 10px; margin: 5px; }}')
        layout.addWidget(mods_container)
        try:
            layout.setStretch(0, 0), layout.setStretch(1, 0), layout.setStretch(2, 0), layout.setStretch(3, 1)
        except BaseException:
            pass
        self.widgets.update({'library_filters_widget': filters, 'import_export_button': import_btn, 'custom_executable_button': exe_btn, 'reset_custom_exe_button': reset_btn, 'change_path_button': path_btn, 'game_type_combo': game_combo, 'chapter_mode_checkbox': chapter_cb, 'full_install_checkbox': full_cb, 'chapter_tabs_widget': chapter_tabs, 'chapter_tabs_layout': tabs_layout, 'chapter_tab_buttons': tab_btns, 'installed_mods_container': mods_container, 'installed_mods_scroll': mods_scroll, 'installed_mods_widget': mods_widget, 'installed_mods_layout': mods_widget_layout, 'priority_button': priority_btn, 'priority_button_layout': priority_layout, 'priority_button_container': priority_container, 'create_modpack_button': modpack_btn, 'fast_merging_checkbox': fast_cb, 'fast_merging_label': fast_lbl, 'installed_mods_label': mods_lbl})
        return widget

    def _create_library_filters_widget(self) -> QFrame:
        w = QFrame()
        w.setObjectName('filters'), w.setFixedHeight(55)
        layout = QHBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter), layout.setContentsMargins(0, 0, 0, 0)
        sort_combo = NoScrollComboBox()
        sort_combo.addItems([tr('ui.sort_by_name'), tr('ui.sort_by_date')])
        layout.addWidget(sort_combo)
        sort_btn = QPushButton('▼')
        sort_btn.setObjectName('sortOrderBtn'), sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed), sort_btn.setToolTip(tr('ui.sort_direction_tooltip'))
        layout.addWidget(sort_btn), layout.addSpacing(20)
        tags_lbl = QLabel(tr('ui.tags_label'))
        layout.addWidget(tags_lbl)
        tags = {n: QCheckBox(tr(f'tags.{n}') if n != 'gamebanana' else tr('ui.only_gamebanana')) for n in ('textedit', 'customization', 'gameplay', 'other', 'gamebanana')}
        style = build_tag_checkbox_style(get_theme_color(self.app_state.local_config, 'text', 'white'))
        tag_widgets = list(tags.values())
        for t in tag_widgets:
            t.setStyleSheet(style), layout.addWidget(t)
        layout.addStretch()
        search_btn = QPushButton('🔍')
        search_btn.setObjectName('searchBtn'), search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        search_btn.setFixedSize(35, 35), search_btn.setToolTip(tr('ui.search_placeholder'))
        layout.addWidget(search_btn)
        self.widgets.update({'library_sort_combo': sort_combo, 'library_sort_order_btn': sort_btn, 'library_tags_label': tags_lbl, 'library_search_button': search_btn, 'library_tag_widgets': tag_widgets})
        self.widgets.update({f'library_tag_{k}': v for k, v in tags.items()})
        return w

    def _update_priority_button_style(self, button, button_color, border_color, hover_color):
        name = button.objectName()
        text = get_theme_color(self.app_state.local_config, 'text', 'white')
        button.setStyleSheet(f'QPushButton#{name} {{ background-color: {button_color}; border: 2px solid {border_color}; color: {text}; font-weight: bold; font-size: 13px; border-radius: 0px; padding: 5px; }} QPushButton#{name}:hover {{ background-color: {hover_color}; }}')

    def update_priority_button_style(self):
        colors = self._get_colors()
        for key in ('priority_button', 'create_modpack_button'):
            if key in self.widgets:
                self._update_priority_button_style(self.widgets[key], colors['button'], colors['border'], colors['button_hover'])
        if 'fast_merging_label' in self.widgets:
            self.widgets['fast_merging_label'].setStyleSheet(f'color: {colors["text"]};')
        if 'library_tags_label' in self.widgets:
            self.widgets['library_tags_label'].setStyleSheet(f'color: {colors["text"]};')

    def get_widgets(self) -> Dict[str, Any]:
        return self.widgets
