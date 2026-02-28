import os
import re
from PyQt6.QtCore import QFile, QIODevice
from utils.path_utils import resource_path

_qss_cache: dict[str, str] = {}


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


def build_stylesheet(frame_bg_color: str, button_color: str, border_color: str, button_hover_color: str, main_text_color: str, font_family_main: str, font_size_main: int, font_size_small: int, checkbox_checked_color: str, scroll_handle_color: str, tooltip_bg_color: str = 'rgba(0, 0, 0, 230)', scroll_groove_color: str = 'rgba(0, 0, 0, 40)', zoom_factor: float = 1.0) -> str:
    main_template = _load_qss_template('main.qss')
    scrollbar_template = _load_qss_template('scrollbar.qss')
    main_stylesheet = _apply_template_replacements(main_template, {'%frame_bg_color%': frame_bg_color, '%button_color%': button_color, '%border_color%': border_color, '%button_hover_color%': button_hover_color, '%main_text_color%': main_text_color, '%font_family_main%': font_family_main, '%font_size_main%': str(font_size_main), '%font_size_small%': str(font_size_small), '%checkbox_checked_color%': checkbox_checked_color, '%tooltip_bg_color%': tooltip_bg_color})
    scrollbar_stylesheet = _apply_template_replacements(scrollbar_template, {'%scroll_handle_color%': scroll_handle_color, '%scroll_groove_color%': scroll_groove_color})
    combined = main_stylesheet + scrollbar_stylesheet
    if zoom_factor != 1.0:
        combined = re.sub(r'(\d+)px', lambda m: f'{max(1, int(int(m.group(1)) * zoom_factor))}px', combined)
    return combined
