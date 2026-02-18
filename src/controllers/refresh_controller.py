import logging
from services.localization_service import localization_service, tr
from workers.fetch_mods_worker import FetchModsThread
from config.constants import UI_COLORS
from services.game_detection_service import is_game_running
from ui.utils.ui_utils import safe_stop_thread
from adapters.gamebanana_cache import GameBananaMetadataCache
from utils.mod_utils import get_mod_key


class RefreshController:

    def __init__(self, app_state, feedback_service, mod_service, used_mods_service, game_launch_controller, update_checker, settings_service=None, app_window=None):
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.used_mods_service = used_mods_service
        self.game_launch_controller = game_launch_controller
        self.update_checker = update_checker
        self.settings_service = settings_service
        self.app_window = app_window
        self.fetch_thread = None
        self.details_thread = None
        self.metadata_thread = None
        self._current_metadata_batch = []

    def cleanup(self):
        self._stop_fetch_thread()

    def _cleanup_thread_later(self, thread) -> None:
        try:
            if thread.isFinished():
                thread.deleteLater()
            else:
                thread.finished.connect(lambda: thread.deleteLater())
        except (RuntimeError, TypeError, AttributeError):
            pass

    def _stop_worker_thread(self, thread, *, disconnect_signals=None, check_running=False, error_label='thread') -> None:
        try:
            if disconnect_signals:
                for signal in disconnect_signals:
                    if signal is None:
                        continue
                    try:
                        signal.disconnect()
                    except (TypeError, RuntimeError, AttributeError):
                        pass
            try:
                if hasattr(thread, 'cancel'):
                    thread.cancel()
            except (RuntimeError, AttributeError):
                pass
            try:
                if not check_running or thread.isRunning():
                    safe_stop_thread(thread, timeout=2000, blocking=True)
            except (RuntimeError, AttributeError):
                pass
            self._cleanup_thread_later(thread)
        except Exception as e:
            logging.debug(f'RefreshController: Error stopping {error_label} (thread may be deleted): {e}')

    def refresh_mods_list(self, is_initial=False, language_combo=None, localization_callback=None, on_fetch_finished_kwargs=None):
        try:
            if hasattr(self.app_state, '_scan_blocked') and self.app_state._scan_blocked:
                return
            if language_combo is not None:
                current_lang_code = localization_service.get_current_language()
                localization_service.rescan_languages()
                language_combo.blockSignals(True)
                try:
                    language_combo.clear()
                    for code, name in localization_service.get_available_languages().items():
                        language_combo.addItem(name, code)
                    index = language_combo.findData(current_lang_code)
                    if index != -1:
                        language_combo.setCurrentIndex(index)
                finally:
                    language_combo.blockSignals(False)
            if not is_initial and localization_callback:
                localization_callback()
            if is_game_running():
                self.feedback_service.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
                return
            self._stop_fetch_thread()
            try:
                if self.fetch_thread:
                    try:
                        if self.fetch_thread.isRunning():
                            logging.warning('RefreshController: Previous fetch thread still running, ignoring new fetch')
                            return
                    except (RuntimeError, AttributeError):
                        self.fetch_thread = None
            except Exception as e:
                logging.debug(f'RefreshController: Error checking fetch thread: {e}')
                self.fetch_thread = None
            self.update_checker.check_for_updates()

            class FetchContext:

                def __init__(self, app_state, mod_service, settings_service):
                    self.app_state = app_state
                    self.mod_service = mod_service
                    self.settings_service = settings_service
            fetch_context = FetchContext(self.app_state, self.mod_service, self.settings_service)
            self.fetch_thread = FetchModsThread(fetch_context, force_update=True, parent=None)
            self.fetch_thread.status.connect(self.feedback_service.update_status)
            finished_kwargs = on_fetch_finished_kwargs or {}
            self.fetch_thread.result.connect(lambda success: self._on_fetch_finished(success, localization_callback=localization_callback, **finished_kwargs))
            self.fetch_thread.start()
        except Exception as e:
            error_msg = f'Failed to refresh mods list: {e}'
            logging.error(f'RefreshController.refresh_mods_list: {error_msg}', exc_info=True)
            self.feedback_service.update_status(f"{tr('errors.update_list_failed')}: {str(e)}", UI_COLORS['status_error'])

    def _stop_fetch_thread(self):
        if self.fetch_thread:
            fetch_thread = self.fetch_thread
            self.fetch_thread = None
            self._stop_worker_thread(fetch_thread, error_label='fetch thread')
        if self.details_thread:
            details_thread = self.details_thread
            self.details_thread = None
            self._stop_worker_thread(details_thread, disconnect_signals=[getattr(details_thread, 'mod_updated', None), getattr(details_thread, 'finished', None), getattr(details_thread, 'progress', None)], check_running=True, error_label='details thread')
        if self.metadata_thread:
            metadata_thread = self.metadata_thread
            self.metadata_thread = None
            self._stop_worker_thread(metadata_thread, disconnect_signals=[getattr(metadata_thread, 'mod_updated', None), getattr(metadata_thread, 'finished', None), getattr(metadata_thread, 'progress', None)], check_running=True, error_label='metadata thread')

    def _on_fetch_finished(self, success: bool, localization_callback=None, update_filtered_mods_callback=None, update_installed_mods_callback=None, update_action_button_callback=None, update_plugin_tabs_callback=None, mods_loaded_signal=None, fetch_thread=None):
        if not hasattr(self, '_fetch_finished_in_progress'):
            self._fetch_finished_in_progress = False
        if self._fetch_finished_in_progress:
            logging.debug('RefreshController: _on_fetch_finished already in progress, skipping')
            return
        self._fetch_finished_in_progress = True
        try:
            self.mod_service.invalidate_mods_cache()
            self.mod_service.load_local_mods()
            downloads_restored = False
            if hasattr(self.app_state, 'cache_dir') and self.app_state.cache_dir and hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                try:
                    metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
                    for mod in self.app_state.all_mods:
                        key = get_mod_key(mod)
                        if not key or not key.startswith('gb_'):
                            continue
                        mod_id = key.replace('gb_', '', 1)
                        if not metadata_cache.is_valid(mod_id):
                            continue
                        downloads = metadata_cache.get_field(mod_id, 'downloads')
                        if downloads is not None and downloads != (getattr(mod, 'downloads', 0) or 0):
                            mod.downloads = downloads
                            downloads_restored = True
                        for attr, field in [('tagline', 'tagline'), ('full_description', 'full_description'), ('screenshots_url', 'screenshots'), ('gamebanana_category', 'category')]:
                            val = metadata_cache.get_field(mod_id, field)
                            if val:
                                setattr(mod, attr, val)
                        mod.has_full_metadata = True
                except Exception as e:
                    logging.warning(f'RefreshController: Error restoring metadata from cache: {e}', exc_info=True)
            if not self.app_state.mods_loaded:
                self.app_state.mods_loaded = True
                if mods_loaded_signal:
                    mods_loaded_signal.emit()
            if update_filtered_mods_callback:
                try:
                    update_filtered_mods_callback()
                except Exception as e:
                    logging.error(f'RefreshController: Error in update_filtered_mods_callback: {e}', exc_info=True)
            elif downloads_restored:
                try:
                    if self.app_window and hasattr(self.app_window, 'search_display'):
                        self.app_window.search_display.update_filtered_mods(preserve_page=False)
                except Exception as e:
                    logging.error(f'RefreshController: Error re-sorting after cache restore: {e}', exc_info=True)
            if update_installed_mods_callback:
                update_installed_mods_callback()
            self.game_launch_controller.refresh_mods_in_use()
            if update_action_button_callback:
                update_action_button_callback()
            if success:
                self.feedback_service.update_status(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.app_state.all_mods else tr('ui.network_update_failed')
                self.feedback_service.update_status(fallback_msg, UI_COLORS['status_error'])
            self.used_mods_service.load_used_mods_state()
        except Exception as e:
            error_msg = f'Error processing mod list: {e}'
            logging.error(f'RefreshController._on_fetch_finished: {error_msg}', exc_info=True)
            self.feedback_service.update_status(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])
        finally:
            self._fetch_finished_in_progress = False
            fetch_thread_to_cleanup = fetch_thread if fetch_thread else self.fetch_thread
            if fetch_thread_to_cleanup:
                self._cleanup_thread_later(fetch_thread_to_cleanup)
            if update_plugin_tabs_callback:
                update_plugin_tabs_callback()
            self._start_metadata_loading()
            self._validate_metadata_cache()

    def _validate_metadata_cache(self):
        try:
            if not hasattr(self.app_state, 'cache_dir') or not self.app_state.cache_dir:
                return
            metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
            stale_count = metadata_cache.clear_stale()
            if stale_count > 0:
                logging.info(f'RefreshController: Cleared {stale_count} stale metadata cache entries')
        except Exception as e:
            logging.warning(f'RefreshController: Error validating metadata cache: {e}', exc_info=True)

    def _start_metadata_loading(self):
        try:
            if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata') or not self.app_state.gamebanana_mods_needing_metadata:
                return
            if self.metadata_thread:
                try:
                    if self.metadata_thread.isRunning():
                        logging.debug(f'RefreshController: Metadata thread already running, {len(self.app_state.gamebanana_mods_needing_metadata)} mods queued')
                        return
                except (RuntimeError, AttributeError):
                    pass
                self._stop_worker_thread(self.metadata_thread, error_label='old metadata thread')
                self.metadata_thread = None
            if not hasattr(self.app_state, 'cache_dir') or not self.app_state.cache_dir:
                return
            metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
            all_mod_ids = list(self.app_state.gamebanana_mods_needing_metadata)
            if not all_mod_ids:
                return
            MAX_METADATA_BATCH_SIZE = 20
            mod_ids_to_load = all_mod_ids[:MAX_METADATA_BATCH_SIZE]
            self._current_metadata_batch = list(mod_ids_to_load)
            self.app_state.gamebanana_mods_needing_metadata = all_mod_ids[MAX_METADATA_BATCH_SIZE:]
            logging.info(f'RefreshController: Loading metadata for {len(mod_ids_to_load)} mods ({len(self.app_state.gamebanana_mods_needing_metadata)} remaining)')
            from workers.gamebanana.load_metadata_worker import LoadGameBananaMetadataThread
            self.metadata_thread = LoadGameBananaMetadataThread(mod_ids_to_load, metadata_cache, parent=self.app_window, app_state=self.app_state)
            if self.app_window and hasattr(self.app_window, 'search_display'):
                self.metadata_thread.mod_updated.connect(self.app_window.search_display._metadata_handler.on_metadata_updated)
            self.metadata_thread.finished.connect(self._on_metadata_loading_finished)
            self.metadata_thread.start()
        except Exception as e:
            logging.error(f'RefreshController: Failed to start metadata loading: {e}', exc_info=True)

    def _on_metadata_loading_finished(self):
        try:
            metadata_thread = self.metadata_thread
            self.metadata_thread = None
            if metadata_thread:
                self._cleanup_thread_later(metadata_thread)
            was_cancelled = metadata_thread and getattr(metadata_thread, '_cancelled', False)
            if self._current_metadata_batch and was_cancelled:
                if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata'):
                    self.app_state.gamebanana_mods_needing_metadata = []
                existing = set(self.app_state.gamebanana_mods_needing_metadata)
                self.app_state.gamebanana_mods_needing_metadata = list(existing | set(self._current_metadata_batch))
            self._current_metadata_batch = []
            if self.app_window and hasattr(self.app_window, 'search_display') and self.app_window.search_display:
                self.app_window.search_display.update_filtered_mods(preserve_page=True)
            remaining = getattr(self.app_state, 'gamebanana_mods_needing_metadata', [])
            if remaining:
                self._start_metadata_loading()
        except Exception as e:
            logging.warning(f'RefreshController: Error in _on_metadata_loading_finished: {e}', exc_info=True)
