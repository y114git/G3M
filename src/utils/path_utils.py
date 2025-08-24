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
