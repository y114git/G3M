"""Game detection and validation utilities.

This module provides utilities for detecting running game processes,
validating game paths, and checking game installations.
"""
import os
import platform
import psutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from config.constants import GAME_PROCESS_NAMES, GAME_EXECUTABLES, DATA_WIN_FILENAME
if TYPE_CHECKING:
    from models.game_modes import GameMode


def is_game_running(pid: Optional[int] = None):
    """Check if a game process is currently running.

    Args:
        pid: Specific process ID to check (optional).

    Returns:
        bool: True if game is running.
    """
    if pid is not None:
        try:
            return psutil.pid_exists(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            return False
    return any((proc.info['name'] in GAME_PROCESS_NAMES for proc in psutil.process_iter(['name'])))


def is_valid_mac_game_path(path: str, skip_data_check: bool, game_type: str) -> bool:
    """Validate a macOS game path.

    Args:
        path: Path to validate.
        skip_data_check: Whether to skip data file checks.
        game_type: Type of game to validate.

    Returns:
        bool: True if valid.
    """
    app_path = Path(path)
    _MAC_APP_NAMES = {'undertale': ('UNDERTALE.app',), 'undertaleyellow': ('UNDERTALE.app',), 'pizzatower': ('PizzaTower.app',), 'sugaryspire': ('SugarySpire_ExhibitionNight.app',)}
    if not path.endswith('.app'):
        app_names = _MAC_APP_NAMES.get(game_type, ('DELTARUNE.app', 'DELTARUNEdemo.app'))
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
    """Validate a game installation path.

    Args:
        path: Path to validate.
        skip_data_check: Whether to skip data file checks.
        game_type: Type of game to validate.

    Returns:
        bool: True if valid.
    """
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
    """Get the chapter/slot ID for a given game mode.

    Args:
        game_mode: Game mode instance.

    Returns:
        int: Chapter/slot ID for the game mode.
    """
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode
    from config.constants import SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_PIZZA_TOWER, SLOT_ID_SUGARY_SPIRE, SLOT_ID_UNIVERSAL
    mode_slots = {DemoGameMode: SLOT_ID_DEMO, UndertaleGameMode: SLOT_ID_UNDERTALE, UndertaleYellowGameMode: SLOT_ID_UNDERTALE_YELLOW, PizzaTowerGameMode: SLOT_ID_PIZZA_TOWER, SugarySpireGameMode: SLOT_ID_SUGARY_SPIRE}
    return mode_slots.get(type(game_mode), SLOT_ID_UNIVERSAL)


def get_game_type_string(game_mode: 'GameMode') -> str:
    """Get the game type string identifier for a game mode.

    Args:
        game_mode: Game mode instance.

    Returns:
        str: Game type string (deltarune, undertale, etc.).
    """
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode
    mode_map = {DemoGameMode: 'deltarune', UndertaleGameMode: 'undertale', UndertaleYellowGameMode: 'undertaleyellow', PizzaTowerGameMode: 'pizzatower', SugarySpireGameMode: 'sugaryspire'}
    return mode_map.get(type(game_mode), 'deltarune')


def get_game_name_string(game_mode: 'GameMode') -> str:
    """Get the display name for a game mode.

    Args:
        game_mode: Game mode instance.

    Returns:
        str: Display name of the game.
    """
    from models.game_modes import DemoGameMode, UndertaleGameMode, UndertaleYellowGameMode, PizzaTowerGameMode, SugarySpireGameMode
    mode_map = {DemoGameMode: 'DELTARUNEdemo', UndertaleGameMode: 'UNDERTALE', UndertaleYellowGameMode: 'UNDERTALE Yellow', PizzaTowerGameMode: 'Pizza Tower', SugarySpireGameMode: 'Sugary Spire'}
    return mode_map.get(type(game_mode), 'DELTARUNE')


def get_executable_name_for_game(game_type: str, os_type: str = None) -> Optional[str]:
    """Get the executable name for a specific game and OS.

    Args:
        game_type: Type of game (deltarune, undertale, etc.).
        os_type: OS type (windows, linux, mac). Auto-detected if None.

    Returns:
        Optional[str]: Executable name or None if not found.
    """
    if os_type is None:
        system = platform.system()
        os_type = 'windows' if system == 'Windows' else 'mac' if system == 'Darwin' else 'linux'
    game_executables = GAME_EXECUTABLES.get(game_type, GAME_EXECUTABLES['deltarune'])
    executables = game_executables.get(os_type, game_executables.get('windows', ()))
    return executables[0] if executables else None
