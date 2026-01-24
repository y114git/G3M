"""Patching operation logging.

This module provides specialized logging for mod patching and conflict tracking.
Logs are stored in: DELTAHUB/logs/ with archives in subdirectories.
"""
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
    """Get the logs directory path, creating it if needed."""
    user_root = get_user_data_root()
    logs_dir = os.path.join(user_root, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def _get_archive_dir(subdir: str) -> str:
    """Get an archive subdirectory path, creating it if needed."""
    logs_dir = _get_logs_dir()
    archive_dir = os.path.join(logs_dir, subdir)
    os.makedirs(archive_dir, exist_ok=True)
    return archive_dir


def _get_timestamp_suffix() -> str:
    """Get a timestamp suffix for archived log files."""
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _cleanup_old_archives(archive_dir: str):
    """Remove oldest archive files if count exceeds MAX_ARCHIVE_FILES.

    Args:
        archive_dir: Directory containing archived logs.
    """
    try:
        files = [f for f in os.listdir(archive_dir) if f.endswith('.log')]
        if len(files) > MAX_ARCHIVE_FILES:
            files_with_mtime = [(f, os.path.getmtime(os.path.join(archive_dir, f))) for f in files]
            files_with_mtime.sort(key=lambda x: x[1])
            files_to_delete = len(files) - MAX_ARCHIVE_FILES
            for f, _ in files_with_mtime[:files_to_delete]:
                try:
                    os.remove(os.path.join(archive_dir, f))
                except Exception:
                    pass
    except Exception as e:
        logging.warning(f'Failed to cleanup old archives in {archive_dir}: {e}')


def _rotate_log(log_path: str, archive_dir: str, base_name: str):
    """Rotate a log file to archive directory with timestamp suffix.

    Args:
        log_path: Path to current log file.
        archive_dir: Directory for archived logs.
        base_name: Base name for the archived file (e.g., 'patching').
    """
    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            timestamp = _get_timestamp_suffix()
            archive_path = os.path.join(archive_dir, f'{base_name}_{timestamp}.log')
            shutil.copy2(log_path, archive_path)
            _cleanup_old_archives(archive_dir)
        except Exception as e:
            logging.warning(f'Failed to archive {base_name}.log: {e}')


def _init_logger(name: str, log_path: str, level: int, fmt: logging.Formatter, truncate: bool = False) -> logging.Logger:
    """Initialize a file logger.

    Args:
        name: Logger name.
        log_path: Path to log file.
        level: Logging level.
        fmt: Log formatter.
        truncate: If True, truncate file; if False, append.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    mode = 'w' if truncate else 'a'
    file_handler = logging.FileHandler(log_path, mode=mode, encoding='utf-8')
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def get_patching_logger() -> logging.Logger:
    """Get or create the patching operations logger.

    The patching log is stored at logs/patching.log.
    Old logs are archived to logs/patching/ with timestamp suffix.

    Returns:
        logging.Logger: Patching logger instance.
    """
    global _patching_logger, _patching_log_rotated
    if _patching_logger is not None:
        return _patching_logger
    logs_dir = _get_logs_dir()
    log_path = os.path.join(logs_dir, 'patching.log')
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    _patching_logger = _init_logger('patching', log_path, logging.DEBUG, fmt, truncate=_patching_log_rotated)
    _patching_log_rotated = False
    return _patching_logger


def get_conflicts_logger() -> logging.Logger:
    """Get or create the merge conflicts logger.

    The conflicts log is stored at logs/conflicts.log.
    Old logs are archived to logs/conflicts/ with timestamp suffix.

    Returns:
        logging.Logger: Conflicts logger instance.
    """
    global _conflicts_logger, _conflicts_log_rotated
    if _conflicts_logger is not None:
        return _conflicts_logger
    logs_dir = _get_logs_dir()
    log_path = os.path.join(logs_dir, 'conflicts.log')
    fmt = logging.Formatter('%(asctime)s [CONFLICT] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    _conflicts_logger = _init_logger('conflicts', log_path, logging.INFO, fmt, truncate=_conflicts_log_rotated)
    _conflicts_log_rotated = False
    return _conflicts_logger


def rotate_patching_log():
    """Archive and reset the patching log. Called on every game start."""
    global _patching_logger, _patching_log_rotated
    logs_dir = _get_logs_dir()
    log_path = os.path.join(logs_dir, 'patching.log')
    archive_dir = _get_archive_dir('patching')
    _rotate_log(log_path, archive_dir, 'patching')
    _patching_logger = None
    _patching_log_rotated = True


def rotate_conflicts_log():
    """Archive and reset the conflicts log. Called ONLY when new conflicts are detected."""
    global _conflicts_logger, _conflicts_log_rotated
    logs_dir = _get_logs_dir()
    log_path = os.path.join(logs_dir, 'conflicts.log')
    archive_dir = _get_archive_dir('conflicts')
    _rotate_log(log_path, archive_dir, 'conflicts')
    _conflicts_logger = None
    _conflicts_log_rotated = True


def get_conflicts_log_path() -> str:
    """Get the path to the current conflicts log file.

    Returns:
        str: Path to conflicts.log
    """
    return os.path.join(_get_logs_dir(), 'conflicts.log')
