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
            color: {theme["text"]};
            border-radius: {theme["border_radius"]}px;
        }}
        QLineEdit {{
            background-color: {theme["background"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["field_radius"]}px;
            color: {theme["text"]};
            padding: 8px;
            font-size: 13px;
        }}
        QComboBox {{
            background-color: {theme["background"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["field_radius"]}px;
            color: {theme["text"]};
            padding: 6px 8px;
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border: 2px solid {theme["button_hover"]};
        }}
        QComboBox:hover, QComboBox:focus {{
            border: 2px solid {theme["button_hover"]};
        }}
        QLineEdit:disabled, QComboBox:disabled {{
            color: #8f8f8f;
            border-color: #6f6f6f;
        }}
        QListWidget {{
            background-color: {theme["background"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["border_radius"]}px;
            color: {theme["text"]};
            padding: 5px;
        }}
        QListWidget::item {{
            padding: 8px;
            border-bottom: 2px solid {theme["border"]};
        }}
        QListWidget::item:selected {{
            background-color: {theme["button_hover"]};
        }}
        QPushButton {{
            background-color: {theme["button"]};
            border: 2px solid {theme["border"]};
            border-radius: {theme["button_radius"]}px;
            color: {theme["text"]};
            padding: 8px 15px;
            font-weight: bold;
        }}
        QPushButton:hover:enabled, QPushButton:pressed:enabled {{
            background-color: {theme["button_hover"]};
        }}
        QPushButton:disabled {{
            background-color: {theme["background"]};
            color: #8f8f8f;
            border-color: #6f6f6f;
        }}
        QLabel {{
            color: {theme["text"]};
        }}
        QCheckBox {{
            color: {theme["text"]};
            font-size: 13px;
        }}
        QCheckBox:disabled {{
            color: #8f8f8f;
        }}
    """


def get_dialog_text_color(app_state) -> str:
    """Return themed text color for dialogs."""
    from ui.common.styling import get_theme_color

    return get_theme_color(app_state.local_config, "text") if app_state else "#e8e9eb"


def apply_dialog_theme(dialog, app_state):
    """Apply consistent theme to dialog."""
    dialog.setStyleSheet(build_dialog_theme_stylesheet(app_state))
