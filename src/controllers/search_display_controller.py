"""Controller for search display and mod filtering.

This module manages the search interface, mod filtering, sorting, pagination,
and interaction with mod plaques in the search results.
"""
from services.mod_filter_service import filter_and_sort_mods
from utils.mod_utils import get_mod_key, get_gamebanana_key, get_gamebanana_mod_id
from PyQt6.QtWidgets import QInputDialog, QMessageBox
from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from services.localization_service import tr
from services.blocklist_service import BlocklistManager
from ui.dialogs.mod_details_dialog import open_mod_details_dialog
from ui.dialogs.blocklist_dialog import BlocklistDialog
from ui.widgets.mod.mod_plaque_widget import ModPlaqueWidget
from workers.gamebanana.load_more_worker import LoadMoreGameBananaModsThread
from workers.gamebanana.search_worker import SearchGameBananaModsThread
from adapters.gamebanana_cache import GameBananaMetadataCache
from config.constants import GAMEBANANA_GAME_IDS, GAMEBANANA_PER_PAGE
from ui.utils.ui_utils import DebounceTimer
import logging
logger = logging.getLogger(__name__)


class SearchDisplayController(QObject):
    """Manages search display, filtering, and mod interaction in search results."""
    ui_button_text_update = pyqtSignal(str, str)
    ui_button_tooltip_update = pyqtSignal(str, str)
    ui_button_enabled_update = pyqtSignal(str, bool)
    ui_label_text_update = pyqtSignal(str, str)
    ui_combo_data_requested = pyqtSignal(str)
    combo_data_received = pyqtSignal(str, object)
    ui_layout_update_requested = pyqtSignal(str, list)
    ui_layout_clear_requested = pyqtSignal(str)
    ui_widget_updates_enabled = pyqtSignal(str, bool)

    def __init__(self, app_state, feedback_service, mod_service, mod_ops, app_window):
        """Initialize the search display controller.

        Args:
            app_state: Application state manager.
            feedback_service: User feedback and dialog manager.
            mod_service: Mod management operations.
            mod_ops: Mod operations controller.
            app_window: Main application window reference.
        """
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
        self._pending_metadata_updates = {}
        self._metadata_update_timer = None
        self.plaque_widget_cache: dict[str, ModPlaqueWidget] = {}
        self._update_display_debounce = DebounceTimer(delay_ms=200)
        self._initial_mods_display_done = False
        self._active_search_timers = []
        self._current_search_text = ''
        self._update_filtered_mods_in_progress = False
        self._pending_filter_update = False

    def _get_metadata_cache(self):
        """Get the metadata cache instance.

        Returns:
            GameBananaMetadataCache instance or None.
        """
        if hasattr(self.app_state, 'cache_dir') and self.app_state.cache_dir:
            try:
                return GameBananaMetadataCache(self.app_state.cache_dir)
            except Exception as e:
                logger.warning(f'SearchDisplayController: Failed to initialize metadata cache: {e}', exc_info=True)
        return None

    def _get_installed_mod_keys(self) -> set:
        """Get set of installed mod keys for filtering.

        Returns:
            Set of mod keys that are installed in the library.
        """
        installed_keys = set()
        try:
            if hasattr(self, 'mod_service') and self.mod_service:
                installed_mods = self.mod_service.get_installed_mods_list()
                for mod_info in installed_mods:
                    key = mod_info.get('key') or mod_info.get('mod_key')
                    if key:
                        installed_keys.add(key)
        except Exception as e:
            logger.warning(f'SearchDisplayController: Error getting installed mod keys: {e}', exc_info=True)
        return installed_keys

    def _cleanup_load_thread(self, thread):
        """Clean up a load more thread.

        Args:
            thread: Thread to clean up.
        """
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
        selected_game = 'deltarune'
        if hasattr(self.app, 'modgame_combo'):
            selected_game = self.app.modgame_combo.currentData() or 'deltarune'
        gamebanana_game = self._map_modgame_to_gamebanana(selected_game)
        if not gamebanana_game:
            gamebanana_game = 'deltarune'
        if gamebanana_game not in GAMEBANANA_GAME_IDS:
            gamebanana_game = 'deltarune'
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
                            QTimer.singleShot(500, trigger_metadata_loading)
                    else:
                        self.app_state.gamebanana_loaded_pages[gid] = 100
                    results_received[0] += 1
                    if results_received[0] >= expected_results:
                        QTimer.singleShot(0, on_all_results_received)
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
        selected_game = 'deltarune'
        if hasattr(self.app, 'modgame_combo'):
            selected_game = self.app.modgame_combo.currentData() or 'deltarune'
        gamebanana_game = self._map_modgame_to_gamebanana(selected_game)
        if not gamebanana_game:
            gamebanana_game = 'deltarune'
        if gamebanana_game not in GAMEBANANA_GAME_IDS:
            gamebanana_game = 'deltarune'
        game_id = GAMEBANANA_GAME_IDS[gamebanana_game]
        search_key = search_text.strip().lower()
        if not hasattr(self.app_state, 'gamebanana_search_loaded_pages'):
            self.app_state.gamebanana_search_loaded_pages = {}
        if search_key not in self.app_state.gamebanana_search_loaded_pages:
            self.app_state.gamebanana_search_loaded_pages[search_key] = {}
        search_pages = self.app_state.gamebanana_search_loaded_pages[search_key]
        last_page = search_pages.get(game_id, 0)
        current_page = self.app_state.current_page
        pages_needed = []
        if current_page > last_page:
            for page in range(last_page + 1, current_page + 1):
                pages_needed.append(page)
        next_page = current_page + 1
        if next_page > last_page:
            pages_needed.append(next_page)
        if not pages_needed:
            return
        for timer in self._active_search_timers[:]:
            try:
                timer.stop()
                timer.deleteLater()
            except (RuntimeError, ValueError):
                pass
        self._active_search_timers.clear()
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

                        def show_no_results_dialog():
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
                        QTimer.singleShot(100, show_no_results_dialog)
                    else:
                        self.update_display()
                else:
                    self.update_filtered_mods(preserve_page=True)
                    self.update_display()
                self.update_pagination()
            try:
                if search_timeout_timer in self._active_search_timers:
                    self._active_search_timers.remove(search_timeout_timer)
            except (ValueError, RuntimeError):
                pass
        search_timeout_timer.timeout.connect(handle_timeout)

        def on_all_results_received():
            search_timeout_timer.stop()
            try:
                if search_timeout_timer in self._active_search_timers:
                    self._active_search_timers.remove(search_timeout_timer)
            except (ValueError, RuntimeError):
                pass
            if self._current_search_text != search_text:
                return
            from PyQt6.QtCore import QThread
            from PyQt6.QtWidgets import QApplication
            current_thread = QThread.currentThread()
            app_instance = QApplication.instance()
            if app_instance and current_thread != app_instance.thread():
                QTimer.singleShot(0, on_all_results_received)
                return
            try:
                if self.app_state.search_text != search_text:
                    return
                self.app_state.gamebanana_loading = False
                if not hasattr(self.app_state, 'all_mods'):
                    self.update_filtered_mods(preserve_page=True)
                    self.update_pagination()
                    return
                existing_keys = {getattr(m, 'key', None) or getattr(m, 'mod_key', None) for m in self.app_state.all_mods if (getattr(m, 'key', None) or getattr(m, 'mod_key', None)) and (getattr(m, 'key', None) or getattr(m, 'mod_key', None)).startswith('gb_')}
                new_mods_to_add = [m for m in all_new_mods if (getattr(m, 'key', None) or getattr(m, 'mod_key', None)) and (getattr(m, 'key', None) or getattr(m, 'mod_key', None)).startswith('gb_') and ((getattr(m, 'key', None) or getattr(m, 'mod_key', None)) not in existing_keys)]
                if self.app_state.search_text == search_text and new_mods_to_add:
                    self.app_state.extend_all_mods(new_mods_to_add)
                    max_loaded_page = max(pages_needed) if pages_needed else last_page
                    search_pages[game_id] = max(search_pages.get(game_id, 0), max_loaded_page)
                if self.app_state.search_text == search_text:
                    self.update_filtered_mods(preserve_page=True)
                    filtered_count = len(self.app_state.filtered_mods) if self.app_state.filtered_mods else 0
                    if filtered_count == 0:

                        def show_no_results_dialog():
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
                        QTimer.singleShot(100, show_no_results_dialog)
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
                        QTimer.singleShot(0, on_all_results_received)
                return on_result

            def on_priority_metadata_added(count):
                try:
                    logger.info(f'SearchDisplayController: {count} priority search result mods added to metadata queue, restarting metadata loading')
                    if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
                        if hasattr(self.app.refresh_controller, 'metadata_thread') and self.app.refresh_controller.metadata_thread:
                            if self.app.refresh_controller.metadata_thread.isRunning():
                                logger.info('SearchDisplayController: Cancelling current metadata batch to prioritize search results')
                                self.app.refresh_controller.metadata_thread.cancel()
                        QTimer.singleShot(100, lambda: self.app.refresh_controller._start_metadata_loading())
                except Exception as e:
                    logger.error(f'SearchDisplayController: Error in on_priority_metadata_added: {e}', exc_info=True)

            search_thread.result.connect(make_on_result(page))
            search_thread.priority_metadata_added.connect(on_priority_metadata_added)
            search_thread.finished.connect(lambda thread=search_thread: self._cleanup_load_thread(thread))
            self._load_more_threads.append(search_thread)
            search_thread.start()

    def show_blocklist_dialog(self):
        try:
            selected_game = 'deltarune'
            if hasattr(self.app, 'modgame_combo'):
                selected_game = self.app.modgame_combo.currentData() or 'deltarune'
            all_games = ['deltarune', 'deltarunedemo', 'undertale', 'undertaleyellow', 'pizzatower', 'sugaryspire']
            all_games.append('global')
            existing_games = self.blocklist_service.get_all_games()
            for game in existing_games:
                if game not in all_games:
                    all_games.append(game)
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
            for timer in self._active_search_timers[:]:
                try:
                    timer.stop()
                    timer.deleteLater()
                except (RuntimeError, ValueError):
                    pass
            self._active_search_timers.clear()
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
                    QTimer.singleShot(100, lambda: self._load_search_results_if_needed(self.app_state.mods_per_page))

    def _build_filters_and_sort(self):
        hide_mods_without_files = self.app_state.local_config.get('hide_mods_without_files', False)
        selected_tags = []
        tag_checkboxes = {'tag_textedit': 'textedit', 'tag_customization': 'customization', 'tag_gameplay': 'gameplay', 'tag_other': 'other'}
        for attr_name, tag_value in tag_checkboxes.items():
            if hasattr(self.app, attr_name) and getattr(self.app, attr_name).isChecked():
                selected_tags.append(tag_value)
        selected_game = 'deltarune'
        if hasattr(self.app, 'modgame_combo'):
            selected_game = self.app.modgame_combo.currentData() or 'deltarune'
        filters = {'tags': selected_tags, 'game': selected_game, 'search_text': self.app_state.search_text, 'hide_banned': True, 'hide_local': True, 'hide_mods_without_files': hide_mods_without_files, 'status_filter': ['approved', 'pending'], 'exclude_installed': False}
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
                            total_mods = len(self.app_state.filtered_mods)
                            max_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
                            if self.app_state.current_page > max_page:
                                self.app_state.current_page = max_page
                        self.update_display()
                    except Exception as e:
                        logger.error(f'SearchDisplayController: Error in async_filter: {e}', exc_info=True)
                    finally:
                        self._update_filtered_mods_in_progress = False
                        if self._pending_filter_update:
                            QTimer.singleShot(100, lambda: self.update_filtered_mods(preserve_page=preserve_page))
                QTimer.singleShot(0, async_filter)
                return
            if preserve_page and (not self.app_state.auto_sorting) and self.app_state.filtered_mods:
                existing_filtered_keys = {key for mod in self.app_state.filtered_mods if (key := get_mod_key(mod))}
                new_mods_to_filter = []
                for mod in self.app_state.all_mods:
                    key = get_mod_key(mod)
                    if key and key in existing_filtered_keys:
                        continue
                    new_mods_to_filter.append(mod)
                if new_mods_to_filter:
                    new_filtered = filter_and_sort_mods(new_mods_to_filter, filters, sort_config=None, blocklist_service=self.blocklist_service, installed_mod_keys=installed_keys)
                    self.app_state.filtered_mods = (self.app_state.filtered_mods or []) + new_filtered
            else:
                self.app_state.filtered_mods = filter_and_sort_mods(self.app_state.all_mods, filters, sort_config, blocklist_service=self.blocklist_service, installed_mod_keys=installed_keys)
            if not preserve_page:
                self.app_state.current_page = 1
            else:
                total_mods = len(self.app_state.filtered_mods)
                max_page = max(1, (total_mods - 1) // self.app_state.mods_per_page + 1) if total_mods > 0 else 1
                if self.app_state.current_page > max_page:
                    self.app_state.current_page = max_page
            self.update_display()
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_filtered_mods: {e}', exc_info=True)
        finally:
            self._update_filtered_mods_in_progress = False
            if self._pending_filter_update:
                QTimer.singleShot(100, lambda: self.update_filtered_mods(preserve_page=preserve_page))

    def update_display(self):
        self._update_display_debounce.call(self._do_update_display)

    def _do_update_display(self):
        """Perform the actual update of the mod search display.

        This is the core method that updates the visible mod list based on
        current filters, pagination, and search criteria. It handles thread
        safety, page management, and dynamic loading of GameBanana mods.

        This method handles:
        - Thread safety checks (defers if not on main thread)
        - Page boundary validation and correction
        - Dynamic loading of additional mods when needed
        - Creating and arranging mod plaque widgets
        - Managing empty states and loading indicators
        - Updating pagination controls
        - Handling chapter mode display
        - Managing selection state and UI updates

        The method is protected against concurrent execution and includes
        comprehensive error handling for all display operations.
        """
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
            if self.app_state.gamebanana_loading and len(current_page_mods) == 0:
                for i in range(self.app.mod_list_layout.count() - 1):
                    item = self.app.mod_list_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if hasattr(widget, 'objectName') and widget.objectName() == 'loading_indicator':
                            self.app.mod_list_layout.removeWidget(widget)
                            widget.deleteLater()
                from PyQt6.QtWidgets import QLabel
                from PyQt6.QtCore import Qt
                loading_label = QLabel(tr('ui.loading_placeholder'))
                loading_label.setObjectName('loading_indicator')
                loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                loading_label.setStyleSheet('font-size: 16px; padding: 20px; color: gray;')
                self.app.mod_list_layout.insertWidget(0, loading_label)
                self._update_display_in_progress = False
                return
            for i in range(self.app.mod_list_layout.count() - 1):
                item = self.app.mod_list_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if hasattr(widget, 'objectName') and widget.objectName() == 'loading_indicator':
                        self.app.mod_list_layout.removeWidget(widget)
                        widget.deleteLater()

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
                    if isinstance(widget, ModPlaqueWidget):
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
            BATCH_DELAY_MS = 10
            target_position = 0
            mods_to_process = [(idx, mod) for idx, mod in enumerate(current_page_mods) if mod is not None]
            try:

                def process_batch(batch_start: int):
                    nonlocal target_position, widgets_shown, widgets_created
                    batch_end = min(batch_start + BATCH_SIZE, len(mods_to_process))
                    from PyQt6.QtWidgets import QApplication
                    app = QApplication.instance()
                    for batch_idx in range(batch_start, batch_end):
                        idx, mod = mods_to_process[batch_idx]
                        if mod is None:
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
                            if (batch_idx - batch_start + 1) % 5 == 0 and app:
                                app.processEvents()
                        except Exception as e:
                            logger.error(f"Error processing plaque for mod {(mod.name if mod else 'unknown')} at index {start_index + idx}: {e}", exc_info=True)
                            continue
                    if app:
                        app.processEvents()
                    if batch_end < len(mods_to_process):
                        QTimer.singleShot(BATCH_DELAY_MS, lambda: process_batch(batch_end))
                    else:
                        finish_widget_processing()

                def finish_widget_processing():
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
                                widget_cache_key = get_mod_cache_key(widget.mod_data) if hasattr(widget, 'mod_data') and widget.mod_data else None
                                if widget_cache_key and widget_cache_key in current_page_cache_keys:
                                    widget.show()
                                elif not widget_cache_key:
                                    widget.show()
                    self.ui_widget_updates_enabled.emit('mod_list_widget', True)
                    self.update_pagination()
                    self._update_display_in_progress = False
                    self._check_and_emit_ready_if_needed()

                def self_check_and_emit_ready_if_needed():
                    if not self._initial_mods_display_done and self.app_state.current_page == 1:
                        has_mods_to_display = len(current_page_mods) > 0 if current_page_mods else False
                        expected_widget_count = len(current_page_mods) if current_page_mods else 0

                        def check_and_emit_ready():
                            try:
                                from PyQt6.QtWidgets import QApplication
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
                                            if isinstance(widget, ModPlaqueWidget):
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
                                        logger.info(f'SearchDisplayController: First page plaques ready ({visible_widget_count}/{expected_widget_count} visible widgets)')
                                    else:
                                        logger.debug(f'SearchDisplayController: First page not ready yet - widgets: {widget_count}/{expected_widget_count}, visible: {visible_widget_count}/{expected_widget_count}')
                                elif expected_widget_count == 0 and (not has_mods_to_display):
                                    should_emit = True
                                    logger.info('SearchDisplayController: First page ready (empty), mods may still be loading')
                                if should_emit:
                                    self._initial_mods_display_done = True
                                    if hasattr(self.app, 'mods_display_ready'):
                                        logger.info(f'SearchDisplayController: First page plaques ready ({visible_widget_count} widgets visible), emitting mods_display_ready signal')
                                        self.app._mods_display_ready_emitted = True
                                        if app:
                                            app.processEvents()
                                        QTimer.singleShot(100, lambda: self.app.mods_display_ready.emit())
                                else:
                                    logger.debug('SearchDisplayController: First page not ready, will check again')
                                    QTimer.singleShot(200, check_and_emit_ready)
                            except Exception as e:
                                logger.error(f'Error in check_and_emit_ready: {e}', exc_info=True)
                        QTimer.singleShot(300, check_and_emit_ready)
                self._check_and_emit_ready_if_needed = self_check_and_emit_ready_if_needed
                if mods_to_process:
                    process_batch(0)
                else:
                    finish_widget_processing()
            except Exception as e:
                logger.error(f'SearchDisplayController: Error in batch processing: {e}', exc_info=True)
                self.ui_widget_updates_enabled.emit('mod_list_widget', True)
                self._update_display_in_progress = False
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_display: {e}', exc_info=True)
        finally:
            if self._update_display_in_progress:
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

    def _map_modgame_to_gamebanana(self, game: str) -> str:
        game_value = game
        mapping = {'deltarune': 'deltarune', 'undertale': 'undertale', 'undertaleyellow': 'undertaleyellow', 'pizzatower': 'pizzatower', 'sugaryspire': 'sugaryspire'}
        return mapping.get((game_value or '').lower(), '')

    def load_mods_for_selected_game(self):
        if not hasattr(self.app, 'modgame_combo'):
            return
        selected_game = self.app.modgame_combo.currentData() or 'deltarune'
        gamebanana_game = self._map_modgame_to_gamebanana(selected_game)
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
        from workers.gamebanana.load_more_worker import LoadMoreGameBananaModsThread
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
                        mods_needing_metadata = []
                        for mod in new_mods_to_add:
                            mod_id_str = get_gamebanana_mod_id(mod)
                            if mod_id_str:
                                needs_metadata = False
                                if not hasattr(mod, 'tagline') or not mod.tagline or mod.tagline.strip() == '':
                                    needs_metadata = True
                                if not hasattr(mod, 'downloads') or mod.downloads is None or mod.downloads == 0:
                                    needs_metadata = True
                                if needs_metadata and mod_id_str:
                                    mods_needing_metadata.append(mod_id_str)
                        if mods_needing_metadata:
                            if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata'):
                                self.app_state.gamebanana_mods_needing_metadata = []
                            existing = set(self.app_state.gamebanana_mods_needing_metadata)
                            new_ids = set(mods_needing_metadata)
                            self.app_state.gamebanana_mods_needing_metadata = list(existing | new_ids)
                            logger.info(f'SearchDisplayController: Added {len(new_ids)} mod IDs to metadata loading queue')
                            if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
                                QTimer.singleShot(500, lambda: self.app.refresh_controller._start_metadata_loading())
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
            start_idx = max(0, (page_num - 1) * per_page)
            if start_idx < len(filtered):
                candidate = filtered[start_idx]
            else:
                candidate = filtered[-1]
            return getattr(candidate, 'game', None) or getattr(candidate, 'modgame', '') or ''
        except Exception:
            return ''

    def on_metadata_updated(self, mod_id: str, downloads: int, tagline: str, category: str = ''):
        try:
            if downloads is not None or tagline or category:
                try:
                    if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
                        if hasattr(self.app.refresh_controller, '_current_metadata_batch'):
                            if mod_id in self.app.refresh_controller._current_metadata_batch:
                                self.app.refresh_controller._current_metadata_batch.remove(mod_id)
                                logger.debug(f'SearchDisplayController: Removed mod {mod_id} from current batch after successful load')
                    if hasattr(self.app_state, 'gamebanana_mods_needing_metadata') and self.app_state.gamebanana_mods_needing_metadata:
                        if mod_id in self.app_state.gamebanana_mods_needing_metadata:
                            self.app_state.gamebanana_mods_needing_metadata.remove(mod_id)
                            logger.debug(f'SearchDisplayController: Removed mod {mod_id} from metadata queue after successful load')
                except (ValueError, AttributeError) as e:
                    logger.debug(f'SearchDisplayController: Error removing mod {mod_id} from queue: {e}')
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
            needs_refilter = False
            downloads_changed = False
            if hasattr(self.app_state, 'all_mods') and self.app_state.all_mods:
                for mod in self.app_state.all_mods:
                    mod_id = get_gamebanana_mod_id(mod)
                    if not mod_id or mod_id not in self._pending_metadata_updates:
                        continue
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
                            downloads_changed = True
                        elif mod.downloads != downloads_int:
                            mod.downloads = downloads_int
                            downloads_changed = True
                    if tagline and tagline != 'No description' and (mod.tagline != tagline):
                        mod.tagline = tagline
                    if category:
                        if not hasattr(mod, 'gamebanana_category') or mod.gamebanana_category != category:
                            mod.gamebanana_category = category
                            needs_refilter = True
                    try:
                        mod.has_full_metadata = True
                    except Exception:
                        pass
                    updated_mods.append(mod_id)
            self._pending_metadata_updates.clear()
            sort_needs_resort = False
            sort_type = None
            if hasattr(self.app, 'sort_combo'):
                sort_type = self.app.sort_combo.currentIndex()
                if sort_type == 0 and downloads_changed and (len(updated_mods) > 1):
                    sort_needs_resort = True
            if (sort_needs_resort or needs_refilter) and len(updated_mods) > 1:
                logger.debug(f"SearchDisplayController: Re-sorting mods after metadata update (downloads_changed={downloads_changed}, needs_refilter={needs_refilter}, sort_type={(sort_type if sort_type is not None else 'N/A')}, mods_count={len(updated_mods)})")
                self.update_filtered_mods(preserve_page=True)
            elif updated_mods:
                self._update_plaques_for_mods(updated_mods)
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _apply_pending_metadata_updates: {e}', exc_info=True)
            self._pending_metadata_updates.clear()

    def _check_installed_mods_for_metadata(self):
        try:
            if not hasattr(self.app_state, 'all_mods') or not self.app_state.all_mods:
                return
            mods_needing_metadata = []
            for mod in self.app_state.all_mods:
                if not hasattr(mod, 'is_gamebanana_mod') or not mod.is_gamebanana_mod():
                    continue
                mod_id_str = get_gamebanana_mod_id(mod)
                if not mod_id_str:
                    continue
                needs_metadata = False
                if not hasattr(mod, 'tagline') or not mod.tagline or mod.tagline.strip() == '':
                    needs_metadata = True
                if not hasattr(mod, 'downloads') or mod.downloads is None or mod.downloads == 0:
                    needs_metadata = True
                if hasattr(mod, 'has_full_metadata') and (not mod.has_full_metadata):
                    needs_metadata = True
                if needs_metadata:
                    mods_needing_metadata.append(mod_id_str)
            if mods_needing_metadata:
                if not hasattr(self.app_state, 'gamebanana_mods_needing_metadata'):
                    self.app_state.gamebanana_mods_needing_metadata = []
                existing = set(self.app_state.gamebanana_mods_needing_metadata)
                new_ids = set(mods_needing_metadata)
                self.app_state.gamebanana_mods_needing_metadata = list(existing | new_ids)
                logger.info(f'SearchDisplayController: Added {len(new_ids)} installed mod IDs to metadata loading queue')
                if hasattr(self.app, 'refresh_controller') and self.app.refresh_controller:
                    QTimer.singleShot(500, lambda: self.app.refresh_controller._start_metadata_loading())
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in _check_installed_mods_for_metadata: {e}', exc_info=True)

    def _update_plaques_for_mods(self, mod_ids: list):
        try:
            if not hasattr(self.app, 'mod_list_layout'):
                return
            mod_ids_set = set(mod_ids)
            updated_widgets = []
            for i in range(self.app.mod_list_layout.count() - 1):
                item = self.app.mod_list_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if isinstance(widget, ModPlaqueWidget):
                        mod = widget.mod_data
                        if mod and mod.is_gamebanana_mod():
                            mod_id = mod.get_gamebanana_mod_id()
                            if mod_id and mod_id in mod_ids_set:
                                try:
                                    widget.update_mod_data()
                                    widget.update_installation_status()
                                    if hasattr(widget, 'update_install_button_state'):
                                        widget.update_install_button_state()
                                    updated_widgets.append(widget)
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
                    if hasattr(plaque, '_update_style'):
                        plaque._update_style()
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
                                if hasattr(widget, '_update_style'):
                                    widget._update_style()
                            except Exception as e:
                                logger.warning(f'SearchDisplayController: Error updating labels for widget in layout: {e}')
        except Exception as e:
            logger.error(f'SearchDisplayController: Error in update_all_plaques_labels: {e}', exc_info=True)
