"""Shared filter widget components for UI builders."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QCheckBox, QSizePolicy
from services.localization_service import tr
from ui.widgets.shared.custom_controls import NoScrollComboBox
from ui.common.styling import get_theme_color, build_tag_checkbox_style


def create_sort_controls(app_state):
    """Create sort combo and order button."""
    sort_combo = NoScrollComboBox()
    sort_btn = QPushButton('▼')
    sort_btn.setObjectName('sortOrderBtn')
    sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    sort_btn.setToolTip(tr('ui.sort_direction_tooltip'))
    return sort_combo, sort_btn


def create_tag_checkboxes(app_state, tag_names):
    """Create tag checkboxes with styling."""
    tags = {n: QCheckBox(tr(f'tags.{n}') if n != 'gamebanana' else tr('ui.only_gamebanana')) for n in tag_names}
    style = build_tag_checkbox_style(get_theme_color(app_state.local_config, 'text', 'white'))
    for t in tags.values():
        t.setStyleSheet(style)
    return tags


def create_search_button():
    """Create search button."""
    search_btn = QPushButton('🔍')
    search_btn.setObjectName('searchBtn')
    search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    search_btn.setFixedSize(35, 35)
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
