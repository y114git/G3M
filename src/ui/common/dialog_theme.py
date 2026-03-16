"""Shared theme helper for dialogs."""
from ui.common.styling import get_theme_colors, get_border_radius, clamp_border_radius


def get_dialog_theme_values(app_state):
    colors = get_theme_colors(
        app_state.local_config,
        background='#282828',
        border='#039d5b',
        button='#222222',
        button_hover='#616b78',
        text='#e8e9eb',
        secondary_text='#6de985',
    )
    br = get_border_radius(app_state.local_config)
    return {
        **colors,
        'border_radius': br,
        'button_radius': clamp_border_radius(br, height=30),
        'field_radius': clamp_border_radius(br, height=30),
    }


def build_dialog_theme_stylesheet(app_state):
    theme = get_dialog_theme_values(app_state)
    return f'''
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
        QLineEdit:focus {{
            border: 2px solid {theme["button_hover"]};
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
        QPushButton:hover, QPushButton:pressed {{
            background-color: {theme["button_hover"]};
        }}
        QLabel {{
            color: {theme["text"]};
        }}
        QCheckBox {{
            color: {theme["text"]};
            font-size: 13px;
        }}
    '''


def get_dialog_text_color(app_state, fallback='#ffffff') -> str:  # get_theme_color wrapper
    from ui.common.styling import get_theme_color
    return get_theme_color(app_state.local_config, 'text', fallback) if app_state else fallback


def apply_dialog_theme(dialog, app_state):
    """Apply consistent theme to dialog."""
    dialog.setStyleSheet(build_dialog_theme_stylesheet(app_state))
