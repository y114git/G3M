"""Shared filter widget components for UI builders."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
)

from config.config import CYOP_AFOM_TAG, DEFAULT_COLORS, FALLBACK_FRAME_BG
from services.localization_service import tr
from ui.common.styling import (
    build_tag_checkbox_style,
    get_border_radius,
    get_theme_color,
    get_widget_border_radius,
    install_widget_update_handler,
)
from ui.widgets.shared.custom_controls import NoScrollComboBox
from utils.path_utils import colored_icon


def _install_themed_button_icon(
    button: QPushButton, icon_name: str, app_state, icon_size: QSize
) -> None:
    if not button:
        return
    button._themed_icon_name = icon_name
    button._themed_icon_app_state = app_state
    button._themed_icon_size = icon_size
    install_widget_update_handler(
        button,
        lambda target=button: (
            _apply_themed_button_icon(
                target,
                getattr(target, "_themed_icon_name", icon_name),
                getattr(target, "_themed_icon_app_state", app_state),
                getattr(target, "_themed_icon_size", icon_size),
            )
        ),
        attr_name=f"_{icon_name}_button_icon_filter",
    )


def _apply_themed_button_icon(
    button: QPushButton, icon_name: str, app_state, icon_size: QSize
) -> None:
    tc = (
        get_theme_color(app_state.local_config, "main_text")
        if app_state
        else "#ffffff"
    )
    button.setIcon(colored_icon(icon_name, tc))
    button.setIconSize(icon_size)


def set_themed_button_icon(
    button: QPushButton, icon_name: str, app_state=None, icon_size: QSize | None = None
) -> None:
    """Update a themed button icon and keep its theme-refresh state in sync."""
    if not button:
        return
    button._themed_icon_name = icon_name
    if app_state is not None:
        button._themed_icon_app_state = app_state
    size = icon_size or getattr(button, "_themed_icon_size", None) or QSize(16, 16)
    button._themed_icon_size = size
    target_state = getattr(button, "_themed_icon_app_state", app_state)
    _apply_themed_button_icon(button, icon_name, target_state, size)


def create_sort_controls(
    app_state, items=None, config_key=None, include_order_button=True
):
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
    sort_combo.setToolTip(tr("tooltips.sort_mode"))
    sort_btn = None
    if include_order_button:
        sort_btn = QPushButton()
        sort_btn.setObjectName("sortOrderBtn")
        sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sort_btn.setToolTip(tr("ui.sort_direction_tooltip"))
        sort_btn.setAccessibleName(tr("ui.sort_direction_tooltip"))
        _install_themed_button_icon(sort_btn, "arrow_down", app_state, QSize(12, 12))
    return sort_combo, sort_btn


def create_tag_checkboxes(app_state, tag_names):
    """Create tag checkboxes with styling."""
    tags = {}
    for item in tag_names:
        if isinstance(item, tuple):
            widget_key, tag_value, label_key = item
            label = tr(label_key)
        else:
            widget_key = item
            tag_value = CYOP_AFOM_TAG if item == "cyop_afom" else item
            label = (
                tr(f"tags.{widget_key}")
                if widget_key not in ("gamebanana", "only_gamebanana")
                else tr("ui.only_gamebanana")
            )
        checkbox = QCheckBox(label)
        checkbox._tag_value = tag_value
        tags[widget_key] = checkbox
    style = build_tag_checkbox_style(
        get_theme_color(app_state.local_config, "main_text")
    )
    for t in tags.values():
        t.setStyleSheet(style)
        t.setToolTip(tr("tooltips.filter_by_tag"))
    return tags


def set_pizzatower_only_tag_visibility(checkbox: QCheckBox | None, visible: bool) -> None:
    """Show CYOP/AFOM tag only for Pizza Tower and clear stale checked state."""
    if checkbox is None:
        return
    blocked = checkbox.blockSignals(True)
    try:
        if not visible and checkbox.isChecked():
            checkbox.setChecked(False)
        checkbox.setVisible(visible)
    finally:
        checkbox.blockSignals(blocked)


def create_modgame_combo(app_state, games_list, config_key=None):
    """Create game selection combo."""
    modgame_combo = QComboBox()
    populate_game_combo(
        modgame_combo,
        games_list,
        app_state.local_config.get(config_key, "deltarune") if config_key else None,
    )
    modgame_combo.setToolTip(tr("tooltips.select_game"))
    return modgame_combo


def populate_game_combo(
    combo: QComboBox, games_list, current_game_id: str | None = None
):
    """Fill a combo with game entries or (label, data) tuples."""

    combo.clear()
    for item in games_list:
        if hasattr(item, "display_name") and hasattr(item, "id"):
            combo.addItem(item.display_name, item.id)
            continue
        name, data = item
        combo.addItem(
            tr(f"ui.{name}") if isinstance(name, str) and not name.isupper() else name,
            data,
        )
    if current_game_id is not None:
        game_idx = combo.findData(current_game_id)
        combo.setCurrentIndex(max(game_idx, 0))


def create_search_button(app_state=None):
    """Create search button."""
    search_btn = QPushButton()
    search_btn.setObjectName("searchBtn")
    search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    search_btn.setToolTip(tr("ui.search_placeholder"))
    search_btn.setAccessibleName(tr("ui.search_placeholder"))
    _install_themed_button_icon(search_btn, "search", app_state, QSize(16, 16))
    return search_btn


def create_blocklist_button(app_state=None):
    """Create Blocklist button with icon only."""
    btn = QPushButton()
    btn.setObjectName("blocklistBtn")
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tr("ui.blocklist"))
    btn.setAccessibleName(tr("ui.blocklist"))
    _install_themed_button_icon(btn, "block", app_state, QSize(22, 22))
    return btn


def create_downloads_button(app_state=None):
    """Create Downloads button with icon only. Badge count managed externally."""
    btn = QPushButton()
    btn.setObjectName("downloadsBtn")
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tr("downloads.title"))
    btn.setAccessibleName(tr("downloads.title"))
    _install_themed_button_icon(btn, "download", app_state, QSize(22, 22))
    return btn


def create_game_versions_button(app_state=None):
    """Create Game Versions button with icon only."""
    btn = QPushButton()
    btn.setObjectName("gameVersionsBtn")
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tr("game_versions.title"))
    btn.setAccessibleName(tr("game_versions.title"))
    _install_themed_button_icon(btn, "filerestore", app_state, QSize(22, 22))
    return btn


def create_modding_tools_button(app_state=None):
    """Create Modding Tools button with icon only."""
    btn = QPushButton()
    btn.setObjectName("moddingToolsBtn")
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tr("modding_tools.title"))
    btn.setAccessibleName(tr("modding_tools.title"))
    _install_themed_button_icon(btn, "tool", app_state, QSize(22, 22))
    return btn


def apply_filters_frame_style(frame: QFrame, app_state):
    if not frame or not app_state:
        return

    def _apply_style():
        filter_bg_color = (
            app_state.local_config.get("custom_background_color") or FALLBACK_FRAME_BG
        )
        filter_border_color = (
            app_state.local_config.get("custom_border_color")
            or DEFAULT_COLORS["border"]
        )
        zoom_factor = app_state.local_config.get("ui_scale", 1.0)
        border_width = max(1, int(2 * zoom_factor))
        radius = get_widget_border_radius(
            frame, get_border_radius(app_state.local_config)
        )
        padding = max(max(1, int(8 * zoom_factor)), (radius * 3 + 9) // 10)
        frame.setStyleSheet(
            f"QFrame#filters {{ background-color: {filter_bg_color}; border: {border_width}px solid {filter_border_color}; padding: {padding}px; border-radius: {radius}px; }}"
        )

    install_widget_update_handler(
        frame, _apply_style, attr_name="_filters_frame_style_filter"
    )


def create_filters_frame():
    """Create base filters frame."""
    w = QFrame()
    w.setObjectName("filters")
    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    w.setMinimumWidth(0)
    layout = QHBoxLayout(w)
    layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return w, layout
