"""Data models for the Downloads system."""
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from utils.time_utils import utc_now_iso


class DownloadStatus(str, Enum):
    """Status of the file download phase."""
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UseStatus(str, Enum):
    """Status of the use/install phase."""
    NOT_STARTED = "not_started"
    PENDING_AUTO = "pending_auto_use"
    OVERWRITE_PENDING = "overwrite_pending"
    READY = "ready_to_use"
    USING = "using"
    NEEDS_MANUAL = "needs_manual_install"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceKind(str, Enum):
    """Where the download originated from."""
    GAMEBANANA = "gamebanana"
    DELTAHUB_PROTOCOL = "deltahub_protocol"
    EXTERNAL_URL = "external_url"
    LOCAL_FILE = "local_file"


class TargetKind(str, Enum):
    """What type of artifact is being downloaded."""
    MOD = "mod"


@dataclass
class DownloadRecord:
    """Persistent download history record. Serialized to JSON."""
    id: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    finished_at: Optional[str] = None
    source_kind: SourceKind = SourceKind.EXTERNAL_URL
    target_kind: TargetKind = TargetKind.MOD
    display_name: str = ""
    source_url: Optional[str] = None
    source_file_path: Optional[str] = None
    canonical_key: Optional[str] = None
    download_status: str = DownloadStatus.QUEUED
    use_status: str = UseStatus.NOT_STARTED
    progress: int = 0
    bytes_received: int = 0
    bytes_total: int = 0
    file_path: Optional[str] = None
    file_exists: bool = False
    auto_use: bool = True
    delete_after_use: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    ever_installed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DownloadRecord':
        """Deserialize from a dict. Unknown keys are silently ignored."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def touch(self):
        self.updated_at = utc_now_iso()

    @property
    def is_active(self) -> bool:
        return self.download_status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING) or self.use_status in (UseStatus.PENDING_AUTO, UseStatus.USING)

    @property
    def needs_attention(self) -> bool:
        return self.use_status in (UseStatus.OVERWRITE_PENDING, UseStatus.NEEDS_MANUAL)

    @property
    def effective_status_key(self) -> str:
        if self.download_status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
            return 'downloading'
        if self.use_status == UseStatus.USING:
            return 'installing'
        if self.use_status == UseStatus.OVERWRITE_PENDING:
            return 'overwrite_pending'
        if self.use_status == UseStatus.NEEDS_MANUAL:
            return 'needs_manual'
        if self.download_status == DownloadStatus.DOWNLOADED and self.file_exists:
            return 'installed' if self.ever_installed else 'ready'
        if self.download_status == DownloadStatus.CANCELLED or self.use_status == UseStatus.CANCELLED:
            return 'cancelled'
        return 'failed'
