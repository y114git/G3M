"""Shared filter widget components for UI builders."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QCheckBox, QSizePolicy, QLabel
from services.localization_service import tr
from ui.widgets.shared.custom_controls import NoScrollComboBox
from ui.common.styling import get_theme_color, build_tag_checkbox_style


def create_sort_controls(app_state, items=None, config_key=None):
    """Create sort combo and order button."""
    sort_combo = NoScrollComboBox()
    if items:
        sort_combo.addItems(items)
    if config_key:
        idx = app_state.local_config.get(config_key, 1)
        sort_combo.setCurrentIndex(idx if 0 <= idx < sort_combo.count() else (1 if sort_combo.count() > 1 else 0))
    sort_btn = QPushButton('▼')
    sort_btn.setObjectName('sortOrderBtn')
    sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    sort_btn.setToolTip(tr('ui.sort_direction_tooltip'))
    return sort_combo, sort_btn


def create_tag_checkboxes(app_state, tag_names):
    """Create tag checkboxes with styling."""
    tags = {n: QCheckBox(tr(f'tags.{n}') if (n != 'gamebanana' and n != 'only_gamebanana') else tr('ui.only_gamebanana')) for n in tag_names}
    style = build_tag_checkbox_style(get_theme_color(app_state.local_config, 'text', 'white'))
    for t in tags.values():
        t.setStyleSheet(style)
    return tags


def create_modgame_combo(app_state, games_list, config_key=None):
    """Create game selection combo."""
    from PyQt6.QtWidgets import QComboBox
    modgame_combo = QComboBox()
    for name, data in games_list:
        modgame_combo.addItem(tr(f'ui.{name}') if isinstance(name, str) and not name.isupper() else name, data)
    if config_key:
        game_idx = modgame_combo.findData(app_state.local_config.get(config_key, 'deltarune'))
        modgame_combo.setCurrentIndex(max(game_idx, 0))
    return modgame_combo


def create_pagination_controls():
    """Create prev/next buttons and page label."""
    from PyQt6.QtWidgets import QWidget, QVBoxLayout
    w = QWidget()
    w.setMinimumHeight(50)
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 5, 0, 8)
    layout.setSpacing(5)
    btn_layout = QHBoxLayout()
    btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    prev_btn = QPushButton(tr('ui.prev_page'))
    prev_btn.setEnabled(False)
    prev_btn.setStyleSheet('padding: 3px 8px;')
    btn_layout.addWidget(prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    page_lbl = QLabel(tr('ui.page_label', current=1, total=1))
    page_lbl.setStyleSheet('padding: 0px 10px;')
    page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    btn_layout.addWidget(page_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
    next_btn = QPushButton(tr('ui.next_page'))
    next_btn.setEnabled(False)
    next_btn.setStyleSheet('padding: 3px 8px;')
    btn_layout.addWidget(next_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(btn_layout)
    return w, prev_btn, page_lbl, next_btn


def create_search_button():
    """Create search button."""
    search_btn = QPushButton('🔍')
    search_btn.setObjectName('searchBtn')
    search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    search_btn.setToolTip(tr('ui.search_placeholder'))
    return search_btn


def create_filters_frame():
    """Create base filters frame."""
    w = QFrame()
    w.setObjectName('filters')
    w.setFixedHeight(55)
    layout = QHBoxLayout(w)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.setContentsMargins(0, 0, 0, 0)
    return w, layout
