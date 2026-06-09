"""Persistent storage for game versions. No business logic."""

import os

from models.game_version_models import GameVersionRecord
from services.base_json_store import BaseJsonStore


class GameVersionsStore(BaseJsonStore):
    """Thin persistence layer: game_versions_data.json, atomic writes, startup recovery."""

    def __init__(self, base_dir: str) -> None:
        super().__init__(
            base_dir, "game_versions", "game_versions_data.json", GameVersionRecord
        )

    @property
    def versions_dir(self) -> str:
        return self._store_dir

    def remove(self, archive_path: str):
        self._records = [r for r in self._records if r.archive_path != archive_path]
        self.save()

    def find(self, archive_path: str) -> GameVersionRecord | None:
        return next((r for r in self._records if r.archive_path == archive_path), None)

    def records_for_game(self, game: str) -> list[GameVersionRecord]:
        return [r for r in self._records if r.game == game]

    def startup_recovery(self):
        """Clean up stale records using a two-phase grace period.

        - Phase 1: If archive is missing but archive_exists=True, update flag to False.
        - Phase 2: If archive is still missing on next startup (archive_exists=False), remove record.
        """
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
