import os
import sys
import platform

def get_legacy_ylauncher_path() -> str:
    system = platform.system()
    if system == 'Windows':
        return os.path.join(os.getenv('APPDATA', ''), 'YLauncher')
    elif system == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'YLauncher')
    else:
        return os.path.join(os.path.expanduser('~'), '.local', 'share', 'YLauncher')

def get_launcher_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.abspath(os.path.dirname(__file__))

def get_user_data_root() -> str:
    system = platform.system()
    if system == 'Windows':
        root = os.getenv('LOCALAPPDATA') or os.getenv('APPDATA')
        return os.path.join(root or os.path.expanduser('~'), 'DELTAHUB')
    elif system == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'DELTAHUB')
    else:
        return os.path.join(os.path.expanduser('~'), '.local', 'share', 'DELTAHUB')

def get_user_mods_dir() -> str:
    return os.path.join(get_user_data_root(), 'mods')

def resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        # The spec file bundles the 'src' folder, so our base is _MEIPASS/src
        base_path = os.path.join(getattr(sys, '_MEIPASS'), 'src')
    else:
        # In dev mode, the base path is the 'src' directory.
        # This file is in src/utils, so we go up one level.
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_path, relative_path)
