"""Close event cleanup logic extracted from AppWindow."""

import contextlib
import logging
import os

from PyQt6.QtWidgets import QApplication

from config.config import THREAD_WAIT_TIMEOUT
from ui.utils.ui_utils import safe_stop_thread


def perform_close_cleanup(w):
    """Perform cleanup during closeEvent. `w` is the AppWindow instance."""
    try:
        w.customization_service.stop_background_music()
        if hasattr(w, "plugin_runtime_service"):
            w.plugin_runtime_service.execute_hook("app_shutdown")
        if hasattr(w, "session_manager"):
            w.session_manager.stop()
        threads_to_stop = []
        for attr in ("_network_init_thread", "_mod_scan_thread"):
            thread = getattr(w, attr, None)
            if thread:
                threads_to_stop.append(thread)
        if w.game_launcher.monitor_thread:
            threads_to_stop.append(w.game_launcher.monitor_thread)
        for attr in ("fetch_thread", "details_thread"):
            thread = getattr(w.refresh_controller, attr, None)
            if thread:
                threads_to_stop.append(thread)
        bg_loader = getattr(w, "_bg_loader", None)
        if bg_loader:
            threads_to_stop.append(bg_loader)
        for thread in threads_to_stop:
            w._safe_set_parent_none(thread)
            safe_stop_thread(thread, timeout=THREAD_WAIT_TIMEOUT, blocking=True)
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
            _gone, alive = psutil.wait_procs(children, timeout=1)
            for proc in alive:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    proc.kill()
        except Exception as e:
            logging.debug(f"Error cleaning up child processes: {e}")
        if hasattr(w, "main_tab_widget"):
            w.app_state.local_config["last_active_tab"] = (
                w.main_tab_widget.currentIndex()
            )
            w.settings_service.write_local_config()
        w.settings_service.save_window_geometry(w)
        QApplication.processEvents()
        w.hide()
    except Exception as e:
        logging.error(f"closeEvent: error during cleanup: {e}", exc_info=True)
