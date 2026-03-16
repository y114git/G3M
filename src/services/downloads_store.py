"""Persistent storage for download history. No business logic."""
import logging
import os
from typing import Optional

from models.download_models import DownloadRecord, DownloadStatus, UseStatus
from services.base_json_store import BaseJsonStore

logger = logging.getLogger(__name__)


class DownloadsStore(BaseJsonStore):
    """Thin persistence layer: downloads_history.json, atomic writes, startup recovery."""

    def __init__(self, base_dir: str):
        super().__init__(base_dir, 'downloads', 'downloads_history.json', DownloadRecord)

    @property
    def downloads_dir(self) -> str:
        return self._store_dir

    def remove(self, record_id: str):
        self._records = [r for r in self._records if r.id != record_id]
        self.save()

    def update(self, record: DownloadRecord):
        existing = self.find(record.id)
        if existing is None:
            logger.warning('DownloadsStore.update called with record not in store: %s', record.id)
            return
        record.touch()
        self.save()

    def find(self, record_id: str) -> Optional[DownloadRecord]:
        return next((r for r in self._records if r.id == record_id), None)

    def find_by_canonical_key(self, key: str) -> Optional[DownloadRecord]:
        if not key:
            return None
        return next(
            (r for r in self._records
             if r.canonical_key == key
             and r.download_status not in (DownloadStatus.FAILED, DownloadStatus.CANCELLED)),
            None,
        )

    def startup_recovery(self):
        changed = False
        for r in self._records:
            interrupted = False
            if r.download_status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                r.download_status = DownloadStatus.FAILED
                r.use_status = UseStatus.FAILED
                r.file_exists = False
                interrupted = True
            elif r.use_status == UseStatus.USING:
                r.use_status = UseStatus.FAILED
                interrupted = True
            if interrupted:
                r.error_code = 'interrupted_on_close'
                r.error_message = 'Interrupted by application close'
                changed = True
            if r.file_path and not os.path.exists(r.file_path):
                r.file_exists = False
                changed = True
        if changed:
            self.save()

    def delete_file_for_record(self, record: DownloadRecord):
        if record.file_path and os.path.exists(record.file_path):
            try:
                os.remove(record.file_path)
            except OSError as e:
                logger.warning('DownloadsStore: could not delete file %s: %s', record.file_path, e)
        record.file_exists = False
        record.file_path = None
        self.save()
