import os
import platform
import psutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from config.constants import GAME_PROCESS_NAMES, GAME_EXECUTABLES, DATA_WIN_FILENAME
if TYPE_CHECKING:
    from models.game_modes import GameMode


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
    has_data = (res_dir / 'game.ios').is_file() or (res_dir / DATA_WIN_FILENAME).is_file()
    return has_executable and has_data


def is_valid_game_path(path: str, skip_data_check: bool = False, game_type: str = 'deltarune') -> bool:
    if not path or not os.path.isdir(path):
        return False
    if platform.system() == 'Darwin':
        return is_valid_mac_game_path(path, skip_data_check, game_type)
    system = platform.system()
    platform_key = 'windows' if system == 'Windows' else 'linux'
    game_executables = GAME_EXECUTABLES.get(game_type, GAME_EXECUTABLES['deltarune'])
    executables = game_executables.get(platform_key, game_executables.get('windows', ()))
    exe_name = get_executable_name_for_game(game_type, platform_key)
    if exe_name:
        return os.path.isfile(os.path.join(path, exe_name))
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


def get_executable_name_for_game(game_type: str, os_type: str = None) -> Optional[str]:
    if os_type is None:
        system = platform.system()
        os_type = 'windows' if system == 'Windows' else 'mac' if system == 'Darwin' else 'linux'
    game_executables = GAME_EXECUTABLES.get(game_type, GAME_EXECUTABLES['deltarune'])
    executables = game_executables.get(os_type, game_executables.get('windows', ()))
    return executables[0] if executables else None
