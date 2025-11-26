from utils.mod_filter_utils import filter_and_sort_mods
from PyQt6.QtWidgets import QInputDialog
from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from managers.localization_manager import tr
from ui.dialogs.mod_details import open_mod_details_dialog
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
from workers.load_more_gamebanana_mods import LoadMoreGameBananaModsThread
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE
from utils.ui_utils import DebounceTimer
import logging
logger = logging.getLogger(__name__)


class SearchDisplayController(QObject):
    ui_button_text_update = pyqtSignal(str, str)
    ui_button_tooltip_update = pyqtSignal(str, str)
    ui_button_enabled_update = pyqtSignal(str, bool)
    ui_label_text_update = pyqtSignal(str, str)
    ui_combo_data_requested = pyqtSignal(str)
    combo_data_received = pyqtSignal(str, object)
    ui_layout_update_requested = pyqtSignal(str, list)
    ui_layout_clear_requested = pyqtSignal(str)
    ui_widget_updates_enabled = pyqtSignal(str, bool)

    def __init__(self, app_state, feedback_manager, mod_manager, mod_ops, app_window):
        super().__init__()
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
        self._update_display_debounce = DebounceTimer(delay_ms=200)

    def prev_page(self):
        try:
            self._cleanup_details_threads()
            if self.app_state.current_page > 1:
                self.app_state.current_page -= 1
                self.update_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in prev_page: {e}', exc_info=True)

    def next_page(self):
        try:
            self._cleanup_details_threads()
            total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
            current_page = self.app_state.current_page
            next_page_num = current_page + 1
            items_needed = next_page_num * self.app_state.mods_per_page
            should_load_more = False
            preferred_game = self._determine_preferred_game_for_page(next_page_num)
            if self.app_state.mods_loaded:
                if total_mods < items_needed:
                    should_load_more = True
                    self._load_more_gamebanana_mods_if_needed(items_needed, preferred_game)
            max_available_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
            can_advance = False
            if should_load_more and self.app_state.gamebanana_loading:
                can_advance = True
            elif current_page < max_available_page:
                can_advance = True
            elif total_mods > 0 and self.app_state.gamebanana_loading:
                can_advance = True
            if can_advance:
                self.app_state.current_page += 1
                self.update_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in next_page: {e}', exc_info=True)

    def _load_more_gamebanana_mods_if_needed(self, items_needed: int, preferred_modgame: str | None = None):
        if not self.app_state.mods_loaded:
            return
        if self.app_state.gamebanana_loading:
            return
        self._load_more_threads = [t for t in self._load_more_threads if t and t.isRunning()]
        if self._load_more_threads:
            return
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
        games_to_load_filtered = {}
        for game_name, game_id in games_to_load.items():
            last_page = self.app_state.gamebanana_loaded_pages.get(game_id, 0)
            if last_page < 50:
                games_to_load_filtered[game_name] = game_id
        if not games_to_load_filtered:
            return
        games_to_load = games_to_load_filtered
        preferred_game_key = ''
        if preferred_modgame:
            preferred_game_key = self._map_modgame_to_gamebanana(preferred_modgame)
        if preferred_game_key and preferred_game_key in games_to_load:
            games_to_load = {preferred_game_key: games_to_load[preferred_game_key]}
        elif games_to_load:
            prioritized = min(games_to_load.items(), key=lambda item: self.app_state.gamebanana_loaded_pages.get(item[1], 0))
            games_to_load = {prioritized[0]: prioritized[1]}
        filtered_mods_count = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
        current_total = len(self.app_state.all_mods)
        if filtered_mods_count >= items_needed:
            return
        if self._last_load_attempt['items_needed'] == items_needed and self._last_load_attempt['current_total'] == current_total:
            self._last_load_attempt['attempts'] += 1
            if self._last_load_attempt['attempts'] >= 3:
                return
        else:
            self._last_load_attempt = {'items_needed': items_needed, 'current_total': current_total, 'attempts': 0}
        pages_needed = 1 if len(games_to_load) == 1 else 2
        self.app_state.gamebanana_loading = True
        all_new_mods = []
        results_received = [0]
        expected_results = len(games_to_load)
        sort_param = getattr(self.app_state, 'gamebanana_sort', 'default')

        def on_all_results_received():
            from PyQt6.QtCore import QThread
            from PyQt6.QtWidgets import QApplication
            current_thread = QThread.currentThread()
            app_instance = QApplication.instance()
            if app_instance and current_thread != app_instance.thread():
                QTimer.singleShot(0, on_all_results_received)
                return
            try:
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
                    self.app_state.extend_all_mods(new_mods_to_add)
                    if hasattr(self, '_last_load_attempt'):
                        self._last_load_attempt['attempts'] = 0

                    def safe_update():
                        try:
                            self.update_filtered_mods(preserve_page=True)
                            self.update_pagination()
                        except Exception as e:
                            logger.error(f'SearchDisplayController: Error in safe_update after loading mods: {e}', exc_info=True)
                    QTimer.singleShot(100, safe_update)
                else:
                    self.update_pagination()
                    return
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

            def make_on_result(gid, gname, lp, sp, pn):

                def on_result(mods_list):
                    current_loaded = self.app_state.gamebanana_loaded_pages.get(gid, 0)
                    if mods_list:
                        all_new_mods.extend(mods_list)
                        if len(mods_list) >= pn * GAMEBANANA_PER_PAGE:
                            real_pages_loaded = pn
                        else:
                            pages_from_mods = (len(mods_list) + GAMEBANANA_PER_PAGE - 1) // GAMEBANANA_PER_PAGE
                            real_pages_loaded = min(pn, max(1, pages_from_mods))
                        new_loaded = max(current_loaded, sp + real_pages_loaded - 1)
                        self.app_state.gamebanana_loaded_pages[gid] = new_loaded
                        if hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata:

                            def trigger_metadata_loading():
                                try:
                                    if hasattr(self.app, 'refresh_controller'):
                                        self.app.refresh_controller._start_metadata_loading()
                                except Exception as e:
                                    logger.warning(f'SearchDisplayController: Error triggering metadata loading: {e}', exc_info=True)
                            QTimer.singleShot(500, trigger_metadata_loading)
                    else:
                        self.app_state.gamebanana_loaded_pages[gid] = 100
                    results_received[0] += 1
                    if results_received[0] >= expected_results:
                        QTimer.singleShot(0, on_all_results_received)
                return on_result
            load_thread.result.connect(make_on_result(game_id, game_name, last_page, start_page, pages_needed))

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
            self.ui_button_text_update.emit('search_button', '🔍')
            self.ui_button_tooltip_update.emit('search_button', tr('ui.search_placeholder'))
            self.update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self.app, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                self.app_state.search_text = text.strip()
                self.ui_button_text_update.emit('search_button', '↻')
                self.ui_button_tooltip_update.emit('search_button', tr('ui.clear_search_tooltip', text=self.app_state.search_text))
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
        self._update_display_debounce.call(self._do_update_display)

    def _do_update_display(self):
        if self._update_display_in_progress:
            return
        self._update_display_in_progress = True
        try:
            from PyQt6.QtCore import QThread
            from PyQt6.QtWidgets import QApplication
            current_thread = QThread.currentThread()
            app_instance = QApplication.instance()
            if app_instance and current_thread != app_instance.thread():
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
                            preferred_game = self._determine_preferred_game_for_page(self.app_state.current_page)
                            self._load_more_gamebanana_mods_if_needed(items_needed, preferred_game)
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

            def get_mod_cache_key(mod):
                if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod:
                    if hasattr(mod, 'gamebanana_mod_id') and mod.gamebanana_mod_id:
                        return f'gb_{mod.gamebanana_mod_id}'
                mod_key = getattr(mod, 'key', None)
                if mod_key:
                    return f'local_{mod_key}'
                mod_name = getattr(mod, 'name', 'unknown')
                return f'name_{mod_name}'
            existing_widgets_in_layout = {}
            for i in range(self.app.mod_list_layout.count() - 1):
                item = self.app.mod_list_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, ModPlaqueWidget):
                        widget.hide()
                        if hasattr(widget, 'mod_data') and widget.mod_data:
                            cache_key = get_mod_cache_key(widget.mod_data)
                            existing_widgets_in_layout[cache_key] = (widget, i)
            self.ui_widget_updates_enabled.emit('mod_list_widget', False)
            widgets_shown = 0
            widgets_created = 0
            try:
                target_position = 0
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
                            current_position = None
                            for i in range(self.app.mod_list_layout.count() - 1):
                                item = self.app.mod_list_layout.itemAt(i)
                                if item and item.widget() == plaque:
                                    current_position = i
                                    break
                            if current_position is not None:
                                if current_position != target_position:
                                    self.app.mod_list_layout.removeWidget(plaque)
                                    self.app.mod_list_layout.insertWidget(target_position, plaque)
                            else:
                                self.app.mod_list_layout.insertWidget(target_position, plaque)
                            if hasattr(plaque, 'update_install_button_state'):
                                plaque.update_install_button_state()
                            widgets_shown += 1
                            target_position += 1
                        else:
                            parent_widget = self.app.mod_list_widget if hasattr(self.app, 'mod_list_widget') else self.app
                            plaque = ModPlaqueWidget(mod, parent=parent_widget, parent_app=self.app)
                            plaque.hide()
                            plaque.install_requested.connect(self.mod_ops.on_mod_install_requested)
                            plaque.uninstall_requested.connect(self.mod_ops.on_mod_uninstall_requested)
                            plaque.clicked.connect(self.on_mod_clicked)
                            plaque.details_requested.connect(self.show_details)
                            if hasattr(plaque, 'update_install_button_state'):
                                plaque.update_install_button_state()
                            self.app.mod_list_layout.insertWidget(target_position, plaque)
                            self.plaque_widget_cache[cache_key] = plaque
                            widgets_created += 1
                            widgets_shown += 1
                            target_position += 1
                    except Exception as e:
                        logger.error(f"Error processing plaque for mod {(mod.name if mod else 'unknown')} at index {start_index + idx}: {e}", exc_info=True)
                        continue
                current_page_cache_keys = {get_mod_cache_key(mod) for mod in current_page_mods if mod is not None}
                widgets_to_hide = []
                for i in range(self.app.mod_list_layout.count() - 1):
                    item = self.app.mod_list_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, ModPlaqueWidget):
                            widget_cache_key = get_mod_cache_key(widget.mod_data) if hasattr(widget, 'mod_data') and widget.mod_data else None
                            if widget_cache_key and widget_cache_key not in current_page_cache_keys:
                                widgets_to_hide.append(widget)
                for widget in widgets_to_hide:
                    try:
                        self.app.mod_list_layout.removeWidget(widget)
                        widget.hide()
                    except Exception as e:
                        logger.debug(f'Error removing widget from layout: {e}')
                for i in range(self.app.mod_list_layout.count() - 1):
                    item = self.app.mod_list_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if isinstance(widget, ModPlaqueWidget):
                            widget.show()
            finally:
                self.ui_widget_updates_enabled.emit('mod_list_widget', True)
            self.update_pagination()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_display: {e}', exc_info=True)
        finally:
            self._update_display_in_progress = False

    def update_pagination(self):
        if not hasattr(self.app, 'page_label') or not hasattr(self.app, 'prev_page_btn') or (not hasattr(self.app, 'next_page_btn')):
            return
        self.ui_label_text_update.emit('page_label', tr('ui.page_number', page=self.app_state.current_page))
        self.ui_button_enabled_update.emit('prev_page_btn', self.app_state.current_page > 1)
        total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
        current_page_mods = total_mods - (self.app_state.current_page - 1) * self.app_state.mods_per_page
        has_more_mods = current_page_mods > self.app_state.mods_per_page
        can_load_more = self.app_state.mods_loaded and (not self.app_state.gamebanana_loading)
        self.ui_button_enabled_update.emit('next_page_btn', has_more_mods or can_load_more)

    def update_search_plaques(self):
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item:
                widget = item.widget()
                if isinstance(widget, ModPlaqueWidget):
                    try:
                        if hasattr(widget, 'update_mod_data'):
                            widget.update_mod_data()
                        widget.update_installation_status()
                        if hasattr(widget, 'update_install_button_state'):
                            widget.update_install_button_state()
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

    def _map_modgame_to_gamebanana(self, modgame: str) -> str:
        mapping = {'deltarune': 'deltarune', 'deltarunedemo': 'deltarune', 'undertale': 'undertale', 'undertaleyellow': 'undertaleyellow'}
        return mapping.get((modgame or '').lower(), '')

    def _determine_preferred_game_for_page(self, page_num: int) -> str:
        try:
            filtered = self.app_state.filtered_mods or []
            if not filtered:
                return ''
            per_page = self.app_state.mods_per_page or GAMEBANANA_PER_PAGE
            start_idx = max(0, (page_num - 1) * per_page)
            if start_idx < len(filtered):
                candidate = filtered[start_idx]
            else:
                candidate = filtered[-1]
            return getattr(candidate, 'modgame', '') or ''
        except Exception:
            return ''

    def on_metadata_updated(self, mod_id: str, downloads: int, tagline: str, category: str = ''):
        try:
            self._pending_metadata_updates[mod_id] = (downloads, tagline, category)
            if self._metadata_update_timer is None:
                self._metadata_update_timer = QTimer()
                self._metadata_update_timer.setSingleShot(True)
                self._metadata_update_timer.timeout.connect(self._apply_pending_metadata_updates)
            self._metadata_update_timer.stop()
            self._metadata_update_timer.start(1500)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in on_metadata_updated: {e}', exc_info=True)

    def _apply_pending_metadata_updates(self):
        try:
            if not self._pending_metadata_updates:
                return
            updated_mods = []
            needs_resort = False
            needs_refilter = False
            downloads_changed = False
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
                            if downloads is not None and downloads >= 0:
                                old_downloads = getattr(mod, 'downloads', None)
                                if old_downloads is None:
                                    old_downloads = 0
                                else:
                                    try:
                                        old_downloads = int(old_downloads)
                                    except (ValueError, TypeError):
                                        old_downloads = 0
                                try:
                                    downloads_int = int(downloads)
                                except (ValueError, TypeError):
                                    downloads_int = 0
                                if old_downloads != downloads_int:
                                    mod.downloads = downloads_int
                                    needs_resort = True
                                    downloads_changed = True
                                elif mod.downloads != downloads_int:
                                    mod.downloads = downloads_int
                                    needs_resort = True
                                    downloads_changed = True
                            if tagline and tagline != 'No description' and (mod.tagline != tagline):
                                mod.tagline = tagline
                            if category:
                                if not hasattr(mod, 'gamebanana_category') or mod.gamebanana_category != category:
                                    mod.gamebanana_category = category
                                    needs_refilter = True
                            updated_mods.append(mod_id)
            self._pending_metadata_updates.clear()
            if downloads_changed or needs_resort or needs_refilter:
                sort_needs_resort = False
                if hasattr(self.app, 'sort_combo'):
                    sort_type = self.app.sort_combo.currentIndex()
                    if sort_type == 0:
                        sort_needs_resort = True
                if sort_needs_resort or needs_refilter or downloads_changed:
                    logger.debug(f"SearchDisplayController: Re-sorting mods after metadata update (downloads_changed={downloads_changed}, needs_resort={needs_resort}, needs_refilter={needs_refilter}, sort_type={(sort_type if hasattr(self.app, 'sort_combo') else 'N/A')})")
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

    def update_all_plaques_labels(self):
        try:
            for cache_key, plaque in self.plaque_widget_cache.items():
                try:
                    if hasattr(plaque, 'update_labels_text'):
                        plaque.update_labels_text()
                except Exception as e:
                    logger.warning(f'SearchDisplayController: Error updating labels for plaque {cache_key}: {e}')
            if hasattr(self.app, 'mod_list_layout'):
                for i in range(self.app.mod_list_layout.count() - 1):
                    item = self.app.mod_list_layout.itemAt(i)
                    if item:
                        widget = item.widget()
                        if isinstance(widget, ModPlaqueWidget):
                            try:
                                if hasattr(widget, 'update_labels_text'):
                                    widget.update_labels_text()
                            except Exception as e:
                                logger.warning(f'SearchDisplayController: Error updating labels for widget in layout: {e}')
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_all_plaques_labels: {e}', exc_info=True)
