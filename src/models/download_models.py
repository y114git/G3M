"""Data models for the Downloads system."""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from utils.time_utils import utc_now_iso


class DownloadStatus(StrEnum):
    """Status of the file download phase."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UseStatus(StrEnum):
    """Status of the use/install phase."""

    NOT_STARTED = "not_started"
    PENDING_AUTO = "pending_auto_use"
    OVERWRITE_PENDING = "overwrite_pending"
    READY = "ready_to_use"
    USING = "using"
    NEEDS_MANUAL = "needs_manual_install"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceKind(StrEnum):
    """Where the download originated from."""

    GAMEBANANA = "gamebanana"
    G3M_PROTOCOL = "g3m_protocol"
    EXTERNAL_URL = "external_url"
    LOCAL_FILE = "local_file"


class TargetKind(StrEnum):
    """What type of artifact is being downloaded."""

    MOD = "mod"
    PLUGIN = "plugin"


@dataclass
class DownloadRecord:
    """Persistent download history record. Serialized to JSON."""

    id: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    source_kind: SourceKind = SourceKind.EXTERNAL_URL
    target_kind: TargetKind = TargetKind.MOD
    display_name: str = ""
    source_url: str | None = None
    source_file_path: str | None = None
    canonical_key: str | None = None
    download_status: str = DownloadStatus.QUEUED
    use_status: str = UseStatus.NOT_STARTED
    progress: int = 0
    bytes_received: int = 0
    bytes_total: int = 0
    file_path: str | None = None
    file_exists: bool = False
    auto_use: bool = True
    delete_after_use: bool = False
    error_code: str | None = None
    error_message: str | None = None
    ever_installed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DownloadRecord:
        """Deserialize from a dict. Unknown keys are silently ignored."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def touch(self):
        self.updated_at = utc_now_iso()

    @property
    def is_active(self) -> bool:
        return self.download_status in (
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
        ) or self.use_status in (UseStatus.PENDING_AUTO, UseStatus.USING)

    @property
    def needs_attention(self) -> bool:
        return self.use_status in (UseStatus.OVERWRITE_PENDING, UseStatus.NEEDS_MANUAL)

    @property
    def effective_status_key(self) -> str:
        if self.download_status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
            return "downloading"
        if self.use_status == UseStatus.USING:
            return "installing"
        if self.use_status == UseStatus.OVERWRITE_PENDING:
            return "overwrite_pending"
        if self.use_status == UseStatus.NEEDS_MANUAL:
            return "needs_manual"
        if self.download_status == DownloadStatus.DOWNLOADED and self.file_exists:
            return "installed" if self.ever_installed else "ready"
        if (
            self.download_status == DownloadStatus.CANCELLED
            or self.use_status == UseStatus.CANCELLED
        ):
            return "cancelled"
        return "failed"
