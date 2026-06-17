"""Game process monitoring worker.

This module provides a worker for monitoring game processes and detecting when they exit.
"""

import contextlib
import logging
import time

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from services.game_detection_service import is_game_running

logger = logging.getLogger(__name__)


class GameMonitorWorker(QObject):
    finished = pyqtSignal(bool)

    def __init__(self, process, vanilla_mode, parent=None) -> None:
        super().__init__(parent)
        self.process = process
        self.vanilla_mode = vanilla_mode
        self.game_pid = None
        if process and hasattr(process, "pid"):
            with contextlib.suppress(AttributeError, ValueError):
                self.game_pid = process.pid

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
                try:
                    logger.info(
                        f"[GAME_MONITOR] Monitoring process: {(self.process.pid if hasattr(self.process, 'pid') else 'unknown')}"
                    )
                    self.process.wait()
                    logger.info("[GAME_MONITOR] Launched process finished")
                except Exception as e:
                    logger.warning(
                        f"[GAME_MONITOR] process.wait() failed: {e}", exc_info=True
                    )
                logger.info(
                    "[GAME_MONITOR] Checking if game is still running after process exit"
                )
                game_appeared = False
                consecutive_checks = 0
                for _ in range(45):
                    if self._is_interruption_requested():
                        logger.debug(
                            "GameMonitorWorker.run: interruption requested, stopping"
                        )
                        return
                    if is_game_running():
                        consecutive_checks += 1
                        if consecutive_checks >= 2:
                            game_appeared = True
                            logger.info(
                                "[GAME_MONITOR] Game process detected, continuing to monitor"
                            )
                            break
                    else:
                        consecutive_checks = 0
                    time.sleep(0.5)
                if game_appeared:
                    while is_game_running():
                        if self._is_interruption_requested():
                            logger.debug(
                                "GameMonitorWorker.run: interruption requested during game monitoring"
                            )
                            return
                        time.sleep(1)
                    time.sleep(2)
                    if not is_game_running():
                        logger.info(
                            "[GAME_MONITOR] Game is no longer running, emitting finished signal"
                        )
                        self._safe_finished()
                        return
                else:
                    logger.info(
                        "[GAME_MONITOR] Game process not found after launch, emitting finished signal"
                    )
                    self._safe_finished()
                    return
            game_appeared = False
            consecutive_checks = 0
            for _ in range(45):
                if self._is_interruption_requested():
                    logger.debug(
                        "GameMonitorWorker.run: interruption requested, stopping"
                    )
                    return
                if is_game_running(self.game_pid):
                    consecutive_checks += 1
                    if consecutive_checks >= 3:
                        game_appeared = True
                        break
                else:
                    consecutive_checks = 0
                time.sleep(1)
            if not game_appeared:
                self._safe_finished()
                return
            time.sleep(3)
            while is_game_running(self.game_pid):
                if self._is_interruption_requested():
                    logger.debug(
                        "GameMonitorWorker.run: interruption requested during game monitoring"
                    )
                    return
                time.sleep(1)
            time.sleep(2)
            if not is_game_running(self.game_pid):
                logger.info(
                    "[GAME_MONITOR] Game is no longer running, emitting finished signal"
                )
                self._safe_finished()
        except Exception as e:
            logger.error(f"[GAME_MONITOR] Unexpected error: {e}", exc_info=True)
            self._safe_finished()
