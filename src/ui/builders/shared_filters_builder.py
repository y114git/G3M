"""Shared filter widget components for UI builders."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QCheckBox, QSizePolicy

from services.localization_service import tr
from ui.widgets.shared.custom_controls import NoScrollComboBox
from ui.common.styling import get_theme_color, build_tag_checkbox_style, get_border_radius, install_widget_update_handler, get_widget_border_radius
from utils.path_utils import colored_icon


def create_sort_controls(app_state, items=None, config_key=None, include_order_button=True):
    """Create sort combo and optional order button."""
    sort_combo = NoScrollComboBox()
    if items:
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                label, data = item
                sort_combo.addItem(label, data)
            else:
                sort_combo.addItem(str(item))
    if config_key:
        idx = app_state.local_config.get(config_key, 0)
        sort_combo.setCurrentIndex(idx if 0 <= idx < sort_combo.count() else 0)
    sort_btn = None
    if include_order_button:
        sort_btn = QPushButton()
        sort_btn.setObjectName('sortOrderBtn')
        sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sort_btn.setToolTip(tr('ui.sort_direction_tooltip'))
        sort_btn.setAccessibleName(tr('ui.sort_direction_tooltip'))
        sort_btn.setIcon(colored_icon('arrow_down', get_theme_color(app_state.local_config, 'text', '#ffffff')))
        sort_btn.setIconSize(QSize(12, 12))
    return sort_combo, sort_btn


def create_tag_checkboxes(app_state, tag_names):
    """Create tag checkboxes with styling."""
    tags = {n: QCheckBox(tr(f'tags.{n}') if (n != 'gamebanana' and n != 'only_gamebanana') else tr('ui.only_gamebanana')) for n in tag_names}
    style = build_tag_checkbox_style(get_theme_color(app_state.local_config, 'text', '#e8e9eb'))
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


def create_search_button(app_state=None):
    """Create search button."""
    search_btn = QPushButton()
    search_btn.setObjectName('searchBtn')
    search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    search_btn.setToolTip(tr('ui.search_placeholder'))
    search_btn.setAccessibleName(tr('ui.search_placeholder'))
    tc = get_theme_color(app_state.local_config, 'text', '#ffffff') if app_state else '#ffffff'
    search_btn.setIcon(colored_icon('search', tc))
    search_btn.setIconSize(QSize(16, 16))
    return search_btn


def create_downloads_button(app_state=None):
    """Create Downloads button with icon only. Badge count managed externally."""
    btn = QPushButton()
    btn.setObjectName('downloadsBtn')
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tr('downloads.title'))
    btn.setAccessibleName(tr('downloads.title'))
    tc = get_theme_color(app_state.local_config, 'text', '#ffffff') if app_state else '#ffffff'
    btn.setIcon(colored_icon('download', tc))
    btn.setIconSize(QSize(16, 16))
    return btn


def apply_filters_frame_style(frame: QFrame, app_state):
    if not frame or not app_state:
        return

    def _apply_style():
        filter_bg_color = app_state.local_config.get('custom_color_background') or 'rgba(40, 40, 40, 150)'
        filter_border_color = app_state.local_config.get('custom_color_border') or '#039d5b'
        zoom_factor = app_state.local_config.get('ui_scale', 1.0)
        border_width = max(1, int(2 * zoom_factor))
        radius = get_widget_border_radius(frame, get_border_radius(app_state.local_config))
        padding = max(max(1, int(8 * zoom_factor)), (radius * 3 + 9) // 10)
        frame.setStyleSheet(f'QFrame#filters {{ background-color: {filter_bg_color}; border: {border_width}px solid {filter_border_color}; padding: {padding}px; border-radius: {radius}px; }}')

    install_widget_update_handler(frame, _apply_style, attr_name='_filters_frame_style_filter')


def create_filters_frame():
    """Create base filters frame."""
    w = QFrame()
    w.setObjectName('filters')
    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    w.setMinimumWidth(0)
    layout = QHBoxLayout(w)
    layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return w, layout
