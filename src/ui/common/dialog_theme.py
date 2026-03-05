"""Shared theme helper for dialogs."""
from ui.common.styling import get_theme_color, get_border_radius


def apply_dialog_theme(dialog, app_state):
    """Apply consistent theme to dialog."""
    bg_color = get_theme_color(app_state.local_config, 'background', '#282828')
    border_color = get_theme_color(app_state.local_config, 'border', '#039d5b')
    button_color = get_theme_color(app_state.local_config, 'button', '#222222')
    hover_color = get_theme_color(app_state.local_config, 'button_hover', '#616b78')
    text_color = get_theme_color(app_state.local_config, 'text', '#e8e9eb')
    br = get_border_radius(app_state.local_config)

    dialog.setStyleSheet(f'''
        QDialog {{
            background-color: {bg_color};
            color: {text_color};
            border-radius: {br}px;
        }}
        QLineEdit {{
            background-color: {bg_color};
            border: 2px solid {border_color};
            border-radius: {br}px;
            color: {text_color};
            padding: 8px;
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border: 2px solid {hover_color};
        }}
        QListWidget {{
            background-color: {bg_color};
            border: 2px solid {border_color};
            border-radius: {br}px;
            color: {text_color};
            padding: 5px;
        }}
        QListWidget::item {{
            padding: 8px;
            border-bottom: 1px solid {border_color};
        }}
        QListWidget::item:selected {{
            background-color: {hover_color};
        }}
        QPushButton {{
            background-color: {button_color};
            border: 2px solid {border_color};
            border-radius: {br}px;
            color: {text_color};
            padding: 8px 15px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {hover_color};
        }}
        QPushButton:pressed {{
            background-color: {hover_color};
        }}
        QLabel {{
            color: {text_color};
        }}
        QCheckBox {{
            color: {text_color};
            font-size: 13px;
        }}
    ''')
