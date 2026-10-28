"""Resolve available GameBanana updates without blocking the UI."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import pyqtSignal

from adapters.gamebanana_adapter import GameBananaAPI
from ui.utils.thread_lifetime import ManagedQThread

logger = logging.getLogger(__name__)


class ResolveGameBananaUpdatesThread(ManagedQThread):
    """Find newer download files for the supplied installed GameBanana mods."""

    result_ready = pyqtSignal(list)

    def __init__(self, candidates: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self._candidates = candidates
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()

    def run(self) -> None:
        api = GameBananaAPI()
        updates: list[dict[str, Any]] = []
        for candidate in self._candidates:
            if self._cancelled or self.isInterruptionRequested():
                return
            mod_id = candidate.get("id")
            game = candidate.get("game")
            if not isinstance(mod_id, str) or not isinstance(game, str):
                continue
            try:
                resolutions = api.resolve_mod_update_downloads(mod_id, game)
            except Exception:
                logger.debug("Failed to resolve GameBanana update for %s", mod_id, exc_info=True)
                continue
            newer_resolutions = self._newer_resolutions(candidate, resolutions)
            if not newer_resolutions:
                continue
            updates.append(
                {
                    **candidate,
                    "resolved": newer_resolutions[0],
                    "resolutions": newer_resolutions,
                }
            )
        if not self._cancelled and not self.isInterruptionRequested():
            self.result_ready.emit(updates)

    @staticmethod
    def _newer_resolutions(
        candidate: dict[str, Any], resolutions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if GameBananaAPI._safe_int(candidate.get("file_timestamp")) is None:
            local_file_id = str(candidate.get("file_id") or "")
            for resolution in resolutions:
                metadata = resolution.get("metadata")
                if (
                    isinstance(metadata, dict)
                    and local_file_id
                    and str(metadata.get("gb_file_id") or "") == local_file_id
                    and (timestamp := GameBananaAPI._safe_int(metadata.get("timestamp"))) is not None
                ):
                    candidate = {**candidate, "file_timestamp": timestamp}
                    break
        local_file_id = str(candidate.get("file_id") or "")
        offered = {
            str(resolution.get("metadata", {}).get("gb_file_id") or "")
            for resolution in resolutions
            if isinstance(resolution.get("metadata"), dict)
        }
        installed_offered = bool(local_file_id) and local_file_id in offered
        return [
            resolution
            for resolution in resolutions
            if ResolveGameBananaUpdatesThread._is_newer(candidate, resolution, installed_offered)
        ]

    @staticmethod
    def _is_newer(
        candidate: dict[str, Any], resolved: dict[str, Any], installed_offered: bool = False
    ) -> bool:
        """`installed_offered`: the installed file is still listed at the newest version."""
        remote_metadata = resolved.get("metadata")
        remote_metadata = remote_metadata if isinstance(remote_metadata, dict) else {}
        remote_file_id = str(remote_metadata.get("gb_file_id") or "")
        local_file_id = str(candidate.get("file_id") or "")
        remote_version = str(remote_metadata.get("version") or "").strip()
        local_version = str(candidate.get("version") or "").strip()
        remote_timestamp = GameBananaAPI._safe_int(remote_metadata.get("timestamp"))
        local_timestamp = GameBananaAPI._safe_int(candidate.get("file_timestamp"))
        if remote_version and local_version:
            remote_key = GameBananaAPI._gamebanana_version_key(remote_version)
            local_key = GameBananaAPI._gamebanana_version_key(local_version)
            if remote_key != local_key:
                return remote_key > local_key
            if installed_offered and remote_file_id != local_file_id:
                return False  # another download of the release that is already installed
            return (
                remote_timestamp is not None
                and local_timestamp is not None
                and remote_timestamp > local_timestamp
            )
        if remote_timestamp is not None and local_timestamp is not None:
            return remote_timestamp > local_timestamp
        if local_file_id and remote_file_id:
            return local_file_id != remote_file_id
        return bool(remote_version and remote_version != local_version)
