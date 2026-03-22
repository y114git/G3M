"""Data models for the Game Versions system."""

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from utils.time_utils import utc_now_iso


@dataclass
class GameVersionRecord:
    """Persistent game version record. Serialized to JSON."""

    archive_path: str = ""
    game: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    source_game_path: str | None = None
    archive_exists: bool = True
    size_bytes: int = 0
    file_count: int = 0
    manifest_version: int = 1
    imported: bool = False
    profile_name: str | None = None
    patching_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameVersionRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def touch(self):
        self.updated_at = utc_now_iso()

    @property
    def display_name(self) -> str:
        return (
            os.path.splitext(os.path.basename(self.archive_path))[0]
            if self.archive_path
            else ""
        )

    @property
    def effective_status_key(self) -> str:
        return "ready" if self.archive_exists else "missing"
