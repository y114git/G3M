"""Helpers for resolving and reading live log files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from utils.path_utils import get_user_data_root

_ARCHIVE_TIMESTAMP_RE = re.compile(r"_(\d{8})_(\d{6})$")


@dataclass(frozen=True)
class LogSource:
    """Resolved log file source for one viewer tab."""

    key: str
    path: str | None
    is_live: bool = False


@dataclass(frozen=True)
class LogSnapshotState:
    """Incremental read state for one log file."""

    path: str
    position: int
    full_text: str


@dataclass(frozen=True)
class LogSnapshot:
    """Result of reading a log file."""

    full_text: str
    state: LogSnapshotState | None


class LogViewerService:
    """Resolve current log files and read them incrementally."""

    def __init__(self, user_data_root: str | None = None) -> None:
        self._user_data_root = user_data_root or get_user_data_root()

    @property
    def logs_dir(self) -> str:
        return os.path.join(self._user_data_root, "logs")

    def resolve_history(self) -> dict[str, list[LogSource]]:
        logs_dir = self.logs_dir
        patching_dir = os.path.join(logs_dir, "patching")
        g3m_archive_dir = os.path.join(logs_dir, "g3m")

        return {
            "g3m": self._resolve_history_entries(
                key="g3m",
                current_candidates=[os.path.join(logs_dir, "g3m.log")],
                archive_dirs=[g3m_archive_dir],
                archive_prefixes=("g3m_",),
                extensions=(".log",),
            ),
            "patching": self._resolve_history_entries(
                key="patching",
                current_candidates=[os.path.join(logs_dir, "patching.log")],
                archive_dirs=[patching_dir],
                archive_prefixes=("patching_",),
                extensions=(".log",),
            ),
            "conflicts": self._resolve_history_entries(
                key="conflicts",
                current_candidates=[os.path.join(logs_dir, "conflicts.log")],
                archive_dirs=[patching_dir],
                archive_prefixes=("conflicts_",),
                extensions=(".log",),
            ),
        }

    def _resolve_history_entries(
        self,
        *,
        key: str,
        current_candidates: list[str],
        archive_dirs: list[str],
        archive_prefixes: tuple[str, ...],
        extensions: tuple[str, ...],
    ) -> list[LogSource]:
        live_path = None
        for candidate in current_candidates:
            if os.path.isfile(candidate):
                live_path = candidate
                break

        archived_candidates: list[str] = []
        normalized_live = os.path.normcase(os.path.abspath(live_path)) if live_path else None
        lower_extensions = tuple(ext.lower() for ext in extensions)
        for archive_dir in archive_dirs:
            if not os.path.isdir(archive_dir):
                continue
            for entry in os.listdir(archive_dir):
                if not entry.lower().endswith(lower_extensions):
                    continue
                if not entry.startswith(archive_prefixes):
                    continue
                path = os.path.join(archive_dir, entry)
                normalized_path = os.path.normcase(os.path.abspath(path))
                if normalized_live and normalized_path == normalized_live:
                    continue
                archived_candidates.append(path)

        archived_candidates.sort(key=self._file_sort_key, reverse=True)
        return [
            LogSource(key=key, path=live_path, is_live=True),
            *(LogSource(key=key, path=path, is_live=False) for path in archived_candidates),
        ]

    @staticmethod
    def _file_sort_key(path: str) -> tuple[str, float, str]:
        filename = os.path.splitext(os.path.basename(path))[0]
        match = _ARCHIVE_TIMESTAMP_RE.search(filename)
        timestamp_key = "".join(match.groups()) if match else ""
        try:
            return (timestamp_key, os.path.getmtime(path), path)
        except OSError:
            return (timestamp_key, 0.0, path)

    def read_snapshot(
        self, path: str | None, previous_state: LogSnapshotState | None
    ) -> LogSnapshot:
        if not path or not os.path.isfile(path):
            return LogSnapshot("", None)

        try:
            current_size = os.path.getsize(path)
        except OSError:
            return LogSnapshot("", None)

        append_only = bool(
            previous_state
            and previous_state.path == path
            and current_size >= previous_state.position
        )

        if append_only and previous_state is not None:
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    handle.seek(previous_state.position)
                    appended_text = handle.read()
            except OSError:
                appended_text = ""
            full_text = previous_state.full_text + appended_text
            return LogSnapshot(
                full_text=full_text,
                state=LogSnapshotState(
                    path=path,
                    position=current_size,
                    full_text=full_text,
                ),
            )

        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                full_text = handle.read()
        except OSError:
            return LogSnapshot("", None)

        return LogSnapshot(
            full_text=full_text,
            state=LogSnapshotState(
                path=path,
                position=current_size,
                full_text=full_text,
            ),
        )

    @staticmethod
    def format_archive_label(path: str | None) -> str:
        if not path:
            return ""
        filename = os.path.basename(path)
        stem = os.path.splitext(filename)[0]
        match = _ARCHIVE_TIMESTAMP_RE.search(stem)
        if not match:
            return filename
        date_part, time_part = match.groups()
        return (
            f"{date_part[6:8]}.{date_part[4:6]}.{date_part[2:4]} - "
            f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"
        )
