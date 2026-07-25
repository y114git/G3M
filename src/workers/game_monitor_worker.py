"""Game process monitoring worker.

This module provides a worker for monitoring game processes and detecting when they exit.
"""

import logging
import time

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from services.game_detection_service import (
    GAME_PROCESS_EXIT_CONFIRMATION_CHECKS,
    GAME_PROCESS_POLL_SECONDS,
    GAME_PROCESS_RUNNING_POLL_SECONDS,
    GAME_PROCESS_START_TIMEOUT_SECONDS,
    GameProcessTracker,
    ProcessIdentity,
)

logger = logging.getLogger(__name__)


class GameMonitorWorker(QObject):
    finished = pyqtSignal(bool)

    _POLL_INTERVAL_SECONDS = GAME_PROCESS_POLL_SECONDS
    _RUNNING_POLL_INTERVAL_SECONDS = GAME_PROCESS_RUNNING_POLL_SECONDS
    _STARTUP_CHECKS = int(
        GAME_PROCESS_START_TIMEOUT_SECONDS / GAME_PROCESS_POLL_SECONDS
    )
    _EXIT_CONFIRMATION_CHECKS = GAME_PROCESS_EXIT_CONFIRMATION_CHECKS

    def __init__(
        self,
        process,
        vanilla_mode,
        process_names: tuple[str, ...] = (),
        baseline_processes: set[ProcessIdentity] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.process = process
        self.vanilla_mode = vanilla_mode
        self.process_names = tuple(name for name in process_names if name)
        self._root_pid = self._read_root_pid()
        self._tracker = GameProcessTracker(
            self._root_pid,
            self.process_names,
            baseline_processes,
        )

    def _read_root_pid(self) -> int | None:
        try:
            pid = int(getattr(self.process, "pid", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
        return pid if pid > 0 else None

    def _refresh_tracked_processes(self) -> bool:
        return self._tracker.refresh()

    def _is_interruption_requested(self) -> bool:
        try:
            current_thread = QThread.currentThread()
            return bool(current_thread and current_thread.isInterruptionRequested())
        except Exception:
            return False

    def _safe_finished(self) -> None:
        try:
            self.finished.emit(self.vanilla_mode)
        except Exception as e:
            logger.warning("GameMonitorWorker: failed to emit finished: %s", e, exc_info=True)

    @pyqtSlot()
    def run(self):
        try:
            logger.info("[GAME_MONITOR] Starting game monitoring")
            if self.process:
                pid = getattr(self.process, "pid", "unknown")
                logger.info("[GAME_MONITOR] Monitoring launched process: %s", pid)

            game_appeared = False
            for _ in range(self._STARTUP_CHECKS):
                if self._is_interruption_requested():
                    logger.debug(
                        "GameMonitorWorker.run: interruption requested, stopping"
                    )
                    return
                if self._refresh_tracked_processes():
                    game_appeared = True
                    logger.info(
                        "[GAME_MONITOR] Game process detected, continuing to monitor"
                    )
                    break
                time.sleep(self._POLL_INTERVAL_SECONDS)

            if not game_appeared:
                logger.info(
                    "[GAME_MONITOR] Game process not found after launch, emitting finished signal"
                )
                self._safe_finished()
                return

            missing_checks = 0
            while missing_checks < self._EXIT_CONFIRMATION_CHECKS:
                if self._is_interruption_requested():
                    logger.debug(
                        "GameMonitorWorker.run: interruption requested during game monitoring"
                    )
                    return
                process_running = self._refresh_tracked_processes()
                if process_running:
                    missing_checks = 0
                else:
                    missing_checks += 1
                if missing_checks < self._EXIT_CONFIRMATION_CHECKS:
                    time.sleep(
                        self._RUNNING_POLL_INTERVAL_SECONDS
                        if process_running
                        else self._POLL_INTERVAL_SECONDS
                    )

            logger.info(
                "[GAME_MONITOR] Game is no longer running, emitting finished signal"
            )
            self._safe_finished()
        except Exception as e:
            logger.error(f"[GAME_MONITOR] Unexpected error: {e}", exc_info=True)
            self._safe_finished()
