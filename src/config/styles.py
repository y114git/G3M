"""Shared theme palettes."""

UI_COLORS = {
    "status_error": "red",
    "status_warning": "orange",
    "status_success": "green",
    "status_info": "gray",
    "status_ready": "lightgreen",
    "status_steam": "blue",
}
DEFAULT_THEME = {
    "name": "G3M",
    "background": "images/background.png",
    "font_family": "",
    "font_size_main": 16,
    "font_size_small": 12,
    "colors": {
        "background": "#282828",
        "elements": "#222222",
        "hover": "#616b78",
        "select": "#ecedef",
        "border": "#039d5b",
        "main_text": "#e8e9eb",
        "secondary_text": "#6de985",
        "disabled_bg": "#333333",
        "disabled_text": "#888888",
        "disabled_border": "#555555",
    },
}
DEFAULT_COLORS = DEFAULT_THEME["colors"]
FALLBACK_FRAME_BG = "rgba(40, 40, 40, 150)"
FALLBACK_TOOLTIP_BG = "rgba(40, 40, 40, 230)"
FALLBACK_WINDOW_BG = "rgba(0, 0, 0, 200)"
FALLBACK_SCROLL_GROOVE = "rgba(40, 40, 40, 40)"
SETTINGS_COLOR_CONFIG = {
    "background": "ui.background_color",
    "elements": "ui.elements_color",
    "border": "ui.border_color",
    "hover": "ui.custom_hover_color",
    "select": "ui.custom_select_color",
    "main_text": "ui.main_text_color",
    "secondary_text": "ui.secondary_text_color",
}
CHAT_MESSAGE_BACKGROUND_COLOR = "rgba(255, 255, 255, 0.1)"

"""Reusable QSS snippets and style templates."""
STYLES_TEMPLATE_SUBDIR = "config/qss"
QSS_TRANSPARENT_SCROLL = "QScrollArea { background-color: transparent; }"
QSS_TRANSPARENT_BG = "background: transparent;"
QSS_BOLD_LABEL = "font-weight: bold;"
QSS_BOLD_TRANSPARENT = "font-weight: bold; background: transparent;"
QSS_TRANSPARENT_NOPAD = "background: transparent; padding: 0px;"
QSS_PADDING_LEFT_8 = "padding-left:8px;"
QSS_PADDING_LEFT_5 = "padding-left: 5px;"
QSS_ARROW_LABEL = "font-size: 10px; background: transparent;"
QSS_LOADING_LABEL = "font-size: 16px; padding: 20px; color: gray;"
QSS_TAB_ALIGNMENT = """
    QTabWidget::tab-bar { alignment: center; }
    QTabBar::tab { min-width: 92px; padding: 6px 10px; }
"""
QSS_SETTINGS_TAB_ALIGNMENT = """
    QTabWidget::tab-bar { alignment: center; }
    QTabBar::tab { min-width: 110px; padding: 6px 14px; }
"""
MOD_WIDGET_STYLE_TEMPLATE = """QFrame#{frame_selector} {{
    background-color: {bg_color};
    border: {border_width} solid {border_color};
    border-radius: {frame_border_radius};
}}
QFrame#{frame_selector}:hover {{
    border-color: {hover_border_color};
}}
QLabel#{icon_selector} {{
    border: 2px solid {border_color};
    border-radius: {icon_border_radius};
}}
QLabel#versionLabel {{
    color: {secondary_text_color};
}}
QLabel#secondaryText {{
    color: {secondary_text_color};
    font-size: {secondary_font_size}px;
}}
QLabel#primaryText {{
    color: {text_color};
    font-size: {primary_font_size}px;
}}
QPushButton#cardButton, QPushButton#cardButtonDownload, QPushButton#cardButtonUninstall {{
    min-width: {button_width}px;
    max-width: {button_width}px;
    min-height: {button_height}px;
    max-height: {button_height}px;
    font-size: {button_font_size}px;
    padding: 1px;
    border-radius: {button_border_radius};
}}
QPushButton#cardButtonDownload {{
    background-color: #4CAF50;
    font-weight: bold;
}}
QPushButton#cardButtonDownload:hover {{
    background-color: #5cb85c;
}}
QPushButton#cardButtonUninstall {{
    background-color: #F44336;
    font-weight: bold;
}}
QPushButton#cardButtonUninstall:hover {{
    background-color: #d32f2f;
}}"""
EMPTY_LAYOUT_MESSAGE_STYLE = "QLabel {{\n    color: {color};\n    font-size: {font_size}px;\n    font-style: italic;\n    opacity: 0.75;\n    background-color: transparent;\n    padding: 40px;\n}}"

"""SVG and rich-text styling assets."""
ARROW_DOWN_SVG_TEMPLATE = '<?xml version="1.0" encoding="utf-8"?>\n<svg fill="{color}" width="800px" height="800px" viewBox="-6.5 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">\n<path d="M18.813 11.406l-7.906 9.906c-0.75 0.906-1.906 0.906-2.625 0l-7.906-9.906c-0.75-0.938-0.375-1.656 0.781-1.656h16.875c1.188 0 1.531 0.719 0.781 1.656z"></path>\n</svg>'
ARROW_UP_SVG_TEMPLATE = '<?xml version="1.0" encoding="utf-8"?>\n<svg fill="{color}" width="800px" height="800px" viewBox="-6.5 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">\n<g transform="translate(0,32) scale(1,-1)"><path d="M18.813 11.406l-7.906 9.906c-0.75 0.906-1.906 0.906-2.625 0l-7.906-9.906c-0.75-0.938-0.375-1.656 0.781-1.656h16.875c1.188 0 1.531 0.719 0.781 1.656z"></path></g>\n</svg>'
RICH_HTML_CSS_CLASS_MAP = {
    "RedColor": "color:#ff4444;",
    "BlueColor": "color:#5599ff;",
    "GreenColor": "color:#44ff44;",
    "YellowColor": "color:#ffdd44;",
    "WhiteColor": "color:#ffffff;",
    "SelectedElement": "",
}
RICH_HTML_IMAGE_CACHE_MAX_SIZE = 128
