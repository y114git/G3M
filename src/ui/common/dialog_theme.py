"""Shared theme helper for dialogs."""
from ui.common.styling import get_theme_color


def apply_dialog_theme(dialog, app_state):
    """Apply consistent theme to dialog."""
    bg_color = get_theme_color(app_state.local_config, 'background', '#000000')
    border_color = get_theme_color(app_state.local_config, 'border', 'white')
    button_color = get_theme_color(app_state.local_config, 'button', 'black')
    hover_color = get_theme_color(app_state.local_config, 'button_hover', '#333')
    text_color = get_theme_color(app_state.local_config, 'text', 'white')

    dialog.setStyleSheet(f'''
        QDialog {{
            background-color: {bg_color};
            color: {text_color};
        }}
        QLineEdit {{
            background-color: {bg_color};
            border: 2px solid {border_color};
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
