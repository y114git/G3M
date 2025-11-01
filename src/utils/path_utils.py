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


def resolve_game_executable(base_dir: str, is_undertale: bool) -> str | None:
    try:
        if not base_dir or not os.path.isdir(base_dir):
            return None
        system = platform.system()
        base_exe_name = 'UNDERTALE' if is_undertale else 'DELTARUNE'
        if system == 'Windows':
            exe_path = os.path.join(base_dir, f'{base_exe_name}.exe')
            return exe_path if os.path.isfile(exe_path) else None
        if system == 'Linux':
            native_path = os.path.join(base_dir, base_exe_name)
            if os.path.isfile(native_path) and os.access(native_path, os.X_OK):
                return native_path
            exe_path = os.path.join(base_dir, f'{base_exe_name}.exe')
            return exe_path if os.path.isfile(exe_path) else None
        if system == 'Darwin':
            app_path = base_dir if base_dir.endswith('.app') and os.path.isdir(base_dir) else None
            if not app_path:
                app_names = ['UNDERTALE.app'] if is_undertale else ['DELTARUNE.app', 'DELTARUNEdemo.app']
                for name in app_names:
                    candidate = os.path.join(base_dir, name)
                    if os.path.isdir(candidate):
                        app_path = candidate
                        break
            return app_path
        return None
    except Exception as e:
        logging.debug(f'resolve_game_executable: failed for {base_dir}: {e}')
        return None


def find_chapter_resource_dir(base_dir: str, chapter_id: int) -> str | None:
    try:
        if not base_dir:
            return None
        target_base = base_dir
        if platform.system() == 'Darwin':
            if not target_base.endswith('.app'):
                for app_name in ('DELTARUNE.app', 'DELTARUNEdemo.app'):
                    candidate = os.path.join(target_base, app_name)
                    if os.path.isdir(candidate):
                        target_base = candidate
                        break
            target_base = os.path.join(target_base, 'Contents', 'Resources')
            if not os.path.isdir(target_base):
                return None
        if chapter_id in (-1, 0):
            return target_base
        chapter_prefix = f'chapter{chapter_id}_'
        for entry in os.listdir(target_base):
            if os.path.isdir(os.path.join(target_base, entry)) and entry.startswith(chapter_prefix):
                return os.path.join(target_base, entry)
        return None
    except Exception as e:
        logging.debug(f'find_chapter_resource_dir: failed for {base_dir}, chapter {chapter_id}: {e}')
        return None
