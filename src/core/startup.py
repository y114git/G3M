import argparse
import os
import platform
import sys
import subprocess
import time
import psutil
from PyQt6.QtCore import QLibraryInfo, Qt, QTranslator, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox
from localization.manager import localization_manager, tr
from utils.audio_utils import _audio_manager
from core.splash import create_splash, create_png_splash
from utils.path_utils import get_user_data_root, get_launcher_dir
if platform.system() == 'Windows':
    import winreg


def create_app_reference():
    from core.app import DeltaHubApp
    return DeltaHubApp


SINGLE_INSTANCE_KEY = 'deltahub.y.114.single-instance-lock'
_translator = QTranslator()
_splash_start_time = None


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
    if getattr(sys, 'frozen', False):
        executable_path = f'"{sys.executable}"'
    else:
        main_script_path = os.path.abspath(os.path.join(get_launcher_dir(), '..', 'src', 'main.py'))
        executable_path = f'"{sys.executable}" "{main_script_path}"'
    system = platform.system()
    try:
        if system == 'Windows':
            key_path = 'Software\\Classes\\deltahub'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValue(key, '', winreg.REG_SZ, 'URL:DELTAHUB Protocol')
                winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
                command_key_path = f'{key_path}\\shell\\open\\command'
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_key_path) as command_key:
                    command = f'{executable_path} "%1"'
                    winreg.SetValue(command_key, '', winreg.REG_SZ, command)
        elif system == 'Linux':
            desktop_file_content = f'[Desktop Entry]\nName=DELTAHUB Launcher\nExec={executable_path} %u\nType=Application\nTerminal=false\nMimeType=x-scheme-handler/deltahub;\n'
            apps_dir = os.path.expanduser('~/.local/share/applications')
            os.makedirs(apps_dir, exist_ok=True)
            desktop_file_path = os.path.join(apps_dir, 'deltahub.desktop')
            with open(desktop_file_path, 'w', encoding='utf-8') as f:
                f.write(desktop_file_content)
            subprocess.run(['xdg-mime', 'default', 'deltahub.desktop', 'x-scheme-handler/deltahub'], check=False)
    except Exception as e:
        print(f'Failed to register URL protocol: {e}')


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
            if url.startswith('deltahub://'):
                self.app_instance.url_received_signal.emit(url)
        socket.close()


def setup_app():
    language_code = localization_manager.detect_system_language()
    localization_manager.load_language(language_code)
    os.environ['QT_LOGGING_RULES'] = ';'.join(['qt.qpa.screen.warning=false', 'qt.qpa.window.warning=false', 'qt.multimedia.ffmpeg=false', 'qt.multimedia=false'])
    if not getattr(sys, 'frozen', False):
        os.environ.setdefault('QT_MEDIA_BACKEND', 'ffmpeg')
    app = QApplication(sys.argv)
    qt_translation_file = localization_manager.get_qt_translation_name(language_code)
    if qt_translation_file:
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if _translator.load(qt_translation_file, path):
            app.installTranslator(_translator)
    app.setApplicationName('DELTAHUB')
    from config.constants import LAUNCHER_VERSION
    app.setApplicationVersion(LAUNCHER_VERSION)
    app.setOrganizationName('deltahub')
    return app


def run_app():
    parser = argparse.ArgumentParser(description='DELTAHUB')
    parser.add_argument('--shortcut-launch', type=str)
    parser.add_argument('--shortcut-path', type=str)
    parser.add_argument('--force-start', action='store_true', help='Force start even if another instance is detected')
    args, unknown_args = parser.parse_known_args()
    url_arg = next((arg for arg in sys.argv[1:] if arg.startswith('deltahub://')), None)
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(500):
        if url_arg:
            socket.writeData(url_arg.encode('utf-8'))
            socket.flush()
            socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        sys.exit(0)
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    if not args.force_start:
        running_game = check_game_processes()
        if running_game:
            app = setup_app()
            error_msg = tr('errors.game_running_message', game_name=running_game)
            print(f"STARTUP ERROR: {error_msg}")
            QMessageBox.critical(None, tr('errors.game_running_title'), error_msg)
            sys.exit(1)
    if platform.system() == 'Linux' and (not args.shortcut_launch):
        os.environ.setdefault('NO_AT_BRIDGE', '1')
    app = setup_app()
    try:
        register_url_protocol()
    except Exception as e:
        print(f'Could not register protocol handler: {e}')
    if args.shortcut_launch:
        DeltaHubApp = create_app_reference()
        DeltaHubApp(args=args)
        return
    config = {}
    try:
        config_path = os.path.join(get_user_data_root(), 'settings', 'config.json')
        if os.path.exists(config_path):
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
    except Exception:
        pass
    is_first_launch = not config.get('first_launch_splash_shown', False)
    splash_disabled_by_user = config.get('disable_splash', False)
    show_animated_splash = is_first_launch or not splash_disabled_by_user
    if not show_animated_splash:
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
                    error_msg = tr('errors.single_instance_error')
                    print(f"STARTUP ERROR: {error_msg}")
                    QMessageBox.critical(None, tr('errors.error'), error_msg)
                    sys.exit(1)
                launcher_app['instance'].server = server
                launcher_app['instance']._post_show_initialization()
                launcher_app['instance'].initialization_finished.connect(close_splash_and_show_launcher)
                QTimer.singleShot(15000, close_splash_and_show_launcher)
            except Exception as e:
                if hasattr(splash, 'movie'):
                    splash.stop_gif_animation()
                splash.close()
                error_msg = tr('errors.startup_error_message', details=str(e))
                print(f"STARTUP ERROR: {error_msg}")
                QMessageBox.critical(None, tr('errors.startup_error_title'), error_msg)
        QTimer.singleShot(100, create_launcher_no_animation)
        try:
            sys.exit(app.exec())
        except Exception as e:
            error_msg = tr('errors.startup_error_message', details=str(e))
            print(f"STARTUP ERROR: {error_msg}")
            QMessageBox.critical(None, tr('errors.startup_error_title'), error_msg)
        return
    global _splash_start_time
    _splash_start_time = time.time()
    splash = create_splash()

    def start_splash_and_sound():
        _audio_manager.play_deltahub_sound()
        if hasattr(splash, 'movie'):
            splash.start_gif_animation()
    if hasattr(splash, 'movie'):
        for _ in range(50):
            app.processEvents()
            if splash.movie.currentFrameNumber() >= 0:
                break
            time.sleep(0.01)
    splash.show()
    app.processEvents()
    QTimer.singleShot(1000, start_splash_and_sound)
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
            show_launcher_window(ex)
        else:
            if _splash_start_time is not None:
                remaining_time = int((11 - (time.time() - _splash_start_time)) * 1000)
            else:
                remaining_time = 0

            def show_launcher():
                close_splash()
                ex = launcher_app.get('instance')
                show_launcher_window(ex)
            QTimer.singleShot(remaining_time, show_launcher)

    def show_launcher_window(ex):
        if ex:
            ex.show()
            ex.is_shown_to_user = True
            ex.activateWindow()
            ex.raise_()
            ex.setWindowState(ex.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)

    def create_launcher():
        try:
            DeltaHubApp = create_app_reference()
            launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash, initial_url=url_arg)
            server = SingleInstanceServer(launcher_app['instance'])
            if not server.listen(SINGLE_INSTANCE_KEY):
                error_msg = tr('errors.single_instance_error')
                print(f"STARTUP ERROR: {error_msg}")
                QMessageBox.critical(None, tr('errors.error'), error_msg)
                sys.exit(1)
            launcher_app['instance'].server = server
            launcher_app['instance']._post_show_initialization()
            launcher_app['instance'].initialization_finished.connect(close_splash_when_ready)
            QTimer.singleShot(15000, close_splash_when_ready)
        except Exception as e:
            splash.close()
            error_msg = tr('errors.startup_error_message', details=str(e))
            print(f"STARTUP ERROR: {error_msg}")
            QMessageBox.critical(None, tr('errors.startup_error_title'), error_msg)
    QTimer.singleShot(100, create_launcher)
    try:
        sys.exit(app.exec())
    except Exception as e:
        error_msg = tr('errors.startup_error_message', details=str(e))
        print(f"STARTUP ERROR: {error_msg}")
        QMessageBox.critical(None, tr('errors.startup_error_title'), error_msg)
