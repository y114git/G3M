"""Application startup and initialization."""

import argparse
import contextlib
import logging
import os
import platform
import shutil
import sys
import time
import traceback

import psutil
from PyQt6.QtCore import QLibraryInfo, QProcess, QTranslator
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from bootstrap.bootstrap_coordinator import BootstrapCoordinator
from config.config import SINGLE_INSTANCE_KEY
from models.game_modes import get_all_process_names
from services.localization_service import localization_service, tr
from utils.path_utils import get_launcher_dir, get_user_data_root, resource_path

if platform.system() == "Windows":
    import winreg
_translator = QTranslator()


def check_game_processes():
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] in get_all_process_names():
                return proc.info["name"]
        except psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess:
            pass
    return None


def configure_logging(app_name: str, user_data_root: str) -> str:
    logs_dir = os.path.join(user_data_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, f"{app_name.lower()}.log")
    archive_dir = os.path.join(logs_dir, "deltahub")
    os.makedirs(archive_dir, exist_ok=True)
    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = os.path.join(archive_dir, f"deltahub_{timestamp}.log")
            shutil.copy2(log_path, archive_path)
        except Exception:
            logging.debug("Failed to archive previous log file", exc_info=True)
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(fmt)
        root.addHandler(console)
        urllib3_logger = logging.getLogger("urllib3")
        urllib3_logger.setLevel(logging.WARNING)
        requests_logger = logging.getLogger("requests")
        requests_logger.setLevel(logging.WARNING)
    return log_path


def install_excepthook(show_message_callback=None):
    def _hook(exctype, value, tb):
        try:
            logging.critical("Uncaught exception", exc_info=(exctype, value, tb))
        except Exception:
            with contextlib.suppress(Exception):
                pass
        try:
            if callable(show_message_callback):
                msg = "".join(traceback.format_exception(exctype, value, tb))
                show_message_callback(msg)
        except Exception as e:
            logging.error("Failed to show exception message: %s", e)

    sys.excepthook = _hook


def register_url_protocol():
    if getattr(sys, "frozen", False):
        executable_path = f'"{sys.executable}"'
    else:
        main_script_path = os.path.abspath(
            os.path.join(get_launcher_dir(), "..", "src", "main.py")
        )
        executable_path = f'"{sys.executable}" "{main_script_path}"'
    system = platform.system()
    try:
        if system == "Windows":
            key_path = "Software\\Classes\\deltahub"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, "URL:DELTAHUB Protocol")
                winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
                command_key_path = f"{key_path}\\shell\\open\\command"
                with winreg.CreateKey(
                    winreg.HKEY_CURRENT_USER, command_key_path
                ) as command_key:
                    command = f'{executable_path} "%1"'
                    winreg.SetValue(command_key, "", winreg.REG_SZ, command)
        elif system == "Linux":
            desktop_file_content = f"[Desktop Entry]\nName=DELTAHUB Launcher\nExec={executable_path} %u\nType=Application\nTerminal=false\nMimeType=x-scheme-handler/deltahub;\n"
            apps_dir = os.path.expanduser("~/.local/share/applications")
            os.makedirs(apps_dir, exist_ok=True)
            desktop_file_path = os.path.join(apps_dir, "deltahub.desktop")
            with open(desktop_file_path, "w", encoding="utf-8") as f:
                f.write(desktop_file_content)
            if shutil.which("xdg-mime"):
                QProcess.startDetached(
                    "xdg-mime",
                    [
                        "default",
                        "deltahub.desktop",
                        "x-scheme-handler/deltahub",
                    ],
                )
    except Exception as e:
        logging.warning(f"Failed to register URL protocol handler: {e}", exc_info=True)


class SingleInstanceServer(QLocalServer):
    def __init__(self, app_instance) -> None:
        super().__init__()
        self.app_instance = app_instance
        self.newConnection.connect(self.handle_new_connection)

    def handle_new_connection(self):
        socket = self.nextPendingConnection()
        if socket:
            socket.readyRead.connect(lambda: self.read_socket_data(socket))

    def read_socket_data(self, socket):
        try:
            data = socket.readAll().data()
            if data:
                try:
                    url = data.decode("utf-8")
                except UnicodeDecodeError as e:
                    logging.warning(
                        f"SingleInstanceServer: failed to decode incoming data: {e}"
                    )
                    return
                if url.startswith("deltahub://"):
                    self.app_instance.url_received_signal.emit(url)
        finally:
            socket.close()


def setup_app():
    language_code = localization_service.detect_system_language()
    localization_service.load_language(language_code)
    os.environ["QT_LOGGING_RULES"] = ";".join(
        [
            "qt.qpa.screen.warning=false",
            "qt.qpa.window.warning=false",
            "qt.multimedia.ffmpeg=false",
            "qt.multimedia=false",
        ]
    )
    if not getattr(sys, "frozen", False):
        os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    app = QApplication(sys.argv)
    qt_locale_file = localization_service.get_qt_locale_name(language_code)
    if qt_locale_file:
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if _translator.load(qt_locale_file, path):
            app.installTranslator(_translator)
    app.setApplicationName("DELTAHUB")
    from config.config import APP_VERSION
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("deltahub")
    from PyQt6.QtGui import QIcon

    app.setWindowIcon(QIcon(resource_path("assets/icons/icon.ico")))
    return app


def cleanup_old_temp_directories():
    import glob
    import tempfile

    from utils.file_utils import safe_rmtree

    temp_base = tempfile.gettempdir()
    patterns = [
        os.path.join(temp_base, "deltahub_modpack_*"),
        os.path.join(temp_base, "deltahub_multimod_*"),
        os.path.join(temp_base, "deltahub-dl-*"),
        os.path.join(temp_base, "deltahub-extract-*"),
    ]
    cleaned_count = 0
    for pattern in patterns:
        try:
            for temp_dir in glob.glob(pattern):
                if os.path.isdir(temp_dir):
                    try:
                        mtime = os.path.getmtime(temp_dir)
                        if time.time() - mtime > 3600 and safe_rmtree(temp_dir):
                            cleaned_count += 1
                            logging.debug(f"Cleaned up old temp directory: {temp_dir}")
                    except OSError as e:
                        logging.debug(
                            f"Failed to check/remove temp directory {temp_dir}: {e}"
                        )
        except Exception as e:
            logging.debug(f"Failed to cleanup temp directories matching {pattern}: {e}")
    if cleaned_count > 0:
        logging.info(
            f"Cleaned up {cleaned_count} old temporary directory(ies) from previous sessions"
        )


def run_app():
    try:
        user_root = get_user_data_root()
        configure_logging("DELTAHUB", user_root)
        install_excepthook()
        cleanup_old_temp_directories()
    except Exception:
        import traceback

        traceback.print_exc(file=sys.stderr)
    parser = argparse.ArgumentParser(description="DELTAHUB")
    parser.add_argument(
        "--force-start",
        action="store_true",
        help="Force start even if another instance is detected",
    )
    args, _ = parser.parse_known_args()
    url_arg = next((arg for arg in sys.argv[1:] if arg.startswith("deltahub://")), None)
    if platform.system() == "Linux":
        os.environ.setdefault("NO_AT_BRIDGE", "1")
    app = setup_app()
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(500):
        if url_arg:
            socket.writeData(url_arg.encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        sys.exit(0)
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    if not args.force_start:
        running_game = check_game_processes()
        if running_game:
            error_msg = tr("errors.game_running_message", game_name=running_game)
            logging.error(f"STARTUP ERROR: {error_msg}")
            QMessageBox.critical(None, tr("errors.game_running_title"), error_msg)
            sys.exit(1)
    try:
        register_url_protocol()
    except Exception as e:
        logging.warning(
            f"Failed to register URL protocol during startup: {e}", exc_info=True
        )
    from app.window import AppWindow

    coordinator = BootstrapCoordinator(
        app=app,
        user_root=user_root,
        initial_url=url_arg,
        window_factory=AppWindow,
        server_factory=SingleInstanceServer,
    )
    app._bootstrap_coordinator = coordinator
    coordinator.launch()
    try:
        sys.exit(app.exec())
    except Exception as e:
        error_msg = tr("errors.unexpected_startup_error", details=str(e))
        logging.exception(f"STARTUP ERROR: {error_msg}")
        QMessageBox.critical(None, tr("errors.startup_error_title"), error_msg)
        sys.exit(1)
