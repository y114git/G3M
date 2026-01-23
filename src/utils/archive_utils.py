"""Archive extraction utilities.

This module provides utilities for extracting various archive formats
including zip, tar, rar, and 7z files with safety checks.
"""
import os
import shutil
import tempfile
import zipfile
import tarfile
import lzma
import re
import logging
import platform
from typing import List, Callable
from utils.file_utils import safe_move, safe_remove, safe_rmtree, _safe_join, _is_symlink


def _is_safe_path(path: str) -> bool:
    """Check if a path is safe (no directory traversal).

    Args:
        path: Path to check.

    Returns:
        bool: True if safe.
    """
    return not ('..' in path or path.startswith('/'))


class UnrarMissingError(Exception):
    """Exception raised when UnRAR utility is not available."""
    pass


def _get_unrar_path() -> str:
    """Get the path to the UnRAR executable.

    Returns:
        str: Path to UnRAR executable.
    """
    from utils.path_utils import get_user_data_root
    bin_dir = os.path.join(get_user_data_root(), 'bin')
    if platform.system() == 'Windows':
        return os.path.join(bin_dir, 'UnRAR.exe')
    else:
        return os.path.join(bin_dir, 'unrar')


def _ensure_unrar_available():
    """Ensure UnRAR utility is available for RAR extraction.

    Raises:
        UnrarMissingError: If UnRAR is not available.
    """
    import rarfile
    import subprocess
    if rarfile.UNRAR_TOOL:
        try:
            subprocess.run([rarfile.UNRAR_TOOL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            pass
    if rarfile.UNRAR_TOOL != 'unrar':
        try:
            subprocess.run(['unrar'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rarfile.UNRAR_TOOL = 'unrar'
            return
        except FileNotFoundError:
            pass
    local_unrar = _get_unrar_path()
    if os.path.exists(local_unrar):
        rarfile.UNRAR_TOOL = local_unrar
        return
    raise UnrarMissingError('UnRAR utility is missing')


def download_and_setup_unrar(status_callback: Callable[[str], None] = None) -> bool:
    """Download and set up the UnRAR utility.

    Args:
        status_callback: Callback for status updates.

    Returns:
        bool: True if successful.
    """
    import platform
    import gzip
    try:
        import requests
        target_path = _get_unrar_path()
        if os.path.exists(target_path):
            import rarfile
            rarfile.UNRAR_TOOL = target_path
            return True
        system_os = platform.system()
        url = None
        is_gz = False
        if system_os == 'Windows':
            url = 'https://www.rarlab.com/rar/unrarw64.exe'
            target_path = os.path.join(os.path.dirname(target_path), 'unrar_sfx.exe')
        elif system_os == 'Darwin':
            url = 'https://www.rarlab.com/rar/unrar_MacOSX_10.13.2_64bit.gz'
            is_gz = True
        else:
            return False
        if status_callback:
            status_callback('Downloading UnRAR utility...')
        bin_dir = os.path.dirname(target_path)
        os.makedirs(bin_dir, exist_ok=True)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        if is_gz:
            final_path = _get_unrar_path()
            with gzip.open(response.raw, 'rb') as f_in, open(final_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.chmod(final_path, 493)
        else:
            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            if status_callback:
                status_callback('Installing UnRAR...')
            import subprocess
            subprocess.run([target_path, '/S'], cwd=bin_dir, check=True)
            try:
                os.remove(target_path)
            except OSError:
                pass
            final_path = _get_unrar_path()
            if not os.path.exists(final_path):
                raise FileNotFoundError('Extraction failed')
        if status_callback:
            status_callback('UnRAR installed successfully.')
        import rarfile
        rarfile.UNRAR_TOOL = _get_unrar_path()
        return True
    except Exception as e:
        logging.error(f'Failed to download UnRAR: {e}')
        return False


def _extract_lzma(tmp_path: str, target_dir: str, fname: str) -> None:
    """Extract LZMA compressed file.

    Args:
        tmp_path: Path to LZMA file.
        target_dir: Directory to extract to.
        fname: Original filename.
    """
    output_path = os.path.join(target_dir, os.path.splitext(fname)[0])
    with lzma.open(tmp_path) as f_in, open(output_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)


def _detect_archive_format_by_signature(file_path: str) -> str:
    """Detect archive format by reading file signature.

    Args:
        file_path: Path to archive file.

    Returns:
        str: Archive format ('zip', 'rar', '7z', or 'unknown').
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(10)
        if len(header) >= 4:
            if header[:2] == b'PK':
                return 'zip'
            if header[:4] == b'Rar!':
                return 'rar'
            if header[:2] == b'7z':
                return '7z'
        return 'unknown'
    except Exception:
        return 'unknown'


def _collect_safe_members(members, name_getter, label: str):
    """Filter archive members to exclude unsafe paths.

    Args:
        members: Archive member list.
        name_getter: Function to extract name from member.
        label: Archive type label for logging.

    Returns:
        list: Safe members to extract.
    """
    targets = []
    for member in members:
        name = name_getter(member)
        if not _is_safe_path(name):
            logging.warning(f'_extract_archive_raw: Skipping suspicious path in {label}: {name}')
            continue
        targets.append(member)
    return targets


def _extract_archive_raw(src_path: str, fname_lower: str, out_dir: str) -> None:
    """Extract archive file to directory with format detection.

    Args:
        src_path: Path to archive file.
        fname_lower: Lowercase filename for format detection.
        out_dir: Output directory.

    Raises:
        UnrarMissingError: If RAR extraction requires UnRAR utility.
    """
    import rarfile
    try:
        import py7zr
    except Exception as e:
        logging.debug(f'_extract_archive_raw: py7zr import failed (not installed): {e}')
        py7zr = None
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    detected_format = _detect_archive_format_by_signature(src_path)
    if fname_lower.endswith('.zip') or fname_lower.endswith('.dhtheme') or detected_format == 'zip':
        with zipfile.ZipFile(src_path, 'r') as zf:
            targets = _collect_safe_members(zf.namelist(), lambda member: member, 'ZIP')
            if targets:
                try:
                    zf.extractall(path=out_dir_abs, members=targets)
                except (ValueError, OSError) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract ZIP archive: {e}')
        return
    if fname_lower.endswith('.tar.gz'):
        with tarfile.open(src_path, 'r:gz') as tf:
            targets = _collect_safe_members(tf.getmembers(), lambda member: member.name, 'TAR')
            if targets:
                try:
                    tf.extractall(path=out_dir_abs, members=targets)
                except (ValueError, OSError, tarfile.TarError) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract TAR archive: {e}')
        return
    if fname_lower.endswith('.rar') or detected_format == 'rar':
        try:
            _ensure_unrar_available()
        except UnrarMissingError:
            raise
        with rarfile.RarFile(src_path, 'r') as rf:
            targets = _collect_safe_members(rf.namelist(), lambda member: member, 'RAR')
            if targets:
                try:
                    rf.extractall(path=out_dir_abs, members=targets)
                except (ValueError, OSError, rarfile.RarCannotExec) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract RAR archive: {e}')
        return
    if (fname_lower.endswith('.7z') or detected_format == '7z') and py7zr is not None:
        with py7zr.SevenZipFile(src_path, mode='r') as zf:
            targets = _collect_safe_members(zf.getnames(), lambda member: member, '7Z')
            if targets:
                try:
                    zf.extract(path=out_dir_abs, targets=targets)
                except (ValueError, OSError) as e:
                    logging.warning(f'_extract_archive_raw: Failed to extract 7z archive: {e}')
        return
    if fname_lower.endswith('.lzma'):
        _extract_lzma(src_path, out_dir, fname_lower)
        return
    shutil.copy2(src_path, os.path.join(out_dir, os.path.basename(src_path)))


def _move_tree_safely(src_root: str, dst_root: str) -> None:
    """Safely move directory tree with path traversal protection.

    Args:
        src_root: Source directory.
        dst_root: Destination directory.
    """
    import errno
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


def _cleanup_extracted_archive(target_dir: str, is_game_installation: bool = False) -> None:
    """Clean up extracted archive contents.

    This function post-processes extracted archive contents to handle
    common archive structure issues. It flattens nested directories
    and removes platform-specific chapter directories for game installations.

    Args:
        target_dir: Directory containing extracted archive contents.
        is_game_installation: Whether this is a game installation (default: False).

    Cleanup operations:
    - Flatten nested single-folder structures
    - Remove platform-specific chapter directories (chapterX_windows/mac)
    - Handle file conflicts during moves
    - Safe directory and file removal

    Returns:
        None, but modifies the target_dir structure in-place.
    """
    if is_game_installation:
        try:
            entries = list(os.listdir(target_dir))
            if len(entries) == 1:
                single_entry = os.path.join(target_dir, entries[0])
                if os.path.isdir(single_entry):
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


class ArchiveExtractor:

    @staticmethod
    def extract(archive_path: str, target_dir: str) -> None:
        if not os.path.exists(archive_path):
            raise FileNotFoundError(f'Archive not found: {archive_path}')
        if not os.path.isfile(archive_path):
            raise ValueError(f'Path is not a file: {archive_path}')
        os.makedirs(target_dir, exist_ok=True)
        fname_lower = os.path.basename(archive_path).lower()
        try:
            _extract_archive_raw(archive_path, fname_lower, target_dir)
            logging.debug(f'ArchiveExtractor: Successfully extracted {archive_path} to {target_dir}')
        except Exception as e:
            error_msg = f'Failed to extract archive {archive_path}: {e}'
            logging.error(error_msg, exc_info=True)
            if isinstance(e, (FileNotFoundError, PermissionError, OSError, ValueError, UnrarMissingError)):
                raise
            raise ValueError(error_msg) from e

    @staticmethod
    def extract_with_options(archive_path: str, target_dir: str, fname: str | None = None, is_game_installation: bool = False, size_cap_bytes: int | None = None) -> None:
        os.makedirs(target_dir, exist_ok=True)
        if size_cap_bytes is not None:
            with tempfile.TemporaryDirectory(prefix='deltahub-extract-') as temp_out:
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
            ArchiveExtractor.extract_with_backup(archive_path, target_dir, backup_temp_dir=None, backup_files=None, add_mod_dir_callback=None, backup_file_callback=None, update_manifest_callback=None, status_callback=None)

    @staticmethod
    def extract_with_backup(archive_path: str, target_dir: str, backup_temp_dir: str | None = None, backup_files: dict | None = None, add_mod_dir_callback: Callable | None = None, backup_file_callback: Callable | None = None, update_manifest_callback: Callable | None = None, status_callback: Callable | None = None) -> List[str]:
        extracted_files = []
        try:
            with tempfile.TemporaryDirectory(prefix='deltahub-extract-') as temp_dir:
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
        except UnrarMissingError:
            raise
        except Exception as e:
            error_msg = f'Archive unpack error: {os.path.basename(archive_path)}: {e}'
            if status_callback:
                try:
                    status_callback(error_msg)
                except (RuntimeError, AttributeError) as e:
                    logging.warning(f'extract_archive_with_backup: status_callback failed: {e}')
            logging.error(f'extract_archive_with_backup: {error_msg}', exc_info=True)
        return extracted_files

    @staticmethod
    def is_supported_format(filename: str) -> bool:
        filename_lower = filename.lower()
        supported_extensions = ('.zip', '.rar', '.7z', '.tar.gz', '.lzma')
        return filename_lower.endswith(supported_extensions)

    @staticmethod
    def _matches_target(name: str, target: str) -> bool:
        n = name.replace('\\', '/').strip('/')
        return n == target or n.endswith(f'/{target}')

    @staticmethod
    def check_archive_has_file(archive_path: str, target_filename: str) -> bool:
        archive_lower = archive_path.lower()
        detected_format = _detect_archive_format_by_signature(archive_path)
        try:
            if archive_lower.endswith('.zip') or archive_lower.endswith('.dhtheme') or detected_format == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    return any((ArchiveExtractor._matches_target(n, target_filename) for n in zf.namelist()))
            elif archive_lower.endswith('.tar.gz'):
                with tarfile.open(archive_path, 'r:gz') as tf:
                    return any((ArchiveExtractor._matches_target(m.name, target_filename) for m in tf.getmembers()))
            elif archive_lower.endswith('.rar') or detected_format == 'rar':
                _ensure_unrar_available()
                import rarfile
                with rarfile.RarFile(archive_path, 'r') as rf:
                    return any((ArchiveExtractor._matches_target(n, target_filename) for n in rf.namelist()))
            elif archive_lower.endswith('.7z') or detected_format == '7z':
                import py7zr
                with py7zr.SevenZipFile(archive_path, mode='r') as zf:
                    return any((ArchiveExtractor._matches_target(n, target_filename) for n in zf.getnames()))
        except UnrarMissingError:
            raise
        except Exception as e:
            logging.error(f'ArchiveExtractor.check_archive_has_file: Error: {e}', exc_info=True)
        return False


def prompt_for_unrar_install(parent_widget=None, signal_callback=None) -> bool:
    """Prompt user to install UnRAR utility for RAR archive extraction.

    This function checks if UnRAR is available, and if not, prompts the
    user to install it. It can handle both GUI and non-GUI scenarios,
    with optional callback signaling for asynchronous operations.

    Args:
        parent_widget: Parent widget for dialog display (optional).
        signal_callback: Callback to signal UnRAR requirement (optional).

    Returns:
        bool: True if UnRAR is available or was successfully installed,
              False if unavailable or installation failed/declined.

    Features:
    - Automatic UnRAR availability checking
    - GUI prompt for user installation choice
    - Automatic download and installation
    - Fallback handling for missing GUI components
    - Callback support for async operations
    """
    try:
        _ensure_unrar_available()
        return True
    except UnrarMissingError:
        pass
    if signal_callback is not None:
        signal_callback()
        return False
    try:
        from PyQt6.QtWidgets import QMessageBox
        from services.localization_service import tr
        if parent_widget is None:
            try:
                from core.app_state import app_state
                parent_widget = app_state.main_window
            except (ImportError, AttributeError):
                logging.warning('Cannot show UnRAR install prompt: no parent widget available')
                return False
        reply = QMessageBox.question(parent_widget, tr('errors.unrar_missing_title'), tr('errors.unrar_missing_text'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            success = download_and_setup_unrar()
            if success:
                logging.info('UnRAR utility installed successfully')
                return True
            else:
                logging.error('Failed to install UnRAR utility')
                return False
        else:
            logging.info('User declined UnRAR installation')
            return False
    except ImportError:
        logging.warning('Cannot show UnRAR install prompt: GUI components not available')
        return False


def get_file_extension_from_url(url: str, content_type: str = None) -> str:
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    filename = unquote(os.path.basename(parsed.path))
    if '.' in filename:
        ext = os.path.splitext(filename)[1].lower()
        supported_exts = ['.zip', '.rar', '.7z', '.tar.gz', '.lzma', '.dhtheme']
        if ext in supported_exts:
            return ext
    if content_type:
        content_type = content_type.lower()
        content_type_map = {'application/zip': '.zip', 'application/x-rar-compressed': '.rar', 'application/x-rar': '.rar', 'application/x-7z-compressed': '.7z', 'application/x-7z': '.7z', 'application/x-tar': '.tar.gz', 'application/gzip': '.tar.gz', 'application/x-gzip': '.tar.gz', 'application/x-lzma': '.lzma', 'application/x-xz': '.lzma'}
        if content_type in content_type_map:
            return content_type_map[content_type]
    return '.zip'


def get_file_extension_from_content(file_path: str) -> str:
    detected_format = _detect_archive_format_by_signature(file_path)
    format_extensions = {'zip': '.zip', 'rar': '.rar', '7z': '.7z', 'unknown': '.zip'}
    return format_extensions.get(detected_format, '.zip')


def extract_any_archive(archive_path: str, target_dir: str) -> None:
    ArchiveExtractor.extract(archive_path, target_dir)


def extract_with_unrar_retry(archive_path: str, target_dir: str, worker=None, extract_func=None) -> None:
    if extract_func is None:
        extract_func = extract_any_archive
    try:
        extract_func(archive_path, target_dir)
    except Exception as e:
        if 'File is not a zip file' in str(e) or isinstance(e, UnrarMissingError):
            if worker is not None and hasattr(worker, 'wait_for_unrar_install'):
                if not worker.wait_for_unrar_install():
                    raise UnrarMissingError('RAR archive requires UnRAR utility to be installed')
            elif not prompt_for_unrar_install():
                raise UnrarMissingError('RAR archive requires UnRAR utility to be installed')
            extract_func(archive_path, target_dir)
        else:
            raise


def extract_archive(archive_path: str, target_dir: str, fname: str | None = None, is_game_installation: bool = False, size_cap_bytes: int | None = None) -> None:
    ArchiveExtractor.extract_with_options(archive_path, target_dir, fname, is_game_installation, size_cap_bytes)


def extract_archive_with_backup(archive_path: str, target_dir: str, backup_temp_dir: str | None = None, backup_files: dict | None = None, add_mod_dir_callback=None, backup_file_callback=None, update_manifest_callback=None, status_callback=None) -> list[str]:
    return ArchiveExtractor.extract_with_backup(archive_path, target_dir, backup_temp_dir, backup_files, add_mod_dir_callback, backup_file_callback, update_manifest_callback, status_callback)
