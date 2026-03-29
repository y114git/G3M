"""UI styling utilities and theme management."""

import contextlib
import logging
import os
import weakref

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QThreadPool
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import QLabel

from config.config import (
    DEFAULT_COLORS,
    EMPTY_LAYOUT_MESSAGE_STYLE,
    MOD_WIDGET_STYLE_TEMPLATE,
    UI_COLORS,
)
from config.settings_schema import get_theme_color_key
from utils.mod_utils import get_mod_id
from utils.path_utils import colored_icon


class _WidgetUpdateFilter(QObject):
    def __init__(self, widget, callback) -> None:
        super().__init__(widget)
        self._widget_ref = weakref.ref(widget)
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            widget = self._widget_ref()
            if not widget:
                return False
            try:
                if sip.isdeleted(widget):
                    return False
            except (RuntimeError, AttributeError):
                return False
            self._callback()
        return False


def install_widget_update_handler(widget, callback, attr_name="_widget_update_filter"):
    if not widget:
        return
    if not isinstance(widget, QObject):
        callback()
        return
    existing = getattr(widget, attr_name, None)
    if existing:
        with contextlib.suppress(RuntimeError, TypeError):
            widget.removeEventFilter(existing)
    handler = _WidgetUpdateFilter(widget, callback)
    widget.installEventFilter(handler)
    setattr(widget, attr_name, handler)
    callback()


class _ScrollAreaUpdateFilter(_WidgetUpdateFilter):
    def eventFilter(self, obj, event):
        if event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        ):
            widget = self._widget_ref()
            if not widget:
                return False
            try:
                if sip.isdeleted(widget):
                    return False
            except (RuntimeError, AttributeError):
                return False
            self._callback()
        return False


def install_scroll_area_component_handler(widget, callback, attr_name: str):
    if not widget:
        return
    existing = getattr(widget, attr_name, None)
    if existing:
        with contextlib.suppress(RuntimeError, TypeError):
            widget.removeEventFilter(existing)
    handler = _ScrollAreaUpdateFilter(widget, callback)
    widget.installEventFilter(handler)
    setattr(widget, attr_name, handler)
    callback()


def install_scroll_area_update_handlers(scroll_area, callback, attr_prefix: str):
    install_scroll_area_component_handler(
        scroll_area, callback, attr_name=f"_{attr_prefix}_scroll_filter"
    )
    for suffix, widget in (
        ("viewport", scroll_area.viewport() if scroll_area else None),
        (
            "vertical_scrollbar",
            scroll_area.verticalScrollBar() if scroll_area else None,
        ),
        (
            "horizontal_scrollbar",
            scroll_area.horizontalScrollBar() if scroll_area else None,
        ),
    ):
        if widget:
            install_scroll_area_component_handler(
                widget, callback, attr_name=f"_{attr_prefix}_{suffix}_filter"
            )


def apply_rounded_mask(widget, radius, inset=0):
    if not widget:
        return
    if not isinstance(widget, QObject):
        return
    try:
        if sip.isdeleted(widget):
            return
    except (RuntimeError, AttributeError, TypeError):
        return
    try:
        width = max(0, int(widget.width()))
        height = max(0, int(widget.height()))
    except (RuntimeError, AttributeError, TypeError, ValueError):
        return
    inset_value = max(0, int(inset))
    if width <= (inset_value * 2) or height <= (inset_value * 2):
        if getattr(widget, "_rounded_mask_applied", False):
            with contextlib.suppress(RuntimeError, AttributeError):
                widget.clearMask()
            widget._rounded_mask_applied = False
            widget._rounded_mask_cache_key = None
        return
    radius_value = clamp_border_radius(
        radius, width=width - (inset_value * 2), height=height - (inset_value * 2)
    )
    if radius_value <= 0:
        if getattr(widget, "_rounded_mask_applied", False):
            with contextlib.suppress(RuntimeError, AttributeError):
                widget.clearMask()
            widget._rounded_mask_applied = False
            widget._rounded_mask_cache_key = None
        return
    cache_key = (width, height, inset_value, radius_value)
    if getattr(widget, "_rounded_mask_cache_key", None) == cache_key and getattr(
        widget, "_rounded_mask_applied", False
    ):
        return
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(
            inset_value,
            inset_value,
            width - (inset_value * 2),
            height - (inset_value * 2),
        ),
        radius_value,
        radius_value,
    )
    try:
        widget.setMask(QRegion(path.toFillPolygon().toPolygon()))
        widget._rounded_mask_applied = True
        widget._rounded_mask_cache_key = cache_key
    except (RuntimeError, AttributeError):
        logging.debug("Failed to apply rounded mask to widget")


def install_size_hint_height_sync(
    widget, scroll_area, attr_name="_size_hint_height_filter"
):
    install_widget_update_handler(
        widget,
        lambda target=widget, target_scroll=scroll_area: target_scroll.setMaximumHeight(
            target.sizeHint().height()
        ),
        attr_name=attr_name,
    )


def set_layout_stretch_factors(layout, *factors):
    try:
        for index, factor in enumerate(factors):
            layout.setStretch(index, factor)
    except Exception as e:
        logging.debug(f"set_layout_stretch_factors: Error setting stretch: {e}")


def get_widget_dimensions(widget):
    width = height = None
    if not widget:
        return width, height
    try:
        width = widget.width() or widget.sizeHint().width() or None
    except (RuntimeError, AttributeError, TypeError, ValueError):
        width = None
    try:
        height = widget.height() or widget.sizeHint().height() or None
    except (RuntimeError, AttributeError, TypeError, ValueError):
        height = None
    return width, height


def get_ui_scale_factor(
    config, default: float = 1.0, minimum: float = 0.5, maximum: float = 2.0
) -> float:
    try:
        if config and hasattr(config, "get"):
            value = float(config.get("ui_scale", default) or default)
        else:
            value = float(default)
    except (TypeError, ValueError):
        value = float(default)
    return max(minimum, min(maximum, value))


def get_card_layout_scale(config, default: float = 1.0) -> float:
    raw_scale = get_ui_scale_factor(config, default=default)
    return max(0.85, min(1.55, 1.0 + (raw_scale - 1.0) * 0.7))


def get_card_button_metrics(config) -> tuple[int, int, int]:
    scale = get_card_layout_scale(config)
    return (
        max(96, round(110 * scale)),
        max(32, round(35 * scale)),
        max(13, round(15 * scale)),
    )


def get_widget_border_radius(
    widget, radius: int, border_width: int = 0, margin: int = 0
) -> int:
    width, height = get_widget_dimensions(widget)
    return clamp_border_radius(
        radius, width=width, height=height, border_width=border_width, margin=margin
    )


def generate_widget_style(
    frame_selector,
    bg_color,
    border_color,
    hover_border_color,
    selected_border_color,
    text_color,
    secondary_text_color,
    is_selected=False,
    icon_selector="modIcon",
    frame_border_radius="0px",
    icon_border_radius="0px",
    button_border_radius="0px",
    primary_font_size=14,
    secondary_font_size=14,
    button_width=110,
    button_height=35,
    button_font_size=15,
):
    border_width = "2px"
    current_border_color = selected_border_color if is_selected else border_color
    hover_border_color = selected_border_color if is_selected else hover_border_color
    return MOD_WIDGET_STYLE_TEMPLATE.format(
        frame_selector=frame_selector,
        bg_color=bg_color,
        border_width=border_width,
        border_color=current_border_color,
        hover_border_color=hover_border_color,
        icon_selector=icon_selector,
        secondary_text_color=secondary_text_color,
        text_color=text_color,
        frame_border_radius=frame_border_radius,
        icon_border_radius=icon_border_radius,
        button_border_radius=button_border_radius,
        primary_font_size=primary_font_size,
        secondary_font_size=secondary_font_size,
        button_width=button_width,
        button_height=button_height,
        button_font_size=button_font_size,
    )


def apply_stylesheet_if_changed(
    widget, stylesheet: str, cache_attr: str = "_stylesheet_cache_key"
) -> bool:
    if widget is None:
        return False
    if getattr(widget, cache_attr, None) == stylesheet:
        return False
    widget.setStyleSheet(stylesheet)
    setattr(widget, cache_attr, stylesheet)
    return True


def update_mod_widget_style(widget, frame_selector, parent_app=None):
    config = None
    if parent_app:
        if hasattr(parent_app, "local_config"):
            config = parent_app.local_config
        elif hasattr(parent_app, "app_state") and hasattr(
            parent_app.app_state, "local_config"
        ):
            config = parent_app.app_state.local_config
    if config:
        card_bg_color = get_theme_color(config, "background")
        border_color = get_theme_color(config, "border")
        hover_border_color = get_theme_color(config, "hover")
        selected_border_color = get_theme_color(config, "select")
        text_color = get_theme_color(config, "main_text")
        secondary_text_color = get_theme_color(config, "secondary_text")
    else:
        card_bg_color = DEFAULT_COLORS["background"]
        border_color = DEFAULT_COLORS["border"]
        hover_border_color = DEFAULT_COLORS["hover"]
        selected_border_color = DEFAULT_COLORS["select"]
        text_color = DEFAULT_COLORS["main_text"]
        secondary_text_color = DEFAULT_COLORS["secondary_text"]
    border_radius_val = get_border_radius(config)
    layout_scale = get_card_layout_scale(config)
    primary_font_size = max(12, round(14 * layout_scale))
    secondary_font_size = max(12, round(14 * layout_scale))
    button_width, button_height, button_font_size = get_card_button_metrics(config)
    frame_border_radius_value = get_widget_border_radius(widget, border_radius_val)
    frame_border_radius = f"{frame_border_radius_value}px"
    icon_width, icon_height = get_widget_dimensions(getattr(widget, "icon_label", None))
    icon_border_radius = border_radius_px(
        border_radius_val, width=icon_width or 80, height=icon_height or 80
    )
    button_border_radius = border_radius_px(
        border_radius_val, width=button_width, height=button_height, border_width=2
    )
    is_selected = getattr(widget, "is_selected", False)
    style_sheet = generate_widget_style(
        frame_selector,
        card_bg_color,
        border_color,
        hover_border_color,
        selected_border_color,
        text_color,
        secondary_text_color,
        is_selected,
        "modIcon",
        frame_border_radius,
        icon_border_radius,
        button_border_radius,
        primary_font_size=primary_font_size,
        secondary_font_size=secondary_font_size,
        button_width=button_width,
        button_height=button_height,
        button_font_size=button_font_size,
    )
    apply_stylesheet_if_changed(
        widget, style_sheet, cache_attr="_mod_widget_stylesheet_cache"
    )
    main_layout = getattr(widget, "main_layout", None)
    if main_layout:
        content_margin = max(
            max(8, round(10 * layout_scale)), (frame_border_radius_value * 3 + 9) // 10
        )
        margin_key = (content_margin,) * 4
        if getattr(widget, "_mod_widget_margin_cache", None) != margin_key:
            main_layout.setContentsMargins(*margin_key)
            widget._mod_widget_margin_cache = margin_key


def show_empty_message_in_layout(layout, text, local_config=None, font_size=16):
    empty_text_color = get_theme_color(local_config, "secondary_text") if local_config else DEFAULT_COLORS["secondary_text"]
    parent = layout.parentWidget() if hasattr(layout, "parentWidget") else None
    empty_label = QLabel(text, parent)
    empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_label.setStyleSheet(
        EMPTY_LAYOUT_MESSAGE_STYLE.format(color=empty_text_color, font_size=font_size)
    )
    layout.insertWidget(layout.count() - 1, empty_label)


_theme_color_cache: dict[tuple, str] = {}
_mod_icon_pixmap_cache: dict[tuple, QPixmap] = {}


def get_theme_color(config, color_key, default_color=None):
    """Return themed color from config, falling back to DEFAULT_COLORS."""
    if default_color is None:
        default_color = DEFAULT_COLORS.get(color_key, DEFAULT_COLORS["main_text"])
    if config and hasattr(config, "get"):
        color_config_key = get_theme_color_key(color_key)
        current_value = config.get(color_config_key)
        cache_key = (id(config), color_key, default_color, current_value)
        cached = _theme_color_cache.get(cache_key)
        if cached is not None:
            return cached
        result = current_value or default_color
        _theme_color_cache[cache_key] = result
        return result
    return default_color


def get_launch_status_color(config):
    return get_theme_color(config, "border", UI_COLORS["status_success"])


def get_theme_colors(config, **overrides):
    """Return dict of themed colors, using DEFAULT_COLORS as base."""
    merged = {**DEFAULT_COLORS, **overrides}
    return {key: get_theme_color(config, key, default) for key, default in merged.items()}


def invalidate_theme_color_cache():
    _theme_color_cache.clear()


def get_color_components(color):
    if not isinstance(color, str):
        return None
    qcolor = QColor(color)
    if not qcolor.isValid():
        return None
    has_explicit_alpha = (
        color.startswith("#") and len(color) == 9
    ) or color.lower().startswith("rgba(")
    return (
        qcolor.red(),
        qcolor.green(),
        qcolor.blue(),
        qcolor.alpha(),
        has_explicit_alpha,
    )


def qt_hex_to_display_hex(color: str) -> str:
    if not isinstance(color, str):
        return ""
    normalized = color.strip().upper()
    if not normalized:
        return ""
    if normalized.startswith("#") and len(normalized) == 9:
        qcolor = QColor(normalized)
        if qcolor.isValid():
            return f"#{qcolor.red():02X}{qcolor.green():02X}{qcolor.blue():02X}{qcolor.alpha():02X}"
    return normalized


def display_hex_to_qt_hex(color: str) -> str:
    if not isinstance(color, str):
        return ""
    normalized = color.strip().upper()
    if normalized.startswith("#") and len(normalized) == 9:
        return f"#{normalized[7:9]}{normalized[1:7]}"
    return normalized


def get_border_radius(config, default: int = 7) -> int:
    """Return custom_border_radius from config, or *default* if missing/None."""
    if config and hasattr(config, "get"):
        value = config.get("custom_border_radius", default)
        return default if value is None else value
    return default


def clamp_border_radius(
    radius: int,
    width: int | None = None,
    height: int | None = None,
    border_width: int = 0,
    margin: int = 0,
) -> int:
    try:
        radius_value = max(0, int(radius))
    except (TypeError, ValueError):
        return 0
    try:
        border_value = max(0, int(border_width))
    except (TypeError, ValueError):
        border_value = 0
    try:
        margin_value = max(0, int(margin))
    except (TypeError, ValueError):
        margin_value = 0
    dimensions = []
    for dimension in (width, height):
        if dimension is None:
            continue
        try:
            available = max(0, int(dimension) + (border_value * 2) - (margin_value * 2))
        except (TypeError, ValueError):
            continue
        if available > 0:
            dimensions.append(available)
    if not dimensions:
        return radius_value
    return min(radius_value, min(dimensions) // 2)


def border_radius_px(
    radius: int,
    width: int | None = None,
    height: int | None = None,
    border_width: int = 0,
    margin: int = 0,
) -> str:
    return f"{clamp_border_radius(radius, width=width, height=height, border_width=border_width, margin=margin)}px"


def _normalize_box_values(values) -> tuple[int, int, int, int]:
    if isinstance(values, str):
        values = tuple(part for part in values.replace("px", " ").split() if part)
    elif not isinstance(values, (list, tuple)):
        values = (values,)
    normalized = []
    for value in values:
        try:
            normalized.append(max(0, int(value)))
        except (TypeError, ValueError):
            normalized.append(0)
    if len(normalized) == 1:
        normalized *= 4
    elif len(normalized) == 2:
        normalized = [normalized[0], normalized[1], normalized[0], normalized[1]]
    elif len(normalized) == 3:
        normalized = [normalized[0], normalized[1], normalized[2], normalized[1]]
    else:
        normalized = normalized[:4]
    return tuple(normalized)


def _format_box_values(values) -> str:
    if isinstance(values, str):
        return values
    normalized = _normalize_box_values(values)
    return " ".join(f"{value}px" for value in normalized)


def build_panel_style(
    selector: str, background_color: str, border_radius: int, margin: int = 5
) -> str:
    try:
        margin_value = max(0, int(margin))
    except (TypeError, ValueError):
        margin_value = 0
    return f"QWidget#{selector} {{ background-color: {background_color}; border-radius: {border_radius}px; margin: {margin_value}px; }}"


def apply_panel_style(
    widget,
    config,
    color_key: str = "background",
    fallback: str = "#282828",
    alpha: int = 128,
    margin: int = 5,
):
    if not widget:
        return
    selector = widget.objectName()
    if not selector:
        return
    background = rgba_from_color(
        get_theme_color(config, color_key, fallback),
        alpha=alpha,
        fallback=f"rgba(40, 40, 40, {alpha})",
    )
    radius = get_widget_border_radius(widget, get_border_radius(config))
    widget.setStyleSheet(build_panel_style(selector, background, radius, margin=margin))
    inner_clip_callback = getattr(widget, "_inner_clip_callback", None)
    if callable(inner_clip_callback):
        inner_clip_callback()


def install_panel_style_handler(
    widget,
    config,
    color_key: str = "background",
    fallback: str = "#282828",
    alpha: int = 128,
    margin: int = 5,
    attr_name="_panel_style_filter",
):
    if widget:
        widget._panel_style_params = {
            "config": config,
            "color_key": color_key,
            "fallback": fallback,
            "alpha": alpha,
            "margin": margin,
        }
    install_widget_update_handler(
        widget,
        lambda target=widget: apply_panel_style(
            target,
            config,
            color_key=color_key,
            fallback=fallback,
            alpha=alpha,
            margin=margin,
        ),
        attr_name=attr_name,
    )


def refresh_panel_style(widget) -> bool:
    params = getattr(widget, "_panel_style_params", None)
    if not params:
        return False
    apply_panel_style(
        widget,
        params.get("config"),
        color_key=params.get("color_key", "background"),
        fallback=params.get("fallback", "#282828"),
        alpha=params.get("alpha", 128),
        margin=params.get("margin", 5),
    )
    return True


def refresh_themed_button_icon(button) -> None:
    if not button:
        return
    icon_name = getattr(button, "_themed_icon_name", None)
    app_state = getattr(button, "_themed_icon_app_state", None)
    icon_size = getattr(button, "_themed_icon_size", None)
    if not icon_name or app_state is None or icon_size is None:
        return
    tc = get_theme_color(app_state.local_config, "main_text") if app_state else "#ffffff"
    button.setIcon(colored_icon(icon_name, tc))
    button.setIconSize(icon_size)


def apply_scroll_area_chrome(
    scroll_area,
    viewport_radius: int | None = None,
    scrollbar_radius: int | None = None,
    qss: str | None = None,
    minimum_extent: int = 16,
) -> int:
    if not scroll_area:
        return 0
    vertical_scrollbar = scroll_area.verticalScrollBar()
    scrollbars = tuple(
        scrollbar
        for scrollbar in (vertical_scrollbar, scroll_area.horizontalScrollBar())
        if scrollbar
    )
    if qss:
        for scrollbar in scrollbars:
            scrollbar.setStyleSheet(qss)
    if viewport_radius is not None:
        if viewport := scroll_area.viewport():
            apply_rounded_mask(viewport, viewport_radius)
        effective_scrollbar_radius = (
            viewport_radius if scrollbar_radius is None else scrollbar_radius
        )
        for scrollbar in scrollbars:
            apply_rounded_mask(scrollbar, effective_scrollbar_radius)
    if not vertical_scrollbar:
        return 0
    try:
        if not vertical_scrollbar.isVisible():
            return 0
    except (RuntimeError, AttributeError):
        return 0
    try:
        active_extent = (
            vertical_scrollbar.width() or vertical_scrollbar.sizeHint().width()
        )
    except (RuntimeError, AttributeError):
        active_extent = 0
    return max(minimum_extent, active_extent)


def install_scroll_viewport_clip(
    scroll_area, container, config, inset: int, attr_name="_viewport_clip_filter"
):
    def _apply():
        base_radius = get_border_radius(config)
        radius = get_widget_border_radius(container, base_radius)
        apply_scroll_area_chrome(
            scroll_area, max(0, radius - inset), scrollbar_radius=base_radius
        )

    container._inner_clip_callback = _apply
    install_scroll_area_update_handlers(
        scroll_area, _apply, attr_name.removeprefix("_").removesuffix("_filter")
    )


def _scrollbar_radii(
    radius: int,
    thickness: int,
    start_margin: int,
    end_margin: int,
    handle_margin: int = 1,
) -> tuple[int, int]:
    extent = max(0, thickness - start_margin - end_margin)
    handle_extent = max(0, extent - (handle_margin * 2))
    return clamp_border_radius(
        radius, width=extent, height=extent
    ), clamp_border_radius(radius, width=handle_extent, height=handle_extent)


def build_scrollbar_qss(
    handle_color: str,
    radius: int,
    thickness: int = 16,
    background: str = "transparent",
    vertical_margin=(0, 0, 0, 0),
    horizontal_margin=(0, 0, 0, 0),
    min_handle: int = 25,
    include_corner: bool = False,
) -> str:
    _vertical_top, vertical_right, _vertical_bottom, vertical_left = (
        _normalize_box_values(vertical_margin)
    )
    horizontal_top, _horizontal_right, horizontal_bottom, _horizontal_left = (
        _normalize_box_values(horizontal_margin)
    )

    handle_margin = 1
    vertical_radius, vertical_handle_radius = _scrollbar_radii(
        radius, thickness, vertical_left, vertical_right, handle_margin=handle_margin
    )
    horizontal_radius, horizontal_handle_radius = _scrollbar_radii(
        radius,
        thickness,
        horizontal_top,
        horizontal_bottom,
        handle_margin=handle_margin,
    )
    corner_rule = (
        ""
        if not include_corner
        else """
                QAbstractScrollArea::corner {
                    background: transparent;
                    border: none;
                }"""
    )
    return f"""
                QScrollBar:vertical {{
                    border: none;
                    background: {background};
                    width: {thickness}px;
                    margin: {_format_box_values(vertical_margin)};
                    border-radius: {vertical_radius}px;
                }}
                QScrollBar::handle:vertical {{
                    background-color: {handle_color};
                    min-height: {min_handle}px;
                    border: none;
                    border-radius: {vertical_handle_radius}px;
                    margin: {handle_margin}px;
                }}
                QScrollBar:horizontal {{
                    border: none;
                    background: {background};
                    height: {thickness}px;
                    margin: {_format_box_values(horizontal_margin)};
                    border-radius: {horizontal_radius}px;
                }}
                QScrollBar::handle:horizontal {{
                    background-color: {handle_color};
                    min-width: {min_handle}px;
                    border: none;
                    border-radius: {horizontal_handle_radius}px;
                    margin: {handle_margin}px;
                }}
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical,
                QScrollBar::add-line:horizontal,
                QScrollBar::sub-line:horizontal,
                QScrollBar::up-arrow:vertical,
                QScrollBar::down-arrow:vertical,
                QScrollBar::left-arrow:horizontal,
                QScrollBar::right-arrow:horizontal,
                QScrollBar::add-page:vertical,
                QScrollBar::sub-page:vertical,
                QScrollBar::add-page:horizontal,
                QScrollBar::sub-page:horizontal {{
                    background: transparent;
                    border: none;
                    width: 0px;
                    height: 0px;
                }}{corner_rule}
            """


def get_section_line_color(config) -> str:
    raw = get_theme_color(config, "elements")
    if components := get_color_components(raw):
        r, g, b, _, _ = components
        return f"rgba({r},{g},{b},0.45)"
    return "rgba(34,34,34,0.45)"


def rgba_from_color(
    color: str, alpha: int = 128, fallback: str = "rgba(40, 40, 40, 128)"
) -> str:
    if components := get_color_components(color):
        r, g, b, parsed_alpha, has_explicit_alpha = components
        return f"rgba({r}, {g}, {b}, {parsed_alpha if has_explicit_alpha else alpha})"
    return fallback


def build_tag_checkbox_style(
    text_color: str, font_size: int = 14, indicator_size: int = 18, spacing: int = 5
) -> str:
    return f"\n            QCheckBox {{\n                color: {text_color};\n                font-size: {font_size}px;\n                spacing: {spacing}px;\n            }}\n            QCheckBox::indicator {{\n                width: {indicator_size}px;\n                height: {indicator_size}px;\n            }}\n        "


def build_button_style(
    obj_name: str,
    bg_color: str,
    hover_color: str,
    text_color: str = DEFAULT_COLORS["main_text"],
    border: str = DEFAULT_COLORS["border"],
    width: int | None = 110,
    height: int | None = 35,
    font_size: int = 15,
    bold: bool = True,
    border_radius: int = 0,
    border_width: int = 2,
    border_style: str = "solid",
    padding: str = "1px",
    checked_bg_color: str | None = None,
    checked_border_color: str | None = None,
    checked_border_width: int | None = None,
    checked_border_style: str | None = None,
) -> str:
    """Build common button stylesheet pattern."""
    weight = "bold" if bold else "normal"
    clamped_border_radius = clamp_border_radius(
        border_radius, width=width, height=height, border_width=border_width
    )
    size_rules = []
    if width is not None:
        size_rules.append(f"min-width: {width}px;")
        size_rules.append(f"max-width: {width}px;")
    if height is not None:
        size_rules.append(f"min-height: {height}px;")
        size_rules.append(f"max-height: {height}px;")
    checked_rule = ""
    if (
        checked_bg_color is not None
        or checked_border_color is not None
        or checked_border_width is not None
    ):
        checked_rule = f"""
        QPushButton#{obj_name}:checked {{
            background-color: {checked_bg_color or bg_color};
            border: {(checked_border_width if checked_border_width is not None else border_width)}px {(checked_border_style or border_style)} {checked_border_color or border};
        }}
    """
    return f"""
        QPushButton#{obj_name} {{
            background-color: {bg_color};
            color: {text_color};
            border: {border_width}px {border_style} {border};
            border-radius: {clamped_border_radius}px;
            font-weight: {weight};
            {" ".join(size_rules)}
            font-size: {font_size}px;
            padding: {padding};
        }}
        QPushButton#{obj_name}:hover {{
            background-color: {hover_color};
        }}
        {checked_rule}
        QPushButton#{obj_name}:disabled {{
            background-color: #3b3b3b;
            color: #808080;
            border-color: #808080;
        }}
    """


def clear_layout_widgets(layout, keep_last_n=1, hide_instead_of_delete=False):
    if not layout:
        return
    end_index = layout.count() - keep_last_n
    widgets_to_remove = []
    for i in reversed(range(end_index)):
        item = layout.itemAt(i)
        if item:
            widget = item.widget()
            if widget:
                widgets_to_remove.append(widget)
            else:
                layout.removeItem(item)
    for widget in widgets_to_remove:
        try:
            layout.removeWidget(widget)
            if hide_instead_of_delete:
                widget.hide()
                widget.setParent(None)
            else:
                widget.setParent(None)
                widget.deleteLater()
        except (RuntimeError, AttributeError) as e:
            logging.debug(f"clear_layout_widgets: Error removing widget: {e}")


def round_pixmap(pixmap, radius, border_width=0, border_color=None):
    """Clip a QPixmap to rounded corners, optionally drawing a border ring.

    When border_width > 0 and border_color is provided, the image is
    scaled into the inner area and a border ring is painted on top,
    producing a pixel-perfect result in a single pixmap.
    """
    if pixmap.isNull():
        return pixmap
    has_border = border_width > 0 and border_color
    if radius <= 0 and not has_border:
        return pixmap
    from PyQt6.QtGui import QImage

    w, h = pixmap.width(), pixmap.height()
    radius = clamp_border_radius(radius, width=w, height=h)
    img = QImage(pixmap.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if has_border:
        bw = border_width
        inner_r = max(0, radius - bw)
        inner_rect = QRectF(bw, bw, w - 2 * bw, h - 2 * bw)
        if radius > 0:
            clip = QPainterPath()
            clip.addRoundedRect(inner_rect, inner_r, inner_r)
            p.setClipPath(clip)
        else:
            p.setClipRect(inner_rect)
        scaled = pixmap.scaled(
            int(w - 2 * bw),
            int(h - 2 * bw),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        p.drawPixmap(int(bw), int(bw), scaled)
        p.setClipping(False)
        pen = QPen(QColor(border_color), bw)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        half = bw / 2
        if radius > 0:
            p.drawRoundedRect(
                QRectF(half, half, w - bw, h - bw), radius - half, radius - half
            )
        else:
            p.drawRect(QRectF(half, half, w - bw, h - bw))
    else:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        p.setClipPath(path)
        p.drawPixmap(0, 0, pixmap)
    p.end()
    return QPixmap.fromImage(img)


def load_mod_icon_universal(
    icon_label,
    mod_data,
    size=80,
    local_fallback=None,
    border_radius=0,
    border_width=0,
    border_color=None,
    prefer_screenshot=False,
):
    from utils.path_utils import resource_path

    def _crop_and_scale_pixmap(pixmap, allow_empty=False):
        source_width = pixmap.width()
        source_height = pixmap.height()
        if source_width <= 0 or source_height <= 0:
            if allow_empty:
                return pixmap.scaled(
                    target_width,
                    target_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return pixmap
        source_ratio = source_width / max(1, source_height)
        target_ratio = target_width / max(1, target_height)
        if source_ratio > target_ratio:
            crop_height = source_height
            crop_width = max(1, round(crop_height * target_ratio))
        else:
            crop_width = source_width
            crop_height = max(1, round(crop_width / target_ratio))
        cropped = pixmap.copy(
            (source_width - crop_width) // 2,
            (source_height - crop_height) // 2,
            crop_width,
            crop_height,
        )
        return cropped.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _stat_key(path):
        try:
            stat_result = os.stat(path)
            return stat_result.st_mtime_ns, stat_result.st_size
        except OSError:
            return None

    def _cached_prepared_pixmap(path=None, *, allow_empty=False, fill=None):
        cache_key = (
            path,
            _stat_key(path) if path else None,
            target_width,
            target_height,
            border_radius,
            border_width,
            border_color,
            fill,
        )
        cached = _mod_icon_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached
        if path:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return None
            pixmap = _crop_and_scale_pixmap(pixmap, allow_empty=allow_empty)
        else:
            pixmap = QPixmap(target_width, target_height)
            pixmap.fill(QColor(fill or "#333"))
        pixmap = (
            round_pixmap(pixmap, border_radius, border_width, border_color)
            if (border_radius > 0 or border_width > 0)
            else pixmap
        )
        _mod_icon_pixmap_cache[cache_key] = pixmap
        return pixmap

    if isinstance(size, (tuple, list)):
        target_width = max(1, int(size[0]))
        target_height = max(1, int(size[1]))
    else:
        target_width = max(1, int(size))
        target_height = target_width

    assets_icon_path = resource_path("assets/icons/icon.ico")
    default_pixmap = None
    for default_icon_path in (assets_icon_path,):
        if os.path.exists(default_icon_path):
            try:
                default_pixmap = _cached_prepared_pixmap(
                    default_icon_path, allow_empty=True
                )
                if default_pixmap is not None:
                    break
            except Exception as e:
                logging.debug(
                    f"load_mod_icon_universal: Error loading default icon from {default_icon_path}: {e}"
                )
                default_pixmap = None
    if default_pixmap is None:
        default_pixmap = _cached_prepared_pixmap(fill="#333")
    icon_label.setPixmap(default_pixmap)
    try:
        screenshots = getattr(mod_data, "screenshots_url", None) or []
        preferred_screenshot = (
            next(
                (url for url in screenshots if isinstance(url, str) and url.strip()),
                None,
            )
            if prefer_screenshot
            else None
        )
        icon_path = getattr(mod_data, "icon_path", None)
        icon_source = preferred_screenshot or getattr(mod_data, "icon", None)
        local_icon_to_load = None
        if icon_source and (not icon_source.startswith(("http://", "https://"))):
            if os.path.isabs(icon_source):
                local_icon_to_load = icon_source
            else:
                key = get_mod_id(mod_data)
                is_local_key = key and isinstance(key, str) and key.startswith("local_")
                if is_local_key:
                    mod_folder_path = None
                    try:
                        if hasattr(mod_data, "folder_path"):
                            mod_folder_path = mod_data.folder_path
                    except Exception as e:
                        logging.debug(
                            f"load_mod_icon_universal: Error getting folder_path from mod_data: {e}"
                        )
                    if mod_folder_path and os.path.isdir(mod_folder_path):
                        resolved_path = os.path.normpath(
                            os.path.join(mod_folder_path, icon_source)
                        )
                        if os.path.exists(resolved_path):
                            local_icon_to_load = resolved_path
                        else:
                            local_icon_to_load = icon_source
                    else:
                        local_icon_to_load = icon_source
                else:
                    local_icon_to_load = icon_source
        elif icon_path:
            local_icon_to_load = icon_path
        if local_icon_to_load and os.path.exists(local_icon_to_load):
            try:
                pixmap = _cached_prepared_pixmap(local_icon_to_load)
                if pixmap is not None:
                    icon_label.setPixmap(pixmap)
                    return
            except Exception as e:
                logging.debug(
                    f"load_mod_icon_universal: Error loading pixmap from {local_icon_to_load}: {e}"
                )
        if (
            icon_source
            and isinstance(icon_source, str)
            and icon_source.startswith(("http://", "https://"))
        ):
            try:
                from ui.utils.image_loader import ImageLoaderRunnable
                from workers import WorkerSignals

                pool = QThreadPool.globalInstance()
                signals = WorkerSignals(icon_label)
                label_ref = weakref.ref(icon_label)

                def _on_loaded_image(img):
                    try:
                        lbl = label_ref()
                        if not lbl:
                            return
                        try:
                            if sip.isdeleted(lbl):
                                return
                        except (RuntimeError, AttributeError):
                            return
                        try:
                            if not hasattr(lbl, "parent") or (
                                hasattr(lbl, "parent")
                                and lbl.parent() is None
                                and (not hasattr(lbl, "window"))
                            ):
                                logging.debug(
                                    "Widget has no parent or window, but continuing"
                                )
                        except (RuntimeError, AttributeError):
                            return
                        if img is not None and (
                            not getattr(img, "isNull", lambda: True)()
                        ):
                            pm = QPixmap.fromImage(img)
                            if not pm.isNull():
                                scaled_pixmap = _crop_and_scale_pixmap(pm)
                                lbl.setPixmap(
                                    round_pixmap(
                                        scaled_pixmap,
                                        border_radius,
                                        border_width,
                                        border_color,
                                    )
                                    if (border_radius > 0 or border_width > 0)
                                    else scaled_pixmap
                                )
                            else:
                                _try_local_fallback()
                        else:
                            _try_local_fallback()
                    except (RuntimeError, AttributeError) as e:
                        logging.debug(
                            f"load_mod_icon_universal: Widget deleted during image load: {e}"
                        )
                    except Exception as e:
                        logging.debug(
                            f"load_mod_icon_universal: Error setting pixmap: {e}"
                        )

                def _try_local_fallback():
                    fallback_paths = []
                    for candidate in (local_fallback, icon_path):
                        if candidate and candidate not in fallback_paths:
                            fallback_paths.append(candidate)
                    for fallback_path in fallback_paths:
                        if not os.path.exists(fallback_path):
                            continue
                        try:
                            lbl = label_ref()
                            if lbl and not sip.isdeleted(lbl):
                                pm = QPixmap(fallback_path)
                                if not pm.isNull():
                                    fb_pm = _crop_and_scale_pixmap(pm)
                                    lbl.setPixmap(
                                        round_pixmap(
                                            fb_pm,
                                            border_radius,
                                            border_width,
                                            border_color,
                                        )
                                        if (border_radius > 0 or border_width > 0)
                                        else fb_pm
                                    )
                                    return
                        except (RuntimeError, AttributeError):
                            return

                def _on_error(url, err):
                    logging.debug(
                        f"load_mod_icon_universal: Failed to load image from URL {url}: {err}"
                    )
                    _try_local_fallback()

                signals.result.connect(_on_loaded_image)
                signals.error.connect(_on_error)
                runnable = ImageLoaderRunnable(icon_source, signals)
                icon_label._icon_loader_signals = signals
                icon_label._icon_loader_runnable = runnable

                def _cleanup_refs():
                    try:
                        signals.result.disconnect(_on_loaded_image)
                        signals.error.disconnect(_on_error)
                    except (TypeError, RuntimeError) as e:
                        logging.debug(
                            f"load_mod_icon_universal: Error disconnecting signals in cleanup: {e}"
                        )
                    try:
                        if hasattr(icon_label, "_icon_loader_signals"):
                            del icon_label._icon_loader_signals
                        if hasattr(icon_label, "_icon_loader_runnable"):
                            del icon_label._icon_loader_runnable
                    except Exception as e:
                        logging.debug(
                            f"load_mod_icon_universal: Error cleaning up icon loader attributes: {e}"
                        )
                    try:
                        if pool is not None and pool.activeThreadCount() > 0:
                            pool.waitForDone(1000)
                    except Exception as e:
                        logging.debug(
                            f"load_mod_icon_universal: Error waiting for pool in cleanup: {e}"
                        )

                try:
                    icon_label.destroyed.connect(_cleanup_refs)
                except Exception as e:
                    logging.debug(
                        f"load_mod_icon_universal: Error connecting destroyed signal: {e}"
                    )
                if pool is not None:
                    pool.start(runnable)
            except Exception as e:
                logging.debug(
                    f"load_mod_icon_universal: Error setting up async icon loader for {icon_source}: {e}"
                )
    except Exception as e:
        logging.debug(f"load_mod_icon_universal: Unexpected error: {e}")
