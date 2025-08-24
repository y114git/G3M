import os
import platform
import psutil
from pathlib import Path
from config.constants import GAME_PROCESS_NAMES

def is_game_running():
    return any((proc.info['name'] in GAME_PROCESS_NAMES for proc in psutil.process_iter(['name'])))

def get_default_save_path() -> str:
    system = platform.system()
    paths = {'Windows': os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Local', 'DELTARUNE'), 'Darwin': os.path.expanduser('~/Library/Application Support/com.tobyfox.deltarune')}
    default_path = os.path.expanduser('~/.steam/steam/steamapps/compatdata/1690940/pfx/drive_c/users/steamuser/Local Settings/Application Data/DELTARUNE')
    return paths.get(system, default_path)

def is_valid_save_path(path: str) -> bool:
    return bool(path and os.path.isdir(path) and os.listdir(path))

def is_valid_mac_game_path(path: str, skip_data_check: bool, game_type: str) -> bool:
    app_path = Path(path)
    if not path.endswith('.app'):
        app_names = ('UNDERTALE.app',) if game_type == 'undertale' else ('DELTARUNE.app', 'DELTARUNEdemo.app')
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

def is_valid_game_path(path: str, skip_data_check: bool=False, game_type: str='deltarune') -> bool:
    if not path or not os.path.isdir(path):
        return False
    if platform.system() == 'Darwin':
        return is_valid_mac_game_path(path, skip_data_check, game_type)
    executables = ('UNDERTALE.exe', 'UNDERTALE') if game_type == 'undertale' else ('DELTARUNE.exe', 'DELTARUNE')
    return any((os.path.isfile(os.path.join(path, exe)) for exe in executables))