"""Patching operation logging."""
import os
import shutil
import logging
from datetime import datetime
from utils.path_utils import get_user_data_root

MAX_ARCHIVE_FILES = 50
_LOG_CFG = {'patching': {'level': logging.DEBUG, 'fmt': '%(asctime)s [%(levelname)s] %(message)s', 'ref': [None], 'rot': [False]},
            'conflicts': {'level': logging.INFO, 'fmt': '%(asctime)s [CONFLICT] %(message)s', 'ref': [None], 'rot': [False]}}


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
            for f, _ in sorted([(f, os.path.getmtime(os.path.join(archive_dir, f))) for f in files], key=lambda x: x[1])[:len(files) - MAX_ARCHIVE_FILES]:
                try:
                    os.remove(os.path.join(archive_dir, f))
                except Exception:
                    pass
    except Exception as e:
        logging.warning(f'Failed to cleanup old archives in {archive_dir}: {e}')


def _rotate_log(name: str):
    log_path = os.path.join(_get_logs_dir(), f'{name}.log')
    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            shutil.copy2(log_path, os.path.join(_get_archive_dir(name), f'{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'))
            _cleanup_old_archives(_get_archive_dir(name))
        except Exception as e:
            logging.warning(f'Failed to archive {name}.log: {e}')


def _get_logger(name: str) -> logging.Logger:
    cfg = _LOG_CFG[name]
    if cfg['ref'][0] is None:
        logger = logging.getLogger(name)
        logger.setLevel(cfg['level'])
        logger.handlers.clear()
        handler = logging.FileHandler(os.path.join(_get_logs_dir(), f'{name}.log'), mode='w' if cfg['rot'][0] else 'a', encoding='utf-8')
        handler.setFormatter(logging.Formatter(cfg['fmt'], datefmt='%Y-%m-%d %H:%M:%S'))
        handler.setLevel(cfg['level'])
        logger.addHandler(handler)
        logger.propagate = False
        cfg['ref'][0], cfg['rot'][0] = logger, False
    return cfg['ref'][0]


def _rotate(name: str):
    _rotate_log(name)
    _LOG_CFG[name]['ref'][0], _LOG_CFG[name]['rot'][0] = None, True


def get_patching_logger() -> logging.Logger: return _get_logger('patching')
def get_conflicts_logger() -> logging.Logger: return _get_logger('conflicts')
def rotate_patching_log(): _rotate('patching')
def rotate_conflicts_log(): _rotate('conflicts')
def get_conflicts_log_path() -> str: return os.path.join(_get_logs_dir(), 'conflicts.log')
