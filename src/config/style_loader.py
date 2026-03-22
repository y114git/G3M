import contextlib
import logging
import os
import re
import tempfile

from PyQt6.QtCore import QFile, QIODevice

from config.constants import (
    ARROW_DOWN_SVG_TEMPLATE,
    ARROW_UP_SVG_TEMPLATE,
    STYLES_TEMPLATE_SUBDIR,
)
from ui.common.styling import border_radius_px
from utils.path_utils import resource_path

logger = logging.getLogger(__name__)
_last_arrow_color = None
_qss_cache: dict[str, str] = {}
_stylesheet_cache: dict[tuple, str] = {}


def _write_arrow_svgs(icons_dir: str, text_color: str) -> tuple[str, str]:
    os.makedirs(icons_dir, exist_ok=True)
    down_path = os.path.join(icons_dir, "arrow_down.svg")
    up_path = os.path.join(icons_dir, "arrow_up.svg")
    for template, path in [
        (ARROW_DOWN_SVG_TEMPLATE, down_path),
        (ARROW_UP_SVG_TEMPLATE, up_path),
    ]:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=icons_dir, suffix=".svg")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(template.format(color=text_color))
            os.replace(tmp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    return down_path, up_path


def _ensure_arrow_svgs(text_color: str) -> tuple[str, str]:
    global _last_arrow_color
    temp_icons_dir = os.path.join(tempfile.gettempdir(), "deltahub_arrows")
    down_path = os.path.join(temp_icons_dir, "arrow_down.svg")
    up_path = os.path.join(temp_icons_dir, "arrow_up.svg")
    if (
        _last_arrow_color == text_color
        and os.path.exists(down_path)
        and os.path.exists(up_path)
    ):
        return down_path.replace("\\", "/"), up_path.replace("\\", "/")
    try:
        dp, up = _write_arrow_svgs(temp_icons_dir, text_color)
        _last_arrow_color = text_color
        return dp.replace("\\", "/"), up.replace("\\", "/")
    except Exception:
        logger.exception(
            "Failed to write temporary arrow SVGs; falling back to data URIs"
        )
    import base64

    down_data = base64.b64encode(
        ARROW_DOWN_SVG_TEMPLATE.format(color=text_color).encode("utf-8")
    ).decode("ascii")
    up_data = base64.b64encode(
        ARROW_UP_SVG_TEMPLATE.format(color=text_color).encode("utf-8")
    ).decode("ascii")
    return (
        f"data:image/svg+xml;base64,{down_data}",
        f"data:image/svg+xml;base64,{up_data}",
    )


def _load_qss_template(filename: str) -> str:
    if filename in _qss_cache:
        return _qss_cache[filename]
    qss_path = resource_path(f"{STYLES_TEMPLATE_SUBDIR}/{filename}")
    if not os.path.exists(qss_path):
        raise FileNotFoundError(f"QSS template not found: {qss_path}")
    file = QFile(qss_path)
    if not file.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        raise OSError(f"Failed to open QSS file: {qss_path}")
    content = file.readAll().data().decode("utf-8")
    file.close()
    _qss_cache[filename] = content
    return content


def _apply_template_replacements(template: str, replacements: dict[str, str]) -> str:
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def invalidate_stylesheet_cache():
    _qss_cache.clear()
    _stylesheet_cache.clear()


def _parse_px_value(value: str, default: int = 0) -> int:
    try:
        return max(0, int(str(value).replace("px", "").strip()))
    except TypeError, ValueError:
        return default


def _scale_px(value: int, zoom_factor: float) -> int:
    return max(1, int(int(value) * zoom_factor))


def build_stylesheet(
    frame_bg_color: str,
    button_color: str,
    border_color: str,
    button_hover_color: str,
    main_text_color: str,
    font_family_main: str,
    font_size_main: int,
    font_size_small: int,
    checkbox_checked_color: str,
    scroll_handle_color: str,
    tooltip_bg_color: str = "rgba(40, 40, 40, 230)",
    scroll_groove_color: str = "rgba(40, 40, 40, 40)",
    zoom_factor: float = 1.0,
    custom_border_radius: str = "7px",
) -> str:
    cache_key = (
        frame_bg_color,
        button_color,
        border_color,
        button_hover_color,
        main_text_color,
        font_family_main,
        font_size_main,
        font_size_small,
        checkbox_checked_color,
        scroll_handle_color,
        tooltip_bg_color,
        scroll_groove_color,
        zoom_factor,
        custom_border_radius,
    )
    if cache_key in _stylesheet_cache:
        return _stylesheet_cache[cache_key]
    main_template = _load_qss_template("main.qss")
    scrollbar_template = _load_qss_template("scrollbar.qss")
    arrow_down_path, arrow_up_path = _ensure_arrow_svgs(main_text_color)
    border_radius_value = _parse_px_value(custom_border_radius)
    title_bar_radius = border_radius_px(border_radius_value, height=38, border_width=2)
    title_bar_menu_button_radius = border_radius_px(
        border_radius_value, height=20, border_width=1
    )
    title_bar_window_button_radius = "__TITLE_BAR_WINDOW_BUTTON_RADIUS__"
    title_bar_popup_radius = border_radius_px(
        border_radius_value, height=28, border_width=2
    )
    title_bar_popup_item_radius = border_radius_px(border_radius_value, height=22)
    button_border_radius = border_radius_px(
        border_radius_value, height=30, border_width=2
    )
    add_localization_button_radius = border_radius_px(
        border_radius_value, width=33, height=33, border_width=2
    )
    top_refresh_button_radius = border_radius_px(
        border_radius_value, width=40, height=40, border_width=2
    )
    field_border_radius = border_radius_px(
        border_radius_value, height=30, border_width=2
    )
    tab_border_radius = border_radius_px(border_radius_value, height=25, border_width=2)
    editor_border_radius = border_radius_px(
        border_radius_value, height=100, border_width=2
    )
    checkbox_indicator_radius = border_radius_px(
        border_radius_value, width=18, height=18, border_width=2
    )
    scrollbar_radius = border_radius_px(
        border_radius_value, width=16, height=16, margin=1
    )
    main_stylesheet = _apply_template_replacements(
        main_template,
        {
            "%frame_bg_color%": frame_bg_color,
            "%button_color%": button_color,
            "%border_color%": border_color,
            "%button_hover_color%": button_hover_color,
            "%main_text_color%": main_text_color,
            "%font_family_main%": font_family_main,
            "%font_size_main%": str(font_size_main),
            "%font_size_small%": str(font_size_small),
            "%checkbox_checked_color%": checkbox_checked_color,
            "%tooltip_bg_color%": tooltip_bg_color,
            "%custom_border_radius%": custom_border_radius,
            "%title_bar_radius%": title_bar_radius,
            "%title_bar_menu_button_radius%": title_bar_menu_button_radius,
            "%title_bar_window_button_radius%": title_bar_window_button_radius,
            "%title_bar_popup_radius%": title_bar_popup_radius,
            "%title_bar_popup_item_radius%": title_bar_popup_item_radius,
            "%button_border_radius%": button_border_radius,
            "%add_localization_button_radius%": add_localization_button_radius,
            "%top_refresh_button_radius%": top_refresh_button_radius,
            "%field_border_radius%": field_border_radius,
            "%tab_border_radius%": tab_border_radius,
            "%editor_border_radius%": editor_border_radius,
            "%checkbox_indicator_radius%": checkbox_indicator_radius,
            "%arrow_down_path%": arrow_down_path,
            "%arrow_up_path%": arrow_up_path,
        },
    )
    scrollbar_stylesheet = _apply_template_replacements(
        scrollbar_template,
        {
            "%scroll_handle_color%": scroll_handle_color,
            "%scroll_groove_color%": scroll_groove_color,
            "%scrollbar_radius%": scrollbar_radius,
        },
    )
    combined = main_stylesheet + scrollbar_stylesheet
    if zoom_factor != 1.0:
        combined = re.sub(
            r"(\d+)px",
            lambda m: f"{max(1, int(int(m.group(1)) * zoom_factor))}px",
            combined,
        )
    scaled_title_bar_window_button_radius = border_radius_px(
        border_radius_value,
        width=_scale_px(26, zoom_factor),
        height=_scale_px(26, zoom_factor),
        border_width=_scale_px(2, zoom_factor),
    )
    combined = combined.replace(
        "__TITLE_BAR_WINDOW_BUTTON_RADIUS__", scaled_title_bar_window_button_radius
    )
    _stylesheet_cache[cache_key] = combined
    return combined
