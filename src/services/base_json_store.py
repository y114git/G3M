"""Base JSON persistence layer shared by DownloadsStore and VersionsStore."""
import json
import logging
import os
import shutil
import tempfile
from typing import List

logger = logging.getLogger(__name__)


class BaseJsonStore:
    """Atomic JSON load/save, backup on corruption, directory management."""

    def __init__(self, base_dir: str, sub_dir: str, filename: str, record_cls):
        self._store_dir = os.path.join(base_dir, sub_dir)
        self._data_path = os.path.join(self._store_dir, filename)
        self._record_cls = record_cls
        self._records: List = []
        os.makedirs(self._store_dir, exist_ok=True)

    @property
    def records(self) -> List:
        return self._records

    def load(self) -> List:
        if not os.path.exists(self._data_path):
            self._records = []
            return self._records
        try:
            with open(self._data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._records = [self._record_cls.from_dict(d) for d in data if isinstance(d, dict)]
        except (json.JSONDecodeError, OSError) as e:
            logger.error('%s: corrupt data, backing up and resetting: %s', type(self).__name__, e)
            self._backup_corrupt()
            self._records = []
        return self._records

    def save(self):
        os.makedirs(self._store_dir, exist_ok=True)
        data = [r.to_dict() for r in self._records]
        fd, tmp_path = tempfile.mkstemp(dir=self._store_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            fd = -1
            os.replace(tmp_path, self._data_path)
            tmp_path = ''
        except Exception as e:
            logger.error('%s: save failed: %s', type(self).__name__, e)
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def add(self, record):
        self._records.append(record)
        self.save()

    def update(self, record):
        if record not in self._records:
            raise ValueError(f'{type(self).__name__}.update: record not in store')
        record.touch()
        self.save()

    def _backup_corrupt(self):
        if os.path.exists(self._data_path):
            try:
                shutil.copy2(self._data_path, self._data_path + '.bak')
            except OSError:
                pass
