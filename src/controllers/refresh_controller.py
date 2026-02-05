import logging
from PyQt6.QtCore import QTimer
from services.localization_service import localization_service, tr
from workers.fetch_mods_worker import FetchModsThread
from config.constants import UI_COLORS
from services.game_detection_service import is_game_running
from ui.utils.ui_utils import safe_stop_thread


class RefreshController:

    def __init__(self, app_state, feedback_service, mod_service, slot_service, game_launch_controller, update_checker, settings_service=None, app_window=None):
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.slot_service = slot_service
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

                def cleanup():
                    try:
                        if thread.isFinished():
                            thread.deleteLater()
                    except (RuntimeError, AttributeError):
                        pass
                try:
                    thread.finished.connect(cleanup)
                except (TypeError, RuntimeError, AttributeError):
                    pass
        except (RuntimeError, AttributeError):
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

    def refresh_mods_list(self, is_initial=False, language_combo=None, retranslate_callback=None, on_fetch_finished_kwargs=None):
        try:
            if hasattr(self.app_state, '_scan_blocked') and self.app_state._scan_blocked:
                if not is_initial:
                    QTimer.singleShot(500, lambda: self.refresh_mods_list(is_initial=is_initial, language_combo=language_combo, retranslate_callback=retranslate_callback, on_fetch_finished_kwargs=on_fetch_finished_kwargs))
                return
            if hasattr(self.app_state, 'cache_dir') and self.app_state.cache_dir:
                try:
                    from adapters.gamebanana_cache import GameBananaMetadataCache
                    metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
                    if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                        for mod in self.app_state.all_mods:
                            key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                            if key and key.startswith('gb_'):
                                mod_id = key.replace('gb_', '', 1)
                                if not metadata_cache.is_valid(mod_id):
                                    downloads = getattr(mod, 'downloads', None)
                                    tagline = getattr(mod, 'tagline', None)
                                    full_description = getattr(mod, 'full_description', None)
                                    screenshots = getattr(mod, 'screenshots_url', None) if hasattr(mod, 'screenshots_url') else None
                                    category = getattr(mod, 'gamebanana_category', None)
                                    if downloads is not None or tagline or full_description or screenshots or category:
                                        metadata_cache.set(mod_id, downloads=downloads, tagline=tagline, full_description=full_description, screenshots=screenshots, category=category)
                                        logging.debug(f'RefreshController: Saved metadata to cache for mod {mod_id}')
                except Exception as e:
                    logging.warning(f'RefreshController: Error saving metadata to cache: {e}', exc_info=True)
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
            if not is_initial and retranslate_callback:
                retranslate_callback()
            if is_game_running():
                self.feedback_service.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
                return
            self._stop_fetch_thread()
            try:
                if self.fetch_thread:
                    try:
                        if self.fetch_thread.isRunning():
                            logging.warning('RefreshController: Previous fetch thread still running, deferring new fetch')
                            QTimer.singleShot(500, lambda: self.refresh_mods_list(is_initial=is_initial, language_combo=language_combo, retranslate_callback=retranslate_callback, on_fetch_finished_kwargs=on_fetch_finished_kwargs))
                            return
                    except (RuntimeError, AttributeError):
                        self.fetch_thread = None
            except Exception as e:
                logging.debug(f'RefreshController: Error checking fetch thread: {e}')
                self.fetch_thread = None
            QTimer.singleShot(3000, self.update_checker.check_for_updates)

            class FetchContext:

                def __init__(self, app_state, mod_service, settings_service):
                    self.app_state = app_state
                    self.mod_service = mod_service
                    self.settings_service = settings_service
            fetch_context = FetchContext(self.app_state, self.mod_service, self.settings_service)
            self.fetch_thread = FetchModsThread(fetch_context, force_update=True, parent=None)
            self.fetch_thread.status.connect(self.feedback_service.update_status)
            finished_kwargs = on_fetch_finished_kwargs or {}
            self.fetch_thread.result.connect(lambda success: self._on_fetch_finished(success, retranslate_callback=retranslate_callback, **finished_kwargs))
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

    def _on_fetch_finished(self, success: bool, retranslate_callback=None, update_filtered_mods_callback=None, update_installed_mods_callback=None, update_action_button_callback=None, update_plugin_tabs_callback=None, mods_loaded_signal=None, fetch_thread=None):
        if not hasattr(self, '_fetch_finished_in_progress'):
            self._fetch_finished_in_progress = False
        if self._fetch_finished_in_progress:
            logging.debug('RefreshController: _on_fetch_finished already in progress, skipping')
            return
        self._fetch_finished_in_progress = True
        try:
            self.mod_service.invalidate_mods_cache()
            QTimer.singleShot(0, self.mod_service.load_local_mods)
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                installed_gb_mods = []
                for mod in self.app_state.all_mods:
                    key = mod.key
                    if key and key.startswith('gb_'):
                        mod_id = key.replace('gb_', '', 1)
                        installed_gb_mods.append(f'{mod.name} (key={key}, id={mod_id})')
                logging.info(f'RefreshController: Found {len(installed_gb_mods)} GameBanana mods in all_mods after load_local_mods')
                for mod_info in installed_gb_mods[:10]:
                    logging.debug(f'RefreshController: GameBanana mod in all_mods: {mod_info}')
            if hasattr(self.app_state, 'cache_dir') and self.app_state.cache_dir:
                try:
                    from adapters.gamebanana_cache import GameBananaMetadataCache
                    metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
                    restored_count = 0
                    downloads_restored = False
                    if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                        for mod in self.app_state.all_mods:
                            key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                            if key and key.startswith('gb_'):
                                mod_id = key.replace('gb_', '', 1)
                                if metadata_cache.is_valid(mod_id):
                                    downloads = metadata_cache.get_field(mod_id, 'downloads')
                                    tagline = metadata_cache.get_field(mod_id, 'tagline')
                                    full_description = metadata_cache.get_field(mod_id, 'full_description')
                                    screenshots = metadata_cache.get_field(mod_id, 'screenshots')
                                    category = metadata_cache.get_field(mod_id, 'category')
                                    if downloads is not None:
                                        old_downloads = getattr(mod, 'downloads', 0) or 0
                                        mod.downloads = downloads
                                        if old_downloads != downloads:
                                            downloads_restored = True
                                    if tagline:
                                        mod.tagline = tagline
                                    if full_description:
                                        mod.full_description = full_description
                                    if screenshots:
                                        mod.screenshots_url = screenshots
                                    if category:
                                        if not hasattr(mod, 'gamebanana_category') or mod.gamebanana_category != category:
                                            mod.gamebanana_category = category
                                            logging.info(f'RefreshController: Restored category for mod {mod_id}: {category}')
                                    try:
                                        key = getattr(mod, 'key', None) or getattr(mod, 'mod_key', None)
                                        if key and key.startswith('gb_'):
                                            mod.has_full_metadata = True
                                    except Exception:
                                        pass
                                    restored_count += 1
                                    logging.debug(f'RefreshController: Restored metadata from cache for mod {mod_id} - downloads: {downloads}, has_desc: {bool(full_description)}, has_screenshots: {bool(screenshots)}, has_tagline: {bool(tagline)}, category: {category}')
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
            self.slot_service.load_used_mods_state()
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
            from adapters.gamebanana_cache import GameBananaMetadataCache
            metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
            stale_count = metadata_cache.clear_stale()
            if stale_count > 0:
                logging.info(f'RefreshController: Cleared {stale_count} stale metadata cache entries')
        except Exception as e:
            logging.warning(f'RefreshController: Error validating metadata cache: {e}', exc_info=True)

    def _start_metadata_loading(self):
        try:
            if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata') or not self.app_state.gamebanana_mods_needing_metadata:
                logging.debug('RefreshController: No mods need metadata loading')
                return
            metadata_thread_old = None
            thread_is_running = False
            try:
                if self.metadata_thread:
                    try:
                        if self.metadata_thread.isRunning():
                            remaining_count = len(self.app_state.gamebanana_mods_needing_metadata) if hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata else 0
                            logging.debug(f'RefreshController: Metadata thread is already running, {remaining_count} mods will be loaded after current batch completes')
                            thread_is_running = True
                            return
                        metadata_thread_old = self.metadata_thread
                    except (RuntimeError, AttributeError):
                        pass
            except Exception as e:
                logging.warning(f'RefreshController: Error checking metadata thread: {e}')
            if not thread_is_running:
                self.metadata_thread = None
            if metadata_thread_old:
                try:
                    try:
                        if hasattr(metadata_thread_old, 'cancel'):
                            metadata_thread_old.cancel()
                        if metadata_thread_old.isRunning():
                            safe_stop_thread(metadata_thread_old, timeout=2000, blocking=True)
                        self._cleanup_thread_later(metadata_thread_old)
                    except (RuntimeError, AttributeError):
                        pass
                except Exception as e:
                    logging.warning(f'RefreshController: Error cleaning up old metadata thread: {e}')
            try:
                from adapters.gamebanana_cache import GameBananaMetadataCache
                if not hasattr(self.app_state, 'cache_dir') or not self.app_state.cache_dir:
                    logging.warning('RefreshController: cache_dir not available, cannot load metadata')
                    return
                metadata_cache = GameBananaMetadataCache(self.app_state.cache_dir)
                all_mod_ids = list(self.app_state.gamebanana_mods_needing_metadata)
                if not all_mod_ids:
                    logging.debug('RefreshController: No mod IDs to load metadata for')
                    return
                MAX_METADATA_BATCH_SIZE = 20
                mod_ids_to_load = all_mod_ids[:MAX_METADATA_BATCH_SIZE]
                remaining_mod_ids = all_mod_ids[MAX_METADATA_BATCH_SIZE:]
                self._current_metadata_batch = list(mod_ids_to_load)
                self.app_state.gamebanana_mods_needing_metadata = remaining_mod_ids
                logging.info(f'RefreshController: Starting metadata loading for batch of {len(mod_ids_to_load)} mods ({len(remaining_mod_ids)} remaining in queue, {len(mod_ids_to_load)} will be processed)')
                from workers.gamebanana.load_metadata_worker import LoadGameBananaMetadataThread
                self.metadata_thread = LoadGameBananaMetadataThread(mod_ids_to_load, metadata_cache, parent=self.app_window, app_state=self.app_state)
                if self.app_window and hasattr(self.app_window, 'search_display'):
                    self.metadata_thread.mod_updated.connect(self.app_window.search_display.on_metadata_updated)
                self.metadata_thread.finished.connect(self._on_metadata_loading_finished)
                self.metadata_thread.start()
                logging.info(f'RefreshController: Metadata loading thread started for {len(mod_ids_to_load)} mods')
            except Exception as e:
                logging.error(f'RefreshController: Failed to start metadata loading: {e}', exc_info=True)
        except Exception as e:
            logging.error(f'RefreshController: Error in _start_metadata_loading: {e}', exc_info=True)

    def _on_metadata_loading_finished(self):
        try:
            logging.info('RefreshController: Metadata loading finished')
            metadata_thread = self.metadata_thread
            self.metadata_thread = None
            if metadata_thread:
                self._cleanup_thread_later(metadata_thread)
            if hasattr(self, '_current_metadata_batch') and self._current_metadata_batch:
                failed_mods = self._current_metadata_batch
                if failed_mods:
                    logging.info(f'RefreshController: {len(failed_mods)} mod(s) in current batch failed to load, re-adding to queue for retry')
                    if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata'):
                        self.app_state.gamebanana_mods_needing_metadata = []
                    existing = set(self.app_state.gamebanana_mods_needing_metadata)
                    failed_set = set(failed_mods)
                    self.app_state.gamebanana_mods_needing_metadata = list(existing | failed_set)
                self._current_metadata_batch = []
            if self.app_window and hasattr(self.app_window, 'search_display') and self.app_window.search_display:

                def ensure_sorted():
                    try:
                        app_window = self.app_window
                        if app_window and hasattr(app_window, 'search_display') and app_window.search_display:
                            app_window.search_display.update_filtered_mods(preserve_page=True)
                    except Exception as e:
                        logging.error(f'RefreshController: Error ensuring sort after metadata load: {e}', exc_info=True)
                ensure_sorted()
            has_more_mods = False
            remaining_count = 0
            try:
                if hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata:
                    remaining_count = len(self.app_state.gamebanana_mods_needing_metadata)
                    has_more_mods = remaining_count > 0
            except Exception as e:
                logging.warning(f'RefreshController: Error checking remaining mods: {e}')
            if has_more_mods:
                logging.info(f'RefreshController: Found {remaining_count} more mods needing metadata, starting another batch in 500ms')
                QTimer.singleShot(500, self._start_metadata_loading)
            else:
                logging.info('RefreshController: All metadata loaded, no more mods to process')
        except Exception as e:
            logging.warning(f'RefreshController: Error in _on_metadata_loading_finished: {e}', exc_info=True)
