import os
import platform
import psutil
from pathlib import Path
from typing import TYPE_CHECKING
from config.constants import GAME_PROCESS_NAMES
if TYPE_CHECKING:
    from models.game_modes import GameMode
    from core.app_state import AppState


def is_game_running():
    return any((proc.info['name'] in GAME_PROCESS_NAMES for proc in psutil.process_iter(['name'])))


def is_valid_mac_game_path(path: str, skip_data_check: bool, game_type: str) -> bool:
    app_path = Path(path)
    if not path.endswith('.app'):
        if game_type == 'undertale' or game_type == 'undertaleyellow':
            app_names = ('UNDERTALE.app',)
        else:
            app_names = ('DELTARUNE.app', 'DELTARUNEdemo.app')
        app_path = next((app_path / name for name in app_names if (app_path / name).is_dir()), None)
    if not app_path or not app_path.is_dir():
        return False
    contents = app_path / 'Contents'
    macos_dir = contents / 'MacOS'
    res_dir = contents / 'Resources'
    if not macos_dir.is_dir() or not res_dir.is_dir():
        return False
    try:
        has_executable = any((p.is_file() and os.access(p, os.X_OK) for p in macos_dir.iterdir()))
    except OSError:
        return False
    if skip_data_check:
        return has_executable
    has_data = (res_dir / 'game.ios').is_file() or (res_dir / 'data.win').is_file()
    return has_executable and has_data


def is_valid_game_path(path: str, skip_data_check: bool = False, game_type: str = 'deltarune') -> bool:
    if not path or not os.path.isdir(path):
        return False
    if platform.system() == 'Darwin':
        return is_valid_mac_game_path(path, skip_data_check, game_type)
    if game_type == 'undertale' or game_type == 'undertaleyellow':
        if game_type == 'undertaleyellow':
            executables = ('Undertale Yellow.exe', 'Undertale Yellow', 'UNDERTALE.exe', 'UNDERTALE')
        else:
            executables = ('UNDERTALE.exe', 'UNDERTALE')
    else:
        executables = ('DELTARUNE.exe', 'DELTARUNE')
    return any((os.path.isfile(os.path.join(path, exe)) for exe in executables))


def get_chapter_id_for_game_mode(game_mode: 'GameMode') -> int:
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode
    from config.constants import SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_UNIVERSAL
    if isinstance(game_mode, DemoGameMode):
        return SLOT_ID_DEMO
    elif isinstance(game_mode, UndertaleGameMode):
        return SLOT_ID_UNDERTALE
    elif isinstance(game_mode, UndertaleYellowGameMode):
        return SLOT_ID_UNDERTALE_YELLOW
    else:
        return SLOT_ID_UNIVERSAL


def get_game_type_string(game_mode: 'GameMode') -> str:
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode
    if isinstance(game_mode, DemoGameMode):
        return 'deltarune'
    elif isinstance(game_mode, UndertaleGameMode):
        return 'undertale'
    elif isinstance(game_mode, UndertaleYellowGameMode):
        return 'undertaleyellow'
    else:
        return 'deltarune'


def get_game_name_string(game_mode: 'GameMode') -> str:
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode
    if isinstance(game_mode, DemoGameMode):
        return 'DELTARUNEdemo'
    elif isinstance(game_mode, UndertaleGameMode):
        return 'UNDERTALE'
    elif isinstance(game_mode, UndertaleYellowGameMode):
        return 'UNDERTALE Yellow'
    else:
        return 'DELTARUNE'
