from utils.mod_filter_utils import filter_and_sort_mods
from PyQt6.QtWidgets import QInputDialog
from PyQt6.QtCore import QTimer
from managers.localization_manager import tr
from ui.dialogs.mod_details import open_mod_details_dialog
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
from workers.load_more_gamebanana_mods import LoadMoreGameBananaModsThread
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE
import logging
logger = logging.getLogger(__name__)


class SearchDisplayController:

    def __init__(self, app_state, feedback_manager, mod_manager, mod_ops, app_window):
        self.app_state = app_state
        self.feedback_manager = feedback_manager
        self.mod_manager = mod_manager
        self.mod_ops = mod_ops
        self.app = app_window
        self._load_more_threads = []
        self._current_details_thread = None
        self._last_load_attempt = {'items_needed': 0, 'current_total': 0, 'attempts': 0}
        self._load_check_done = False
        self._update_display_in_progress = False
        self._pending_metadata_updates = {}
        self._metadata_update_timer = None
        self.plaque_widget_cache: dict[str, ModPlaqueWidget] = {}

    def prev_page(self):
        try:
            self._cleanup_details_threads()

            def do_page_change():
                try:
                    if self.app_state.current_page > 1:
                        self.app_state.current_page -= 1
                        self.update_display()
                except Exception as e:
                    logger.error(f'SearchDisplayController: Error in prev_page do_page_change: {e}', exc_info=True)
            QTimer.singleShot(200, do_page_change)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in prev_page: {e}', exc_info=True)

    def next_page(self):
        try:
            self._cleanup_details_threads()

            def do_page_change():
                try:
                    total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
                    if self.app_state.mods_loaded:
                        next_page_num = self.app_state.current_page + 1
                        items_needed = next_page_num * self.app_state.mods_per_page
                        if total_mods < items_needed:
                            self._load_more_gamebanana_mods_if_needed(items_needed)
                    if total_mods > 0 or self.app_state.gamebanana_loading:
                        max_available_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
                        if self.app_state.current_page < max_available_page or self.app_state.gamebanana_loading:
                            self.app_state.current_page += 1
                            self.update_display()
                except Exception as e:
                    logger.error(f'SearchDisplayController: Error in next_page do_page_change: {e}', exc_info=True)
            QTimer.singleShot(200, do_page_change)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in next_page: {e}', exc_info=True)

    def _load_more_gamebanana_mods_if_needed(self, items_needed: int):
        if not self.app_state.mods_loaded:
            return
        if self.app_state.gamebanana_loading:
            return
        self._load_more_threads = [t for t in self._load_more_threads if t and t.isRunning()]
        if self._load_more_threads:
            return
        current_total = len(self.app_state.all_mods)
        if current_total >= items_needed:
            return
        if self._last_load_attempt['items_needed'] == items_needed and self._last_load_attempt['current_total'] == current_total:
            self._last_load_attempt['attempts'] += 1
            if self._last_load_attempt['attempts'] >= 2:
                logger.warning(f"Stopping load attempt after {self._last_load_attempt['attempts']} attempts with no new mods")
                return
        else:
            self._last_load_attempt = {'items_needed': items_needed, 'current_total': current_total, 'attempts': 0}
        pages_needed = 2
        selected_modgame = ''
        if hasattr(self.app, 'modgame_combo'):
            selected_modgame = self.app.modgame_combo.currentData() or ''
        games_to_load = {}
        if selected_modgame == 'deltarune':
            games_to_load = {'deltarune': GAMEBANANA_GAME_IDS['deltarune']}
        elif selected_modgame == 'undertale':
            games_to_load = {'undertale': GAMEBANANA_GAME_IDS['undertale']}
        else:
            games_to_load = GAMEBANANA_GAME_IDS
        self.app_state.gamebanana_loading = True
        all_new_mods = []
        results_received = [0]
        expected_results = len(games_to_load)
        sort_param = getattr(self.app_state, 'gamebanana_sort', 'default')

        def on_all_results_received():
            try:
                from PyQt6.QtCore import QThread
                if QThread.currentThread() != self.app.thread():
                    logger.warning('SearchDisplayController: on_all_results_received called from non-main thread, deferring')
                    QTimer.singleShot(0, on_all_results_received)
                    return
                self.app_state.gamebanana_loading = False
                if hasattr(self, '_last_load_attempt'):
                    self._last_load_attempt['current_total'] = len(self.app_state.all_mods)
                if not all_new_mods:
                    self.update_pagination()
                    return
                if not hasattr(self.app_state, 'all_mods'):
                    logger.error('SearchDisplayController: app_state.all_mods not available')
                    return
                existing_ids = {str(m.gamebanana_mod_id) for m in self.app_state.all_mods if hasattr(m, 'gamebanana_mod_id') and m.gamebanana_mod_id}
                new_mods_to_add = [m for m in all_new_mods if hasattr(m, 'gamebanana_mod_id') and m.gamebanana_mod_id and (str(m.gamebanana_mod_id) not in existing_ids)]
                if new_mods_to_add:
                    self.app_state.all_mods.extend(new_mods_to_add)
                    if hasattr(self, '_last_load_attempt'):
                        self._last_load_attempt['attempts'] = 0
                else:
                    self.update_pagination()
                    return

                def safe_update():
                    try:
                        self.update_filtered_mods(preserve_page=True)
                        self.update_pagination()
                    except Exception as e:
                        logger.error(f'SearchDisplayController: Error in safe_update after loading mods: {e}', exc_info=True)
                QTimer.singleShot(100, safe_update)
            except Exception as e:
                logger.error(f'SearchDisplayController: Error in on_all_results_received: {e}', exc_info=True)
                self.app_state.gamebanana_loading = False
                try:
                    self.update_filtered_mods(preserve_page=True)
                    self.update_pagination()
                except BaseException:
                    pass
        metadata_cache = None
        if hasattr(self.app_state, 'config_dir') and self.app_state.config_dir:
            try:
                from utils.gamebanana_cache import GameBananaMetadataCache
                metadata_cache = GameBananaMetadataCache(self.app_state.config_dir)
            except Exception as e:
                logger.warning(f'SearchDisplayController: Failed to initialize metadata cache: {e}', exc_info=True)
        for game_name, game_id in games_to_load.items():
            last_page = self.app_state.gamebanana_loaded_pages.get(game_id, 0)
            start_page = last_page + 1
            load_thread = LoadMoreGameBananaModsThread(game_id, start_page, num_pages=pages_needed, sort=sort_param, parent=self.app, metadata_cache=metadata_cache)

            def make_on_result(gid, lp):

                def on_result(mods_list):
                    if mods_list:
                        all_new_mods.extend(mods_list)
                        pages_loaded = (len(mods_list) + GAMEBANANA_PER_PAGE - 1) // GAMEBANANA_PER_PAGE
                        current_loaded = self.app_state.gamebanana_loaded_pages.get(gid, 0)
                        self.app_state.gamebanana_loaded_pages[gid] = max(current_loaded, lp + pages_loaded)
                        if hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata:

                            def trigger_metadata_loading():
                                try:
                                    if hasattr(self.app, 'refresh_controller'):
                                        self.app.refresh_controller._start_metadata_loading()
                                except Exception as e:
                                    logger.warning(f'SearchDisplayController: Error triggering metadata loading: {e}', exc_info=True)
                            QTimer.singleShot(500, trigger_metadata_loading)
                    else:
                        current_loaded = self.app_state.gamebanana_loaded_pages.get(gid, 0)
                        self.app_state.gamebanana_loaded_pages[gid] = max(current_loaded, lp + pages_needed)
                        logger.info(f'No mods returned for game {gid}, marking pages {lp + 1}-{lp + pages_needed} as loaded')
                    results_received[0] += 1
                    if results_received[0] >= expected_results:
                        QTimer.singleShot(0, on_all_results_received)
                return on_result
            load_thread.result.connect(make_on_result(game_id, last_page))

            def on_thread_finished(thread=load_thread):
                try:
                    if thread in self._load_more_threads:
                        self._load_more_threads.remove(thread)
                    thread.deleteLater()
                except (RuntimeError, ValueError):
                    pass
            load_thread.finished.connect(on_thread_finished)
            self._load_more_threads.append(load_thread)
            load_thread.start()

    def show_search_dialog(self):
        if self.app_state.search_text:
            self.app_state.search_text = ''
            self.app.search_button.setText('🔍')
            self.app.search_button.setToolTip(tr('ui.search_placeholder'))
            self.update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self.app, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.app_state.search_text = text.strip()
                self.app.search_button.setText('↻')
                self.app.search_button.setToolTip(tr('ui.clear_search_tooltip', search_text=self.app_state.search_text))
                self.update_filtered_mods()

    def _build_filters_and_sort(self):
        selected_tags = []
        tag_checkboxes = {'tag_textedit': 'textedit', 'tag_customization': 'customization', 'tag_gameplay': 'gameplay', 'tag_other': 'other'}
        for attr_name, tag_value in tag_checkboxes.items():
            if hasattr(self.app, attr_name) and getattr(self.app, attr_name).isChecked():
                selected_tags.append(tag_value)
        selected_modgame = ''
        if hasattr(self.app, 'modgame_combo'):
            selected_modgame = self.app.modgame_combo.currentData() or ''
        filters = {'tags': selected_tags, 'modgame': selected_modgame, 'search_text': self.app_state.search_text, 'hide_banned': True, 'hide_local': True, 'status_filter': ['approved', 'pending']}
        sort_config = None
        if hasattr(self.app, 'sort_combo'):
            sort_type = self.app.sort_combo.currentIndex()
            reverse = not self.app.sort_ascending
            sort_config = {'sort_type': sort_type, 'reverse': reverse}
        return (filters, sort_config)

    def update_filtered_mods(self, preserve_page=False):
        if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
            self.app_state.filtered_mods = []
            self.update_display()
            return
        filters, sort_config = self._build_filters_and_sort()
        self.app_state.filtered_mods = filter_and_sort_mods(self.app_state.all_mods, filters, sort_config)
        if not preserve_page:
            self.app_state.current_page = 1
        else:
            total_mods = len(self.app_state.filtered_mods)
            max_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
            if self.app_state.current_page > max_page:
                self.app_state.current_page = max_page
        self.update_display()

    def update_display(self):
        if self._update_display_in_progress:
            QTimer.singleShot(200, self.update_display)
            return
        self._update_display_in_progress = True
        try:
            from PyQt6.QtCore import QThread
            if QThread.currentThread() != self.app.thread():
                logger.warning('SearchDisplayController: update_display called from non-main thread, deferring')
                QTimer.singleShot(0, self.update_display)
                self._update_display_in_progress = False
                return
            if not hasattr(self.app_state, 'filtered_mods'):
                logger.warning('SearchDisplayController: filtered_mods not available')
                self._update_display_in_progress = False
                return
            total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
            if total_mods == 0:
                self.app_state.current_page = 1
            else:
                max_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1)
                if self.app_state.current_page > max_page:
                    self.app_state.current_page = max_page
            if self.app_state.mods_loaded and total_mods > 0 and (not self._load_check_done):
                items_needed = self.app_state.current_page * self.app_state.mods_per_page
                if total_mods < items_needed and (not self.app_state.gamebanana_loading):

                    def deferred_load_check():
                        try:
                            self._load_check_done = True
                            self._load_more_gamebanana_mods_if_needed(items_needed)
                            QTimer.singleShot(500, lambda: setattr(self, '_load_check_done', False))
                        except Exception as e:
                            logger.error(f'SearchDisplayController: Error in deferred_load_check: {e}', exc_info=True)
                    QTimer.singleShot(100, deferred_load_check)
            start_index = (self.app_state.current_page - 1) * self.app_state.mods_per_page
            end_index = start_index + self.app_state.mods_per_page
            if start_index < 0:
                start_index = 0
            if end_index > total_mods:
                end_index = total_mods
            if not hasattr(self.app, 'mod_list_layout'):
                logger.warning('SearchDisplayController: mod_list_layout not available')
                self._update_display_in_progress = False
                return
            current_page_mods = self.app_state.filtered_mods[start_index:end_index] if self.app_state.filtered_mods else []
            if not hasattr(self.app, 'mod_list_widget'):
                logger.warning('SearchDisplayController: mod_list_widget not available')
                self._update_display_in_progress = False
                return
            widgets_to_hide = []
            for i in range(self.app.mod_list_layout.count() - 1):
                item = self.app.mod_list_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, ModPlaqueWidget):
                        widgets_to_hide.append(widget)
            for widget in widgets_to_hide:
                widget.hide()
            self.app.mod_list_widget.setUpdatesEnabled(False)
            widgets_shown = 0
            widgets_created = 0

            def get_mod_cache_key(mod):
                if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod:
                    if hasattr(mod, 'gamebanana_mod_id') and mod.gamebanana_mod_id:
                        return f'gb_{mod.gamebanana_mod_id}'
                mod_key = getattr(mod, 'key', None)
                if mod_key:
                    return f'local_{mod_key}'
                mod_name = getattr(mod, 'name', 'unknown')
                return f'name_{mod_name}'
            try:
                for idx, mod in enumerate(current_page_mods):
                    if mod is None:
                        logger.warning(f'SearchDisplayController: Mod at index {start_index + idx} is None, skipping')
                        continue
                    try:
                        cache_key = get_mod_cache_key(mod)
                        if cache_key in self.plaque_widget_cache:
                            plaque = self.plaque_widget_cache[cache_key]
                            if hasattr(plaque, 'mod_data'):
                                plaque.mod_data = mod
                                if hasattr(plaque, 'update_mod_data'):
                                    plaque.update_mod_data()
                                if hasattr(plaque, 'update_installation_status'):
                                    plaque.update_installation_status()
                            is_in_layout = False
                            for i in range(self.app.mod_list_layout.count() - 1):
                                item = self.app.mod_list_layout.itemAt(i)
                                if item and item.widget() == plaque:
                                    is_in_layout = True
                                    break
                            if not is_in_layout:
                                self.app.mod_list_layout.insertWidget(self.app.mod_list_layout.count() - 1, plaque)
                            plaque.show()
                            plaque.install_button.setEnabled(not self.app_state.is_installing)
                            widgets_shown += 1
                        else:
                            parent_widget = self.app.mod_list_widget if hasattr(self.app, 'mod_list_widget') else self.app
                            plaque = ModPlaqueWidget(mod, parent=parent_widget, parent_app=self.app)
                            plaque.install_requested.connect(self.mod_ops.on_mod_install_requested)
                            plaque.uninstall_requested.connect(self.mod_ops.on_mod_uninstall_requested)
                            plaque.clicked.connect(self.on_mod_clicked)
                            plaque.details_requested.connect(self.show_details)
                            plaque.install_button.setEnabled(not self.app_state.is_installing)
                            self.app.mod_list_layout.insertWidget(self.app.mod_list_layout.count() - 1, plaque)
                            self.plaque_widget_cache[cache_key] = plaque
                            widgets_created += 1
                            widgets_shown += 1
                    except Exception as e:
                        logger.error(f"Error processing plaque for mod {(mod.name if mod else 'unknown')} at index {start_index + idx}: {e}", exc_info=True)
                        continue
            finally:
                self.app.mod_list_widget.setUpdatesEnabled(True)
            self.update_pagination()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_display: {e}', exc_info=True)
        finally:
            self._update_display_in_progress = False

    def update_pagination(self):
        if not hasattr(self.app, 'page_label') or not hasattr(self.app, 'prev_page_btn') or (not hasattr(self.app, 'next_page_btn')):
            return
        self.app.page_label.setText(tr('ui.page_number', page=self.app_state.current_page))
        self.app.prev_page_btn.setEnabled(self.app_state.current_page > 1)
        total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
        current_page_mods = total_mods - (self.app_state.current_page - 1) * self.app_state.mods_per_page
        has_more_mods = current_page_mods > self.app_state.mods_per_page
        can_load_more = self.app_state.mods_loaded and (not self.app_state.gamebanana_loading)
        self.app.next_page_btn.setEnabled(has_more_mods or can_load_more)

    def update_search_plaques(self):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    try:
                        widget.update_installation_status()
                    except Exception:
                        pass

    def on_mod_clicked(self, mod):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget) and widget.mod_data == mod:
                    self.clear_all_selections()
                    widget.set_selected(True)
                    break

    def show_details(self, mod_data):
        open_mod_details_dialog(self.app, mod_data)

    def clear_all_selections(self):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    widget.set_selected(False)

    def _cleanup_details_threads(self):
        try:
            if not self._current_details_thread:
                return
            thread = self._current_details_thread
            self._current_details_thread = None
            try:
                if hasattr(thread, 'cancel'):
                    thread.cancel()
                try:
                    thread.blockSignals(True)
                    try:
                        thread.mod_updated.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        thread.finished.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        thread.progress.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    thread.blockSignals(False)
                except (TypeError, RuntimeError):
                    pass
                if not thread.isRunning():
                    thread.deleteLater()
            except Exception as e:
                logger.error(f'SearchDisplayController: Error cleaning up details thread: {e}', exc_info=True)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _cleanup_details_threads: {e}', exc_info=True)

    def on_metadata_updated(self, mod_id: str, downloads: int, tagline: str, category: str = ''):
        try:
            self._pending_metadata_updates[mod_id] = (downloads, tagline, category)
            if self._metadata_update_timer is None:
                self._metadata_update_timer = QTimer()
                self._metadata_update_timer.setSingleShot(True)
                self._metadata_update_timer.timeout.connect(self._apply_pending_metadata_updates)
            if not self._metadata_update_timer.isActive():
                self._metadata_update_timer.start(200)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in on_metadata_updated: {e}', exc_info=True)

    def _apply_pending_metadata_updates(self):
        try:
            if not self._pending_metadata_updates:
                return
            updated_mods = []
            needs_resort = False
            needs_refilter = False
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                for mod in self.app_state.all_mods:
                    if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod:
                        mod_id = str(mod.gamebanana_mod_id) if mod.gamebanana_mod_id else None
                        if mod_id and mod_id in self._pending_metadata_updates:
                            update_data = self._pending_metadata_updates[mod_id]
                            if len(update_data) >= 3:
                                downloads, tagline, category = update_data
                            else:
                                downloads, tagline = (update_data[0], update_data[1])
                                category = ''
                            if downloads > 0 and mod.downloads != downloads:
                                mod.downloads = downloads
                                needs_resort = True
                            if tagline and tagline != 'No description' and (mod.tagline != tagline):
                                mod.tagline = tagline
                            if category:
                                if not hasattr(mod, 'gamebanana_category') or mod.gamebanana_category != category:
                                    mod.gamebanana_category = category
                                    needs_refilter = True
                            updated_mods.append(mod_id)
            self._pending_metadata_updates.clear()
            if (needs_resort or needs_refilter) and hasattr(self.app_state, 'filtered_mods'):
                sort_needs_resort = False
                if hasattr(self.app, 'sort_combo'):
                    sort_type = self.app.sort_combo.currentIndex()
                    if sort_type == 0:
                        sort_needs_resort = True
                if sort_needs_resort or needs_refilter:
                    self.update_filtered_mods(preserve_page=True)
            if updated_mods:
                self._update_plaques_for_mods(updated_mods)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _apply_pending_metadata_updates: {e}', exc_info=True)
            self._pending_metadata_updates.clear()

    def _update_plaques_for_mods(self, mod_ids: list):
        try:
            if not hasattr(self.app, 'mod_list_layout'):
                return
            updated_count = 0
            for i in range(self.app.mod_list_layout.count() - 1):
                item = self.app.mod_list_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, ModPlaqueWidget):
                        mod = widget.mod_data
                        if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod:
                            mod_id = str(mod.gamebanana_mod_id) if mod.gamebanana_mod_id else None
                            if mod_id and mod_id in mod_ids:
                                try:
                                    widget.update_installation_status()
                                    widget.update_mod_data()
                                    updated_count += 1
                                except Exception as e:
                                    logger.warning(f'SearchDisplayController: Error updating plaque for mod {mod_id}: {e}')
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _update_plaques_for_mods: {e}', exc_info=True)
