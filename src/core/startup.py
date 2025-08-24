import argparse
import os
import platform
import sys
import tempfile
import time
import psutil
from PyQt6.QtCore import QLibraryInfo, Qt, QTranslator, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
from localization.manager import get_localization_manager, tr
from utils.audio_utils import play_deltahub_sound
from core.splash import create_splash, create_png_splash
from utils.path_utils import get_user_data_root

def create_app_reference():
    from core.app import DeltaHubApp
    return DeltaHubApp
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

def check_single_instance():
    global _lock_file
    temp_dir = tempfile.gettempdir()
    lock_file_path = os.path.join(temp_dir, 'deltahub_launcher.lock')
    if os.path.exists(lock_file_path):
        try:
            file_age = time.time() - os.path.getmtime(lock_file_path)
            if file_age > 10:
                os.remove(lock_file_path)
            else:
                with open(lock_file_path, 'r') as f:
                    pid = int(f.read().strip())
                process_alive = False
                if platform.system() == 'Windows':
                    import subprocess
                    try:
                        result = subprocess.check_output(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'], creationflags=subprocess.CREATE_NO_WINDOW, text=True)
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
                    return False
                else:
                    os.remove(lock_file_path)
        except Exception:
            try:
                os.remove(lock_file_path)
            except Exception:
                pass
    try:
        _lock_file = open(lock_file_path, 'w')
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except Exception:
        return False

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
    args = parser.parse_args()
    if not args.force_start:
        running_game = check_game_processes()
        if running_game:
            app = setup_app()
            QMessageBox.critical(None, tr('errors.game_running_title'), tr('errors.game_running_message', game_name=running_game))
            sys.exit(1)
    if not args.shortcut_launch and (not args.force_start) and (not check_single_instance()):
        app = setup_app()
        QMessageBox.critical(None, tr('errors.already_running_title'), tr('errors.already_running'))
        sys.exit(1)
    if platform.system() == 'Linux' and (not args.shortcut_launch):
        os.environ.setdefault('NO_AT_BRIDGE', '1')
    app = setup_app()
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
                launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash)
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
            launcher_app['instance'] = DeltaHubApp(parent_for_dialogs=splash)
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
