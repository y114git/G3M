"""Close event cleanup logic extracted from AppWindow."""
import os
import logging
from PyQt6.QtWidgets import QApplication
from ui.utils.ui_utils import safe_stop_thread
from config.constants import THREAD_WAIT_TIMEOUT


def perform_close_cleanup(w):
    """Perform cleanup during closeEvent. `w` is the AppWindow instance."""
    try:
        w.customization_service.stop_background_music()
        w._online_timer.stop()
        threads_to_stop = []
        if w.game_launcher.monitor_thread:
            threads_to_stop.append(w.game_launcher.monitor_thread)
        for attr in ('install_thread', 'full_install_thread', 'current_install_thread', 'changelog_thread'):
            thread = getattr(w, attr, None)
            if thread:
                threads_to_stop.append(thread)
        for attr in ('fetch_thread', 'details_thread', 'metadata_thread'):
            thread = getattr(w.refresh_controller, attr, None)
            if thread:
                threads_to_stop.append(thread)
        bg_loader = getattr(w, '_bg_loader', None)
        if bg_loader:
            threads_to_stop.append(bg_loader)
        for thread in threads_to_stop:
            w._safe_set_parent_none(thread)
            safe_stop_thread(thread, timeout=THREAD_WAIT_TIMEOUT, blocking=False)
        if w.presence_thread:
            w._safe_set_parent_none(w.presence_thread)
            safe_stop_thread(w.presence_thread, timeout=2000, blocking=False)
        w.game_launcher._cleanup_direct_launch_files()
        if hasattr(w.game_launcher, 'mod_patcher'):
            w.game_launcher.mod_patcher.cleanup_processes_and_temp_files()
        try:
            import psutil
            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            gone, alive = psutil.wait_procs(children, timeout=1)
            for proc in alive:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logging.debug(f'Error cleaning up child processes: {e}')
        if hasattr(w, 'main_tab_widget'):
            w.app_state.local_config['last_active_tab'] = w.main_tab_widget.currentIndex()
            w.settings_service.write_local_config()
        w.settings_service.save_window_geometry(w)
        QApplication.processEvents()
        w.hide()
    except Exception as e:
        logging.error(f'closeEvent: error during cleanup: {e}', exc_info=True)
