import logging
import os
import platform
import sys


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


def get_user_lang_dir() -> str:
    return os.path.join(get_user_data_root(), 'lang')


def get_user_plugins_dir() -> str:
    return os.path.join(get_user_data_root(), 'plugins')


def resource_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = os.path.join(getattr(sys, '_MEIPASS'), 'src')
    else:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(base_path, relative_path)


def get_xdelta_path():
    system = platform.system()
    if system == 'Windows':
        exe_names = ['xdelta3.exe', 'xdelta.exe']
    elif system == 'Darwin':
        exe_names = ['xdelta3_mac']
    else:
        exe_names = ['xdelta3']
    for exe_name in exe_names:
        xdelta_path = resource_path(f'assets/bin/{exe_name}')
        if os.path.exists(xdelta_path):
            if system != 'Windows':
                try:
                    os.chmod(xdelta_path, 493)
                except Exception as e:
                    logging.warning(f'Could not set executable permission on {xdelta_path}: {e}')
            return os.path.normpath(xdelta_path)
    return None
