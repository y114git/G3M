"""Patching operation logging.

This module provides specialized logging for mod patching and conflict tracking.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional
from utils.path_utils import get_user_data_root
_patching_logger: Optional[logging.Logger] = None
_conflicts_logger: Optional[logging.Logger] = None


def _init_logger(name: str, log_path: str, level: int, fmt: logging.Formatter) -> logging.Logger:
    """Initialize a rotating file logger.

    Args:
        name: Logger name.
        log_path: Path to log file.
        level: Logging level.
        fmt: Log formatter.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    file_handler = RotatingFileHandler(log_path, maxBytes=10000000, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def get_patching_logger() -> logging.Logger:
    """Get or create the patching operations logger.

    Returns:
        logging.Logger: Patching logger instance.
    """
    global _patching_logger
    if _patching_logger is not None:
        return _patching_logger
    user_root = get_user_data_root()
    log_path = os.path.join(user_root, 'patching.log')
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    _patching_logger = _init_logger('patching', log_path, logging.DEBUG, fmt)
    return _patching_logger


def get_conflicts_logger() -> logging.Logger:
    """Get or create the merge conflicts logger.

    Returns:
        logging.Logger: Conflicts logger instance.
    """
    global _conflicts_logger
    if _conflicts_logger is not None:
        return _conflicts_logger
    user_root = get_user_data_root()
    log_path = os.path.join(user_root, 'merge_conflicts.log')
    fmt = logging.Formatter('%(asctime)s [CONFLICT] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    _conflicts_logger = _init_logger('conflicts', log_path, logging.INFO, fmt)
    return _conflicts_logger


def clear_patching_logs():
    """Clear all patching and conflict log files."""
    user_root = get_user_data_root()
    patching_log_path = os.path.join(user_root, 'patching.log')
    conflicts_log_path = os.path.join(user_root, 'merge_conflicts.log')
    for log_path in [patching_log_path, conflicts_log_path]:
        if os.path.exists(log_path):
            try:
                with open(log_path, 'w', encoding='utf-8'):
                    pass
            except Exception as e:
                logging.warning(f'Failed to clear {os.path.basename(log_path)}: {e}')
    global _patching_logger, _conflicts_logger
    _patching_logger = None
    _conflicts_logger = None


def clear_conflicts_log():
    """Clear the merge conflicts log file."""
    user_root = get_user_data_root()
    conflicts_log_path = os.path.join(user_root, 'merge_conflicts.log')
    if os.path.exists(conflicts_log_path):
        try:
            with open(conflicts_log_path, 'w', encoding='utf-8'):
                pass
        except Exception as e:
            logging.warning(f'Failed to clear merge_conflicts.log: {e}')
