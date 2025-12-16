import argparse
import logging
import os
import platform
import sys
import subprocess
import time
import psutil
from PyQt6.QtCore import QLibraryInfo, QTranslator, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox
from managers.localization_manager import localization_manager, tr
from utils.audio_utils import _audio_manager
from utils.network_utils import sanitize_log_message
from core.splash import create_png_splash
from utils.path_utils import resource_path, get_user_data_root, get_launcher_dir
from logging.handlers import RotatingFileHandler
from config.constants import SPLASH_MIN_DURATION, LAUNCHER_FALLBACK_TIMEOUT, SPLASH_RETRY_DELAY
import traceback
if platform.system() == 'Windows':
    import winreg


class ShortcutLaunchError(Exception):
    pass


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


class SecureLogFilter(logging.Filter):

    def filter(self, record):
        try:
            if record.getMessage():
                record.msg = sanitize_log_message(str(record.msg))
                record.args = ()
        except Exception:
            pass
        return True


def configure_logging(app_name: str, user_data_root: str, clear_logs: bool = False) -> str:
    log_path = os.path.join(user_data_root, f'{app_name.lower()}.log')
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
        secure_filter = SecureLogFilter()
        if clear_logs and os.path.exists(log_path):
            try:
                with open(log_path, 'w', encoding='utf-8'):
                    pass
            except Exception as e:
                logging.warning(f'Failed to clear log file: {e}')
        file_handler = RotatingFileHandler(log_path, maxBytes=10000000, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(fmt)
        file_handler.addFilter(secure_filter)
        root.addHandler(file_handler)
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(fmt)
        console.addFilter(secure_filter)
        root.addHandler(console)
        urllib3_logger = logging.getLogger('urllib3')
        urllib3_logger.addFilter(secure_filter)
        urllib3_logger.setLevel(logging.WARNING)
        requests_logger = logging.getLogger('requests')
        requests_logger.addFilter(secure_filter)
        requests_logger.setLevel(logging.WARNING)
    return log_path


def install_excepthook(show_message_callback=None):

    def _hook(exctype, value, tb):
        try:
            logging.critical('Uncaught exception', exc_info=(exctype, value, tb))
        except Exception as e:
            try:
                print(f'CRITICAL: Failed to log uncaught exception: {e}', file=sys.stderr)
            except Exception:
                pass
        try:
            if callable(show_message_callback):
                msg = ''.join(traceback.format_exception(exctype, value, tb))
                show_message_callback(msg)
        except Exception as e:
            try:
                print(f'WARNING: Failed to show exception message: {e}', file=sys.stderr)
            except Exception:
                pass
    sys.excepthook = _hook


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
        pass


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


def cleanup_old_temp_directories():
    import tempfile
    import glob
    from utils.file_utils import safe_rmtree
    temp_base = tempfile.gettempdir()
    patterns = [os.path.join(temp_base, 'deltahub_modpack_*'), os.path.join(temp_base, 'deltahub_multimod_*'), os.path.join(temp_base, 'deltahub-dl-*'), os.path.join(temp_base, 'deltahub-extract-*')]
    cleaned_count = 0
    for pattern in patterns:
        try:
            for temp_dir in glob.glob(pattern):
                if os.path.isdir(temp_dir):
                    try:
                        mtime = os.path.getmtime(temp_dir)
                        import time
                        if time.time() - mtime > 3600:
                            if safe_rmtree(temp_dir):
                                cleaned_count += 1
                                logging.debug(f'Cleaned up old temp directory: {temp_dir}')
                    except OSError:
                        pass
        except Exception as e:
            logging.debug(f'Failed to cleanup temp directories matching {pattern}: {e}')
    if cleaned_count > 0:
        logging.info(f'Cleaned up {cleaned_count} old temporary directory(ies) from previous sessions')


def _load_config_file() -> dict:
    user_root = get_user_data_root()
    settings_path = os.path.join(user_root, 'settings', 'settings.json')
    old_config_path = os.path.join(user_root, 'settings', 'config.json')
    config_path = settings_path if os.path.exists(settings_path) else old_config_path
    if not os.path.exists(config_path):
        return {}
    try:
        import json
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if config_path == old_config_path and (not os.path.exists(settings_path)):
            import shutil
            shutil.move(old_config_path, settings_path)
            logging.info('Migrated settings config.json to settings.json in startup')
        return config
    except json.JSONDecodeError as e:
        backup_path = f'{config_path}.invalid.bak'
        try:
            import shutil
            shutil.copy2(config_path, backup_path)
            logging.warning(f'Corrupted config file detected, backed up to {backup_path}')
            os.remove(config_path)
            logging.info(f'Removed corrupted config file: {config_path}')
        except Exception:
            pass
        pass
        return {}
    except (PermissionError, OSError) as e:
        return {}
    except Exception as e:
        return {}


def run_app():
    try:
        user_root = get_user_data_root()
        config = _load_config_file()
        clear_logs = config.get('clear_logs_on_startup', False)
        configure_logging('DELTAHUB', user_root, clear_logs=clear_logs)
        install_excepthook()
        cleanup_old_temp_directories()
    except Exception as e:
        logging.warning(f'Failed to initialize logging: {e}')
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
            logging.error(f'STARTUP ERROR: {error_msg}')
            QMessageBox.critical(None, tr('errors.game_running_title'), error_msg)
            sys.exit(1)
    if platform.system() == 'Linux' and (not args.shortcut_launch):
        os.environ.setdefault('NO_AT_BRIDGE', '1')
    app = setup_app()
    try:
        register_url_protocol()
    except Exception as e:
        pass
    if args.shortcut_launch:
        from core.app_window import AppWindow
        try:
            AppWindow(args=args)
        except ShortcutLaunchError as e:
            error_msg = str(e) or tr('errors.error')
            logging.error(f'STARTUP ERROR: {error_msg}')
            QMessageBox.critical(None, tr('errors.error'), error_msg)
            sys.exit(1)
        return
    config = _load_config_file()
    splash_disabled_by_user = config.get('disable_splash', False)
    show_animated_splash = not splash_disabled_by_user

    def create_launcher_and_show_splash(app, initial_url, show_animation: bool):
        global _splash_start_time
        launcher_app = {}
        splash = create_png_splash()
        if show_animation:
            _splash_start_time = time.time()
            from core.splash import CustomSplashScreen
            gif_path = resource_path('assets/images/splash.gif')
            if os.path.exists(gif_path):
                gif_splash = CustomSplashScreen(gif_path=gif_path)
                if hasattr(gif_splash, 'movie') and gif_splash.movie.isValid():
                    splash = gif_splash
                    splash.start_gif_animation(sound_start_callback=_audio_manager.play_deltahub_sound)
            else:
                _audio_manager.play_deltahub_sound()
        splash.show()
        app.processEvents()

        def show_launcher_window(ex):
            if ex:
                if hasattr(ex, 'app_state') and getattr(ex.app_state, 'game_is_running', False):
                    return
                try:
                    ex.show()
                    ex.is_shown_to_user = True
                    if hasattr(ex, 'app_state'):
                        ex.app_state.is_shown_to_user = True
                    from PyQt6.QtWidgets import QApplication
                    qapp = QApplication.instance()
                    if qapp:
                        qapp.processEvents()
                except Exception as e:
                    logging.error(f'Error showing launcher window: {e}', exc_info=True)

        def close_splash():
            if hasattr(splash, 'movie'):
                splash.stop_gif_animation()
            splash.close()

        def check_minimum_splash_time():
            if _splash_start_time is None:
                return True
            elapsed = time.time() - _splash_start_time
            return elapsed >= SPLASH_MIN_DURATION

        def close_splash_and_show_launcher():
            close_splash()
            ex = launcher_app.get('instance')
            show_launcher_window(ex)

        def close_splash_when_ready():
            if show_animation and (not check_minimum_splash_time()) and (_splash_start_time is not None):
                remaining_time = max(0, int((SPLASH_MIN_DURATION - (time.time() - _splash_start_time)) * 1000))
                QTimer.singleShot(remaining_time, lambda: (close_splash(), show_launcher_window(launcher_app.get('instance'))))
            else:
                close_splash()
                show_launcher_window(launcher_app.get('instance'))

        def create_launcher():
            try:
                from core.app_window import AppWindow
                launcher_app['instance'] = AppWindow(parent_for_dialogs=splash, initial_url=initial_url)
                server = SingleInstanceServer(launcher_app['instance'])
                if not server.listen(SINGLE_INSTANCE_KEY):
                    error_msg = tr('errors.single_instance_error')
                    logging.error(f'STARTUP ERROR: {error_msg}')
                    QMessageBox.critical(None, tr('errors.error'), error_msg)
                    sys.exit(1)
                launcher_app['instance'].server = server
                if show_animation:
                    launcher_app['instance']._splash_was_shown = True
                launcher_app['instance']._post_show_initialization()
                mods_display_ready_flag = {'ready': False}
                window_shown_flag = {'shown': False}

                def on_mods_display_ready():
                    if window_shown_flag['shown']:
                        return
                    mods_display_ready_flag['ready'] = True
                    window_shown_flag['shown'] = True
                    if show_animation:
                        close_splash_when_ready()
                    else:
                        close_splash_and_show_launcher()
                launcher_app['instance'].mods_display_ready.connect(on_mods_display_ready)
                if hasattr(launcher_app['instance'], '_mods_display_ready_emitted'):
                    if launcher_app['instance']._mods_display_ready_emitted:
                        QTimer.singleShot(100, on_mods_display_ready)

                def fallback_show_window():
                    if window_shown_flag['shown']:
                        return
                    if not mods_display_ready_flag['ready']:
                        logging.info('Fallback: Showing window after timeout (mods display not ready in time)')
                        window_shown_flag['shown'] = True
                        if show_animation:
                            close_splash_when_ready()
                        else:
                            close_splash_and_show_launcher()
                if show_animation:
                    fallback_time = max(LAUNCHER_FALLBACK_TIMEOUT, int(SPLASH_MIN_DURATION * 1000))
                    QTimer.singleShot(fallback_time, fallback_show_window)
                else:
                    fallback_time = max(LAUNCHER_FALLBACK_TIMEOUT, 10000)
                    QTimer.singleShot(fallback_time, fallback_show_window)
            except Exception as e:
                import traceback
                traceback.print_exc()
                if hasattr(splash, 'movie'):
                    splash.stop_gif_animation()
                splash.close()
                error_msg = tr('errors.startup_error_message', details=str(e))
                logging.error(f'STARTUP ERROR: {error_msg}')
                QMessageBox.critical(None, tr('errors.startup_error_title'), error_msg)
        QTimer.singleShot(SPLASH_RETRY_DELAY, create_launcher)
    create_launcher_and_show_splash(app, url_arg, show_animated_splash)
    try:
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = tr('errors.startup_error_message', details=str(e))
        logging.error(f'STARTUP ERROR: {error_msg}')
        QMessageBox.critical(None, tr('errors.startup_error_title'), error_msg)
