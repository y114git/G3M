"""Game detection and validation utilities."""
import os
import platform
import psutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from config.constants import GAME_PROCESS_NAMES, GAME_EXECUTABLES, DATA_WIN_FILENAME, TAB_ALL
if TYPE_CHECKING:
    from models.game_modes import GameDefinition


def is_game_running(pid: Optional[int] = None):
    if pid is not None:
        try:
            return psutil.pid_exists(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False
    return any(proc.info['name'] in GAME_PROCESS_NAMES for proc in psutil.process_iter(['name']))


def is_valid_mac_game_path(path: str, skip_data_check: bool, game_type: str) -> bool:
    app_path = Path(path)
    from models.game_modes import get_game
    gm = get_game(game_type)
    app_names = gm.macos_app_names if gm else ('DELTARUNE.app', 'DELTARUNEdemo.app')
    if not path.endswith('.app'):
        app_path = next((app_path / name for name in app_names if (app_path / name).is_dir()), None)
    if not app_path or not app_path.is_dir():
        return False
    macos_dir, res_dir = app_path / 'Contents' / 'MacOS', app_path / 'Contents' / 'Resources'
    if not (macos_dir.is_dir() and res_dir.is_dir()):
        return False
    try:
        has_executable = any(p.is_file() and os.access(p, os.X_OK) for p in macos_dir.iterdir())
    except OSError:
        return False
    return has_executable if skip_data_check else (has_executable and ((res_dir / 'game.ios').is_file() or (res_dir / DATA_WIN_FILENAME).is_file()))


def is_valid_game_path(path: str, skip_data_check: bool = False, game_type: str = 'deltarune') -> bool:
    if not path or not os.path.isdir(path):
        return False
    if platform.system() == 'Darwin':
        return is_valid_mac_game_path(path, skip_data_check, game_type)
    platform_key = 'windows' if platform.system() == 'Windows' else 'linux'
    if exe_name := get_executable_name_for_game(game_type, platform_key):
        return os.path.isfile(os.path.join(path, exe_name))
    executables = GAME_EXECUTABLES.get(game_type, GAME_EXECUTABLES['deltarune']).get(platform_key, ())
    return any(os.path.isfile(os.path.join(path, exe)) for exe in executables)


def get_game_type_string(game_mode: 'GameDefinition') -> str:
    return getattr(game_mode, 'game_id', 'deltarune')


def get_game_name_string(game_mode: 'GameDefinition') -> str:
    return getattr(game_mode, 'display_name', 'DELTARUNE')


def get_chapter_id_for_game_mode(game_mode: 'GameDefinition') -> int:
    return getattr(game_mode, 'default_tab_id', TAB_ALL)


def get_executable_name_for_game(game_type: str, os_type: str = None) -> Optional[str]:
    if os_type is None:
        os_type = 'windows' if platform.system() == 'Windows' else ('mac' if platform.system() == 'Darwin' else 'linux')
    executables = GAME_EXECUTABLES.get(game_type, GAME_EXECUTABLES['deltarune']).get(os_type, ())
    return executables[0] if executables else None
