import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path
import requests
from PyQt6.QtWidgets import QMessageBox
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.constants import BROWSER_HEADERS

def resource_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.join(os.path.dirname(__file__), '..', 'resources')
    return os.path.join(base_path, relative_path)

def download_and_extract_archive(url: str, target_dir: str, progress_signal, total_size: int, downloaded_ref: list[int], session=None, is_game_installation=False):
    os.makedirs(target_dir, exist_ok=True)
    if session is None:
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        retry_strategy = Retry(total=3, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=10)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
    fname = _get_filename_from_url(session, url)
    with tempfile.TemporaryDirectory(prefix='deltahub-dl-') as tmp:
        tmp_path = os.path.join(tmp, fname)
        _download_file(session, url, tmp_path, progress_signal, total_size, downloaded_ref)
        _extract_archive(tmp_path, target_dir, fname, is_game_installation)

def _get_filename_from_url(session, url):
    try:
        from urllib.parse import urlparse, unquote
        response = session.head(url, timeout=10, allow_redirects=True)
        if (content_disp := response.headers.get('Content-Disposition')):
            if (fn_match := re.search('filename\\*?=(.+)', content_disp, re.IGNORECASE)):
                fn_data = fn_match.group(1).strip()
                if fn_data.lower().startswith("utf-8''"):
                    return unquote(fn_data[7:], 'utf-8')
                return fn_data.strip('"\'')
        path = urlparse(response.url).path
        if path and path != '/' and (not path.endswith('/')):
            potential_name = os.path.basename(unquote(path))
            if '.' in potential_name:
                return potential_name
    except Exception:
        pass
    return Path(url.split('?', 1)[0]).name or 'file.tmp'

def _download_file(session, url, tmp_path, progress_signal, total_size, downloaded_ref, max_retries: int=5):
    expected_size = 0
    try:
        h = session.head(url, allow_redirects=True, timeout=15)
        expected_size = int(h.headers.get('content-length', 0))
    except Exception:
        expected_size = 0
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            current_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            headers = {}
            if expected_size and 0 < current_size < expected_size:
                headers['Range'] = f'bytes={current_size}-'
            r = session.get(url, stream=True, timeout=60, allow_redirects=True, headers=headers)
            r.raise_for_status()
            status_code = getattr(r, 'status_code', 200)
            duplicate_remaining = 0
            mode = 'ab'
            if status_code == 206 and 'Range' in headers:
                mode = 'ab'
            else:
                mode = 'wb'
                if current_size > 0:
                    duplicate_remaining = current_size
            this_request_expected = 0
            try:
                this_request_expected = int(r.headers.get('content-length', 0))
            except Exception:
                this_request_expected = 0
            written_this_request = 0
            with open(tmp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    sz = len(chunk)
                    written_this_request += sz
                    if duplicate_remaining > 0:
                        if sz <= duplicate_remaining:
                            duplicate_remaining -= sz
                        else:
                            add = sz - duplicate_remaining
                            downloaded_ref[0] += add
                            duplicate_remaining = 0
                    else:
                        downloaded_ref[0] += sz
                    if total_size > 0:
                        try:
                            progress = int(min(100, max(0, downloaded_ref[0] / total_size * 100)))
                            progress_signal.emit(progress)
                        except Exception:
                            pass
            final_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if this_request_expected and written_this_request < this_request_expected:
                raise IOError('connection dropped during download')
            if expected_size and final_size < expected_size:
                continue
            return
        except Exception:
            if attempt >= max_retries:
                raise
            try:
                time.sleep(min(2.0, 0.2 * attempt))
            except Exception:
                pass

def _extract_archive(tmp_path, target_dir, fname, is_game_installation=False):
    import rarfile
    low = fname.lower()
    extractors = {'zip': lambda: zipfile.ZipFile(tmp_path, 'r').extractall(target_dir), 'rar': lambda: rarfile.RarFile(tmp_path, 'r').extractall(target_dir)}
    try:
        import py7zr
        extractors['7z'] = lambda: py7zr.SevenZipFile(tmp_path, mode='r').extractall(path=target_dir)
    except Exception:
        pass
    for ext, extractor in extractors.items():
        if low.endswith(f'.{ext}'):
            extractor()
            _cleanup_extracted_archive(target_dir, is_game_installation)
            return
    shutil.copy2(tmp_path, os.path.join(target_dir, fname))

def _cleanup_extracted_archive(target_dir: str, is_game_installation: bool=False):
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
            except Exception:
                target_rel = 'Python.framework/Versions/3.12/Python'
            p.unlink(missing_ok=True)
            os.symlink(target_rel, p)
            st = os.lstat(p)
            os.chmod(p, stat.S_IMODE(st.st_mode) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass

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
    except Exception:
        pass

def show_error(parent, title, message):
    QMessageBox.critical(parent, title, message)

def show_info(parent, title, message):
    QMessageBox.information(parent, title, message)

def confirm_action(parent, title, message):
    return QMessageBox.question(parent, title, message) == QMessageBox.StandardButton.Yes

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
    except Exception:
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
    except Exception:
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
    FILTER_EXTENSIONS = {'image_files': '*.jpg *.png *.bmp *.gif', 'background_images': '*.jpg *.png *.bmp *.gif', 'xdelta_files': '*.xdelta', 'data_files': '*.win *.ios', 'archive_files': '*.zip *.rar *.7z', 'extended_archives': '*.zip *.rar *.7z *.tar.gz', 'game_files': '*.exe', 'text_files': '*.txt', 'all_files': '*'}

    def tr(key):
        return key.replace('file_descriptions.', '').replace('_', ' ').title()
    FILTER_DESCRIPTIONS = {'image_files': tr('file_descriptions.image_files'), 'background_images': tr('file_descriptions.background_images'), 'xdelta_files': tr('file_descriptions.xdelta_files'), 'data_files': tr('file_descriptions.data_files'), 'archive_files': tr('file_descriptions.archive_files'), 'extended_archives': tr('file_descriptions.extended_archives'), 'game_files': tr('file_descriptions.game_files'), 'text_files': tr('file_descriptions.text_files'), 'all_files': tr('file_descriptions.all_files')}
    extensions = FILTER_EXTENSIONS.get(filter_type, '*')
    description = FILTER_DESCRIPTIONS.get(filter_type, filter_type)
    all_files_desc = FILTER_DESCRIPTIONS.get('all_files', 'All files')
    return f'{description} ({extensions});;{all_files_desc} (*)'
