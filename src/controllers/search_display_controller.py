"""Controller for search display and mod filtering."""
from services.mod_filter_service import filter_and_sort_mods
from utils.mod_utils import get_mod_key, get_gamebanana_key, get_gamebanana_mod_id
from PyQt6.QtWidgets import QInputDialog, QMessageBox, QApplication
from PyQt6.QtCore import QTimer, QObject, QThread, pyqtSignal, QMetaObject, Qt
from services.localization_service import tr
from services.blocklist_service import BlocklistManager
from ui.widgets.mod_details_overlay import show_mod_details_overlay
from ui.dialogs.blocklist_dialog import BlocklistDialog
from ui.widgets.mod.mod_card_widget import ModCardWidget
from workers.gamebanana.load_more_worker import LoadMoreGameBananaModsThread
from workers.gamebanana.search_worker import SearchGameBananaModsThread
from adapters.gamebanana_cache import GameBananaMetadataCache
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE
from ui.utils.ui_utils import DebounceTimer
from controllers.search_metadata_handler import SearchMetadataHandler
import logging
logger = logging.getLogger(__name__)


class SearchDisplayController(QObject):
    """Manages search display, filtering, and mod interaction in search results."""
    ui_button_text_update = pyqtSignal(str, str)
    ui_button_tooltip_update = pyqtSignal(str, str)
    ui_button_enabled_update = pyqtSignal(str, bool)
    ui_combo_data_requested = pyqtSignal(str)
    combo_data_received = pyqtSignal(str, object)
    ui_layout_update_requested = pyqtSignal(str, list)
    ui_layout_clear_requested = pyqtSignal(str)
    ui_widget_updates_enabled = pyqtSignal(str, bool)

    def __init__(self, app_state, feedback_service, mod_service, mod_ops, app_window):
        super().__init__()
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.mod_ops = mod_ops
        self.app = app_window
        self.blocklist_service = BlocklistManager()
        self._load_more_threads = []
        self._current_details_thread = None
        self._last_load_attempt = {'items_needed': 0, 'current_total': 0, 'attempts': 0}
        self._load_check_done = False
        self._update_display_in_progress = False
        self._pending_display_update = False
        self.card_widget_cache: dict[str, ModCardWidget] = {}
        self._update_display_debounce = DebounceTimer(delay_ms=200)
        self._initial_mods_display_done = False
        self._active_search_timers = []
        self._current_search_text = ''
        self._update_filtered_mods_in_progress = False
        self._pending_filter_update = False
        self._metadata_handler = SearchMetadataHandler(
            app_state=app_state,
            app_window=app_window,
            update_filtered_mods_cb=self.update_filtered_mods,
            update_cards_cb=self._update_cards_for_mods,
        )

    def _iter_layout_cards(self):
        """Yield all ModCardWidget instances currently in mod_list_layout."""
        if not hasattr(self.app, 'mod_list_layout'):
            return
        for i in range(self.app.mod_list_layout.count() - 1):
            item = self.app.mod_list_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ModCardWidget):
                yield item.widget()

    @staticmethod
    def _mod_needs_metadata(mod) -> bool:
        """Check whether a GameBanana mod is missing metadata."""
        if getattr(mod, 'has_full_metadata', False):
            return False
        if not getattr(mod, 'tagline', '').strip():
            return True
        if getattr(mod, 'downloads', None) is None:
            return True
        return False

    def _queue_mods_for_metadata(self, mod_id_list: list) -> None:
        """Add mod IDs to the metadata loading queue and trigger loading."""
        if not mod_id_list:
            return
        if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata'):
            self.app_state.gamebanana_mods_needing_metadata = []
        existing = set(self.app_state.gamebanana_mods_needing_metadata)
        new_ids = set(mod_id_list)
        self.app_state.gamebanana_mods_needing_metadata = list(existing | new_ids)
        logger.info(f'SearchDisplayController: Added {len(new_ids)} mod IDs to metadata loading queue')
        if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
            self.app.refresh_controller._start_metadata_loading()

    def _show_no_results_and_clear_search(self, search_text: str):
        def _do_show():
            if self.app_state.search_text == search_text:
                msg_box = QMessageBox(self.app)
                msg_box.setIcon(QMessageBox.Icon.Information)
                msg_box.setWindowTitle(tr('ui.search_tab'))
                msg_box.setText(tr('ui.no_search_results'))
                msg_box.exec()
                if self.app_state.search_text == search_text:
                    self.app_state.search_text = ''
                    self._current_search_text = ''
                    self.ui_button_text_update.emit('search_button', '🔍')
                    self.ui_button_tooltip_update.emit('search_button', tr('ui.search_placeholder'))
                    self.update_filtered_mods()
        _do_show()

    def _clamp_current_page(self):
        total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
        max_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
        if self.app_state.current_page > max_page:
            self.app_state.current_page = max_page

    def _get_metadata_cache(self):
        if hasattr(self.app_state, 'cache_dir') and self.app_state.cache_dir:
            try:
                return GameBananaMetadataCache(self.app_state.cache_dir)
            except Exception as e:
                logger.warning(f'SearchDisplayController: Failed to initialize metadata cache: {e}', exc_info=True)
        return None

    def _get_installed_mod_keys(self) -> set:
        try:
            if self.mod_service:
                return {k for m in self.mod_service.get_installed_mods_list() if (k := m.get('key') or m.get('mod_key'))}
        except Exception as e:
            logger.warning(f'SearchDisplayController: Error getting installed mod keys: {e}', exc_info=True)
        return set()

    def _remove_active_timer(self, timer):
        try:
            if timer in self._active_search_timers:
                self._active_search_timers.remove(timer)
        except (ValueError, RuntimeError):
            pass

    def _clear_search_timers(self):
        """Stop and delete all active search timers."""
        for timer in self._active_search_timers[:]:
            try:
                timer.stop()
                timer.deleteLater()
            except (RuntimeError, ValueError):
                pass
        self._active_search_timers.clear()

    def _cleanup_load_thread(self, thread):
        try:
            if thread in self._load_more_threads:
                self._load_more_threads.remove(thread)
            if thread.isFinished():
                thread.deleteLater()
            else:

                def cleanup_when_really_finished():
                    try:
                        if thread and thread.isFinished():
                            thread.deleteLater()
                    except Exception:
                        pass
                thread.finished.connect(cleanup_when_really_finished)
        except (RuntimeError, ValueError):
            pass

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
            can_advance = (should_load_more and self.app_state.gamebanana_loading) or (current_page < max_available_page) or (total_mods > 0 and self.app_state.gamebanana_loading)
            if can_advance:
                self.app_state.current_page += 1
                self.update_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in next_page: {e}', exc_info=True)

    def _load_more_gamebanana_mods_if_needed(self, items_needed: int, preferred_game: str | None = None):
        if not self.app_state.mods_loaded:
            return
        if self.app_state.gamebanana_loading:
            return
        self._load_more_threads = [t for t in self._load_more_threads if t and t.isRunning()]
        if self._load_more_threads:
            return
        search_text = self.app_state.search_text
        if search_text and len(search_text.strip()) >= 2:
            self._load_search_results_if_needed(items_needed, preferred_game)
            return
        gamebanana_game = self._get_selected_gamebanana_game()
        games_to_load = {gamebanana_game: GAMEBANANA_GAME_IDS[gamebanana_game]}
        games_to_load_filtered = {}
        for game_name, game_id in games_to_load.items():
            last_page = self.app_state.gamebanana_loaded_pages.get(game_id, 0)
            if last_page < 50:
                games_to_load_filtered[game_name] = game_id
        if not games_to_load_filtered:
            return
        games_to_load = games_to_load_filtered
        preferred_game_key = ''
        if preferred_game:
            preferred_game_key = self._map_modgame_to_gamebanana(preferred_game)
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
            current_thread = QThread.currentThread()
            app_instance = QApplication.instance()
            if app_instance and current_thread != app_instance.thread():
                QMetaObject.invokeMethod(self, lambda: on_all_results_received(), Qt.ConnectionType.QueuedConnection)
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
                existing_keys = {key for mod in self.app_state.all_mods if (key := get_gamebanana_key(mod))}
                new_mods_to_add = [mod for mod in all_new_mods if (key := get_gamebanana_key(mod)) and key not in existing_keys]
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
                    safe_update()
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
        metadata_cache = self._get_metadata_cache()
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
                            trigger_metadata_loading()
                    else:
                        self.app_state.gamebanana_loaded_pages[gid] = 100
                    results_received[0] += 1
                    if results_received[0] >= expected_results:
                        on_all_results_received()
                return on_result
            load_thread.result.connect(make_on_result(game_id, game_name, last_page, start_page, pages_needed))
            load_thread.finished.connect(lambda thread=load_thread: self._cleanup_load_thread(thread))
            self._load_more_threads.append(load_thread)
            load_thread.start()

    def _load_search_results_if_needed(self, items_needed: int, preferred_game: str | None = None):
        if not self.app_state.mods_loaded:
            return
        if self.app_state.gamebanana_loading:
            return
        self._load_more_threads = [t for t in self._load_more_threads if t and t.isRunning()]
        if self._load_more_threads:
            return
        search_text = self.app_state.search_text
        if not search_text or len(search_text.strip()) < 2:
            return
        gamebanana_game = self._get_selected_gamebanana_game()
        game_id = GAMEBANANA_GAME_IDS[gamebanana_game]
        search_key = search_text.strip().lower()
        if not hasattr(self.app_state, 'gamebanana_search_loaded_pages'):
            self.app_state.gamebanana_search_loaded_pages = {}
        if search_key not in self.app_state.gamebanana_search_loaded_pages:
            self.app_state.gamebanana_search_loaded_pages[search_key] = {}
        search_pages = self.app_state.gamebanana_search_loaded_pages[search_key]
        last_page = search_pages.get(game_id, 0)
        current_page = self.app_state.current_page
        pages_needed = sorted(set(list(range(last_page + 1, current_page + 1)) + ([current_page + 1] if current_page + 1 > last_page else [])))
        if not pages_needed:
            return
        self._clear_search_timers()
        self._current_search_text = search_text
        self.app_state.gamebanana_loading = True
        all_new_mods = []
        results_received = [0]
        expected_results = len(pages_needed)
        sort_param = 'best_match'
        search_timeout_timer = QTimer()
        search_timeout_timer.setSingleShot(True)
        self._active_search_timers.append(search_timeout_timer)

        def handle_timeout():
            if self._current_search_text != search_text:
                return
            if self.app_state.gamebanana_loading and self.app_state.search_text == search_text:
                logger.warning('SearchDisplayController: Search timeout after 10 seconds')
                self.app_state.gamebanana_loading = False
                for thread in self._load_more_threads[:]:
                    if isinstance(thread, SearchGameBananaModsThread):
                        thread.cancel()
                if self.app_state.search_text == search_text:
                    self.update_filtered_mods(preserve_page=True)
                    filtered_count = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
                    if filtered_count == 0:
                        self._show_no_results_and_clear_search(search_text)
                    else:
                        self.update_display()
                else:
                    self.update_filtered_mods(preserve_page=True)
                    self.update_display()
                self.update_pagination()
            self._remove_active_timer(search_timeout_timer)
        search_timeout_timer.timeout.connect(handle_timeout)

        def on_all_results_received():
            search_timeout_timer.stop()
            self._remove_active_timer(search_timeout_timer)
            if self._current_search_text != search_text:
                return
            current_thread = QThread.currentThread()
            app_instance = QApplication.instance()
            if app_instance and current_thread != app_instance.thread():
                QMetaObject.invokeMethod(self, lambda: on_all_results_received(), Qt.ConnectionType.QueuedConnection)
                return
            try:
                if self.app_state.search_text != search_text:
                    return
                self.app_state.gamebanana_loading = False
                if not hasattr(self.app_state, 'all_mods'):
                    self.update_filtered_mods(preserve_page=True)
                    self.update_pagination()
                    return
                existing_keys = {k for m in self.app_state.all_mods if (k := get_mod_key(m)) and k.startswith('gb_')}
                new_mods_to_add = [m for m in all_new_mods if (k := get_mod_key(m)) and k.startswith('gb_') and k not in existing_keys]
                if self.app_state.search_text == search_text and new_mods_to_add:
                    self.app_state.extend_all_mods(new_mods_to_add)
                    max_loaded_page = max(pages_needed) if pages_needed else last_page
                    search_pages[game_id] = max(search_pages.get(game_id, 0), max_loaded_page)
                if self.app_state.search_text == search_text:
                    self.update_filtered_mods(preserve_page=True)
                    filtered_count = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
                    if filtered_count == 0:
                        self._show_no_results_and_clear_search(search_text)
                    else:
                        self.update_display()
                self.update_pagination()
                return
            except Exception as e:
                logger.error(f'SearchDisplayController: Error in on_all_results_received: {e}', exc_info=True)
                if self.app_state.search_text == search_text:
                    self.app_state.gamebanana_loading = False
                    self.update_filtered_mods(preserve_page=True)
                    self.update_display()
                self.update_pagination()
        search_timeout_timer.start(10000)
        metadata_cache = self._get_metadata_cache()
        for page in pages_needed:
            search_thread = SearchGameBananaModsThread(game_id=game_id, search_string=search_text, start_page=page, num_pages=1, sort=sort_param, parent=self.app, metadata_cache=metadata_cache)

            def make_on_result(pg):

                def on_result(mods_list):
                    if mods_list:
                        all_new_mods.extend(mods_list)
                        search_pages[game_id] = max(search_pages.get(game_id, 0), pg)
                    results_received[0] += 1
                    if results_received[0] >= expected_results:
                        search_timeout_timer.stop()
                        on_all_results_received()
                return on_result

            def on_priority_metadata_added(count):
                try:
                    logger.info(f'SearchDisplayController: {count} priority search result mods added to metadata queue, restarting metadata loading')
                    if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
                        if hasattr(self.app.refresh_controller, 'metadata_thread') and self.app.refresh_controller.metadata_thread:
                            if self.app.refresh_controller.metadata_thread.isRunning():
                                logger.info('SearchDisplayController: Cancelling current metadata batch to prioritize search results')
                                self.app.refresh_controller.metadata_thread.cancel()
                        self.app.refresh_controller._start_metadata_loading()
                except Exception as e:
                    logger.error(f'SearchDisplayController: Error in on_priority_metadata_added: {e}', exc_info=True)

            search_thread.result.connect(make_on_result(page))
            search_thread.priority_metadata_added.connect(on_priority_metadata_added)
            search_thread.finished.connect(lambda thread=search_thread: self._cleanup_load_thread(thread))
            self._load_more_threads.append(search_thread)
            search_thread.start()

    def show_blocklist_dialog(self):
        try:
            selected_game = self._get_selected_game()
            all_games = ['deltarune', 'deltarunedemo', 'undertale', 'undertaleyellow', 'pizzatower', 'sugaryspire', 'global']
            all_games.extend(g for g in self.blocklist_service.get_all_games() if g not in all_games)
            dialog = BlocklistDialog(self.blocklist_service, selected_game, all_games, self.app)
            dialog.blocklist_changed.connect(self.on_blocklist_changed)
            dialog.exec()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in show_blocklist_dialog: {e}', exc_info=True)

    def on_blocklist_changed(self):
        try:
            self.update_filtered_mods(preserve_page=False)
            self.update_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in on_blocklist_changed: {e}', exc_info=True)

    def show_search_dialog(self):
        if self.app_state.search_text:
            self._clear_search_timers()
            for thread in self._load_more_threads[:]:
                if isinstance(thread, SearchGameBananaModsThread):
                    thread.cancel()
            self.app_state.gamebanana_loading = False
            self._current_search_text = ''
            self.app_state.search_text = ''
            self.ui_button_text_update.emit('search_button', '🔍')
            self.ui_button_tooltip_update.emit('search_button', tr('ui.search_placeholder'))
            self.update_filtered_mods()
        else:
            text, ok = QInputDialog.getText(self.app, tr('ui.search_tab'), tr('ui.search_in_name_description'))
            if ok and text.strip():
                search_text = text.strip()
                search_key = search_text.lower()
                if hasattr(self.app_state, 'gamebanana_search_loaded_pages') and search_key in self.app_state.gamebanana_search_loaded_pages:
                    self.app_state.gamebanana_search_loaded_pages[search_key] = {}
                self.app_state.search_text = search_text
                self.ui_button_text_update.emit('search_button', '↻')
                self.ui_button_tooltip_update.emit('search_button', tr('ui.clear_search_tooltip', text=self.app_state.search_text))
                self.app_state.current_page = 1
                self.update_filtered_mods()
                if self.app_state.mods_loaded:
                    self._load_search_results_if_needed(self.app_state.mods_per_page)

    def _build_filters_and_sort(self):
        hide_wips_without_downloads = self.app_state.local_config.get('hide_wips_without_downloads', False)
        selected_tags = []
        tag_checkboxes = {'tag_textedit': 'textedit', 'tag_customization': 'customization', 'tag_gameplay': 'gameplay', 'tag_other': 'other'}
        for attr_name, tag_value in tag_checkboxes.items():
            if hasattr(self.app, attr_name) and getattr(self.app, attr_name).isChecked():
                selected_tags.append(tag_value)
        selected_game = self._get_selected_game()
        filters = {'tags': selected_tags, 'game': selected_game, 'search_text': self.app_state.search_text, 'hide_banned': True, 'hide_local': True, 'hide_wips_without_downloads': hide_wips_without_downloads, 'status_filter': ['approved', 'pending'], 'exclude_installed': False}
        sort_config = None
        if hasattr(self.app, 'sort_combo'):
            sort_type = self.app.sort_combo.currentIndex()
            reverse = not self.app.sort_ascending
            sort_config = {'sort_type': sort_type, 'reverse': reverse}
        return (filters, sort_config)

    def update_filtered_mods(self, preserve_page=False):
        if self._update_filtered_mods_in_progress:
            self._pending_filter_update = True
            return
        self._update_filtered_mods_in_progress = True
        self._pending_filter_update = False
        try:
            if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
                self.app_state.filtered_mods = []
                if not preserve_page:
                    self.app_state.current_page = 1
                self.update_display()
                return
            if not hasattr(self, '_checked_installed_mods_metadata') or not self._checked_installed_mods_metadata:
                self._check_installed_mods_for_metadata()
                self._checked_installed_mods_metadata = True
            filters, sort_config = self._build_filters_and_sort()
            installed_keys = self._get_installed_mod_keys()
            total_mods_count = len(self.app_state.all_mods) if self.app_state.all_mods else 0
            use_async = total_mods_count > 1000
            if use_async:

                def async_filter():
                    try:
                        filtered_result = filter_and_sort_mods(self.app_state.all_mods, filters, sort_config, blocklist_service=self.blocklist_service, installed_mod_keys=installed_keys)
                        self.app_state.filtered_mods = filtered_result
                        if not preserve_page:
                            self.app_state.current_page = 1
                        else:
                            self._clamp_current_page()
                        self.update_display()
                    except Exception as e:
                        logger.error(f'SearchDisplayController: Error in async_filter: {e}', exc_info=True)
                    finally:
                        self._update_filtered_mods_in_progress = False
                        if self._pending_filter_update:
                            self.update_filtered_mods(preserve_page=preserve_page)
                async_filter()
                return
            if preserve_page and (not self.app_state.auto_sorting) and self.app_state.filtered_mods:
                re_filtered_existing = filter_and_sort_mods(self.app_state.filtered_mods, filters, sort_config=None, blocklist_service=self.blocklist_service, installed_mod_keys=installed_keys)
                existing_filtered_keys = {key for mod in re_filtered_existing if (key := get_mod_key(mod))}
                new_mods_to_filter = []
                for mod in self.app_state.all_mods:
                    key = get_mod_key(mod)
                    if key and key in existing_filtered_keys:
                        continue
                    new_mods_to_filter.append(mod)
                if new_mods_to_filter:
                    new_filtered = filter_and_sort_mods(new_mods_to_filter, filters, sort_config=None, blocklist_service=self.blocklist_service, installed_mod_keys=installed_keys)
                    self.app_state.filtered_mods = re_filtered_existing + new_filtered
                else:
                    self.app_state.filtered_mods = re_filtered_existing
            else:
                self.app_state.filtered_mods = filter_and_sort_mods(self.app_state.all_mods, filters, sort_config, blocklist_service=self.blocklist_service, installed_mod_keys=installed_keys)
            if not preserve_page:
                self.app_state.current_page = 1
            else:
                self._clamp_current_page()
            self.update_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_filtered_mods: {e}', exc_info=True)
        finally:
            self._update_filtered_mods_in_progress = False
            if self._pending_filter_update:
                self.update_filtered_mods(preserve_page=preserve_page)

    def _flush_pending_display(self):
        if self._pending_display_update:
            self._pending_display_update = False
            self.update_display()

    def update_display(self):
        self._update_display_debounce.call(self._do_update_display)

    def _do_update_display(self):
        if self._update_display_in_progress:
            self._pending_display_update = True
            return
        self._update_display_in_progress = True
        try:
            current_thread = QThread.currentThread()
            app_instance = QApplication.instance()
            if app_instance and current_thread != app_instance.thread():
                logger.warning('SearchDisplayController: update_display called from non-main thread, deferring')
                from PyQt6.QtCore import Qt as QtCore
                QMetaObject.invokeMethod(self, 'update_display', QtCore.ConnectionType.QueuedConnection)
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
                self._clamp_current_page()
            if self.app_state.mods_loaded and total_mods > 0 and (not self._load_check_done):
                items_needed = self.app_state.current_page * self.app_state.mods_per_page
                if total_mods < items_needed and (not self.app_state.gamebanana_loading):

                    def deferred_load_check():
                        try:
                            self._load_check_done = True
                            preferred_game = self._determine_preferred_game_for_page(self.app_state.current_page)
                            self._load_more_gamebanana_mods_if_needed(items_needed, preferred_game)
                            self._load_check_done = False
                        except Exception as e:
                            logger.error(f'SearchDisplayController: Error in deferred_load_check: {e}', exc_info=True)
                    deferred_load_check()
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

            def _remove_loading_indicators():
                for i in range(self.app.mod_list_layout.count() - 1):
                    item = self.app.mod_list_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if hasattr(widget, 'objectName') and widget.objectName() == 'loading_indicator':
                            self.app.mod_list_layout.removeWidget(widget)
                            widget.deleteLater()

            if not self.app_state.mods_loaded or (self.app_state.gamebanana_loading and len(current_page_mods) == 0):
                _remove_loading_indicators()
                from PyQt6.QtWidgets import QLabel
                from PyQt6.QtCore import Qt
                loading_label = QLabel(tr('ui.loading_placeholder'))
                loading_label.setObjectName('loading_indicator')
                loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                loading_label.setStyleSheet('font-size: 16px; padding: 20px; color: gray;')
                self.app.mod_list_layout.insertWidget(0, loading_label)
                if not getattr(self.app, '_mods_display_ready_emitted', False) and hasattr(self.app, 'mods_display_ready'):
                    self.app._mods_display_ready_emitted = True
                    self.app.mods_display_ready.emit()
                self._update_display_in_progress = False
                return
            _remove_loading_indicators()

            def get_mod_cache_key(mod):
                key = get_mod_key(mod)
                if key and key.startswith('gb_'):
                    return key
                if key:
                    return f'local_{key}'
                mod_name = getattr(mod, 'name', 'unknown')
                return f'name_{mod_name}'
            current_page_cache_keys = {get_mod_cache_key(mod) for mod in current_page_mods if mod is not None}
            existing_widgets_in_layout = {}
            for i in range(self.app.mod_list_layout.count() - 1):
                item = self.app.mod_list_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, ModCardWidget):
                        if hasattr(widget, 'mod_data') and widget.mod_data:
                            cache_key = get_mod_cache_key(widget.mod_data)
                            existing_widgets_in_layout[cache_key] = (widget, i)
                            if cache_key not in current_page_cache_keys:
                                widget.hide()
                        else:
                            widget.hide()
            self.ui_widget_updates_enabled.emit('mod_list_widget', False)
            widgets_shown = 0
            widgets_created = 0
            BATCH_SIZE = 15
            target_position = 0
            mods_to_process = [(idx, mod) for idx, mod in enumerate(current_page_mods) if mod is not None]
            try:

                def process_batch(batch_start: int):
                    nonlocal target_position, widgets_shown, widgets_created
                    batch_end = min(batch_start + BATCH_SIZE, len(mods_to_process))
                    for batch_idx in range(batch_start, batch_end):
                        idx, mod = mods_to_process[batch_idx]
                        if mod is None:
                            continue
                        try:
                            cache_key = get_mod_cache_key(mod)
                            if cache_key in self.card_widget_cache:
                                card = self.card_widget_cache[cache_key]
                                if hasattr(card, 'mod_data'):
                                    card.mod_data = mod
                                    if hasattr(card, 'update_mod_data'):
                                        card.update_mod_data()
                                    if hasattr(card, 'update_installation_status'):
                                        card.update_installation_status()
                                current_position = None
                                for i in range(self.app.mod_list_layout.count() - 1):
                                    item = self.app.mod_list_layout.itemAt(i)
                                    if item and item.widget() == card:
                                        current_position = i
                                        break
                                if current_position is not None:
                                    if current_position != target_position:
                                        self.app.mod_list_layout.removeWidget(card)
                                        self.app.mod_list_layout.insertWidget(target_position, card)
                                else:
                                    self.app.mod_list_layout.insertWidget(target_position, card)
                                if hasattr(card, 'update_install_button_state'):
                                    card.update_install_button_state()
                                widgets_shown += 1
                                target_position += 1
                            else:
                                parent_widget = self.app.mod_list_widget if hasattr(self.app, 'mod_list_widget') else self.app
                                card = ModCardWidget(mod, parent=parent_widget, parent_app=self.app)
                                card.install_requested.connect(self.mod_ops.on_mod_install_requested)
                                card.uninstall_requested.connect(self.mod_ops.on_mod_uninstall_requested)
                                card.clicked.connect(self.on_mod_clicked)
                                card.details_requested.connect(self.show_details)
                                if hasattr(card, 'update_install_button_state'):
                                    card.update_install_button_state()
                                self.app.mod_list_layout.insertWidget(target_position, card)
                                self.card_widget_cache[cache_key] = card
                                widgets_created += 1
                                widgets_shown += 1
                                target_position += 1
                        except Exception as e:
                            logger.error(f"Error processing card for mod {(mod.name if mod else 'unknown')} at index {start_index + idx}: {e}", exc_info=True)
                            continue
                    if batch_end < len(mods_to_process):
                        process_batch(batch_end)
                    else:
                        finish_widget_processing()

                def finish_widget_processing():
                    widgets_to_hide = []
                    for i in range(self.app.mod_list_layout.count() - 1):
                        item = self.app.mod_list_layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            if isinstance(widget, ModCardWidget):
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
                            if isinstance(widget, ModCardWidget):
                                widget_cache_key = get_mod_cache_key(widget.mod_data) if hasattr(widget, 'mod_data') and widget.mod_data else None
                                if widget_cache_key and widget_cache_key in current_page_cache_keys:
                                    widget.show()
                                elif not widget_cache_key:
                                    widget.show()
                    self.ui_widget_updates_enabled.emit('mod_list_widget', True)
                    self.update_pagination()
                    self._update_display_in_progress = False
                    self._flush_pending_display()
                    self._check_and_emit_ready_if_needed()

                def self_check_and_emit_ready_if_needed():
                    if not self._initial_mods_display_done and self.app_state.current_page == 1:
                        has_mods_to_display = len(current_page_mods) > 0 if current_page_mods else False
                        expected_widget_count = len(current_page_mods) if current_page_mods else 0

                        _ready_retries = 0
                        _MAX_READY_RETRIES = 40

                        def check_and_emit_ready():
                            nonlocal _ready_retries
                            try:
                                app = QApplication.instance()
                                if app:
                                    for _ in range(5):
                                        app.processEvents()
                                widgets_ready = True
                                widget_count = 0
                                visible_widget_count = 0
                                try:
                                    for i in range(self.app.mod_list_layout.count() - 1):
                                        item = self.app.mod_list_layout.itemAt(i)
                                        if item and item.widget():
                                            widget = item.widget()
                                            if isinstance(widget, ModCardWidget):
                                                widget_count += 1
                                                if not widget.isVisible():
                                                    widgets_ready = False
                                                    break
                                                visible_widget_count += 1
                                                if not hasattr(widget, 'mod_data') or widget.mod_data is None:
                                                    widgets_ready = False
                                                    break
                                                if not widget.parent():
                                                    widgets_ready = False
                                                    break
                                                if widget.width() <= 0 or widget.height() <= 0:
                                                    widgets_ready = False
                                                    break
                                except Exception as e:
                                    logger.warning(f'Error checking widget readiness: {e}')
                                    widgets_ready = False
                                should_emit = False
                                if has_mods_to_display and expected_widget_count > 0:
                                    if widgets_ready and widget_count >= expected_widget_count and (visible_widget_count >= expected_widget_count):
                                        should_emit = True
                                        logger.info(f'SearchDisplayController: First page cards ready ({visible_widget_count}/{expected_widget_count} visible widgets)')
                                    else:
                                        logger.debug(f'SearchDisplayController: First page not ready yet - widgets: {widget_count}/{expected_widget_count}, visible: {visible_widget_count}/{expected_widget_count}')
                                elif expected_widget_count == 0 and (not has_mods_to_display):
                                    should_emit = True
                                    logger.info('SearchDisplayController: First page ready (empty), mods may still be loading')
                                if should_emit:
                                    self._initial_mods_display_done = True
                                    if hasattr(self.app, 'mods_display_ready'):
                                        logger.info(f'SearchDisplayController: First page cards ready ({visible_widget_count} widgets visible), emitting mods_display_ready signal')
                                        self.app._mods_display_ready_emitted = True
                                        if app:
                                            app.processEvents()
                                        self.app.mods_display_ready.emit()
                                else:
                                    _ready_retries += 1
                                    if _ready_retries < _MAX_READY_RETRIES:
                                        logger.debug('SearchDisplayController: First page not ready, will check again')
                                        QTimer.singleShot(150, check_and_emit_ready)
                                    else:
                                        logger.debug(f'SearchDisplayController: Gave up waiting for first page after {_MAX_READY_RETRIES} retries, emitting mods_display_ready anyway')
                                        self._initial_mods_display_done = True
                                        if hasattr(self.app, 'mods_display_ready') and not self.app._mods_display_ready_emitted:
                                            self.app._mods_display_ready_emitted = True
                                            self.app.mods_display_ready.emit()
                            except Exception as e:
                                logger.error(f'Error in check_and_emit_ready: {e}')
                        check_and_emit_ready()
                self._check_and_emit_ready_if_needed = self_check_and_emit_ready_if_needed
                if mods_to_process:
                    process_batch(0)
                else:
                    finish_widget_processing()
            except Exception as e:
                logger.error(f'SearchDisplayController: Error in batch processing: {e}', exc_info=True)
                self.ui_widget_updates_enabled.emit('mod_list_widget', True)
                self._update_display_in_progress = False
                self._flush_pending_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_display: {e}', exc_info=True)
        finally:
            if self._update_display_in_progress:
                self._update_display_in_progress = False
                self._flush_pending_display()

    def update_pagination(self):
        if not hasattr(self.app, 'page_label') or not hasattr(self.app, 'prev_page_btn') or (not hasattr(self.app, 'next_page_btn')):
            return
        self.ui_button_text_update.emit('page_label', tr('ui.page_number', page=self.app_state.current_page))
        self.ui_button_enabled_update.emit('prev_page_btn', self.app_state.current_page > 1)
        total_mods = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
        current_page_mods = total_mods - (self.app_state.current_page - 1) * self.app_state.mods_per_page
        has_more_mods = current_page_mods > self.app_state.mods_per_page
        can_load_more = self.app_state.mods_loaded and (not self.app_state.gamebanana_loading)
        self.ui_button_enabled_update.emit('next_page_btn', has_more_mods or can_load_more)

    @staticmethod
    def _refresh_card(widget):
        """Refresh a single card widget's data, status, and button state."""
        if hasattr(widget, 'update_mod_data'):
            widget.update_mod_data()
        widget.update_installation_status()
        if hasattr(widget, 'update_install_button_state'):
            widget.update_install_button_state()

    def update_search_cards(self):
        mod_list_widget = getattr(self.app, 'mod_list_widget', None)
        if mod_list_widget:
            mod_list_widget.setUpdatesEnabled(False)
        try:
            for widget in self._iter_layout_cards():
                try:
                    self._refresh_card(widget)
                except Exception:
                    pass
        finally:
            if mod_list_widget:
                mod_list_widget.setUpdatesEnabled(True)

    def on_mod_clicked(self, mod):
        for widget in self._iter_layout_cards():
            if widget.mod_data == mod:
                self.clear_all_selections()
                widget.set_selected(True)
                break

    def show_details(self, mod_data):
        source_card = None
        for widget in self._iter_layout_cards():
            if widget.mod_data == mod_data:
                source_card = widget
                break
        show_mod_details_overlay(self.app, mod_data, source_card=source_card)

    def clear_all_selections(self):
        for widget in self._iter_layout_cards():
            widget.set_selected(False)

    def _cleanup_details_threads(self):
        if not self._current_details_thread:
            return
        thread = self._current_details_thread
        self._current_details_thread = None
        try:
            if hasattr(thread, 'cancel'):
                thread.cancel()
            thread.blockSignals(True)
            for signal_name in ('mod_updated', 'finished', 'progress'):
                try:
                    getattr(thread, signal_name).disconnect()
                except (TypeError, RuntimeError, AttributeError):
                    pass
            thread.blockSignals(False)
            if not thread.isRunning():
                thread.deleteLater()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error cleaning up details thread: {e}', exc_info=True)

    def _get_selected_game(self) -> str:
        """Return the currently selected game from the combo box, defaulting to 'deltarune'."""
        if hasattr(self.app, 'modgame_combo'):
            return self.app.modgame_combo.currentData() or 'deltarune'
        return 'deltarune'

    def _get_selected_gamebanana_game(self) -> str:
        mapped = self._map_modgame_to_gamebanana(self._get_selected_game())
        return mapped if mapped in GAMEBANANA_GAME_IDS else 'deltarune'

    @staticmethod
    def _map_modgame_to_gamebanana(game: str) -> str:
        key = (game or '').lower()
        return key if key in GAMEBANANA_GAME_IDS else ''

    def load_mods_for_selected_game(self):
        if not hasattr(self.app, 'modgame_combo'):
            return
        gamebanana_game = self._get_selected_gamebanana_game()
        if not gamebanana_game:
            gamebanana_game = 'deltarune'
        game_id = GAMEBANANA_GAME_IDS.get(gamebanana_game)
        if not game_id:
            return
        last_page = self.app_state.gamebanana_loaded_pages.get(game_id, 0)
        if last_page > 0:
            self.update_filtered_mods()
            return
        if self.app_state.gamebanana_loading:
            return
        self.app_state.gamebanana_loading = True
        self.app_state.filtered_mods = []
        self.update_display()
        metadata_cache = self._get_metadata_cache()
        sort_param = getattr(self.app_state, 'gamebanana_sort', 'default')
        load_thread = LoadMoreGameBananaModsThread(game_id, start_page=1, num_pages=3, sort=sort_param, parent=self.app, metadata_cache=metadata_cache)

        def on_result(mods_list):
            try:
                self.app_state.gamebanana_loading = False
                if mods_list:
                    existing_ids = {m.get_gamebanana_mod_id() for m in self.app_state.all_mods if m.is_gamebanana_mod() and m.get_gamebanana_mod_id()}
                    new_mods_to_add = [m for m in mods_list if m.is_gamebanana_mod() and m.get_gamebanana_mod_id() and (m.get_gamebanana_mod_id() not in existing_ids)]
                    if new_mods_to_add:
                        self.app_state.extend_all_mods(new_mods_to_add)
                        pages_loaded = 3
                        self.app_state.gamebanana_loaded_pages[game_id] = pages_loaded
                        mods_needing = [
                            mid for mod in new_mods_to_add
                            if (mid := get_gamebanana_mod_id(mod)) and self._mod_needs_metadata(mod)
                        ]
                        self._queue_mods_for_metadata(mods_needing)
                        self.update_filtered_mods()
                else:
                    self.app_state.gamebanana_loaded_pages[game_id] = 100
                    self.update_filtered_mods()
            except Exception as e:
                logger.error(f'SearchDisplayController: Error in on_result for game load: {e}', exc_info=True)
                self.app_state.gamebanana_loading = False
                self.update_filtered_mods()
        load_thread.result.connect(on_result)
        load_thread.start()

    def _determine_preferred_game_for_page(self, page_num: int) -> str:
        try:
            filtered = self.app_state.filtered_mods or []
            if not filtered:
                return ''
            per_page = self.app_state.mods_per_page or GAMEBANANA_PER_PAGE
            idx = min(max(0, (page_num - 1) * per_page), len(filtered) - 1)
            return getattr(filtered[idx], 'game', None) or getattr(filtered[idx], 'modgame', '') or ''
        except Exception:
            return ''

    def _check_installed_mods_for_metadata(self):
        try:
            if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
                return
            mods_needing = [
                mod_id_str
                for mod in self.app_state.all_mods
                if hasattr(mod, 'is_gamebanana_mod') and mod.is_gamebanana_mod()
                and (mod_id_str := get_gamebanana_mod_id(mod))
                and self._mod_needs_metadata(mod)
            ]
            self._queue_mods_for_metadata(mods_needing)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _check_installed_mods_for_metadata: {e}', exc_info=True)

    def _update_cards_for_mods(self, mod_ids: list):
        try:
            mod_ids_set = set(mod_ids)
            for widget in self._iter_layout_cards():
                mod = widget.mod_data
                if mod and mod.is_gamebanana_mod():
                    mod_id = mod.get_gamebanana_mod_id()
                    if mod_id and mod_id in mod_ids_set:
                        try:
                            self._refresh_card(widget)
                        except Exception as e:
                            logger.warning(f'SearchDisplayController: Error updating card for mod {mod_id}: {e}')
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _update_cards_for_mods: {e}', exc_info=True)

    def update_all_cards_labels(self):
        try:
            for cache_key, card in self.card_widget_cache.items():
                try:
                    if hasattr(card, 'update_labels_text'):
                        card.update_labels_text()
                    if hasattr(card, '_update_style'):
                        card._update_style()
                except Exception as e:
                    logger.warning(f'SearchDisplayController: Error updating labels for card {cache_key}: {e}')
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_all_cards_labels: {e}', exc_info=True)
