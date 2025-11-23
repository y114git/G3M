import os
import logging
from typing import Optional
from utils.file_utils import _extract_archive_raw


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
            if isinstance(e, (FileNotFoundError, PermissionError, OSError, ValueError)):
                raise
            raise ValueError(error_msg) from e

    @staticmethod
    def is_supported_format(filename: str) -> bool:
        filename_lower = filename.lower()
        supported_extensions = ('.zip', '.rar', '.7z', '.tar.gz', '.lzma')
        return filename_lower.endswith(supported_extensions)
