"""Close event cleanup logic extracted from AppWindow."""

import contextlib
import logging
import os
from collections.abc import Iterable, Mapping

from PyQt6.QtCore import QObject, QThread, QThreadPool
from PyQt6.QtWidgets import QApplication

from config.config import THREAD_WAIT_TIMEOUT
from ui.utils.ui_utils import safe_stop_thread

logger = logging.getLogger(__name__)

_THREAD_ATTRS = (
    "_compatibility_thread",
    "_mod_scan_thread",
    "_scan_thread",
    "_bg_loader",
    "_catalog_worker",
    "_worker",
    "_post_fetch_worker",
    "_user_data_root_worker",
    "thread",
    "_thread",
    "worker_thread",
    "_worker_thread",
    "monitor_thread",
    "fetch_thread",
    "details_thread",
    "metadata_thread",
    "install_thread",
    "full_install_thread",
    "current_install_thread",
    "changelog_thread",
    "presence_thread",
)
_THREAD_CONTAINER_ATTRS = (
    "_workers",
    "_load_more_threads",
    "_retiring_patching_threads",
)
_THREAD_OWNER_ATTRS = (
    "downloads_manager",
    "game_launcher",
    "library_display",
    "mod_service",
    "refresh_controller",
    "search_display",
    "update_checker",
)


def _is_managed_shutdown_thread(w, thread, owner) -> bool:
    managed_owners = []
    for attr in ("session_manager",):
        candidate = getattr(w, attr, None)
        if candidate is not None:
            managed_owners.append(candidate)
    if owner in managed_owners:
        return True
    with contextlib.suppress(Exception):
        parent = thread.parent()
        if parent in managed_owners:
            return True
    return False


def _thread_running_state(thread):
    with contextlib.suppress(RuntimeError, AttributeError, TypeError):
        return thread.isRunning()
    return None


def _iter_shutdown_threads(w):
    seen = set()
    seen_owners = set()

    def emit(thread, owner=None, source=None):
        if isinstance(thread, QThread) and id(thread) not in seen:
            seen.add(id(thread))
            return thread, owner, source
        return None

    def append_owner(owners, owner):
        if owner is None or id(owner) in seen_owners:
            return
        seen_owners.add(id(owner))
        owners.append(owner)

    owners = []
    append_owner(owners, w)
    with contextlib.suppress(Exception):
        for child in w.findChildren(QObject):
            append_owner(owners, child)
    for attr in _THREAD_OWNER_ATTRS:
        with contextlib.suppress(Exception):
            append_owner(owners, getattr(w, attr, None))
    for owner in owners:
        if owner is None:
            continue
        if payload := emit(owner, owner=owner, source="<owner>"):
            yield payload
        for attr in _THREAD_ATTRS:
            if payload := emit(getattr(owner, attr, None), owner=owner, source=attr):
                yield payload
        for attr in _THREAD_CONTAINER_ATTRS:
            container = getattr(owner, attr, None)
            values = container.values() if isinstance(container, Mapping) else container
            if not values or not isinstance(values, Iterable):
                continue
            for candidate in values:
                if payload := emit(candidate, owner=owner, source=attr):
                    yield payload


def perform_close_cleanup(w):
    """Perform cleanup during closeEvent. `w` is the AppWindow instance."""
    try:
        w.customization_service.stop_background_music()
        if getattr(w, "plugin_runtime_service", None):
            w.plugin_runtime_service.execute_hook("app_shutdown")
        if getattr(w, "discord_rich_presence_service", None):
            w.discord_rich_presence_service.shutdown()
        if getattr(w, "session_manager", None):
            w.session_manager.stop()
        if getattr(w, "search_display", None) and w.search_display:
            with contextlib.suppress(Exception):
                w.search_display.cleanup()
        for thread, owner, source in _iter_shutdown_threads(w):
            if _is_managed_shutdown_thread(w, thread, owner):
                logger.debug(
                    "Cleanup skipping managed thread source=%s owner=%s object=%r",
                    source,
                    type(owner).__name__ if owner is not None else None,
                    thread,
                )
                continue
            logger.debug(
                "Cleanup stopping thread source=%s owner=%s running=%s object=%r",
                source,
                type(owner).__name__ if owner is not None else None,
                _thread_running_state(thread),
                thread,
            )
            w._safe_set_parent_none(thread)
            safe_stop_thread(thread, timeout=THREAD_WAIT_TIMEOUT, blocking=True)
            logger.debug(
                "Cleanup stopped thread source=%s owner=%s running=%s object=%r",
                source,
                type(owner).__name__ if owner is not None else None,
                _thread_running_state(thread),
                thread,
            )
        pool = QThreadPool.globalInstance()
        if pool is not None:
            pool.clear()
            with contextlib.suppress(Exception):
                pool.waitForDone(THREAD_WAIT_TIMEOUT)
        w.game_launcher._cleanup_direct_launch_files()
        if hasattr(w.game_launcher, "mod_patcher"):
            w.game_launcher.mod_patcher.cleanup_processes_and_temp_files()
        try:
            import psutil

            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            for child in children:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.terminate()
            terminated_children, alive_children = psutil.wait_procs(children, timeout=1)
            if terminated_children:
                logger.debug(
                    "Cleanup terminated %s child process(es) gracefully",
                    len(terminated_children),
                )
            for proc in alive_children:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    proc.kill()
        except Exception as e:
            logger.debug(f"Error cleaning up child processes: {e}")
        if getattr(w, "main_tab_widget", None):
            w.app_state.local_config["last_active_tab"] = (
                w.main_tab_widget.currentIndex()
            )
            w.settings_service.write_local_config()
        w.settings_service.save_window_geometry(w)
        QApplication.processEvents()
        w.hide()
    except Exception as e:
        logger.error(f"closeEvent: error during cleanup: {e}", exc_info=True)
