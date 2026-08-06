"""Central lifetime and cancellation registry for background operations."""

from __future__ import annotations

import contextlib
import logging
import operator
import threading
import time
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QRunnable

logger = logging.getLogger(__name__)


class _RunnableProxy(QRunnable):
    def __init__(self, target, release: Callable[[], None]) -> None:
        super().__init__()
        self._target = target
        self._release = release

    def run(self) -> None:
        try:
            self._target.run()
        finally:
            self._release()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


def terminate_process(process) -> Any:
    return operator.methodcaller("terminate")(process)


class BackgroundOperationManager:
    """Retain background objects until completion and coordinate cancellation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._threads: dict[int, Any] = {}
        self._threads_pending_delete: set[int] = set()
        self._runnables: dict[int, Any] = {}
        self._processes: dict[
            int, tuple[Any, Callable[[], Any] | None, object | None]
        ] = {}

    def retain_thread(self, thread) -> None:
        key = id(thread)
        with self._lock:
            if key in self._threads:
                return
            self._threads[key] = thread
        if getattr(thread, "_g3m_lifetime_connected", False):
            return
        try:
            thread.finished.connect(lambda key=key: self._thread_finished(key))
            thread._g3m_lifetime_connected = True
        except (AttributeError, RuntimeError, TypeError):
            with self._lock:
                self._threads.pop(key, None)
            raise

    def _thread_finished(self, key: int) -> None:
        with self._lock:
            thread = self._threads.pop(key, None)
            delete_requested = key in self._threads_pending_delete
            self._threads_pending_delete.discard(key)
        if thread is not None and delete_requested:
            with contextlib.suppress(RuntimeError):
                thread.deleteLater()

    def release_thread(self, thread) -> None:
        if thread is not None:
            self._thread_finished(id(thread))

    def retire_thread(self, thread) -> None:
        if thread is None:
            return
        key = id(thread)
        try:
            if not thread.isRunning():
                with self._lock:
                    self._threads.pop(key, None)
                    self._threads_pending_delete.discard(key)
                thread.deleteLater()
                return
            self.retain_thread(thread)
            with self._lock:
                self._threads_pending_delete.add(key)
            if not thread.isRunning():
                self._thread_finished(key)
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("Unable to retire background thread", exc_info=True)

    def start_runnable(
        self,
        pool,
        runnable,
    ) -> None:
        key = id(runnable)

        def release() -> None:
            with self._lock:
                self._runnables.pop(key, None)

        proxy = _RunnableProxy(runnable, release)
        with self._lock:
            self._runnables[key] = proxy
        try:
            pool.start(proxy)
        except Exception:
            release()
            raise

    def register_process(
        self,
        process,
        *,
        cancel: Callable[[], Any] | None = None,
        owner: object | None = None,
    ) -> None:
        with self._lock:
            self._processes[id(process)] = (process, cancel, owner)

    def track_process(
        self,
        process,
        *,
        cancel: Callable[[], Any] | None = None,
        owner: object | None = None,
    ) -> None:
        """Register a process and release it automatically after it exits."""
        self.register_process(process, cancel=cancel, owner=owner)

        def wait_and_release() -> None:
            try:
                process.wait()
            except (AttributeError, OSError, RuntimeError):
                logger.debug("Unable to wait for background process", exc_info=True)
            finally:
                self.release_process(process)

        threading.Thread(target=wait_and_release, daemon=True).start()

    def release_process(self, process) -> None:
        if process is None:
            return
        with self._lock:
            self._processes.pop(id(process), None)

    def cancel_processes(self, *, owner: object | None = None) -> None:
        with self._lock:
            records = list(self._processes.values())
        for process, cancel, process_owner in records:
            if owner is not None and process_owner is not owner:
                continue
            try:
                if cancel is not None:
                    cancel()
                elif process.poll() is None:
                    terminate_process(process)
            except (AttributeError, OSError, RuntimeError):
                logger.debug("Unable to cancel background process", exc_info=True)
            finally:
                self.release_process(process)

    def cancel_threads(self, timeout_ms: int = 1000) -> None:
        """Request cooperative cancellation and bounded shutdown of all threads."""
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            try:
                cancel = getattr(thread, "cancel", None)
                if callable(cancel):
                    cancel()
                thread.requestInterruption()
                thread.quit()
            except (AttributeError, RuntimeError, TypeError):
                logger.debug("Unable to request thread cancellation", exc_info=True)
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        for thread in threads:
            try:
                if thread.isRunning():
                    remaining_ms = max(0, round((deadline - time.monotonic()) * 1000))
                    if remaining_ms:
                        thread.wait(remaining_ms)
            except (AttributeError, RuntimeError, TypeError):
                logger.debug("Unable to wait for background thread", exc_info=True)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "threads": len(self._threads),
                "runnables": len(self._runnables),
                "processes": len(self._processes),
            }


background_operations = BackgroundOperationManager()
