import argparse
import os
import platform
import sys
import tempfile
import subprocess
import time
import psutil
from PyQt6.QtCore import QLibraryInfo, Qt, QTranslator, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox
from localization.manager import get_localization_manager, tr
from utils.audio_utils import play_deltahub_sound
from core.splash import create_splash, create_png_splash
from utils.path_utils import get_user_data_root, get_launcher_dir

if platform.system() == "Windows":
    import winreg

def create_app_reference():
    from core.app import DeltaHubApp
    return DeltaHubApp
SINGLE_INSTANCE_KEY = "deltahub.y.114.single-instance-lock"
_translator = QTranslator()
_lock_file = None
_splash_start_time = None
_player, _audio_output = (None, None)
_sound_instance = None

def check_game_processes():
    game_processes = {'DELTARUNE.exe', 'UNDERTALE.exe', 'DELTARUNEdemo.exe', 'DELTARUNE', 'UNDERTALE', 'DELTARUNEdemo'}
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] in game_processes:
                return proc.info['name']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None

def register_url_protocol():
    """Registers the deltahub:// URL protocol."""
    if getattr(sys, 'frozen', False):
        executable_path = f'"{sys.executable}"'
    else:
        # In dev mode, construct the command to run the main script
        main_script_path = os.path.abspath(os.path.join(get_launcher_dir(), '..', 'src', 'main.py'))
        executable_path = f'"{sys.executable}" "{main_script_path}"'

    system = platform.system()
    try:
        if system == "Windows":
            key_path = r"Software\Classes\deltahub"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, "URL:DELTAHUB Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
                
                command_key_path = fr"{key_path}\shell\open\command"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_key_path) as command_key:
                    # The "%1" is crucial for passing the URL to the application
                    command = f'{executable_path} "%1"'
                    winreg.SetValue(command_key, "", winreg.REG_SZ, command)
        elif system == "Linux":
            desktop_file_content = f"""[Desktop Entry]
Name=DELTAHUB Launcher
Exec={executable_path} %u
Type=Application
Terminal=false
MimeType=x-scheme-handler/deltahub;
"""
            apps_dir = os.path.expanduser("~/.local/share/applications")
            os.makedirs(apps_dir, exist_ok=True)
            desktop_file_path = os.path.join(apps_dir, "deltahub.desktop")
            with open(desktop_file_path, "w", encoding="utf-8") as f:
                f.write(desktop_file_content)
            
            # Register the handler
            subprocess.run(["xdg-mime", "default", "deltahub.desktop", "x-scheme-handler/deltahub"], check=False)
    except Exception as e:
        print(f"Failed to register URL protocol: {e}")

class SingleInstanceServer(QLocalServer):
    def __init__(self, app_instance):
        super().__init__()
        self.app_instance = app_instance

        self.newConnection.connect(self.handle_new_connection)

    def handle_new_connection(self):
        socket = self.nextPendingConnection()
        if socket:
            socket.readyRead.connect(lambda: self.read_socket_data(socket))

    def read_socket_data(self, socket):
        data = socket.readAll().data()
        if data:
            url = data.decode('utf-8')
            if url.startswith("deltahub://"):
                self.app_instance.url_received_signal.emit(url)
        socket.close()

def setup_app():
    manager = get_localization_manager()
    language_code = manager.detect_system_language()
    manager.load_language(language_code)
    os.environ['QT_LOGGING_RULES'] = ';'.join(['qt.qpa.screen.warning=false', 'qt.qpa.window.warning=false', 'qt.multimedia.ffmpeg=false', 'qt.multimedia=false'])
    if not getattr(sys, 'frozen', False):
        os.environ.setdefault('QT_MEDIA_BACKEND', 'ffmpeg')
    app = QApplication(sys.argv)
    qt_translation_file = manager.get_qt_translation_name(language_code)
    if qt_translation_file:
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if _translator.load(qt_translation_file, path):
            app.installTranslator(_translator)
    app.setApplicationName('DELTAHUB')
    from config.constants import LAUNCHER_VERSION
    app.setApplicationVersion(LAUNCHER_VERSION)
    app.setOrganizationName('deltahub')
    return app

def check_splash_settings():
    try:
        config_path = os.path.join(get_user_data_root(), 'cache', 'config.json')
        if os.path.exists(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                disable_splash = config.get('disable_splash', False)
                return not disable_splash
    except Exception:
        pass
    return True

def run_app():
    parser = argparse.ArgumentParser(description='DELTAHUB')
    parser.add_argument('--shortcut-launch', type=str)
    parser.add_argument('--shortcut-path', type=str)
    parser.add_argument('--force-start', action='store_true', help='Force start even if another instance is detected')
    args, unknown_args = parser.parse_known_args()
    url_arg = next((arg for arg in sys.argv[1:] if arg.startswith('deltahub://')), None)

    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)

    # waitForConnected(500) дает полсекунды на установку соединения.
    # Этого более чем достаточно и решает проблему гонки состояний.
    if socket.waitForConnected(500):
        if url_arg:
            socket.writeData(url_arg.encode('utf-8'))
            socket.flush()
            socket.waitForBytesWritten(1000)
        # Второй экземпляр успешно передал информацию и должен завершиться.
        socket.disconnectFromServer()
        sys.exit(0)
    
    # Если подключиться не удалось, значит, это первый экземпляр.
    # Удаляем старый файл сокета, если он остался от аварийного завершения.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    if not args.force_start:
        running_game = check_game_processes()
        if running_game:
            app = setup_app()
            QMessageBox.critical(None, tr('errors.game_running_title'), tr('errors.game_running_message', game_name=running_game))
            sys.exit(1)
    if platform.system() == 'Linux' and (not args.shortcut_launch):
        os.environ.setdefault('NO_AT_BRIDGE', '1')
    app = setup_app()
    try:
        register_url_protocol()
    except Exception as e:
        print(f"Could not register protocol handler: {e}")
    if args.shortcut_launch:
        DeltaHubApp = create_app_reference()
        DeltaHubApp(args=args)
        return
    splash_enabled = check_splash_settings()
    if not splash_enabled:
        splash = create_png_splash()
        splash.show()
        app.processEvents()
        launcher_app = {}

        def close_splash_and_show_launcher():
            if hasattr(splash, 'movie'):
                splash.stop_gif_animation()
            splash.close()
            ex = launcher_app.get('instance')
            if ex:
                ex.show()
                ex.is_shown_to_user = True
                ex.activateWindow()
                ex.raise_()
                ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)

        def create_launcher_no_animation():
            try:
                DeltaHubApp = create_app_reference()
                launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash, initial_url=url_arg)
                server = SingleInstanceServer(launcher_app['instance'])
                if not server.listen(SINGLE_INSTANCE_KEY):
                    QMessageBox.critical(None, "Error", "Couldn't start single instance server.")
                    sys.exit(1)
                launcher_app['instance'].server = server
                launcher_app['instance'].initialization_finished.connect(close_splash_and_show_launcher)
                QTimer.singleShot(15000, close_splash_and_show_launcher)
            except Exception as e:
                if hasattr(splash, 'movie'):
                    splash.stop_gif_animation()
                splash.close()
                QMessageBox.critical(None, tr('errors.startup_error_title'), tr('errors.startup_error_message', details=str(e)))
        QTimer.singleShot(100, create_launcher_no_animation)
        try:
            sys.exit(app.exec())
        except Exception as e:
            QMessageBox.critical(None, tr('errors.startup_error_title'), tr('errors.startup_error_message', details=str(e)))
        return
    global _splash_start_time
    _splash_start_time = time.time()
    splash = create_splash()
    if hasattr(splash, 'movie'):
        splash.movie.start()
        splash.movie.setPaused(True)
        for _ in range(50):
            app.processEvents()
            if splash.movie.currentFrameNumber() >= 0:
                break
            time.sleep(0.01)
        splash.movie.stop()
        splash.movie.jumpToFrame(0)
    splash.show()
    app.processEvents()
    QTimer.singleShot(1000, play_deltahub_sound)
    if hasattr(splash, 'movie'):
        splash.start_gif_animation()
    launcher_app = {}

    def check_minimum_splash_time():
        if _splash_start_time is None:
            return True
        elapsed = time.time() - _splash_start_time
        return elapsed >= 10.0

    def close_splash():
        if hasattr(splash, 'movie'):
            splash.stop_gif_animation()
        splash.close()

    def close_splash_when_ready():
        if check_minimum_splash_time():
            close_splash()
            ex = launcher_app.get('instance')
            if ex:
                ex.show()
                ex.is_shown_to_user = True
                ex.activateWindow()
                ex.raise_()
                ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        else:
            if _splash_start_time is not None:
                remaining_time = int((11 - (time.time() - _splash_start_time)) * 1000)
            else:
                remaining_time = 0

            def show_launcher():
                close_splash()
                ex = launcher_app.get('instance')
                if ex:
                    ex.show()
                    ex.is_shown_to_user = True
                    ex.activateWindow()
                    ex.raise_()
                    ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            QTimer.singleShot(remaining_time, show_launcher)

    def create_launcher():
        try:
            DeltaHubApp = create_app_reference()
            launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash, initial_url=url_arg)
            server = SingleInstanceServer(launcher_app['instance'])
            if not server.listen(SINGLE_INSTANCE_KEY):
                QMessageBox.critical(None, "Error", "Couldn't start single instance server.")
                sys.exit(1)
            launcher_app['instance'].server = server # Сохраняем ссылку на сервер
            launcher_app['instance'].initialization_finished.connect(close_splash_when_ready)
            QTimer.singleShot(15000, close_splash_when_ready)
        except Exception as e:
            splash.close()
            QMessageBox.critical(None, tr('errors.startup_error_title'), tr('errors.startup_error_message', details=str(e)))
    QTimer.singleShot(100, create_launcher)
    try:
        sys.exit(app.exec())
    except Exception as e:
        QMessageBox.critical(None, tr('errors.startup_error_title'), tr('errors.startup_error_message', details=str(e)))
