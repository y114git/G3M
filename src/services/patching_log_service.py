"""Patching operation logging."""
import os
import shutil
import logging
from datetime import datetime
from typing import Optional
from utils.path_utils import get_user_data_root

_patching_logger: Optional[logging.Logger] = None
_conflicts_logger: Optional[logging.Logger] = None
_patching_log_rotated: bool = False
_conflicts_log_rotated: bool = False
MAX_ARCHIVE_FILES = 50


def _get_logs_dir() -> str:
    logs_dir = os.path.join(get_user_data_root(), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def _get_archive_dir(subdir: str) -> str:
    archive_dir = os.path.join(_get_logs_dir(), subdir)
    os.makedirs(archive_dir, exist_ok=True)
    return archive_dir


def _cleanup_old_archives(archive_dir: str):
    try:
        files = [f for f in os.listdir(archive_dir) if f.endswith('.log')]
        if len(files) > MAX_ARCHIVE_FILES:
            files_by_mtime = sorted([(f, os.path.getmtime(os.path.join(archive_dir, f))) for f in files], key=lambda x: x[1])
            for f, _ in files_by_mtime[:len(files) - MAX_ARCHIVE_FILES]:
                try:
                    os.remove(os.path.join(archive_dir, f))
                except Exception:
                    pass
    except Exception as e:
        logging.warning(f'Failed to cleanup old archives in {archive_dir}: {e}')


def _rotate_log(log_path: str, archive_dir: str, base_name: str):
    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            shutil.copy2(log_path, os.path.join(archive_dir, f'{base_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'))
            _cleanup_old_archives(archive_dir)
        except Exception as e:
            logging.warning(f'Failed to archive {base_name}.log: {e}')


def _init_logger(name: str, log_path: str, level: int, fmt_str: str, truncate: bool = False) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, mode='w' if truncate else 'a', encoding='utf-8')
    handler.setFormatter(logging.Formatter(fmt_str, datefmt='%Y-%m-%d %H:%M:%S'))
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _get_or_create_logger(name: str, log_file: str, level: int, fmt_str: str, logger_ref: list, rotated_ref: list) -> logging.Logger:
    if logger_ref[0] is not None:
        return logger_ref[0]
    logger_ref[0] = _init_logger(name, os.path.join(_get_logs_dir(), log_file), level, fmt_str, truncate=rotated_ref[0])
    rotated_ref[0] = False
    return logger_ref[0]


_patching_refs, _conflicts_refs = [None], [None]
_patching_rot, _conflicts_rot = [False], [False]


def get_patching_logger() -> logging.Logger:
    global _patching_refs, _patching_rot
    return _get_or_create_logger('patching', 'patching.log', logging.DEBUG, '%(asctime)s [%(levelname)s] %(message)s', _patching_refs, _patching_rot)


def get_conflicts_logger() -> logging.Logger:
    global _conflicts_refs, _conflicts_rot
    return _get_or_create_logger('conflicts', 'conflicts.log', logging.INFO, '%(asctime)s [CONFLICT] %(message)s', _conflicts_refs, _conflicts_rot)


def rotate_patching_log():
    global _patching_refs, _patching_rot
    _rotate_log(os.path.join(_get_logs_dir(), 'patching.log'), _get_archive_dir('patching'), 'patching')
    _patching_refs[0] = None
    _patching_rot[0] = True


def rotate_conflicts_log():
    global _conflicts_refs, _conflicts_rot
    _rotate_log(os.path.join(_get_logs_dir(), 'conflicts.log'), _get_archive_dir('conflicts'), 'conflicts')
    _conflicts_refs[0] = None
    _conflicts_rot[0] = True


def get_conflicts_log_path() -> str: return os.path.join(_get_logs_dir(), 'conflicts.log')
