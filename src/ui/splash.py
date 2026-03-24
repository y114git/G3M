"""Splash screen helpers."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QSplashScreen

from utils.path_utils import resource_path


class CustomSplashScreen(QSplashScreen):
    """Splash screen widget."""

    def __init__(self, pixmap=None) -> None:
        super().__init__(pixmap or QPixmap(600, 600))
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, event):
        pass

    def keyPressEvent(self, event):
        pass


def create_png_splash(config_dir: str | None = None):
    pixmap = QPixmap()
    splash_path = None
    if config_dir:
        import os

        for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]:
            logo_path = os.path.join(config_dir, f"custom_logo{ext}")
            if os.path.exists(logo_path):
                splash_path = logo_path
                break
    if not splash_path:
        splash_path = resource_path("assets/images/logo.png")
    if not pixmap.load(splash_path):
        pixmap = QPixmap(600, 600)
        pixmap.fill(Qt.GlobalColor.transparent)
    scaled_pixmap = pixmap.scaled(
        600,
        600,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    splash = CustomSplashScreen(scaled_pixmap)
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    splash.setWindowFlags(
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    )
    return splash
