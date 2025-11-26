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
import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional
from utils.network_utils import download_file, get_filename_from_url, get_session
from config.constants import MOD_CONFIG_FILENAME, DATA_WIN_FILENAME, META_JSON_FILENAME, ICON_PNG_FILENAME, LEGACY_MOD_CONFIG_FILENAME, LEGACY_META_JSON_FILENAME, LEGACY_ICON_PNG_FILENAME
import errno


def download_file_with_progress(url: str, target_path: str, progress_callback=None, session=None, cancel_check=None, on_response=None, downloaded_ref=None) -> bool:
    from utils.network_utils import get_session, download_file
    from config.constants import NETWORK_TIMEOUT_HEAD
    if session is None:
        session = get_session()
    total_size = 0
    try:
        head_response = session.head(url, allow_redirects=True, timeout=NETWORK_TIMEOUT_HEAD)
        total_size = int(head_response.headers.get('content-length', 0))
    except Exception as e:
        logging.debug(f'download_file_with_progress: Could not get content-length from HEAD request: {e}')
    if downloaded_ref is None:
        downloaded_ref = [0]
    try:
        download_file(session, url, target_path, progress_callback=progress_callback, total_size=total_size, downloaded_ref=downloaded_ref, cancel_check=cancel_check, on_response=on_response)
        if progress_callback:
            progress_callback(100)
        return True
    except RuntimeError as e:
        if str(e) == 'download_cancelled':
            logging.debug('download_file_with_progress: Download cancelled by user')
            return False
        logging.error(f'download_file_with_progress: Download failed: {e}', exc_info=True)
        return False
    except Exception as e:
        logging.error(f'download_file_with_progress: Download failed: {e}', exc_info=True)
        return False


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
    if size_cap_bytes is not None:
        low = (fname or os.path.basename(archive_path)).lower()
        with tempfile.TemporaryDirectory(prefix='deltahub-extract-') as temp_out:
            from utils.archive_utils import ArchiveExtractor
            ArchiveExtractor.extract(archive_path, temp_out)
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
    else:
        extract_archive_with_backup(archive_path, target_dir, backup_temp_dir=None, backup_files=None, add_mod_dir_callback=None, backup_file_callback=None, update_manifest_callback=None, status_callback=None)


def extract_archive_with_backup(archive_path: str, target_dir: str, backup_temp_dir: str | None = None, backup_files: dict | None = None, add_mod_dir_callback=None, backup_file_callback=None, update_manifest_callback=None, status_callback=None) -> list[str]:
    import platform
    extracted_files = []
    file_lower = archive_path.lower()
    try:
        with tempfile.TemporaryDirectory(prefix='deltahub-extract-') as temp_dir:
            from utils.archive_utils import ArchiveExtractor
            ArchiveExtractor.extract(archive_path, temp_dir)
            _cleanup_extracted_archive(temp_dir, False)
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    source_file = os.path.join(root, file)
                    rel_path = os.path.relpath(source_file, temp_dir)
                    target_file = os.path.join(target_dir, rel_path)
                    file_lower = file.lower()
                    if platform.system() == 'Darwin':
                        if file_lower.endswith('.win'):
                            name_without_ext = os.path.splitext(file)[0]
                            target_file = os.path.join(os.path.dirname(target_file), name_without_ext + '.ios')
                    elif file_lower.endswith('.ios'):
                        name_without_ext = os.path.splitext(file)[0]
                        target_file = os.path.join(os.path.dirname(target_file), name_without_ext + '.win')
                    target_dirname = os.path.dirname(target_file)
                    os.makedirs(target_dirname, exist_ok=True)
                    if add_mod_dir_callback:
                        try:
                            add_mod_dir_callback(target_dirname)
                        except Exception as e:
                            logging.error(f'extract_archive_with_backup: add_mod_dir_callback failed: {e}', exc_info=True)
                    tmp_target = target_file + '.tmp'
                    try:
                        shutil.copy2(source_file, tmp_target)
                        if os.path.exists(target_file) and backup_temp_dir and (backup_files is not None):
                            backup_rel_path = os.path.relpath(target_file, target_dir)
                            backup_file_path = os.path.join(backup_temp_dir, backup_rel_path)
                            os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)
                            shutil.move(target_file, backup_file_path)
                            backup_files[target_file] = backup_file_path
                            if backup_file_callback:
                                try:
                                    backup_file_callback(target_file, backup_file_path)
                                except Exception as e:
                                    logging.error(f'extract_archive_with_backup: backup_file_callback failed: {e}', exc_info=True)
                            if update_manifest_callback:
                                try:
                                    update_manifest_callback({target_file: backup_file_path}, None, None)
                                except Exception as e:
                                    logging.error(f'extract_archive_with_backup: update_manifest_callback failed: {e}', exc_info=True)
                        os.replace(tmp_target, target_file)
                        extracted_files.append(target_file)
                    finally:
                        try:
                            if os.path.exists(tmp_target):
                                os.remove(tmp_target)
                        except Exception as e:
                            logging.warning(f'extract_archive_with_backup: tmp cleanup failed: {e}', exc_info=True)
    except Exception as e:
        error_msg = f'Archive unpack error: {os.path.basename(archive_path)}: {e}'
        if status_callback:
            try:
                status_callback(error_msg)
            except (RuntimeError, AttributeError) as e:
                logging.warning(f'extract_archive_with_backup: status_callback failed: {e}')
        logging.error(f'extract_archive_with_backup: {error_msg}', exc_info=True)
    return extracted_files


def _extract_archive_raw(src_path: str, fname_lower: str, out_dir: str) -> None:
    import rarfile
    try:
        import py7zr
    except Exception as e:
        logging.debug(f'_extract_archive_raw: py7zr import failed (not installed): {e}')
        py7zr = None
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    if fname_lower.endswith('.zip'):
        with zipfile.ZipFile(src_path, 'r') as zf:
            for member in zf.namelist():
                if '..' in member or member.startswith('/'):
                    logging.warning(f'_extract_archive_raw: Skipping suspicious path in ZIP: {member}')
                    continue
                try:
                    target_path = _safe_join(out_dir_abs, member)
                    if not os.path.abspath(target_path).startswith(out_dir_abs):
                        logging.warning(f'_extract_archive_raw: Path traversal attempt blocked: {member}')
                        continue
                    parent_dir = os.path.dirname(target_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                    if not member.endswith('/'):
                        with zf.open(member) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                except (ValueError, OSError) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract {member}: {e}')
                    continue
        return
    if fname_lower.endswith('.tar.gz'):
        with tarfile.open(src_path, 'r:gz') as tf:
            for member in tf.getmembers():
                if '..' in member.name or member.name.startswith('/'):
                    logging.warning(f'_extract_archive_raw: Skipping suspicious path in TAR: {member.name}')
                    continue
                try:
                    target_path = _safe_join(out_dir_abs, member.name)
                    if not os.path.abspath(target_path).startswith(out_dir_abs):
                        logging.warning(f'_extract_archive_raw: Path traversal attempt blocked: {member.name}')
                        continue
                    tf.extract(member, out_dir_abs)
                except (ValueError, OSError, tarfile.TarError) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract {member.name}: {e}')
                    continue
        return
    if fname_lower.endswith('.rar'):
        with rarfile.RarFile(src_path, 'r') as rf:
            for member in rf.namelist():
                if '..' in member or member.startswith('/'):
                    logging.warning(f'_extract_archive_raw: Skipping suspicious path in RAR: {member}')
                    continue
                try:
                    target_path = _safe_join(out_dir_abs, member)
                    if not os.path.abspath(target_path).startswith(out_dir_abs):
                        logging.warning(f'_extract_archive_raw: Path traversal attempt blocked: {member}')
                        continue
                    parent_dir = os.path.dirname(target_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                    if not member.endswith('/'):
                        rf.extract(member, out_dir_abs)
                except (ValueError, OSError, rarfile.RarCannotExec) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract {member}: {e}')
                    continue
        return
    if fname_lower.endswith('.7z') and py7zr is not None:
        with py7zr.SevenZipFile(src_path, mode='r') as zf:
            for member in zf.getnames():
                if '..' in member or member.startswith('/'):
                    logging.warning(f'_extract_archive_raw: Skipping suspicious path in 7Z: {member}')
                    continue
                try:
                    target_path = _safe_join(out_dir_abs, member)
                    if not os.path.abspath(target_path).startswith(out_dir_abs):
                        logging.warning(f'_extract_archive_raw: Path traversal attempt blocked: {member}')
                        continue
                    parent_dir = os.path.dirname(target_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                    if not member.endswith('/'):
                        zf.extract(member, out_dir_abs)
                except (ValueError, OSError) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract {member}: {e}')
                    continue
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


def _safe_extract_zip(zip_path: str, out_dir: str) -> None:
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            if '..' in member or member.startswith('/'):
                logging.warning(f'_safe_extract_zip: Skipping suspicious path in ZIP: {member}')
                continue
            try:
                target_path = _safe_join(out_dir_abs, member)
                if not os.path.abspath(target_path).startswith(out_dir_abs):
                    logging.warning(f'_safe_extract_zip: Path traversal attempt blocked: {member}')
                    continue
                parent_dir = os.path.dirname(target_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                if not member.endswith('/'):
                    with zf.open(member) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
            except (ValueError, OSError) as e:
                logging.warning(f'_safe_extract_zip: Failed to extract {member}: {e}')
                continue


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
        try:
            entries = list(os.listdir(target_dir))
            if len(entries) == 1:
                single_entry = os.path.join(target_dir, entries[0])
                if os.path.isdir(single_entry):
                    import logging
                    logging.info(f'Moving contents from nested folder {single_entry} to {target_dir}')
                    for item in os.listdir(single_entry):
                        src = os.path.join(single_entry, item)
                        dst = os.path.join(target_dir, item)
                        if os.path.exists(dst):
                            if os.path.isdir(dst):
                                safe_rmtree(dst)
                            else:
                                safe_remove(dst)
                        safe_move(src, dst)
                    try:
                        os.rmdir(single_entry)
                    except OSError as e:
                        logging.debug(f'_cleanup_extracted_archive: Failed to remove directory {single_entry}: {e}')
        except Exception as e:
            import logging
            logging.warning(f'Failed to handle nested folder structure: {e}')
        cleanup_dir_pattern = re.compile('^chapter\\d+_(windows|mac)$', re.I)
        for root, dirs, _ in os.walk(target_dir, topdown=False):
            for dir_name in dirs[:]:
                if cleanup_dir_pattern.match(dir_name):
                    dir_path = os.path.join(root, dir_name)
                    if safe_rmtree(dir_path):
                        dirs.remove(dir_name)
                    else:
                        logging.debug(f'_cleanup_extracted_archive: Failed to remove directory {dir_name}')
    else:
        return


def normalize_mod_package(mod_root: str, *, rename_legacy: bool = True, check_executables: bool = True, require_mod_config: bool = False, require_manifest: bool = False) -> Dict[str, Optional[str]]:
    if not os.path.isdir(mod_root):
        raise ValueError('mod_root_not_directory')
    _flatten_single_child_directories(mod_root)
    if rename_legacy:
        _rename_legacy_files(mod_root)
    meta_path = find_deltamod_info_file(mod_root)
    mod_config_path = _find_file_recursive(mod_root, MOD_CONFIG_FILENAME)
    icon_path = _find_file_recursive(mod_root, ICON_PNG_FILENAME)
    if require_manifest and (not meta_path):
        raise FileNotFoundError('manifest_missing')
    if require_mod_config and (not mod_config_path):
        raise FileNotFoundError('mod_config_missing')
    if check_executables:
        _ensure_no_prohibited_files(mod_root)
    return {'meta_path': meta_path, 'mod_config_path': mod_config_path, 'icon_path': icon_path}


def _flatten_single_child_directories(root: str):
    while True:
        try:
            entries = [e for e in os.listdir(root) if e not in ('.', '..') and (not e.startswith('__MACOSX'))]
        except OSError:
            return
        files = [e for e in entries if os.path.isfile(os.path.join(root, e))]
        dirs = [e for e in entries if os.path.isdir(os.path.join(root, e))]
        if files or len(dirs) != 1:
            return
        child = os.path.join(root, dirs[0])
        try:
            for item in os.listdir(child):
                src = os.path.join(child, item)
                dst = os.path.join(root, item)
                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        safe_rmtree(dst)
                    else:
                        safe_remove(dst)
                safe_move(src, dst)
            os.rmdir(child)
        except OSError:
            return


def _rename_legacy_files(root: str):
    legacy_meta = os.path.join(root, LEGACY_META_JSON_FILENAME)
    target_meta = os.path.join(root, META_JSON_FILENAME)
    if os.path.exists(legacy_meta):
        try:
            shutil.copy2(legacy_meta, target_meta)
            safe_remove(legacy_meta)
        except (OSError, PermissionError) as e:
            logging.warning(f'_rename_legacy_files: Failed to rename {legacy_meta}: {e}')
    legacy_icon = os.path.join(root, LEGACY_ICON_PNG_FILENAME)
    target_icon = os.path.join(root, ICON_PNG_FILENAME)
    if os.path.exists(legacy_icon):
        try:
            shutil.copy2(legacy_icon, target_icon)
            safe_remove(legacy_icon)
        except (OSError, PermissionError) as e:
            logging.warning(f'_rename_legacy_files: Failed to rename {legacy_icon}: {e}')


def _find_file_recursive(root: str, filename: str) -> Optional[str]:
    filename_lower = filename.lower()
    for current_root, _, files in os.walk(root):
        for f in files:
            if f.lower() == filename_lower:
                return os.path.join(current_root, f)
    return None


def _ensure_no_prohibited_files(root: str):
    prohibited_exts = {'.exe', '.js', '.ts', '.bat', '.cmd'}
    for current_root, _, files in os.walk(root):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in prohibited_exts:
                raise ValueError(f'prohibited_file:{os.path.join(current_root, f)}')


def sanitize_filename(name: str) -> str:
    return re.sub('[\\\\/*?:"<>|]', '', name).strip()


def atomic_write_json(path: str, data: Dict, indent: int = 2) -> None:
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except (PermissionError, OSError) as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    except (TypeError, ValueError) as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise ValueError(f'Data is not JSON-serializable: {e}') from e


def remove_archive_extension(filename: str) -> str:
    filename_lower = filename.lower()
    if filename_lower.endswith('.tar.gz'):
        return filename[:-7]
    elif filename_lower.endswith('.tar.lzma'):
        return filename[:-9]
    else:
        return os.path.splitext(filename)[0]


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
    if game_name == 'UNDERTALE YELLOW' or game_name == 'UndertaleYellow' or game_name == 'undertaleyellow':
        return None
    system = platform.system()
    paths = []
    if system == 'Windows':
        program_files = [os.getenv('ProgramFiles(x86)'), os.getenv('ProgramFiles')]
        steam_paths = [os.path.join(p, 'Steam', 'steamapps', 'common', game_name) for p in program_files if p]
        drive_letters = 'CDEFGHIJKLMNOPQRSTUVWXYZ'
        for drive in drive_letters:
            for steam_subpath in ['Steam/steamapps/common', 'SteamLibrary/steamapps/common', 'Program Files/Steam/steamapps/common', 'Program Files (x86)/Steam/steamapps/common']:
                paths.append(f'{drive}:/{steam_subpath}/{game_name}')
        paths.extend(steam_paths)
    elif system == 'Linux':
        home = os.path.expanduser('~')
        base_steam_paths = [f'{home}/.steam/steam/steamapps/common/{game_name}', f'{home}/.local/share/Steam/steamapps/common/{game_name}', f'{home}/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/{game_name}']
        paths.extend(base_steam_paths)
        mount_points = ['/mnt', '/media', '/run/media', f'{home}/.steam/steam/steamapps']
        for mount_base in mount_points:
            if os.path.isdir(mount_base):
                try:
                    for item in os.listdir(mount_base):
                        item_path = os.path.join(mount_base, item)
                        if os.path.isdir(item_path):
                            steam_lib_path = os.path.join(item_path, 'SteamLibrary', 'steamapps', 'common', game_name)
                            if os.path.exists(steam_lib_path):
                                paths.append(steam_lib_path)
                            steam_path = os.path.join(item_path, 'steamapps', 'common', game_name)
                            if os.path.exists(steam_path):
                                paths.append(steam_path)
                except (OSError, PermissionError):
                    pass
        additional_paths = [f'/run/media/mmcblk0p1/steamapps/common/{game_name}', f'/run/media/mmcblk1p1/steamapps/common/{game_name}', f'/mnt/steam/steamapps/common/{game_name}', f'/media/steam/steamapps/common/{game_name}']
        paths.extend(additional_paths)
    elif system == 'Darwin':
        home = os.path.expanduser('~')
        base_paths = [f'{home}/Library/Application Support/Steam/steamapps/common/{game_name}', f'/Applications/{game_name}', f'{home}/Steam/steamapps/common/{game_name}']
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
            safe_rmtree(backup_path)
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


def get_file_filter(filter_type: str) -> str:
    FILTER_EXTENSIONS = {'image_files': '*.jpg *.png *.bmp *.gif', 'background_images': '*.jpg *.png *.bmp *.gif', 'xdelta_files': '*.xdelta', 'data_files': '*.win *.ios *.xdelta *.vcdiff *.csx', 'archive_files': '*.zip *.rar *.7z *.tar.gz *.lzma', 'extended_archives': '*.zip *.rar *.7z *.tar.gz *.lzma', 'game_files': '*.exe', 'text_files': '*.txt', 'all_files': '*'}

    def tr(key):
        return key.replace('file_descriptions.', '').replace('_', ' ').title()
    FILTER_DESCRIPTIONS = {'image_files': tr('file_descriptions.image_files'), 'background_images': tr('file_descriptions.background_images'), 'xdelta_files': tr('file_descriptions.xdelta_files'), 'data_files': tr('file_descriptions.data_files'), 'archive_files': tr('file_descriptions.archives'), 'extended_archives': tr('file_descriptions.archives'), 'game_files': tr('file_descriptions.game_files'), 'text_files': tr('file_descriptions.text_files'), 'all_files': tr('file_descriptions.all_files')}
    extensions = FILTER_EXTENSIONS.get(filter_type, '*')
    description = FILTER_DESCRIPTIONS.get(filter_type, filter_type)
    all_files_desc = FILTER_DESCRIPTIONS.get('all_files', 'All files')
    return f'{description} ({extensions});;{all_files_desc} (*)'


def find_deltamod_info_file(directory: str) -> str | None:
    info_path_1 = os.path.join(directory, LEGACY_META_JSON_FILENAME)
    info_path_2 = os.path.join(directory, META_JSON_FILENAME)
    if os.path.exists(info_path_1):
        return info_path_1
    if os.path.exists(info_path_2):
        return info_path_2
    return None


def has_deltamod_info_file(file_list: list[str] | set[str]) -> bool:
    file_set = set(file_list)
    return LEGACY_META_JSON_FILENAME in file_set or META_JSON_FILENAME in file_set


def check_filename_is_deltamod_info(filename: str) -> bool:
    filename_lower = filename.lower()
    return filename_lower.endswith('_deltamodinfo.json') or filename == LEGACY_META_JSON_FILENAME or filename == META_JSON_FILENAME or (filename_lower == META_JSON_FILENAME.lower())


def safe_remove(path: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(path):
        return True
    for attempt in range(max_retries):
        try:
            if platform.system() == 'Windows':
                try:
                    os.chmod(path, stat.S_IWRITE)
                except OSError:
                    pass
            os.remove(path)
            return True
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_remove: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                time.sleep(delay)
            else:
                logging.warning(f'safe_remove: Failed to remove {path} after {max_retries} attempts: {e}')
                return False
    return False


def safe_move(src: str, dst: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(src):
        return False
    dst_dir = os.path.dirname(dst)
    if dst_dir and (not os.path.exists(dst_dir)):
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            logging.warning(f'safe_move: Failed to create destination directory {dst_dir}: {e}')
            return False
    for attempt in range(max_retries):
        try:
            if platform.system() == 'Windows' and os.path.isfile(src):
                try:
                    os.chmod(src, stat.S_IWRITE)
                except OSError:
                    pass
            shutil.move(src, dst)
            return True
        except (OSError, PermissionError, shutil.Error) as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_move: Attempt {attempt + 1}/{max_retries} failed for {src} -> {dst}: {e}, retrying...')
                time.sleep(delay)
            else:
                logging.warning(f'safe_move: Failed to move {src} to {dst} after {max_retries} attempts: {e}')
                return False
    return False


def safe_rmtree(path: str, max_retries: int = 5, delay: float = 0.1) -> bool:
    if not os.path.exists(path):
        return True
    if not os.path.isdir(path):
        return safe_remove(path, max_retries, delay)
    if platform.system() == 'Windows':
        try:
            ensure_writable(path)
        except Exception:
            pass
    for attempt in range(max_retries):
        try:
            shutil.rmtree(path)
            return True
        except (OSError, PermissionError, shutil.Error) as e:
            if attempt < max_retries - 1:
                logging.debug(f'safe_rmtree: Attempt {attempt + 1}/{max_retries} failed for {path}: {e}, retrying...')
                if platform.system() == 'Windows':
                    try:
                        for root, dirs, files in os.walk(path):
                            for name in files:
                                file_path = os.path.join(root, name)
                                try:
                                    os.chmod(file_path, stat.S_IWRITE)
                                except OSError:
                                    pass
                            for name in dirs:
                                dir_path = os.path.join(root, name)
                                try:
                                    os.chmod(dir_path, stat.S_IWRITE)
                                except OSError:
                                    pass
                    except Exception:
                        pass
                time.sleep(delay)
            else:
                logging.warning(f'safe_rmtree: Failed to remove {path} after {max_retries} attempts: {e}')
                return False
    return False


def migrate_mod_config(mod_dir: str) -> bool:
    import shutil
    import logging
    old_config_path = os.path.join(mod_dir, LEGACY_MOD_CONFIG_FILENAME)
    config_path = os.path.join(mod_dir, MOD_CONFIG_FILENAME)
    if os.path.exists(old_config_path) and (not os.path.exists(config_path)):
        try:
            safe_move(old_config_path, config_path)
            folder_name = os.path.basename(mod_dir)
            logging.info(f'Migrated mod config.json to mod_config.json in {folder_name}')
            return True
        except Exception as e:
            folder_name = os.path.basename(mod_dir)
            logging.warning(f'Failed to migrate mod config.json to mod_config.json in {folder_name}: {e}')
            return False
    return True
