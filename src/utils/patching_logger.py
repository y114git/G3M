import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional
from utils.path_utils import get_user_data_root
_patching_logger: Optional[logging.Logger] = None
_conflicts_logger: Optional[logging.Logger] = None


def get_patching_logger() -> logging.Logger:
    global _patching_logger
    if _patching_logger is not None:
        return _patching_logger
    user_root = get_user_data_root()
    log_path = os.path.join(user_root, 'patching.log')
    if os.path.exists(log_path):
        try:
            with open(log_path, 'w', encoding='utf-8'):
                pass
        except Exception as e:
            print(f'Failed to clear patching.log: {e}')
    _patching_logger = logging.getLogger('patching')
    _patching_logger.setLevel(logging.DEBUG)
    _patching_logger.handlers.clear()
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(log_path, maxBytes=10000000, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    _patching_logger.addHandler(file_handler)
    _patching_logger.propagate = False
    return _patching_logger


def get_conflicts_logger() -> logging.Logger:
    global _conflicts_logger
    if _conflicts_logger is not None:
        return _conflicts_logger
    user_root = get_user_data_root()
    log_path = os.path.join(user_root, 'merge_conflicts.log')
    if os.path.exists(log_path):
        try:
            with open(log_path, 'w', encoding='utf-8'):
                pass
        except Exception as e:
            print(f'Failed to clear merge_conflicts.log: {e}')
    _conflicts_logger = logging.getLogger('conflicts')
    _conflicts_logger.setLevel(logging.INFO)
    _conflicts_logger.handlers.clear()
    fmt = logging.Formatter('%(asctime)s [CONFLICT] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(log_path, maxBytes=10000000, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)
    _conflicts_logger.addHandler(file_handler)
    _conflicts_logger.propagate = False
    return _conflicts_logger


def clear_patching_logs():
    user_root = get_user_data_root()
    patching_log_path = os.path.join(user_root, 'patching.log')
    conflicts_log_path = os.path.join(user_root, 'merge_conflicts.log')
    for log_path in [patching_log_path, conflicts_log_path]:
        if os.path.exists(log_path):
            try:
                with open(log_path, 'w', encoding='utf-8'):
                    pass
            except Exception as e:
                print(f'Failed to clear {os.path.basename(log_path)}: {e}')
    global _patching_logger, _conflicts_logger
    _patching_logger = None
    _conflicts_logger = None
