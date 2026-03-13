"""Persistent storage for download history. No business logic."""
import json
import logging
import os
import shutil
import tempfile
from typing import List, Optional

from models.download_models import DownloadRecord, DownloadStatus, UseStatus

logger = logging.getLogger(__name__)


class DownloadsStore:
    """Thin persistence layer: load/save downloads_history.json, atomic writes, startup recovery."""

    def __init__(self, base_dir: str):
        self._downloads_dir = os.path.join(base_dir, 'downloads')
        self._history_path = os.path.join(self._downloads_dir, 'downloads_history.json')
        self._records: List[DownloadRecord] = []
        self._ensure_dirs()

    @property
    def downloads_dir(self) -> str:
        return self._downloads_dir

    @property
    def records(self) -> List[DownloadRecord]:
        return self._records

    def _ensure_dirs(self):
        os.makedirs(self._downloads_dir, exist_ok=True)

    def load(self) -> List[DownloadRecord]:
        if not os.path.exists(self._history_path):
            self._records = []
            return self._records
        try:
            with open(self._history_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._records = [DownloadRecord.from_dict(d) for d in data if isinstance(d, dict)]
        except (json.JSONDecodeError, OSError) as e:
            logger.error('DownloadsStore: corrupt history, backing up and resetting: %s', e)
            self._backup_corrupt()
            self._records = []
        return self._records

    def save(self):
        self._ensure_dirs()
        data = [r.to_dict() for r in self._records]
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self._downloads_dir, suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._history_path)
        except OSError as e:
            logger.error('DownloadsStore: save failed: %s', e)

    def add(self, record: DownloadRecord):
        self._records.append(record)
        self.save()

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

    def _backup_corrupt(self):
        if os.path.exists(self._history_path):
            bak = self._history_path + '.bak'
            try:
                shutil.copy2(self._history_path, bak)
            except OSError:
                pass

    def delete_file_for_record(self, record: DownloadRecord):
        if record.file_path and os.path.exists(record.file_path):
            try:
                os.remove(record.file_path)
            except OSError as e:
                logger.warning('DownloadsStore: could not delete file %s: %s', record.file_path, e)
        record.file_exists = False
        record.file_path = None
        self.save()
