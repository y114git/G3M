"""Handler for GameBanana sort change logic extracted from AppWindow."""
import logging
from PyQt6.QtCore import QTimer
from utils.mod_utils import get_mod_key


def handle_gamebanana_sort_changed(w, index: int):
    """Handle GameBanana sort combo change. `w` is the AppWindow instance."""
    try:
        if not hasattr(w, 'gb_sort_combo'):
            return
        new_sort = w.gb_sort_combo.currentData()
        if not new_sort:
            return
        old_sort = getattr(w.app_state, 'gamebanana_sort', 'default')
        if old_sort == new_sort:
            return
        if hasattr(w, '_gamebanana_sort_timer') and w._gamebanana_sort_timer:
            try:
                w._gamebanana_sort_timer.stop()
                w._gamebanana_sort_timer.deleteLater()
            except (RuntimeError, ValueError):
                pass
            w._gamebanana_sort_timer = None
        w._gamebanana_sort_change_in_progress = True
        w.app_state.gamebanana_sort = new_sort
        w.app_state.gamebanana_loaded_pages.clear()
        if hasattr(w, 'search_display'):
            w.search_display._update_display_in_progress = False
            try:
                w.search_display._update_display_debounce.cancel()
            except Exception:
                pass
            w.search_display._cleanup_details_threads()
            for thread in list(w.search_display._load_more_threads):
                if thread and thread.isRunning() and hasattr(thread, 'cancel'):
                    thread.cancel()
            w.search_display._load_more_threads.clear()
        if hasattr(w.app_state, 'all_mods') and w.app_state.all_mods:
            w.app_state.all_mods = [mod for mod in w.app_state.all_mods if not ((k := get_mod_key(mod)) and k.startswith('gb_'))]
        w.app_state.current_page = 1
        if hasattr(w.app_state, 'filtered_mods'):
            w.app_state.filtered_mods = []
        try:
            if hasattr(w, 'refresh_controller'):
                if hasattr(w.refresh_controller, 'fetch_thread') and w.refresh_controller.fetch_thread and w.refresh_controller.fetch_thread.isRunning():
                    w.refresh_controller._stop_fetch_thread()
                if hasattr(w.refresh_controller, 'metadata_thread') and w.refresh_controller.metadata_thread:
                    try:
                        if hasattr(w.refresh_controller.metadata_thread, 'cancel'):
                            w.refresh_controller.metadata_thread.cancel()
                        if w.refresh_controller.metadata_thread.isRunning():
                            try:
                                w.refresh_controller.metadata_thread.mod_updated.disconnect()
                                w.refresh_controller.metadata_thread.finished.disconnect()
                            except (TypeError, RuntimeError):
                                pass
                            if w.refresh_controller.metadata_thread.isRunning():
                                logging.debug('AppWindow: Metadata thread still running after sort change, will clean up via finished signal.')
                        w.refresh_controller.metadata_thread.deleteLater()
                        w.refresh_controller.metadata_thread = None
                    except Exception as e:
                        logging.warning(f'AppWindow: Error stopping metadata thread on sort change: {e}')
        except Exception:
            pass

        def _finish_sort_change():
            w._gamebanana_sort_change_in_progress = False

        def _async_sort_update():
            try:
                w.search_display.update_filtered_mods()
                w.app_state.current_page = 1
                QTimer.singleShot(50, lambda: w.search_display.update_display())
            except Exception as e:
                logging.error(f'AppWindow: Error in async_update after sort change: {e}', exc_info=True)
            finally:
                _finish_sort_change()

        def trigger_refresh():
            try:
                if not w._gamebanana_sort_change_in_progress:
                    return
                w.app_state.gamebanana_loading = False
                if not getattr(w.app_state, 'mods_loaded', False):
                    w.app_state.mods_loaded = True
                if hasattr(w, 'refresh_controller'):
                    def update_callback():
                        _finish_sort_change()
                        QTimer.singleShot(0, _async_sort_update)
                    w.refresh_controller.refresh_mods_list(is_initial=False, on_fetch_finished_kwargs={'update_filtered_mods_callback': update_callback})
                elif hasattr(w, 'search_display'):
                    QTimer.singleShot(0, _async_sort_update)
            except Exception as e:
                logging.error(f'AppWindow: Error in trigger_refresh after sort change: {e}', exc_info=True)
                _finish_sort_change()
        w._gamebanana_sort_timer = QTimer()
        w._gamebanana_sort_timer.setSingleShot(True)
        w._gamebanana_sort_timer.timeout.connect(trigger_refresh)
        w._gamebanana_sort_timer.start(300)
    except Exception as e:
        logging.error(f'AppWindow: Error in _on_gamebanana_sort_changed: {e}', exc_info=True)
        if hasattr(w, '_gamebanana_sort_change_in_progress'):
            w._gamebanana_sort_change_in_progress = False
