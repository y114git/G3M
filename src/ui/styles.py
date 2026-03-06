import os
import re
import tempfile
from PyQt6.QtCore import QFile, QIODevice
from ui.common.styling import border_radius_px
from utils.path_utils import resource_path

_ARROW_DOWN_SVG = '<?xml version="1.0" encoding="utf-8"?>\n<svg fill="{color}" width="800px" height="800px" viewBox="-6.5 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">\n<path d="M18.813 11.406l-7.906 9.906c-0.75 0.906-1.906 0.906-2.625 0l-7.906-9.906c-0.75-0.938-0.375-1.656 0.781-1.656h16.875c1.188 0 1.531 0.719 0.781 1.656z"></path>\n</svg>'

_ARROW_UP_SVG = '<?xml version="1.0" encoding="utf-8"?>\n<svg fill="{color}" width="800px" height="800px" viewBox="-6.5 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">\n<g transform="translate(0,32) scale(1,-1)"><path d="M18.813 11.406l-7.906 9.906c-0.75 0.906-1.906 0.906-2.625 0l-7.906-9.906c-0.75-0.938-0.375-1.656 0.781-1.656h16.875c1.188 0 1.531 0.719 0.781 1.656z"></path></g>\n</svg>'

_last_arrow_color = None


def _write_arrow_svgs(icons_dir: str, text_color: str) -> tuple[str, str]:
    """Write arrow SVG files into *icons_dir*. Raises on any I/O failure."""
    os.makedirs(icons_dir, exist_ok=True)
    down_path = os.path.join(icons_dir, 'arrow_down.svg')
    up_path = os.path.join(icons_dir, 'arrow_up.svg')
    for template, path in [(_ARROW_DOWN_SVG, down_path), (_ARROW_UP_SVG, up_path)]:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=icons_dir, suffix='.svg')
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                f.write(template.format(color=text_color))
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    return down_path, up_path


def _ensure_arrow_svgs(text_color: str) -> tuple[str, str]:
    """Generate arrow SVG files with the given color. Returns (down_path, up_path)."""
    global _last_arrow_color
    temp_icons_dir = os.path.join(tempfile.gettempdir(), 'deltahub_arrows')
    down_path = os.path.join(temp_icons_dir, 'arrow_down.svg')
    up_path = os.path.join(temp_icons_dir, 'arrow_up.svg')
    if _last_arrow_color == text_color and os.path.exists(down_path) and os.path.exists(up_path):
        return down_path.replace('\\', '/'), up_path.replace('\\', '/')
    try:
        dp, up = _write_arrow_svgs(temp_icons_dir, text_color)
        _last_arrow_color = text_color
        return dp.replace('\\', '/'), up.replace('\\', '/')
    except Exception:
        pass
    import base64
    down_data = base64.b64encode(_ARROW_DOWN_SVG.format(color=text_color).encode('utf-8')).decode('ascii')
    up_data = base64.b64encode(_ARROW_UP_SVG.format(color=text_color).encode('utf-8')).decode('ascii')
    return f'data:image/svg+xml;base64,{down_data}', f'data:image/svg+xml;base64,{up_data}'


_qss_cache: dict[str, str] = {}
_stylesheet_cache: dict[tuple, str] = {}


def _load_qss_template(filename: str) -> str:
    if filename in _qss_cache:
        return _qss_cache[filename]
    qss_path = resource_path(f'assets/styles/{filename}')
    if not os.path.exists(qss_path):
        raise FileNotFoundError(f'QSS template not found: {qss_path}')
    file = QFile(qss_path)
    if not file.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        raise IOError(f'Failed to open QSS file: {qss_path}')
    content = file.readAll().data().decode('utf-8')
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
        return max(0, int(str(value).replace('px', '').strip()))
    except (TypeError, ValueError):
        return default


def build_stylesheet(
    frame_bg_color: str, button_color: str, border_color: str,
    button_hover_color: str, main_text_color: str,
    font_family_main: str, font_size_main: int, font_size_small: int,
    checkbox_checked_color: str, scroll_handle_color: str,
    tooltip_bg_color: str = 'rgba(40, 40, 40, 230)',
    scroll_groove_color: str = 'rgba(40, 40, 40, 40)',
    zoom_factor: float = 1.0,
    custom_border_radius: str = '7px',
) -> str:
    cache_key = (
        frame_bg_color, button_color, border_color, button_hover_color,
        main_text_color, font_family_main, font_size_main, font_size_small,
        checkbox_checked_color, scroll_handle_color, tooltip_bg_color,
        scroll_groove_color, zoom_factor, custom_border_radius,
    )
    if cache_key in _stylesheet_cache:
        return _stylesheet_cache[cache_key]
    main_template = _load_qss_template('main.qss')
    scrollbar_template = _load_qss_template('scrollbar.qss')
    arrow_down_path, arrow_up_path = _ensure_arrow_svgs(main_text_color)
    border_radius_value = _parse_px_value(custom_border_radius)
    button_border_radius = border_radius_px(border_radius_value, height=30, border_width=2)
    add_localization_button_radius = border_radius_px(border_radius_value, width=33, height=33, border_width=2)
    top_refresh_button_radius = border_radius_px(border_radius_value, width=40, height=40, border_width=2)
    field_border_radius = border_radius_px(border_radius_value, height=30, border_width=2)
    tab_border_radius = border_radius_px(border_radius_value, height=25, border_width=2)
    editor_border_radius = border_radius_px(border_radius_value, height=100, border_width=2)
    checkbox_indicator_radius = border_radius_px(border_radius_value, width=18, height=18, border_width=2)
    scrollbar_radius = border_radius_px(border_radius_value, width=16, height=16, margin=1)
    main_stylesheet = _apply_template_replacements(main_template, {'%frame_bg_color%': frame_bg_color, '%button_color%': button_color, '%border_color%': border_color, '%button_hover_color%': button_hover_color, '%main_text_color%': main_text_color, '%font_family_main%': font_family_main, '%font_size_main%': str(font_size_main), '%font_size_small%': str(font_size_small), '%checkbox_checked_color%': checkbox_checked_color, '%tooltip_bg_color%': tooltip_bg_color, '%custom_border_radius%': custom_border_radius, '%button_border_radius%': button_border_radius, '%add_localization_button_radius%': add_localization_button_radius, '%top_refresh_button_radius%': top_refresh_button_radius, '%field_border_radius%': field_border_radius, '%tab_border_radius%': tab_border_radius, '%editor_border_radius%': editor_border_radius, '%checkbox_indicator_radius%': checkbox_indicator_radius, '%arrow_down_path%': arrow_down_path, '%arrow_up_path%': arrow_up_path})
    scrollbar_stylesheet = _apply_template_replacements(scrollbar_template, {'%scroll_handle_color%': scroll_handle_color, '%scroll_groove_color%': scroll_groove_color, '%scrollbar_radius%': scrollbar_radius})
    combined = main_stylesheet + scrollbar_stylesheet
    if zoom_factor != 1.0:
        combined = re.sub(r'(\d+)px', lambda m: f'{max(1, int(int(m.group(1)) * zoom_factor))}px', combined)
    _stylesheet_cache[cache_key] = combined
    return combined
