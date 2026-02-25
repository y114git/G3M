"""Path resolution and platform-specific utilities."""
import logging
import os
import platform
import re
import stat
import sys
from pathlib import Path
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
def get_user_themes_dir(): return os.path.join(get_user_data_root(), 'themes')


def resource_path(relative_path):
    base = os.path.join(getattr(sys, '_MEIPASS'), 'src') if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(base, relative_path)


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


def find_chapter_resource_dir(base_dir, chapter_id: str):
    try:
        if not base_dir:
            return None
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
        if '_' in str(chapter_id):
            _, suffix = chapter_id.rsplit('_', 1)
            if suffix.isdigit() and int(suffix) > 0:
                prefix = f'chapter{suffix}_'
                return next((os.path.join(target_base, e) for e in os.listdir(target_base) if os.path.isdir(os.path.join(target_base, e)) and e.startswith(prefix)), None)
        return target_base
    except Exception as e:
        logging.debug(f'find_chapter_resource_dir: failed for {base_dir}, chapter {chapter_id}: {e}')
        return None


def _match_steam_path(normalized, steam_path):
    try:
        if os.path.exists(steam_path):
            sp = os.path.normpath(os.path.abspath(steam_path)).lower().replace('\\', '/')
            if normalized == sp or normalized.startswith(sp + '/'):
                return True
    except (OSError, ValueError):
        pass
    return False


def is_path_in_steam_common(game_path: str, game_name: str) -> bool:
    if not game_path or not os.path.isdir(game_path):
        return False
    try:
        game_path_normalized = os.path.normpath(os.path.abspath(game_path)).lower()
    except (OSError, ValueError):
        return False
    path_parts = game_path_normalized.replace('\\', '/').split('/')
    if any(path_parts[i] == 'steamapps' and i + 2 < len(path_parts) and path_parts[i + 1] == 'common' for i in range(len(path_parts))):
        return True
    home = os.path.expanduser('~')
    if _SYS == 'Windows':
        for pf in filter(None, [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')]):
            if _match_steam_path(game_path_normalized, os.path.join(pf, 'Steam', 'steamapps', 'common', game_name)):
                return True
    elif _SYS == 'Linux':
        for sp in [os.path.join(home, '.steam', 'steam'), os.path.join(home, '.local', 'share', 'Steam'), os.path.join(home, '.var', 'app', 'com.valvesoftware.Steam', 'data', 'Steam')]:
            if _match_steam_path(game_path_normalized, os.path.join(sp, 'steamapps', 'common', game_name)):
                return True
    elif _SYS == 'Darwin':
        for sp in [os.path.join(home, 'Library', 'Application Support', 'Steam'), os.path.join(home, 'Steam')]:
            if _match_steam_path(game_path_normalized, os.path.join(sp, 'steamapps', 'common', game_name)):
                return True
    return False


def _pizza_names(game_name):
    return ['Pizza Tower', 'PizzaTower', 'pizzatower'] if game_name == 'Pizza Tower' else [game_name]


def autodetect_path(game_name: str) -> str | None:
    if game_name in ('UNDERTALE YELLOW', 'UndertaleYellow', 'undertaleyellow', 'SUGARY SPIRE', 'SugarySpire', 'sugaryspire'):
        return None
    system, paths, names = _SYS, [], _pizza_names(game_name)
    home = os.path.expanduser('~')
    if system == 'Windows':
        pf_dirs = [p for p in [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')] if p]
        for n in names:
            paths.extend(os.path.join(p, 'Steam', 'steamapps', 'common', n) for p in pf_dirs)
        steam_subs = [['Steam', 'steamapps', 'common'], ['SteamLibrary', 'steamapps', 'common'], ['Program Files', 'Steam', 'steamapps', 'common'], ['Program Files (x86)', 'Steam', 'steamapps', 'common']]
        for drive in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            for sub in steam_subs:
                for n in names:
                    paths.append(os.path.join(f'{drive}:', *sub, n))
    elif system == 'Linux':
        steam_bases = [f'{home}/.steam/steam', f'{home}/.local/share/Steam', f'{home}/.var/app/com.valvesoftware.Steam/data/Steam']
        for sb in steam_bases:
            for n in names:
                paths.append(f'{sb}/steamapps/common/{n}')
        for mount_base in ['/mnt', '/media', '/run/media', f'{home}/.steam/steam/steamapps']:
            if os.path.isdir(mount_base):
                try:
                    for item in os.listdir(mount_base):
                        item_path = os.path.join(mount_base, item)
                        if os.path.isdir(item_path):
                            for sub in ['SteamLibrary/steamapps/common', 'steamapps/common']:
                                sp = os.path.join(item_path, sub, game_name)
                                if os.path.exists(sp):
                                    paths.append(sp)
                except (OSError, PermissionError):
                    pass
        for extra in ['/run/media/mmcblk0p1', '/run/media/mmcblk1p1', '/mnt/steam', '/media/steam']:
            paths.append(f'{extra}/steamapps/common/{game_name}')
    elif system == 'Darwin':
        base_paths = [f'{home}/Library/Application Support/Steam/steamapps/common', '/Applications', f'{home}/Steam/steamapps/common']
        all_bases = []
        for bp in base_paths:
            for n in names:
                all_bases.append(f'{bp}/{n}')
        if game_name.endswith('demo'):
            for parent in filter(os.path.isdir, all_bases):
                for app in [f'{game_name}.app', 'DELTARUNE.app']:
                    fp = os.path.join(parent, app)
                    if os.path.exists(fp):
                        paths.append(fp)
        else:
            for bp in all_bases:
                for n in names:
                    paths.extend(filter(os.path.isdir, [f'{bp}/{n}.app']))
            paths.extend(filter(os.path.isdir, [f'{bp}/{game_name}.app' for bp in all_bases]))
    return next((p for p in paths if os.path.exists(p)), None)


def fix_macos_python_symlink(app_dir: Path) -> None:
    try:
        if _SYS != 'Darwin':
            return
        p = app_dir / 'Contents' / 'Frameworks' / 'Python'
        if not p.exists() or p.is_symlink():
            return
        if p.is_file() and p.stat().st_size < 512:
            try:
                target_rel = p.read_text(encoding='utf-8').strip()
            except Exception as e:
                logging.debug(f'fix_macos_python_symlink: failed to read symlink target: {e}')
                target_rel = 'Python.framework/Versions/3.12/Python'
            p.unlink(missing_ok=True)
            os.symlink(target_rel, p)
            st = os.lstat(p)
            os.chmod(p, stat.S_IMODE(st.st_mode) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as e:
        logging.debug(f'fix_macos_python_symlink: failed: {e}')


def cleanup_old_updater_files():
    try:
        if not getattr(sys, 'frozen', False):
            return
        system = _SYS
        current_exe_path = os.path.realpath(sys.executable)
        if system == 'Darwin':
            replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), '..', '..'))
        else:
            replace_target = current_exe_path
        backup_path = f'{replace_target}.old'
        if os.path.exists(backup_path):
            from utils.file_utils import safe_rmtree
            safe_rmtree(backup_path)
    except Exception as e:
        logging.debug(f'cleanup_old_updater_files: failed: {e}')


def version_sort_key(version_string: str):
    try:
        s = (version_string or '').strip()
        m = re.match(r'^(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?(?P<suffix>[A-Za-z0-9][A-Za-z0-9._-]*)?$', s)
        if m:
            p = m.groupdict()
            suffix = (p.get('suffix') or '').lower()
            return (int(p.get('major') or 0), int(p.get('minor') or 0), int(p.get('patch') or 0), 1 if suffix else 0, suffix)
        parts, nums, suffix_part = re.split('[.-]', s), [], ''
        for part in parts:
            if part.isdigit():
                nums.append(int(part))
            else:
                suffix_part = ''.join(parts[parts.index(part):]).lower()
                break
        nums.extend([0] * (3 - len(nums)))
        return (nums[0], nums[1], nums[2], 1 if suffix_part else 0, suffix_part)
    except Exception:
        return (0, 0, 0, 0, '')
