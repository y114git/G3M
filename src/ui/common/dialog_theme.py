"""Shared theme helper for dialogs."""

from ui.common.styling import (
    DEFAULT_COLORS,
    clamp_border_radius,
    get_border_radius,
    get_theme_colors,
)


def get_dialog_theme_values(app_state):
    if not app_state:
        return {
            **DEFAULT_COLORS,
            "border_radius": get_border_radius(None),
            "button_radius": clamp_border_radius(get_border_radius(None), height=30),
            "field_radius": clamp_border_radius(get_border_radius(None), height=30),
        }
    colors = get_theme_colors(app_state.local_config)
    br = get_border_radius(app_state.local_config)
    return {
        **colors,
        "border_radius": br,
        "button_radius": clamp_border_radius(br, height=30),
        "field_radius": clamp_border_radius(br, height=30),
    }


def build_dialog_theme_stylesheet(app_state):
    theme = get_dialog_theme_values(app_state)
    return f"""
        QDialog {{
            background-color: {theme["background"]};
            color: {theme["main_text"]};
            border-radius: {theme["border_radius"]}px;
        }}
        QLineEdit {{
            background-color: {theme["elements"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["field_radius"]}px;
            color: {theme["main_text"]};
            padding: 8px;
            font-size: 16px;
        }}
        QComboBox {{
            background-color: {theme["elements"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["field_radius"]}px;
            color: {theme["main_text"]};
            padding: 7px 10px;
            font-size: 16px;
            min-height: 36px;
        }}
        QLineEdit:focus {{
            border: 2px solid {theme["hover"]};
        }}
        QComboBox:hover, QComboBox:focus {{
            border: 2px solid {theme["hover"]};
        }}
        QLineEdit:disabled, QComboBox:disabled {{
            color: #8f8f8f;
            border-color: #6f6f6f;
        }}
        QListWidget {{
            background-color: {theme["elements"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["border_radius"]}px;
            color: {theme["main_text"]};
            padding: 6px;
            font-size: 16px;
        }}
        QListWidget::item {{
            padding: 11px 8px;
            border-bottom: 2px solid {theme["border"]};
        }}
        QListWidget::item:selected {{
            background-color: {theme["hover"]};
        }}
        QComboBox QAbstractItemView {{
            background-color: {theme["elements"]};
            color: {theme["main_text"]};
            selection-background-color: {theme["hover"]};
            font-size: 16px;
            padding: 4px;
        }}
        QPushButton {{
            background-color: {theme["elements"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["button_radius"]}px;
            color: {theme["main_text"]};
            padding: 8px 15px;
            font-weight: bold;
        }}
        QPushButton:hover:enabled {{
            background-color: {theme["hover"]};
        }}
        QPushButton:pressed:enabled {{
            background-color: {theme["hover"]};
        }}
        QPushButton:disabled {{
            background-color: {theme["background"]};
            color: #8f8f8f;
            border-color: #6f6f6f;
        }}
        QLabel {{
            color: {theme["main_text"]};
        }}
        QCheckBox {{
            color: {theme["main_text"]};
            font-size: 16px;
        }}
        QCheckBox:disabled {{
            color: #8f8f8f;
        }}
    """


def get_dialog_text_color(app_state) -> str:
    """Return themed text color for dialogs."""
    from ui.common.styling import get_theme_color

    return get_theme_color(app_state.local_config, "main_text") if app_state else "#e8e9eb"


def apply_dialog_theme(dialog, app_state):
    """Apply consistent theme to dialog."""
    dialog.setStyleSheet(build_dialog_theme_stylesheet(app_state))
