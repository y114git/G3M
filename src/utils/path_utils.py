"""Path resolution and platform-specific utilities."""
import logging
import os
import platform
import sys
from config.constants import GAME_EXECUTABLES

_SYS = platform.system()


def get_launcher_dir():
    return os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath(os.path.dirname(__file__))


def get_user_data_root():
    home = os.path.expanduser('~')
    if _SYS == 'Windows':
        return os.path.join(os.getenv('LOCALAPPDATA') or os.getenv('APPDATA') or home, 'DELTAHUB')
    if _SYS == 'Darwin':
        return os.path.join(home, 'Library', 'Application Support', 'DELTAHUB')
    return os.path.join(home, '.local', 'share', 'DELTAHUB')


def get_user_mods_dir(): return os.path.join(get_user_data_root(), 'mods')
def get_user_lang_dir(): return os.path.join(get_user_data_root(), 'lang')
def get_user_plugins_dir(): return os.path.join(get_user_data_root(), 'plugins')


def resource_path(relative_path):
    base = os.path.join(getattr(sys, '_MEIPASS'), 'src') if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(base, relative_path)


def get_xdelta_path():
    exe_names = ['xdelta3.exe', 'xdelta.exe'] if _SYS == 'Windows' else (['xdelta3_mac'] if _SYS == 'Darwin' else ['xdelta3'])
    for name in exe_names:
        p = resource_path(f'assets/bin/{name}')
        if os.path.exists(p):
            if _SYS != 'Windows':
                try:
                    os.chmod(p, 493)
                except Exception as e:
                    logging.warning(f'Could not set executable permission on {p}: {e}')
            return os.path.normpath(p)
    return None


def resolve_game_executable(base_dir, is_undertale=False, game_type=None):
    try:
        if not base_dir or not os.path.isdir(base_dir):
            return None
        game_types = [game_type] if game_type else (['undertaleyellow', 'undertale'] if is_undertale else ['deltarune'])
        search_order = {'Windows': ['windows', 'linux', 'mac'], 'Linux': ['linux', 'windows', 'mac'], 'Darwin': ['mac', 'linux', 'windows']}.get(_SYS, ['windows', 'linux', 'mac'])
        for plat_key in search_order:
            for gt in game_types:
                for name in list(GAME_EXECUTABLES.get(gt, {}).get(plat_key, ())):
                    if plat_key == 'mac':
                        app = base_dir if base_dir.endswith('.app') and os.path.isdir(base_dir) else None
                        if not app:
                            candidate = os.path.join(base_dir, name)
                            if os.path.isdir(candidate):
                                app = candidate
                        if app:
                            return app
                    else:
                        exe_path = os.path.join(base_dir, name)
                        if os.path.isfile(exe_path) and (plat_key != 'linux' or name.endswith('.exe') or os.access(exe_path, os.X_OK)):
                            return exe_path
        return None
    except Exception as e:
        logging.debug(f'resolve_game_executable: failed for {base_dir}: {e}')
        return None


def find_chapter_resource_dir(base_dir, chapter_id):
    try:
        if not base_dir:
            return None
        from config.constants import SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_PIZZA_TOWER, SLOT_ID_SUGARY_SPIRE
        target_base = base_dir
        if _SYS == 'Darwin':
            if not target_base.endswith('.app'):
                for app_name in ('DELTARUNE.app', 'DELTARUNEdemo.app'):
                    candidate = os.path.join(target_base, app_name)
                    if os.path.isdir(candidate):
                        target_base = candidate
                        break
            target_base = os.path.join(target_base, 'Contents', 'Resources')
            if not os.path.isdir(target_base):
                return None
        if chapter_id in (-1, 0, SLOT_ID_DEMO, SLOT_ID_UNDERTALE, SLOT_ID_UNDERTALE_YELLOW, SLOT_ID_PIZZA_TOWER, SLOT_ID_SUGARY_SPIRE):
            return target_base
        prefix = f'chapter{chapter_id}_'
        return next((os.path.join(target_base, e) for e in os.listdir(target_base) if os.path.isdir(os.path.join(target_base, e)) and e.startswith(prefix)), None)
    except Exception as e:
        logging.debug(f'find_chapter_resource_dir: failed for {base_dir}, chapter {chapter_id}: {e}')
        return None
