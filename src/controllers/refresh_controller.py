import logging
from PyQt6.QtCore import QTimer
from managers.localization_manager import localization_manager, tr
from workers.fetch_mods import FetchModsThread
from config.constants import UI_COLORS
from utils.game_utils import is_game_running
from utils.ui_utils import safe_stop_thread


class RefreshController:

    def __init__(self, app_state, feedback_manager, mod_manager, slot_manager, game_launch_controller, update_checker, settings_manager=None, app_window=None):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.slot_manager = slot_manager
        self.game_launch_controller = game_launch_controller
        self.update_checker = update_checker
        self.settings_manager = settings_manager
        self.app_window = app_window
        self.fetch_thread = None
        self.details_thread = None
        self.metadata_thread = None

    def refresh_mods_list(self, is_initial=False, language_combo=None, retranslate_callback=None, on_fetch_finished_kwargs=None):
        try:
            if hasattr(self.app_state, 'config_dir') and self.app_state.config_dir:
                try:
                    from utils.gamebanana_cache import GameBananaMetadataCache
                    metadata_cache = GameBananaMetadataCache(self.app_state.config_dir)
                    if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                        for mod in self.app_state.all_mods:
                            if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod and mod.gamebanana_mod_id:
                                mod_id = str(mod.gamebanana_mod_id)
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
                current_lang_code = localization_manager.get_current_language()
                localization_manager.rescan_languages()
                language_combo.blockSignals(True)
                try:
                    language_combo.clear()
                    for code, name in localization_manager.get_available_languages().items():
                        language_combo.addItem(name, code)
                    index = language_combo.findData(current_lang_code)
                    if index != -1:
                        language_combo.setCurrentIndex(index)
                finally:
                    language_combo.blockSignals(False)
            if not is_initial and retranslate_callback:
                retranslate_callback()
            if is_game_running():
                self.feedback_manager.update_status(tr('status.cant_update_while_running'), UI_COLORS['status_warning'])
                return
            self._stop_fetch_thread()
            QTimer.singleShot(0, self.update_checker.check_for_updates)

            class FetchContext:

                def __init__(self, app_state, mod_manager, settings_manager):
                    self.app_state = app_state
                    self.mod_manager = mod_manager
                    self.settings_manager = settings_manager
            fetch_context = FetchContext(self.app_state, self.mod_manager, self.settings_manager)
            self.fetch_thread = FetchModsThread(fetch_context, force_update=True, parent=None)
            self.fetch_thread.status.connect(self.feedback_manager.update_status)
            finished_kwargs = on_fetch_finished_kwargs or {}
            self.fetch_thread.result.connect(lambda success: self._on_fetch_finished(success, retranslate_callback=retranslate_callback, **finished_kwargs))
            self.fetch_thread.start()
        except Exception as e:
            error_msg = f'Failed to refresh mods list: {e}'
            logging.error(f'RefreshController.refresh_mods_list: {error_msg}', exc_info=True)
            self.feedback_manager.update_status(f"{tr('errors.update_list_failed')}: {str(e)}", UI_COLORS['status_error'])

    def _stop_fetch_thread(self):
        if self.fetch_thread:
            safe_stop_thread(self.fetch_thread)
            if not (self.fetch_thread and self.fetch_thread.isRunning()):
                self.fetch_thread = None
        if self.details_thread:
            try:
                try:
                    self.details_thread.mod_updated.disconnect()
                    self.details_thread.finished.disconnect()
                    self.details_thread.progress.disconnect()
                except (TypeError, RuntimeError):
                    pass
                if hasattr(self.details_thread, 'cancel'):
                    self.details_thread.cancel()
                if self.details_thread.isRunning():
                    safe_stop_thread(self.details_thread, timeout=2000, blocking=False)
                    if self.details_thread.isRunning():
                        logging.debug('RefreshController: Details thread still running, will clean up via finished signal')
                self.details_thread.deleteLater()
            except Exception as e:
                logging.warning(f'RefreshController: Error stopping details thread: {e}')
            finally:
                self.details_thread = None
        if self.metadata_thread:
            try:
                try:
                    self.metadata_thread.mod_updated.disconnect()
                    self.metadata_thread.finished.disconnect()
                    self.metadata_thread.progress.disconnect()
                except (TypeError, RuntimeError):
                    pass
                if hasattr(self.metadata_thread, 'cancel'):
                    self.metadata_thread.cancel()
                if self.metadata_thread.isRunning():
                    safe_stop_thread(self.metadata_thread, timeout=2000, blocking=False)
                    if self.metadata_thread.isRunning():
                        logging.debug('RefreshController: Metadata thread still running, will clean up via finished signal')
                self.metadata_thread.deleteLater()
            except Exception as e:
                logging.warning(f'RefreshController: Error stopping metadata thread: {e}')
            finally:
                self.metadata_thread = None

    def _on_fetch_finished(self, success: bool, retranslate_callback=None, update_filtered_mods_callback=None, update_installed_mods_callback=None, update_action_button_callback=None, update_plugin_tabs_callback=None, mods_loaded_signal=None, fetch_thread=None):
        if not hasattr(self, '_fetch_finished_in_progress'):
            self._fetch_finished_in_progress = False
        if self._fetch_finished_in_progress:
            logging.debug('RefreshController: _on_fetch_finished already in progress, skipping')
            return
        self._fetch_finished_in_progress = True
        try:
            self.mod_manager.invalidate_mods_cache()
            self.mod_manager.load_local_mods()
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                installed_gb_mods = []
                for mod in self.app_state.all_mods:
                    if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod and hasattr(mod, 'gamebanana_mod_id') and mod.gamebanana_mod_id:
                        installed_gb_mods.append(f'{mod.name} (key={mod.key}, id={mod.gamebanana_mod_id})')
                logging.info(f'RefreshController: Found {len(installed_gb_mods)} GameBanana mods in all_mods after load_local_mods')
                for mod_info in installed_gb_mods[:10]:
                    logging.debug(f'RefreshController: GameBanana mod in all_mods: {mod_info}')
            if hasattr(self.app_state, 'config_dir') and self.app_state.config_dir:
                try:
                    from utils.gamebanana_cache import GameBananaMetadataCache
                    metadata_cache = GameBananaMetadataCache(self.app_state.config_dir)
                    restored_count = 0
                    downloads_restored = False
                    if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                        for mod in self.app_state.all_mods:
                            if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod and mod.gamebanana_mod_id:
                                mod_id = str(mod.gamebanana_mod_id)
                                if metadata_cache.is_valid(mod_id):
                                    downloads = metadata_cache.get_downloads(mod_id)
                                    tagline = metadata_cache.get_tagline(mod_id)
                                    full_description = metadata_cache.get_full_description(mod_id)
                                    screenshots = metadata_cache.get_screenshots(mod_id)
                                    category = metadata_cache.get_category(mod_id)
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
                                        if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod:
                                            mod.has_full_metadata = True
                                    except Exception:
                                        pass
                                    restored_count += 1
                                    logging.debug(f'RefreshController: Restored metadata from cache for mod {mod_id} - downloads: {downloads}, has_desc: {bool(full_description)}, has_screenshots: {bool(screenshots)}, has_tagline: {bool(tagline)}, category: {category}')
                except Exception as e:
                    logging.warning(f'RefreshController: Error restoring metadata from cache: {e}', exc_info=True)
            if update_filtered_mods_callback and (not downloads_restored):
                try:
                    update_filtered_mods_callback()
                except Exception as e:
                    logging.error(f'RefreshController: Error in update_filtered_mods_callback: {e}', exc_info=True)
            elif downloads_restored:
                try:
                    if self.app_window and hasattr(self.app_window, 'search_display'):
                        self.app_window.search_display.update_filtered_mods(preserve_page=True)
                except Exception as e:
                    logging.error(f'RefreshController: Error re-sorting after cache restore: {e}', exc_info=True)
            if not self.app_state.mods_loaded:
                self.app_state.mods_loaded = True
                if mods_loaded_signal:
                    mods_loaded_signal.emit()
            if update_installed_mods_callback:
                update_installed_mods_callback()
            self.game_launch_controller.refresh_mods_in_use()
            if update_action_button_callback:
                update_action_button_callback()
            if success:
                self.feedback_manager.update_status(tr('status.mod_list_updated'), UI_COLORS['status_success'])
            else:
                fallback_msg = tr('ui.network_fallback_message') if self.app_state.all_mods else tr('ui.network_update_failed')
                self.feedback_manager.update_status(fallback_msg, UI_COLORS['status_error'])
            self.slot_manager.load_used_mods_state()
        except Exception as e:
            error_msg = f'Error processing mod list: {e}'
            logging.error(f'RefreshController._on_fetch_finished: {error_msg}', exc_info=True)
            self.feedback_manager.update_status(tr('errors.mod_list_processing_error', error=str(e)), UI_COLORS['status_error'])
        finally:
            self._fetch_finished_in_progress = False
            if fetch_thread:
                if fetch_thread.isFinished():
                    fetch_thread.deleteLater()
                else:

                    def cleanup_fetch_thread():
                        try:
                            if fetch_thread and fetch_thread.isFinished():
                                fetch_thread.deleteLater()
                        except Exception:
                            pass
                    fetch_thread.finished.connect(cleanup_fetch_thread)
            if update_plugin_tabs_callback:
                update_plugin_tabs_callback()
            self._start_metadata_loading()
            self._validate_metadata_cache()

    def _validate_metadata_cache(self):
        try:
            if not hasattr(self.app_state, 'config_dir') or not self.app_state.config_dir:
                return
            from utils.gamebanana_cache import GameBananaMetadataCache
            metadata_cache = GameBananaMetadataCache(self.app_state.config_dir)
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
            mod_ids = list(self.app_state.gamebanana_mods_needing_metadata)
            if not mod_ids:
                return
            if self.metadata_thread and self.metadata_thread.isRunning():
                try:
                    logging.debug(f'RefreshController: Metadata thread is already running, {len(mod_ids)} mods will be loaded after current batch completes')
                    return
                except Exception as e:
                    logging.warning(f'RefreshController: Error checking metadata thread: {e}')
            if self.metadata_thread:
                try:
                    if hasattr(self.metadata_thread, 'cancel'):
                        self.metadata_thread.cancel()
                    if self.metadata_thread.isRunning():
                        logging.debug('RefreshController: Metadata thread running, will clean up via finished signal')
                        try:
                            self.metadata_thread.mod_updated.disconnect()
                            self.metadata_thread.finished.disconnect()
                            self.metadata_thread.progress.disconnect()
                        except (TypeError, RuntimeError):
                            pass

                        def cleanup_old_thread():
                            try:
                                if self.metadata_thread and self.metadata_thread.isFinished():
                                    self.metadata_thread.deleteLater()
                            except Exception:
                                pass
                        self.metadata_thread.finished.connect(cleanup_old_thread)
                    elif self.metadata_thread.isFinished():
                        self.metadata_thread.deleteLater()
                except Exception as e:
                    logging.warning(f'RefreshController: Error stopping metadata thread: {e}')
                finally:
                    if self.metadata_thread and (not self.metadata_thread.isRunning()):
                        self.metadata_thread = None
            try:
                from utils.gamebanana_cache import GameBananaMetadataCache
                if not hasattr(self.app_state, 'config_dir') or not self.app_state.config_dir:
                    logging.warning('RefreshController: config_dir not available, cannot load metadata')
                    return
                metadata_cache = GameBananaMetadataCache(self.app_state.config_dir)
                all_mod_ids = list(self.app_state.gamebanana_mods_needing_metadata)
                if not all_mod_ids:
                    return
                MAX_METADATA_BATCH_SIZE = 20
                mod_ids_to_load = all_mod_ids[:MAX_METADATA_BATCH_SIZE]
                remaining_mod_ids = all_mod_ids[MAX_METADATA_BATCH_SIZE:]
                self.app_state.gamebanana_mods_needing_metadata = remaining_mod_ids
                from workers.load_gamebanana_metadata import LoadGameBananaMetadataThread
                self.metadata_thread = LoadGameBananaMetadataThread(mod_ids_to_load, metadata_cache, parent=self.app_window)
                if self.app_window and hasattr(self.app_window, 'search_display'):
                    self.metadata_thread.mod_updated.connect(self.app_window.search_display.on_metadata_updated)
                self.metadata_thread.finished.connect(self._on_metadata_loading_finished)
                self.metadata_thread.start()
                logging.info(f'RefreshController: Started metadata loading for {len(mod_ids_to_load)} mods ({len(remaining_mod_ids)} remaining in queue)')
            except Exception as e:
                logging.error(f'RefreshController: Failed to start metadata loading: {e}', exc_info=True)
        except Exception as e:
            logging.error(f'RefreshController: Error in _start_metadata_loading: {e}', exc_info=True)

    def _on_metadata_loading_finished(self):
        try:
            logging.info('RefreshController: Metadata loading finished')
            has_more_mods = hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata
            if self.app_window and hasattr(self.app_window, 'search_display') and self.app_window.search_display:

                def ensure_sorted():
                    try:
                        app_window = self.app_window
                        if app_window and hasattr(app_window, 'search_display') and app_window.search_display:
                            app_window.search_display.update_filtered_mods(preserve_page=True)
                    except Exception as e:
                        logging.error(f'RefreshController: Error ensuring sort after metadata load: {e}', exc_info=True)
                ensure_sorted()
            if has_more_mods:
                logging.info(f'RefreshController: Found {len(self.app_state.gamebanana_mods_needing_metadata)} more mods needing metadata, starting another batch')
                self._start_metadata_loading()
            if self.metadata_thread:
                try:
                    if self.metadata_thread.isFinished():
                        self.metadata_thread.deleteLater()
                    else:

                        def cleanup_thread():
                            try:
                                if self.metadata_thread and self.metadata_thread.isFinished():
                                    self.metadata_thread.deleteLater()
                                    self.metadata_thread = None
                            except Exception:
                                pass
                        self.metadata_thread.finished.connect(cleanup_thread)
                except Exception as e:
                    logging.warning(f'RefreshController: Error cleaning up metadata thread: {e}')
                finally:
                    if self.metadata_thread and self.metadata_thread.isFinished():
                        self.metadata_thread = None
        except Exception as e:
            logging.warning(f'RefreshController: Error in _on_metadata_loading_finished: {e}')
