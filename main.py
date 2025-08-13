import argparse
import os
import platform
import sys
import tempfile
import threading
import time

from PyQt6.QtCore import QLibraryInfo, Qt, QTranslator, QTimer, QUrl
# QtMultimedia removed; using playsound3 for audio
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from localization import get_localization_manager
from launcher import DeltaHubApp
from helpers import resource_path, cleanup_old_updater_files
from localization import tr
_translator = QTranslator()
_lock_file = None
_splash_start_time = None
_player, _audio_output = None, None
_sound_instance = None  # Глобальная ссылка на playsound3 объект

class CustomSplashScreen(QSplashScreen):
    """Кастомный splash экран с поддержкой GIF анимации"""
    def __init__(self, pixmap=None, gif_path=None):
        if pixmap:
            super().__init__(pixmap)
        else:
            super().__init__()

        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.animation = None

        # Если указан путь к GIF, настраиваем анимацию
        if gif_path:
            self.setup_gif_animation(gif_path)
        # Для PNG splash - сразу полностью видимый (без анимации)

    def setup_gif_animation(self, gif_path):
        """Настройка анимированного GIF"""
        try:
            from PyQt6.QtGui import QMovie
            from PyQt6.QtWidgets import QLabel

            # Создаем QMovie для GIF
            self.movie = QMovie(gif_path)

            if not self.movie.isValid():
                return False

            # Настраиваем QMovie для одного воспроизведения
            self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
            self.movie.setSpeed(100)  # Нормальная скорость

            # Получаем размер GIF
            self.movie.jumpToFrame(0)  # Переходим к первому кадру
            gif_size = self.movie.currentPixmap().size()

            # Масштабируем под размер экрана
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                screen_geom = screen.geometry()
                target_width = min(550, screen_geom.width() // 2)
                target_height = int(target_width * gif_size.height() / gif_size.width())
            else:
                target_width = 550
                target_height = int(target_width * gif_size.height() / gif_size.width())

            # Сначала устанавливаем правильный масштаб для movie
            self.movie.setScaledSize(QPixmap(target_width, target_height).size())

            # Создаем QLabel для отображения GIF ПОСЛЕ масштабирования
            self.gif_label = QLabel(self)
            self.gif_label.setFixedSize(target_width, target_height)
            self.gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Настраиваем прозрачность
            self.gif_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.gif_label.setStyleSheet("background: transparent;")

            # ВАЖНО: Скрываем label до момента установки movie
            self.gif_label.hide()

            # Устанавливаем movie ТОЛЬКО после всех настроек
            self.gif_label.setMovie(self.movie)

            # Устанавливаем размер splash screen
            self.setFixedSize(target_width, target_height)

            # Настраиваем прозрачность splash screen
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setStyleSheet("background: transparent;")

            # Центрируем splash screen
            if screen:
                self.move(
                    (screen_geom.width() - target_width) // 2,
                    (screen_geom.height() - target_height) // 2
                )
            else:
                self.move(100, 100)  # Позиция по умолчанию

            # Подключаем сигнал завершения для остановки повтора
            self.movie.finished.connect(self.on_gif_finished)

            return True

        except Exception:
            return False

    def start_gif_animation(self):
        """Запуск GIF анимации"""
        if hasattr(self, 'movie'):
            # Показываем GIF label перед запуском анимации
            if hasattr(self, 'gif_label'):
                self.gif_label.show()
            self.movie.start()

    def stop_gif_animation(self):
        """Остановка GIF анимации"""
        if hasattr(self, 'movie'):
            self.movie.stop()

    def on_gif_finished(self):
        """Обработка завершения GIF анимации"""
        if hasattr(self, 'movie'):
            self.movie.stop()  # Останавливаем для предотвращения повтора

    def mousePressEvent(self, event):
        # Игнорируем клики мыши
        pass

    def keyPressEvent(self, event):
        # Игнорируем нажатия клавиш
        pass

def check_single_instance():
    """Проверяет, что запущен только один экземпляр лаунчера"""
    global _lock_file

    lock_file_path = os.path.join(tempfile.gettempdir(), "deltahub_launcher.lock")

    # Проверяем, существует ли уже файл блокировки
    if os.path.exists(lock_file_path):
        try:
            # Проверяем возраст файла - если старше 10 секунд, считаем процесс мертвым
            file_age = time.time() - os.path.getmtime(lock_file_path)
            if file_age > 10:
                os.remove(lock_file_path)
            else:
                with open(lock_file_path, 'r') as f:
                    pid = int(f.read().strip())

                # Проверяем, жив ли процесс с этим PID
                process_alive = False
                if platform.system() == "Windows":
                    import subprocess
                    try:
                        result = subprocess.check_output(
                            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            text=True
                        )
                        # Если в выводе есть PID (больше одной строки - заголовки + процесс)
                        lines = result.strip().split('\n')
                        process_alive = len(lines) > 1 and str(pid) in result
                    except subprocess.CalledProcessError:
                        process_alive = False
                else:
                    try:
                        os.kill(pid, 0)
                        process_alive = True
                    except OSError:
                        process_alive = False

                if process_alive:
                    return False  # Процесс жив
                else:
                    # Процесс не найден, удаляем старый файл блокировки
                    os.remove(lock_file_path)
        except:
            # Если не можем прочитать файл, удаляем его
            try:
                os.remove(lock_file_path)
            except:
                pass

    try:
        # Создаем новый файл блокировки
        _lock_file = open(lock_file_path, 'w')
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True

    except Exception:
        return False

def get_launcher_volume():
    """Reads launcher volume from config."""
    try:
        config_path = os.path.join(get_app_support_path(), "config.json")
        if os.path.exists(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get("launcher_volume", 100)
    except Exception:
        pass
    return 100



def play_deltahub_sound():
    """Воспроизводит звук заставки через playsound3 (только MP3)."""
    global _sound_instance

    sound_path: str = ""
    try:
        # Предпочтительные варианты звука (только MP3)
        # 1) Кастомный звук из config_dir
        config_mp3 = os.path.join(get_app_support_path(), "custom_startup_sound.mp3")
        # 2) Встроенный ассет
        asset_mp3 = resource_path("assets/deltahub.wav")

        sound_candidates = [config_mp3, asset_mp3]

        found = next((p for p in sound_candidates if os.path.exists(p)), None)
        if not found:
            return
        sound_path = found

        from playsound3 import playsound
        # Неблокирующее воспроизведение возвращает объект с .is_alive()/.stop()
        _sound_instance = playsound(sound_path, block=False)
    except Exception:
        # Если playsound3 не сработал — ничего не делаем
        pass

def stop_deltahub_sound():
    """Останавливает воспроизведение звука (playsound3)."""
    try:
        global _sound_instance
        if '_sound_instance' in globals() and _sound_instance:
            if hasattr(_sound_instance, 'is_alive') and _sound_instance.is_alive():
                try:
                    _sound_instance.stop()
                except Exception:
                    pass
            _sound_instance = None
    except Exception:
        pass

def setup_app():
    global _translator
    manager = get_localization_manager()
    language_code = manager.detect_system_language()
    manager.load_language(language_code)
    os.environ["QT_LOGGING_RULES"] = ";".join([
        "qt.qpa.screen.warning=false",
        "qt.qpa.window.warning=false",
        "qt.multimedia.ffmpeg=false",
        "qt.multimedia=false"
    ])
    # Do not force ffmpeg backend in frozen app; let Qt choose platform default (WMF on Windows)
    if not getattr(sys, 'frozen', False):
        os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    app = QApplication(sys.argv)
    qt_translation_file = manager.get_qt_translation_name(language_code)
    if qt_translation_file:
        if _translator.load(qt_translation_file, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(_translator)
    app.setApplicationName("DELTAHUB")
    app.setApplicationVersion(DeltaHubApp.get_launcher_version())
    app.setOrganizationName("deltahub")
    return app

def create_png_splash():
    """Создает PNG splash экран"""
    pixmap = QPixmap()
    splash_path = resource_path("assets/splash.png")

    if not pixmap.load(splash_path):
        pixmap = QPixmap(600, 600)
        pixmap.fill(Qt.GlobalColor.transparent)  # Прозрачный фон

    scaled_pixmap = pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    splash = CustomSplashScreen(scaled_pixmap)
    # Возвращаем TranslucentBackground для прозрачного фона
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    splash.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    return splash

def create_splash():
    """Создает splash экран - GIF если доступен, иначе PNG с анимацией"""
    # Проверяем наличие GIF файла
    gif_path = resource_path("assets/splash.gif")

    if os.path.exists(gif_path):
        # Создаем GIF splash
        splash = CustomSplashScreen(gif_path=gif_path)
        return splash
    else:
        # Используем PNG splash
        return create_png_splash()

def get_app_support_path():
    """Получает путь к папке конфигов (совпадает с launcher.py)"""
    system = platform.system()
    if system == "Windows":
        path = os.path.join(os.getenv('APPDATA', ''), "DELTAHUB")
    elif system == "Darwin":
        path = os.path.join(os.path.expanduser('~'), "Library/Application Support/DELTAHUB")
    else:
        path = os.path.join(os.path.expanduser('~'), ".local/share/DELTAHUB")

    cache_path = os.path.join(path, "cache")
    os.makedirs(cache_path, exist_ok=True)
    return cache_path

def check_splash_settings():
    """Проверяет настройки заставки используя ту же логику что и launcher.py"""
    try:
        config_path = os.path.join(get_app_support_path(), "config.json")

        if os.path.exists(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                disable_splash = config.get("disable_splash", False)
                return not disable_splash
    except Exception:
        pass

    return True  # По умолчанию заставка включена

def run_app():
    parser = argparse.ArgumentParser(description="DELTAHUB")
    parser.add_argument('--shortcut-launch', type=str)
    parser.add_argument('--shortcut-path', type=str)
    parser.add_argument('--force-start', action='store_true', help='Force start even if another instance is detected')
    args = parser.parse_args()

    # Проверяем единственный экземпляр только для обычного запуска
    if not args.shortcut_launch and not args.force_start and not check_single_instance():
        app = setup_app()
        QMessageBox.critical(None, tr("errors.already_running_title"),
                           tr("errors.already_running"))
        sys.exit(1)

    if platform.system() == "Linux" and not args.shortcut_launch:
        os.environ.setdefault("NO_AT_BRIDGE", "1")

    app = setup_app()
    if args.shortcut_launch:
        DeltaHubApp(args=args)
        return

    # Проверяем настройки заставки
    splash_enabled = check_splash_settings()

    if not splash_enabled:
        # Если заставка отключена, показываем статичный PNG splash до завершения инициализации
        splash = create_png_splash()
        splash.show()
        app.processEvents()

        # Переменная для DeltaHubApp
        launcher_app = {}

        def close_splash_and_show_launcher():
            """Закрывает splash и показывает лаунчер после инициализации"""
            if hasattr(splash, 'movie'):
                splash.stop_gif_animation()
            splash.close()

            ex = launcher_app.get('instance')
            if ex:
                ex.show()
                # Устанавливаем флаг что лаунчер показан пользователю
                ex.is_shown_to_user = True
                ex.activateWindow()
                ex.raise_()
                ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)

        def create_launcher_no_animation():
            """Создает лаунчер без анимации но ждет инициализации"""
            try:
                # Создаем лаунчер в фоне
                launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash)
                # Подключаем сигнал завершения инициализации
                launcher_app['instance'].initialization_finished.connect(close_splash_and_show_launcher)

                # Принудительный таймер на случай если сигнал не сработает
                QTimer.singleShot(15000, close_splash_and_show_launcher)

            except Exception as e:
                if hasattr(splash, 'movie'):
                    splash.stop_gif_animation()
                splash.close()
                QMessageBox.critical(None, tr("errors.startup_error_title"), tr("errors.startup_error_message", details=str(e)))

        # Запускаем создание лаунчера
        QTimer.singleShot(100, create_launcher_no_animation)

        try:
            sys.exit(app.exec())
        except Exception as e:
            QMessageBox.critical(None, tr("errors.startup_error_title"), tr("errors.startup_error_message", details=str(e)))
        return

    global _splash_start_time
    _splash_start_time = time.time()

    # Создаем и подготавливаем splash (загружаем GIF)
    splash = create_splash()

    # Если это GIF, дожидаемся полной загрузки
    if hasattr(splash, 'movie'):
        # Альтернативный подход: запускаем и сразу ставим на паузу для прогрузки
        splash.movie.start()
        splash.movie.setPaused(True)

        # Ждем загрузки первых кадров
        for _ in range(50):  # Максимум 50 итераций ожидания
            app.processEvents()
            if splash.movie.currentFrameNumber() >= 0:
                break
            time.sleep(0.01)  # 10мс между проверками

        # Возвращаемся к первому кадру и останавливаем
        splash.movie.stop()
        splash.movie.jumpToFrame(0)

    # Теперь показываем подготовленный splash
    splash.show()
    app.processEvents()

    # Запускаем звук через 1 секунду
    QTimer.singleShot(1000, play_deltahub_sound)

    # Если это GIF, запускаем анимацию
    if hasattr(splash, 'movie'):
        splash.start_gif_animation()

    # Переменная для DeltaHubApp (используем словарь для избежания global)
    launcher_app = {}

    # Функция для проверки минимального времени показа splash
    def check_minimum_splash_time():
        if _splash_start_time is None:
            return True
        elapsed = time.time() - _splash_start_time
        return elapsed >= 10.0  # Минимум 10 секунд

    # Функция для корректного закрытия splash
    def close_splash():
        """Корректно закрывает splash с остановкой анимации"""
        if hasattr(splash, 'movie'):
            splash.stop_gif_animation()
        splash.close()

    # Модифицированная функция закрытия splash
    def close_splash_when_ready():
        if check_minimum_splash_time():
            close_splash()
            ex = launcher_app.get('instance')
            if ex:
                ex.show()
                # Устанавливаем флаг что лаунчер показан пользователю
                ex.is_shown_to_user = True
                ex.activateWindow()
                ex.raise_()
                ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        else:
            # Если прошло меньше 11 секунд, ждем
            if _splash_start_time is not None:
                remaining_time = int((11 - (time.time() - _splash_start_time)) * 1000)
            else:
                remaining_time = 0
            def show_launcher():
                close_splash()
                ex = launcher_app.get('instance')
                if ex:
                    ex.show()
                    # Устанавливаем флаг что лаунчер показан пользователю
                    ex.is_shown_to_user = True
                    ex.activateWindow()
                    ex.raise_()
                    ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            QTimer.singleShot(remaining_time, show_launcher)

    # Создаем DeltaHubApp через QTimer, чтобы не блокировать UI
    def create_launcher():
        try:
            launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash)
            launcher_app['instance'].initialization_finished.connect(close_splash_when_ready)

            # Добавляем принудительный таймер на случай если сигнал не сработает
            QTimer.singleShot(15000, close_splash_when_ready)  # 15 секунд принудительно

        except Exception as e:
            splash.close()
            QMessageBox.critical(None, tr("errors.startup_error_title"), tr("errors.startup_error_message", details=str(e)))

    # Запускаем создание лаунчера через 100мс, чтобы splash успел показаться
    QTimer.singleShot(100, create_launcher)

    try:
        sys.exit(app.exec())
    except Exception as e:
        QMessageBox.critical(None, tr("errors.startup_error_title"), tr("errors.startup_error_message", details=str(e)))

if __name__ == "__main__":
    cleanup_old_updater_files()
    run_app()
