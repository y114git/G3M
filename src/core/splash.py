import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QMovie, QPainter
from PyQt6.QtWidgets import QSplashScreen
from utils.path_utils import resource_path


class CustomSplashScreen(QSplashScreen):

    def __init__(self, pixmap=None, gif_path=None):
        if pixmap:
            super().__init__(pixmap)
        else:
            empty_pixmap = QPixmap(550, 309)
            empty_pixmap.fill(Qt.GlobalColor.transparent)
            super().__init__(empty_pixmap)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if gif_path:
            self.setup_gif_animation(gif_path)

    def setup_gif_animation(self, gif_path):
        try:
            from PyQt6.QtGui import QMovie
            self.movie = QMovie(gif_path)
            if not self.movie.isValid():
                return False
            self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
            self.movie.setSpeed(100)
            self.movie.jumpToFrame(0)
            gif_size = self.movie.currentPixmap().size()
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                screen_geom = screen.geometry()
                target_width = min(550, screen_geom.width() // 2)
            else:
                target_width = 550
            ratio = gif_size.height() / gif_size.width()
            target_height = int(target_width * ratio)
            if gif_size.width() != target_width or gif_size.height() != target_height:
                size = QPixmap(target_width, target_height).size()
                self.movie.setScaledSize(size)
            self.setFixedSize(target_width, target_height)
            self.setStyleSheet('background: transparent;')
            if screen:
                self.move((screen_geom.width() - target_width) // 2, (screen_geom.height() - target_height) // 2)
            else:
                self.move(100, 100)
            self.movie.frameChanged.connect(self._on_frame_changed)
            self.movie.finished.connect(self.on_gif_finished)
            return True
        except Exception:
            return False

    def _on_frame_changed(self, frame_number):
        self.update()

    def start_gif_animation(self):
        if hasattr(self, 'movie') and self.movie.isValid():
            self.movie.start()

    def stop_gif_animation(self):
        if hasattr(self, 'movie'):
            self.movie.stop()

    def on_gif_finished(self):
        if hasattr(self, 'movie'):
            self.movie.stop()

    def paintEvent(self, event):
        if hasattr(self, 'movie') and self.movie:
            pixmap = self.movie.currentPixmap()
            if pixmap:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                painter.drawPixmap(0, 0, pixmap)
                return
        super().paintEvent(event)

    def mousePressEvent(self, event):
        pass

    def keyPressEvent(self, event):
        pass


def create_png_splash():
    pixmap = QPixmap()
    splash_path = resource_path('assets/images/splash.png')
    if not pixmap.load(splash_path):
        pixmap = QPixmap(600, 600)
        pixmap.fill(Qt.GlobalColor.transparent)
    scaled_pixmap = pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    splash = CustomSplashScreen(scaled_pixmap)
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    splash.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    return splash


def create_splash():
    gif_path = resource_path('assets/images/splash.gif')
    if os.path.exists(gif_path):
        splash = CustomSplashScreen(gif_path=gif_path)
        if hasattr(splash, 'movie') and splash.movie.isValid():
            return splash
    return create_png_splash()
