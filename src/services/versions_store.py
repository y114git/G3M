"""Persistent storage for versions. No business logic."""
import os
from typing import List, Optional

from models.version_models import VersionRecord
from services.base_json_store import BaseJsonStore


class VersionsStore(BaseJsonStore):
    """Thin persistence layer: versions_data.json, atomic writes, startup recovery."""

    def __init__(self, base_dir: str):
        super().__init__(base_dir, 'versions', 'versions_data.json', VersionRecord)

    @property
    def versions_dir(self) -> str:
        return self._store_dir

    def remove(self, archive_path: str):
        self._records = [r for r in self._records if r.archive_path != archive_path]
        self.save()

    def find(self, archive_path: str) -> Optional[VersionRecord]:
        return next((r for r in self._records if r.archive_path == archive_path), None)

    def records_for_game(self, game: str) -> List[VersionRecord]:
        return [r for r in self._records if r.game == game]

    def startup_recovery(self):
        changed = False
        stale = set()
        for r in self._records:
            exists = bool(r.archive_path and os.path.exists(r.archive_path))
            if not exists and not r.archive_exists:
                stale.add(r.archive_path)
                changed = True
                continue
            if r.archive_exists != exists:
                r.archive_exists = exists
                changed = True
        if stale:
            self._records = [r for r in self._records if r.archive_path not in stale]
        if changed:
            self.save()
