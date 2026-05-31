"""Close event cleanup logic extracted from AppWindow."""

import contextlib
import logging
import os
from collections.abc import Mapping

from PyQt6.QtCore import QObject, QThread, QThreadPool
from PyQt6.QtWidgets import QApplication

from config.config import THREAD_WAIT_TIMEOUT
from ui.utils.ui_utils import safe_stop_thread

_THREAD_ATTRS = (
    "_compatibility_thread",
    "_network_init_thread",
    "_mod_scan_thread",
    "_bg_loader",
    "_catalog_worker",
    "_worker",
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
_THREAD_CONTAINER_ATTRS = ("_workers", "_load_more_threads")


def _iter_shutdown_threads(w):
    seen = set()

    def emit(thread):
        if isinstance(thread, QThread) and id(thread) not in seen:
            seen.add(id(thread))
            return thread
        return None

    owners = [w]
    with contextlib.suppress(Exception):
        owners.extend(w.findChildren(QObject))
    for owner in owners:
        if owner is None:
            continue
        if thread := emit(owner):
            yield thread
        for attr in _THREAD_ATTRS:
            if thread := emit(getattr(owner, attr, None)):
                yield thread
        for attr in _THREAD_CONTAINER_ATTRS:
            container = getattr(owner, attr, None)
            values = container.values() if isinstance(container, Mapping) else container
            if not values:
                continue
            for candidate in values:
                if thread := emit(candidate):
                    yield thread


def perform_close_cleanup(w):
    """Perform cleanup during closeEvent. `w` is the AppWindow instance."""
    try:
        w.customization_service.stop_background_music()
        if getattr(w, "plugin_runtime_service", None):
            w.plugin_runtime_service.execute_hook("app_shutdown")
        if getattr(w, "session_manager", None):
            w.session_manager.stop()
        if getattr(w, "search_display", None) and w.search_display:
            with contextlib.suppress(Exception):
                w.search_display.cleanup()
        for thread in _iter_shutdown_threads(w):
            w._safe_set_parent_none(thread)
            safe_stop_thread(thread, timeout=THREAD_WAIT_TIMEOUT, blocking=True)
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
                logging.debug(
                    "Cleanup terminated %s child process(es) gracefully",
                    len(terminated_children),
                )
            for proc in alive_children:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    proc.kill()
        except Exception as e:
            logging.debug(f"Error cleaning up child processes: {e}")
        if getattr(w, "main_tab_widget", None):
            w.app_state.local_config["last_active_tab"] = (
                w.main_tab_widget.currentIndex()
            )
            w.settings_service.write_local_config()
        w.settings_service.save_window_geometry(w)
        QApplication.processEvents()
        w.hide()
    except Exception as e:
        logging.error(f"closeEvent: error during cleanup: {e}", exc_info=True)
