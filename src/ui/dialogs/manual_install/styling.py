"""Manual-install additions to the shared dialog theme."""

from PyQt6.QtCore import QSize

from ui.common.dialog_theme import apply_dialog_theme, get_dialog_theme_values
from utils.path_utils import colored_icon, resource_path


def apply_manual_install_theme(dialog) -> None:
    apply_dialog_theme(dialog, dialog.app_state)
    theme = get_dialog_theme_values(dialog.app_state)
    arrow = resource_path("assets/icons/arrow_down.svg").replace("\\", "/")
    dialog.browse_button.setIcon(colored_icon("folder", theme["main_text"]))
    dialog.set_theme_stylesheet(
        dialog._theme_stylesheet
        + f"""
        QTreeWidget {{ background: {theme["elements"]}; color: {theme["main_text"]}; border: 2px solid {theme["border"]}; border-radius: {theme["field_radius"]}px; }}
        QTreeWidget::item {{ padding: 5px; }}
        QTreeWidget::item:selected {{ background: {theme["hover"]}; color: {theme["main_text"]}; }}
        QHeaderView::section {{ background: {theme["background"]}; color: {theme["main_text"]}; border: 2px solid {theme["border"]}; padding: 6px; }}
        QLineEdit[invalid="true"] {{ border: 2px solid #F44336; }}
        QTreeWidget QLineEdit, QTreeWidget QLineEdit:focus, QTreeWidget QComboBox {{ border: none; border-radius: 0px; padding: 0px 4px; min-height: 0px; }}
        QToolButton {{ background: {theme["elements"]}; color: {theme["main_text"]}; border: 2px solid {theme["border"]}; border-radius: {theme["button_radius"]}px; padding: 8px 36px 8px 10px; font-weight: bold; }}
        QToolButton:hover:enabled {{ background: {theme["hover"]}; }}
        QToolButton:disabled {{ color: #8f8f8f; border-color: #6f6f6f; }}
        QToolButton::menu-button {{ subcontrol-origin: padding; subcontrol-position: top right; border-left: 2px solid {theme["border"]}; width: 30px; }}
        QToolButton::menu-button:disabled {{ border-left-color: #6f6f6f; }}
        QToolButton::menu-arrow {{ image: url({arrow}); width: 16px; height: 10px; }}
        QPushButton#manualInstallAddGameButton {{ background: {theme["elements"]}; border: 2px solid {theme["border"]}; border-radius: {theme["button_radius"]}px; padding: 0px; }}
        QPushButton#manualInstallAddGameButton:hover:enabled {{ background: {theme["hover"]}; }}
        QPushButton#manualInstallAddGameButton:focus {{ border-color: {theme["select"]}; }}
        QPushButton#manualInstallAddGameButton:disabled {{ border-color: #6f6f6f; }}
        QMenu {{ background: {theme["elements"]}; color: {theme["main_text"]}; border: 2px solid {theme["border"]}; }}
        QMenu::item {{ padding: 6px 18px; }}
        QMenu::item:selected {{ background: {theme["hover"]}; }}
        QTabWidget::tab-bar {{ alignment: center; top: 4px; }}
        QTabWidget::pane {{ border: 2px solid {theme["border"]}; border-radius: {theme["field_radius"]}px; background: {theme["background"]}; padding-top: 10px; top: -2px; }}
        QTabBar::tab {{ background: {theme["elements"]}; color: {theme["main_text"]}; border: 2px solid {theme["border"]}; border-bottom: none; padding: 6px 14px; margin: 0 3px 6px 3px; border-top-left-radius: {theme["button_radius"]}px; border-top-right-radius: {theme["button_radius"]}px; border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; }}
        QTabBar::tab:selected {{ background: {theme["hover"]}; border-bottom: 2px solid {theme["background"]}; margin-bottom: 2px; }}
        QTabBar::tab:hover {{ background: {theme["hover"]}; }}
        QTextBrowser {{ background: {theme["elements"]}; color: {theme["main_text"]}; border: 2px solid {theme["border"]}; border-radius: {theme["field_radius"]}px; padding: 12px; selection-background-color: {theme["hover"]}; }}
    """
    )
    dialog.game_combo.ensurePolished()
    side = dialog.game_combo.sizeHint().height()
    dialog.add_game_button.setFixedSize(side, side)
    dialog.add_game_button.setIconSize(QSize(side // 2, side // 2))
    dialog.add_game_button.setIcon(colored_icon("add", theme["main_text"]))
