"""Utilities for the mod merge system: context managers, decorators, and helpers."""
import os
import tempfile
import logging
from typing import Optional
from utils.file_utils import safe_rmtree, safe_remove


class CancelledException(Exception):
    """Raised when a merge operation is cancelled by the user."""
    pass


class TemporaryMergeContext:
    """Context manager for temporary merge directory lifecycle.

    Usage:
        with TemporaryMergeContext(prefix='deltahub_multimod_', logger=self.patching_logger) as ctx:
            ctx.path
            backup_dir = ctx.ensure_subdir('backups')
            output_dir = ctx.ensure_subdir('output')
    """

    def __init__(self, prefix: str = 'deltahub_multimod_', logger=None):
        self.prefix = prefix
        self.logger = logger or logging.getLogger(__name__)
        self.path: Optional[str] = None

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix=self.prefix)
        self.logger.info(f'Created temp merge directory: {self.path}')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.path and os.path.exists(self.path):
            if safe_rmtree(self.path):
                self.logger.info(f'Cleaned up temp merge directory: {self.path}')
            else:
                self.logger.warning(f'Failed to cleanup temp merge dir {self.path}')
        self.path = None
        return False

    def ensure_subdir(self, *parts: str) -> str:
        """Create and return a subdirectory path within the temp dir."""
        subdir = os.path.join(self.path, *parts)
        os.makedirs(subdir, exist_ok=True)
        return subdir

    def cleanup_except(self, keep_name: str = 'backups') -> None:
        """Remove all items in the temp dir except the named one."""
        if not self.path or not os.path.exists(self.path):
            return
        try:
            for item in os.listdir(self.path):
                if item == keep_name:
                    continue
                item_path = os.path.join(self.path, item)
                if os.path.isdir(item_path):
                    if not safe_rmtree(item_path):
                        self.logger.warning(f'Failed to remove temp directory {item_path}')
                elif not safe_remove(item_path):
                    self.logger.warning(f'Failed to remove temp file {item_path}')
            self.logger.info(f'Cleaned up temp files, kept {keep_name}: {self.path}')
        except Exception as e:
            self.logger.warning(f'Failed to cleanup temp files from merge dir {self.path}: {e}')

    def full_cleanup(self) -> None:
        """Remove the entire temp directory."""
        if not self.path or not os.path.exists(self.path):
            return
        if safe_rmtree(self.path):
            self.logger.info(f'Cleaned up temp merge directory: {self.path}')
        else:
            self.logger.warning(f'Failed to cleanup temp merge dir {self.path}')
        self.path = None


def check_cancelled(merger) -> None:
    """Check if the merger has been cancelled and raise CancelledException if so."""
    if merger._cancelled:
        raise CancelledException('Merge cancelled by user')


def classify_xdelta_error(error_msg: str) -> str:
    """Classify an xdelta error message into a category."""
    lower = error_msg.lower()
    if 'checksum mismatch' in lower or 'XD3_INVALID_INPUT' in error_msg:
        return 'checksum'
    if any(k in lower for k in ('no such file', 'cannot find', 'file not found')):
        return 'not_found'
    if any(k in lower for k in ('permission denied', 'access denied')):
        return 'permission'
    if 'XD3_INTERNAL' in error_msg or any(k in lower for k in ('corrupt', 'invalid')):
        return 'corrupted'
    if any(k in lower for k in ('io error', 'input/output', 'disk')):
        return 'io'
    return 'unknown'
