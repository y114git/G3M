import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import zipfile
import tarfile
import lzma
import logging
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.constants import BROWSER_HEADERS
from utils.network_utils import download_file, get_filename_from_url, get_session
import errno


def download_and_extract_archive(url: str, target_dir: str, progress_callback=None, total_size: int = 0, downloaded_ref: list[int] | None = None, session=None, is_game_installation=False, cancel_check=None, on_response=None):
    if downloaded_ref is None:
        downloaded_ref = [0]
    os.makedirs(target_dir, exist_ok=True)
    if session is None:
        session = get_session()
    fname = get_filename_from_url(session, url)
    with tempfile.TemporaryDirectory(prefix='deltahub-dl-') as tmp:
        tmp_path = os.path.join(tmp, fname)
        download_file(session, url, tmp_path, progress_callback, total_size, downloaded_ref, cancel_check=cancel_check, on_response=on_response)
        if cancel_check and cancel_check():
            return
        extract_archive(tmp_path, target_dir, fname=fname, is_game_installation=is_game_installation)


def extract_archive(archive_path: str, target_dir: str, fname: str | None = None, is_game_installation: bool = False, size_cap_bytes: int | None = None) -> None:
    os.makedirs(target_dir, exist_ok=True)
    low = (fname or os.path.basename(archive_path)).lower()
    with tempfile.TemporaryDirectory(prefix='deltahub-extract-') as temp_out:
        _extract_archive_raw(archive_path, low, temp_out)
        if size_cap_bytes is not None:
            total = 0
            for root, _, files in os.walk(temp_out):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            if total > size_cap_bytes:
                raise IOError('extracted_content_too_large')
        _move_tree_safely(temp_out, target_dir)
        _cleanup_extracted_archive(target_dir, is_game_installation)


def _extract_archive_raw(src_path: str, fname_lower: str, out_dir: str) -> None:
    import rarfile
    try:
        import py7zr
    except Exception as e:
        logging.debug(f'_extract_archive_raw: py7zr import failed (not installed): {e}')
        py7zr = None
    if fname_lower.endswith('.zip'):
        with zipfile.ZipFile(src_path, 'r') as zf:
            zf.extractall(out_dir)
        return
    if fname_lower.endswith('.tar.gz'):
        with tarfile.open(src_path, 'r:gz') as tf:
            tf.extractall(out_dir)
        return
    if fname_lower.endswith('.rar'):
        with rarfile.RarFile(src_path, 'r') as rf:
            rf.extractall(out_dir)
        return
    if fname_lower.endswith('.7z') and py7zr is not None:
        with py7zr.SevenZipFile(src_path, mode='r') as zf:
            zf.extractall(path=out_dir)
        return
    if fname_lower.endswith('.lzma'):
        _extract_lzma(src_path, out_dir, fname_lower)
        return
    shutil.copy2(src_path, os.path.join(out_dir, os.path.basename(src_path)))


def _is_symlink(path: str) -> bool:
    try:
        return os.path.islink(path)
    except OSError:
        return False


def _safe_join(base: str, *paths: str) -> str:
    base_abs = os.path.abspath(base)
    final = os.path.abspath(os.path.join(base_abs, *paths))
    if os.path.commonpath([final, base_abs]) != base_abs:
        raise ValueError('path_traversal')
    return final


def _move_tree_safely(src_root: str, dst_root: str) -> None:
    for root, dirs, files in os.walk(src_root):
        rel_root = os.path.relpath(root, src_root)
        rel_root = '' if rel_root == '.' else rel_root
        if os.path.isabs(rel_root):
            continue
        if len(rel_root) >= 2 and rel_root[1] == ':' and rel_root[0].isalpha():
            continue
        dst_dir = _safe_join(dst_root, rel_root) if rel_root else dst_root
        os.makedirs(dst_dir, exist_ok=True)
        for d in list(dirs):
            try:
                _safe_join(dst_dir, d)
            except ValueError:
                dirs.remove(d)
                continue
        for f in files:
            src_path = os.path.join(root, f)
            if _is_symlink(src_path):
                continue
            try:
                dst_path = _safe_join(dst_dir, f)
            except ValueError:
                continue
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            try:
                shutil.move(src_path, dst_path)
            except (OSError, shutil.Error):
                try:
                    shutil.copy2(src_path, dst_path)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise


def _extract_lzma(tmp_path, target_dir, fname):
    output_path = os.path.join(target_dir, os.path.splitext(fname)[0])
    with lzma.open(tmp_path) as f_in, open(output_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)


def _cleanup_extracted_archive(target_dir: str, is_game_installation: bool = False):
    if is_game_installation:
        cleanup_dir_pattern = re.compile('^chapter\\d+_(windows|mac)$', re.I)
        for root, dirs, _ in os.walk(target_dir, topdown=False):
            for dir_name in dirs[:]:
                if cleanup_dir_pattern.match(dir_name):
                    try:
                        shutil.rmtree(os.path.join(root, dir_name))
                        dirs.remove(dir_name)
                    except OSError:
                        pass
    else:
        return


def sanitize_filename(name: str) -> str:
    return re.sub('[\\\\/*?:"<>|]', '', name).strip()


def get_unique_mod_dir(mods_dir, mod_name):
    sanitized_name = sanitize_filename(mod_name)
    base_dir = os.path.join(mods_dir, sanitized_name)
    if not os.path.exists(base_dir):
        return sanitized_name
    counter = 1
    while True:
        unique_name = f'{sanitized_name}_{counter}'
        unique_dir = os.path.join(mods_dir, unique_name)
        if not os.path.exists(unique_dir):
            return unique_name
        counter += 1


def ensure_writable(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    os.chmod(os.path.join(root, name), mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWRITE)
        return True
    except (OSError, PermissionError):
        return False


def autodetect_path(game_name: str) -> str | None:
    system = platform.system()
    paths = []
    if system == 'Windows':
        program_files = [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')]
        steam_paths = [os.path.join(p, 'Steam', 'steamapps', 'common', game_name) for p in program_files if p]
        drive_paths = [f'{d}:/{s}/{game_name}' for d in 'CDE' for s in ['Steam/steamapps/common', 'SteamLibrary/steamapps/common']]
        paths.extend(steam_paths + drive_paths)
    elif system == 'Linux':
        home = os.path.expanduser('~')
        paths.extend([f'{home}/.steam/steam/steamapps/common/{game_name}', f'{home}/.local/share/Steam/steamapps/common/{game_name}', f'/run/media/mmcblk0p1/steamapps/common/{game_name}'])
    elif system == 'Darwin':
        home = os.path.expanduser('~')
        base_paths = [f'{home}/Library/Application Support/Steam/steamapps/common/{game_name}', f'/Applications/{game_name}']
        if game_name.endswith('demo'):
            for parent in filter(os.path.isdir, base_paths):
                for app_name in [f'{game_name}.app', 'DELTARUNE.app']:
                    full_path = os.path.join(parent, app_name)
                    if os.path.exists(full_path):
                        paths.append(full_path)
        else:
            app_paths = [f'{p}/{game_name}.app' for p in base_paths]
            paths.extend(filter(os.path.isdir, app_paths))
    return next((p for p in paths if os.path.exists(p)), None)


def fix_macos_python_symlink(app_dir: Path) -> None:
    try:
        if platform.system() != 'Darwin':
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
        system = platform.system()
        current_exe_path = os.path.realpath(sys.executable)
        if system == 'Darwin':
            replace_target = os.path.abspath(os.path.join(os.path.dirname(current_exe_path), '..', '..'))
        else:
            replace_target = current_exe_path
        backup_path = f'{replace_target}.old'
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path, ignore_errors=True)
    except Exception as e:
        logging.debug(f'cleanup_old_updater_files: failed: {e}')


def version_sort_key(version_string: str):
    try:
        s = (version_string or '').strip()
        m = re.match('^(?P<major>\\d+)(?:\\.(?P<minor>\\d+))?(?:\\.(?P<patch>\\d+))?(?P<suffix>[A-Za-z0-9][A-Za-z0-9._-]*)?$', s)
        if m:
            parts = m.groupdict()
            major = int(parts.get('major') or 0)
            minor = int(parts.get('minor') or 0)
            patch = int(parts.get('patch') or 0)
            suffix = (parts.get('suffix') or '').lower()
            has_suffix = 1 if suffix else 0
            return (major, minor, patch, has_suffix, suffix)
        parts = re.split('[.-]', s)
        nums = []
        suffix_part = ''
        for part in parts:
            if part.isdigit():
                nums.append(int(part))
            else:
                suffix_part = ''.join(parts[parts.index(part):]).lower()
                break
        while len(nums) < 3:
            nums.append(0)
        has_suffix = 1 if suffix_part else 0
        return (nums[0], nums[1], nums[2], has_suffix, suffix_part)
    except Exception as e:
        logging.debug(f'version_sort_key: failed to parse "{version_string}": {e}')
        return (0, 0, 0, 0, '')


def game_version_sort_key(version_string: str):
    try:
        match = re.match('^(\\d+)\\.(\\d+)([A-Z]?)$', version_string.strip())
        if match:
            major, minor, letter = (int(match.group(1)), int(match.group(2)), match.group(3))
            letter_ord = 0 if letter == '' else ord(letter) - ord('A') + 1
            return (major, minor, letter_ord)
        else:
            parts = version_string.split('.')
            major = 0
            minor = 0
            if len(parts) > 0 and parts[0].isdigit():
                major = int(parts[0])
            if len(parts) > 1 and parts[1].isdigit():
                minor = int(parts[1])
            return (major, minor, 0)
    except Exception as e:
        logging.debug(f'game_version_sort_key: failed to parse "{version_string}": {e}')
        return (0, 0, 0)


def detect_field_type_by_text(text: str) -> str:
    text_lower = text.lower()
    if any((keyword in text_lower for keyword in ['ссылка', 'путь', 'url', 'link'])):
        return 'file_path'
    elif 'версия' in text_lower or 'version' in text_lower:
        return 'version'
    elif 'дополнительные файлы' in text_lower or 'extra files' in text_lower:
        return 'extra_files'
    return 'unknown'


def get_file_filter(filter_type: str) -> str:
    FILTER_EXTENSIONS = {'image_files': '*.jpg *.png *.bmp *.gif', 'background_images': '*.jpg *.png *.bmp *.gif', 'xdelta_files': '*.xdelta', 'data_files': '*.win *.ios *.xdelta *.vcdiff *.csx', 'archive_files': '*.zip *.rar *.7z *.tar.gz *.lzma', 'extended_archives': '*.zip *.rar *.7z *.tar.gz *.lzma', 'game_files': '*.exe', 'text_files': '*.txt', 'all_files': '*'}

    def tr(key):
        return key.replace('file_descriptions.', '').replace('_', ' ').title()
    FILTER_DESCRIPTIONS = {'image_files': tr('file_descriptions.image_files'), 'background_images': tr('file_descriptions.background_images'), 'xdelta_files': tr('file_descriptions.xdelta_files'), 'data_files': tr('file_descriptions.data_files'), 'archive_files': tr('file_descriptions.archives'), 'extended_archives': tr('file_descriptions.archives'), 'game_files': tr('file_descriptions.game_files'), 'text_files': tr('file_descriptions.text_files'), 'all_files': tr('file_descriptions.all_files')}
    extensions = FILTER_EXTENSIONS.get(filter_type, '*')
    description = FILTER_DESCRIPTIONS.get(filter_type, filter_type)
    all_files_desc = FILTER_DESCRIPTIONS.get('all_files', 'All files')
    return f'{description} ({extensions});;{all_files_desc} (*)'
