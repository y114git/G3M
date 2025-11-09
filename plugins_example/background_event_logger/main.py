import os
import logging

# --- Plugin Metadata ---
PLUGIN_NAME = "background_logger_name"
VERSION = "1.0.0"
DESCRIPTION = "Logs game launch and exit events to a file"
TAB_HIDE = True

# --- Localization ---
LANG_EN = {
    "background_logger_name": "Background Event Logger",
    "log_game_launch": "Game launched.",
    "log_game_exit": "Game exited."
}

LANG_RU = {
    "background_logger_name": "Фоновый логгер событий",
    "log_game_launch": "Игра запущена.",
    "log_game_exit": "Игра закрыта."
}

# --- Logging Setup ---
log_file_path = os.path.join(os.path.dirname(__file__), 'events.log')
logging.basicConfig(filename=log_file_path, level=logging.INFO,
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')


def log_event(message):
    """Helper function to log messages with a timestamp."""
    logging.info(message)
    print(f"[Background Logger]: {message}")


# --- Event Hooks ---


def on_after_game_launch(main_app_instance):
    """Called after the game is launched."""
    tr = main_app_instance.lang_manager.get_text
    log_event(tr("log_game_launch"))


def on_before_game_exit(main_app_instance):
    """Called before the game exits."""
    tr = main_app_instance.lang_manager.get_text
    log_event(tr("log_game_exit"))
