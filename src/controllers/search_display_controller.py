"""Controller for search display and mod filtering."""

import contextlib
import logging

from PyQt6.QtCore import QMetaObject, QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QGridLayout, QInputDialog, QMessageBox

from config.config import QSS_LOADING_LABEL, SEARCH_EXHAUSTED_PAGE_SENTINEL
from models.game_modes import (
    get_gamebanana_game_ids,
    get_search_game_entries,
)
from services.blocklist_service import BlocklistManager
from services.localization_service import tr
from services.mod_filter_service import filter_and_sort_mods
from ui.common.styling import get_theme_color
from ui.dialogs.blocklist_dialog import BlocklistDialog
from ui.utils.ui_utils import DebounceTimer
from ui.widgets.mod.mod_card_widget import ModCardWidget
from ui.widgets.mod.search_mod_card_widget import SearchModCardWidget
from ui.widgets.mod_details_overlay import show_mod_details_overlay
from utils.mod_utils import get_mod_id
from utils.path_utils import colored_icon
from workers.gamebanana.load_more_worker import LoadMoreGameBananaModsThread
from workers.gamebanana.search_worker import SearchGameBananaModsThread

logger = logging.getLogger(__name__)


class SearchDisplayController(QObject):
    """Manages search display, filtering, and mod interaction in search results."""

    ui_button_text_update = pyqtSignal(str, str)
    ui_button_tooltip_update = pyqtSignal(str, str)
    ui_button_icon_update = pyqtSignal(str, object)
    ui_button_enabled_update = pyqtSignal(str, bool)
    ui_combo_data_requested = pyqtSignal(str)
    combo_data_received = pyqtSignal(str, object)
    ui_layout_update_requested = pyqtSignal(str, list)
    ui_layout_clear_requested = pyqtSignal(str)
    ui_widget_updates_enabled = pyqtSignal(str, bool)

    def __init__(
        self, app_state, feedback_service, mod_service, mod_ops, app_window
    ) -> None:
        super().__init__()
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.mod_service = mod_service
        self.mod_ops = mod_ops
        self.app = app_window
        self.blocklist_service = BlocklistManager()
        self._load_more_threads = []
        self._current_details_thread = None
        self._active_search_timers = []
        self._update_display_in_progress = False
        self._pending_display_update = False
        self._update_filtered_mods_in_progress = False
        self._pending_filter_update = False
        self._exhausted_search_keys = set()
        self.card_widget_cache: dict[str, ModCardWidget] = {}
        self._update_display_debounce = DebounceTimer(delay_ms=200)
        self._virtual_scroll_debounce = DebounceTimer(delay_ms=80)
        self._initial_mods_display_done = False

    def _iter_layout_cards(self):
        """Yield all ModCardWidget instances currently in mod_list_layout."""
        if not hasattr(self.app, "mod_list_layout"):
            return
        for i in range(self.app.mod_list_layout.count()):
            item = self.app.mod_list_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ModCardWidget):
                yield item.widget()

    def _mod_list_column_count(self) -> int:
        try:
            return max(1, int(getattr(self.app, "mod_list_columns", 1) or 1))
        except Exception:
            return 1

    def _get_mod_list_available_width(self) -> int:
        scroll = getattr(self.app, "mods_browser_scroll", None)
        if scroll and hasattr(scroll, "viewport"):
            try:
                viewport = scroll.viewport()
                if viewport:
                    return max(0, int(viewport.width()))
            except Exception as e:
                logger.debug(
                    f"_get_mod_list_available_width: failed to read scroll viewport width: {e}",
                    exc_info=True,
                )
        widget = getattr(self.app, "mod_list_widget", None)
        if widget:
            try:
                return max(0, int(widget.width() or widget.sizeHint().width()))
            except Exception as e:
                logger.debug(
                    f"_get_mod_list_available_width: failed to read widget width: {e}",
                    exc_info=True,
                )
        return 0

    def _sync_mod_grid_metrics(self):
        layout = getattr(self.app, "mod_list_layout", None)
        if not layout:
            return False
        config = getattr(self.app_state, "local_config", None)
        spacing = SearchModCardWidget.grid_spacing_for_config(config)
        side_padding = SearchModCardWidget.side_padding_for_config(config)
        available_width = max(
            0, self._get_mod_list_available_width() - side_padding * 2
        )
        card_width = SearchModCardWidget.card_width_for_config(config)
        if available_width > 0:
            columns = max(
                1, (available_width + spacing) // max(1, card_width + spacing)
            )
        else:
            columns = self._mod_list_column_count()
        grid_alignment = Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        metrics_key = (
            int(spacing),
            int(side_padding),
            int(columns),
            int(grid_alignment),
        )
        if getattr(self, "_last_grid_metrics_key", None) == metrics_key:
            return False
        try:
            layout.setHorizontalSpacing(spacing)
            layout.setVerticalSpacing(spacing)
            layout.setContentsMargins(side_padding, 0, side_padding, 0)
            layout.setAlignment(grid_alignment)
        except Exception as e:
            logger.debug(
                f"_sync_mod_grid_metrics: failed to apply layout metrics: {e}",
                exc_info=True,
            )
        self.app.mod_list_columns = max(1, int(columns))
        scroll = getattr(self.app, "mods_browser_scroll", None)
        if scroll:
            with contextlib.suppress(Exception):
                scroll.setAlignment(grid_alignment)
        widget = getattr(self.app, "mod_list_widget", None)
        if widget:
            with contextlib.suppress(Exception):
                widget.updateGeometry()
        if isinstance(layout, QGridLayout):
            try:
                for column in range(
                    max(self._mod_list_column_count(), layout.columnCount() or 0, 6)
                ):
                    layout.setColumnStretch(column, 0)
                    layout.setColumnMinimumWidth(column, 0)
                layout.invalidate()
                self._last_grid_metrics_key = metrics_key
                return True
            except Exception:
                logger.debug(
                    "_sync_mod_grid_metrics: Failed to set layout spacing/margins"
                )
        else:
            self._last_grid_metrics_key = metrics_key
            return True
        return False

    def _place_layout_widget(
        self,
        widget,
        position: int,
        column_span: int = 1,
        alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
    ):
        if not hasattr(self.app, "mod_list_layout"):
            return
        layout = self.app.mod_list_layout
        with contextlib.suppress(Exception):
            layout.removeWidget(widget)

        if isinstance(layout, QGridLayout):
            row, column = divmod(max(0, position), self._mod_list_column_count())
            layout.addWidget(widget, row, column, 1, max(1, column_span), alignment)
        else:
            layout.insertWidget(position, widget)

    def _remove_layout_widget(self, widget):
        if not hasattr(self.app, "mod_list_layout"):
            return
        with contextlib.suppress(Exception):
            self.app.mod_list_layout.removeWidget(widget)

    def refresh_visible_layout(self):
        layout = getattr(self.app, "mod_list_layout", None)
        if not layout:
            return
        metrics_changed = self._sync_mod_grid_metrics()
        if not metrics_changed:
            return
        visible_cards = [
            widget for widget in self._iter_layout_cards() if widget.isVisible()
        ]
        if not visible_cards:
            self.update_pagination()
            return
        self.ui_widget_updates_enabled.emit("mod_list_widget", False)
        try:
            for position, widget in enumerate(visible_cards):
                self._place_layout_widget(widget, position)
            layout.invalidate()
            widget_container = getattr(self.app, "mod_list_widget", None)
            if widget_container:
                widget_container.updateGeometry()
        finally:
            self.ui_widget_updates_enabled.emit("mod_list_widget", True)
            self._maybe_load_more_for_short_viewport()

    def _get_installed_mod_ids(self) -> set:
        try:
            if self.mod_service:
                return {
                    mod_id
                    for m in self.mod_service.get_installed_mods_list()
                    if (mod_id := m.get("id"))
                }
        except Exception as e:
            logger.warning(
                f"SearchDisplayController: Error getting installed mod ids: {e}",
                exc_info=True,
            )
        return set()

    def _has_active_tag_filters(self) -> bool:
        for attr_name in (
            "tag_textedit",
            "tag_customization",
            "tag_gameplay",
            "tag_other",
        ):
            if (
                hasattr(self.app, attr_name)
                and getattr(self.app, attr_name).isChecked()
            ):
                return True
        return False

    def _set_search_btn_icon(self, is_searching: bool):
        tc = get_theme_color(self.app_state.local_config, "main_text")
        icon = colored_icon("reset", tc) if is_searching else colored_icon("search", tc)
        self.ui_button_icon_update.emit("search_button", icon)
        tooltip = (
            tr("ui.clear_search_tooltip", text=self.app_state.search_text)
            if is_searching
            else tr("ui.search_placeholder")
        )
        self.ui_button_tooltip_update.emit("search_button", tooltip)

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
                    except Exception as e:
                        logger.debug(
                            f"_cleanup_load_thread: failed to delete finished thread: {e}",
                            exc_info=True,
                        )

                thread.finished.connect(cleanup_when_really_finished)
        except (RuntimeError, ValueError):
            pass

    def _load_more_gamebanana_mods_if_needed(
        self, items_needed: int | None = None, preferred_game: str | None = None
    ):
        if not self.app_state.mods_loaded or self.app_state.gamebanana_loading:
            return
        self._load_more_threads = [
            t for t in self._load_more_threads if t and t.isRunning()
        ]
        if self._load_more_threads:
            return
        search_text = (self.app_state.search_text or "").strip()
        if search_text:
            self._load_search_results_if_needed(items_needed, preferred_game)
            return
        gamebanana_game = self._get_selected_gamebanana_game()
        game_id = get_gamebanana_game_ids().get(gamebanana_game)
        if not game_id:
            return
        last_page = self.app_state.gamebanana_loaded_pages.get(game_id, 0)
        if last_page >= SEARCH_EXHAUSTED_PAGE_SENTINEL:
            return
        self.app_state.gamebanana_loading = True
        self._show_bottom_loading_indicator()
        sort_param = self._get_selected_sort()
        start_page = max(1, last_page + 1)
        identity = (game_id, start_page, sort_param, "")
        load_thread = LoadMoreGameBananaModsThread(
            game_id, start_page, num_pages=1, sort=sort_param, parent=self.app
        )

        def on_result(mods_list, request_id=identity, thread=load_thread):
            try:
                current_game_id = get_gamebanana_game_ids().get(
                    self._get_selected_gamebanana_game()
                )
                current_search = (self.app_state.search_text or "").strip()
                current_sort = self._get_selected_sort()
                current_page = max(
                    1,
                    self.app_state.gamebanana_loaded_pages.get(request_id[0], 0) + 1,
                )
                if (
                    current_game_id != request_id[0]
                    or current_search != request_id[3]
                    or current_sort != request_id[2]
                    or current_page != request_id[1]
                ):
                    self.app_state.gamebanana_loading = False
                    self._cleanup_load_thread(thread)
                    return
                self.app_state.gamebanana_loading = False
                if mods_list:
                    self.app_state.gamebanana_loaded_pages[game_id] = start_page
                    self._append_unique_gamebanana_mods(mods_list)
                else:
                    self.app_state.gamebanana_loaded_pages[game_id] = (
                        SEARCH_EXHAUSTED_PAGE_SENTINEL
                    )
                self.update_filtered_mods(preserve_page=True)
            except Exception as e:
                logger.error(
                    f"SearchDisplayController: Error loading more GameBanana mods: {e}",
                    exc_info=True,
                )
                self.app_state.gamebanana_loading = False
                self.update_filtered_mods(preserve_page=True)

        load_thread.result.connect(on_result)
        load_thread.finished.connect(
            lambda thread=load_thread: self._cleanup_load_thread(thread)
        )
        self._load_more_threads.append(load_thread)
        load_thread.start()

    def _load_search_results_if_needed(
        self, items_needed: int | None = None, preferred_game: str | None = None
    ):
        if not self.app_state.mods_loaded or self.app_state.gamebanana_loading:
            return
        self._load_more_threads = [
            t for t in self._load_more_threads if t and t.isRunning()
        ]
        if self._load_more_threads:
            return
        search_text = (self.app_state.search_text or "").strip()
        if len(search_text) < 2:
            return
        gamebanana_game = self._get_selected_gamebanana_game()
        game_id = get_gamebanana_game_ids()[gamebanana_game]
        search_key = search_text.lower()
        if not hasattr(self.app_state, "gamebanana_search_loaded_pages"):
            self.app_state.gamebanana_search_loaded_pages = {}
        search_pages = self.app_state.gamebanana_search_loaded_pages.setdefault(
            search_key, {}
        )
        last_page = search_pages.get(game_id, 0)
        if last_page >= SEARCH_EXHAUSTED_PAGE_SENTINEL:
            return
        start_page = max(1, last_page + 1)
        search_sort = self._get_selected_sort()
        search_identity = (game_id, start_page, search_sort, search_text)
        self.app_state.gamebanana_loading = True
        self._show_bottom_loading_indicator()
        search_thread = SearchGameBananaModsThread(
            game_id=game_id,
            search_string=search_text,
            start_page=start_page,
            num_pages=1,
            sort=search_sort,
            parent=self.app,
        )

        def on_result(mods_list, request_id=search_identity, thread=search_thread):
            try:
                current_game_id = get_gamebanana_game_ids().get(
                    self._get_selected_gamebanana_game()
                )
                current_search = (self.app_state.search_text or "").strip()
                current_sort = self._get_selected_sort()
                current_s_pages = getattr(
                    self.app_state, "gamebanana_search_loaded_pages", {}
                )
                current_page = max(
                    1,
                    current_s_pages.get(current_search.lower(), {}).get(request_id[0], 0)
                    + 1,
                )
                if (
                    current_game_id != request_id[0]
                    or current_search != request_id[3]
                    or current_sort != request_id[2]
                    or current_page != request_id[1]
                ):
                    self.app_state.gamebanana_loading = False
                    self._cleanup_load_thread(thread)
                    return
                self.app_state.gamebanana_loading = False
                if mods_list:
                    search_pages[game_id] = start_page
                    self._append_unique_gamebanana_mods(mods_list)
                    self.update_filtered_mods(preserve_page=True)
                    return
                search_pages[game_id] = SEARCH_EXHAUSTED_PAGE_SENTINEL
                self.update_filtered_mods(preserve_page=True)
                if start_page == 1 and not (self.app_state.filtered_mods or []):
                    self._show_no_results_and_clear_search(search_text)
            except Exception as e:
                logger.error(
                    f"SearchDisplayController: Error loading search results: {e}",
                    exc_info=True,
                )
                self.app_state.gamebanana_loading = False
                self.update_filtered_mods(preserve_page=True)

        search_thread.result.connect(on_result)
        search_thread.finished.connect(
            lambda thread=search_thread: self._cleanup_load_thread(thread)
        )
        self._load_more_threads.append(search_thread)
        search_thread.start()

    def _show_no_results_and_clear_search(self, search_text: str):
        if self.app_state.search_text != search_text:
            return
        msg_box = QMessageBox(self.app)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(tr("ui.search_tab"))
        msg_box.setText(tr("ui.no_search_results"))
        msg_box.exec()
        if self.app_state.search_text == search_text:
            self.app_state.search_text = ""
            self._set_search_btn_icon(False)
            self.load_mods_for_selected_game()

    def show_blocklist_dialog(self):
        try:
            selected_game = self._get_selected_game()
            search_games = get_search_game_entries()
            dialog = BlocklistDialog(
                self.blocklist_service, selected_game, search_games, self.app
            )
            dialog.blocklist_changed.connect(self.on_blocklist_changed)
            dialog.exec()
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in show_blocklist_dialog: {e}",
                exc_info=True,
            )

    def on_blocklist_changed(self):
        try:
            self.update_filtered_mods(preserve_page=False)
            self.update_display()
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in on_blocklist_changed: {e}",
                exc_info=True,
            )

    def show_search_dialog(self):
        if self.app_state.search_text:
            self._clear_search_timers()
            for thread in self._load_more_threads[:]:
                if isinstance(thread, SearchGameBananaModsThread):
                    thread.cancel()
            self.app_state.gamebanana_loading = False
            self.app_state.search_text = ""
            self._set_search_btn_icon(False)
            self.load_mods_for_selected_game()
        else:
            text, ok = QInputDialog.getText(
                self.app, tr("ui.search_tab"), tr("ui.search_in_name_description")
            )
            if ok and len(text.strip()) >= 2:
                self.app_state.search_text = text.strip()
                self._set_search_btn_icon(True)
                self.load_mods_for_selected_game()

    def _build_filters_and_sort(self):
        selected_tags = []
        tag_checkboxes = {
            "tag_textedit": "textedit",
            "tag_customization": "customization",
            "tag_gameplay": "gameplay",
            "tag_other": "other",
        }
        for attr_name, tag_value in tag_checkboxes.items():
            if (
                hasattr(self.app, attr_name)
                and getattr(self.app, attr_name).isChecked()
            ):
                selected_tags.append(tag_value)
        selected_game = self._get_selected_game()
        show_nsfw = bool(
            hasattr(self.app, "show_nsfw_checkbox")
            and self.app.show_nsfw_checkbox.isChecked()
        )
        filters = {
            "tags": selected_tags,
            "game": selected_game,
            "search_text": self.app_state.search_text,
            "hide_banned": True,
            "hide_local": True,
            "show_nsfw": show_nsfw,
            "status_filter": ["approved", "pending"],
            "exclude_installed": False,
        }
        return (filters, None)

    def update_filtered_mods(self, preserve_page=False):
        if self._update_filtered_mods_in_progress:
            self._pending_filter_update = True
            return
        self._update_filtered_mods_in_progress = True
        self._pending_filter_update = False
        try:
            if not hasattr(self.app_state, "all_mods") or not self.app_state.all_mods:
                self.app_state.filtered_mods = []
                self.app_state.current_page = 1
                self.update_display()
                return
            filters, sort_config = self._build_filters_and_sort()
            installed_ids = self._get_installed_mod_ids()
            self.app_state.filtered_mods = filter_and_sort_mods(
                self.app_state.all_mods,
                filters,
                sort_config,
                blocklist_service=self.blocklist_service,
                installed_mod_ids=installed_ids,
            )
            if not preserve_page:
                self.app_state.current_page = 1
            self.update_display()
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in update_filtered_mods: {e}",
                exc_info=True,
            )
        finally:
            self._update_filtered_mods_in_progress = False
            if self._pending_filter_update:
                self.update_filtered_mods(preserve_page=preserve_page)

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
                logger.warning(
                    "SearchDisplayController: update_display called from non-main thread, deferring"
                )
                QMetaObject.invokeMethod(
                    self, "update_display", Qt.ConnectionType.QueuedConnection
                )
                self._update_display_in_progress = False
                return
            if not hasattr(self.app_state, "filtered_mods"):
                logger.warning("SearchDisplayController: filtered_mods not available")
                self._update_display_in_progress = False
                return
            self.app_state.current_page = 1
            if not hasattr(self.app, "mod_list_layout"):
                logger.warning("SearchDisplayController: mod_list_layout not available")
                self._update_display_in_progress = False
                return
            self._sync_mod_grid_metrics()
            current_page_mods = list(self.app_state.filtered_mods or [])
            if not hasattr(self.app, "mod_list_widget"):
                logger.warning("SearchDisplayController: mod_list_widget not available")
                self._update_display_in_progress = False
                return

            def _remove_loading_indicators():
                for i in reversed(range(self.app.mod_list_layout.count())):
                    item = self.app.mod_list_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if (
                            hasattr(widget, "objectName")
                            and widget.objectName() == "loading_indicator"
                        ):
                            self._remove_layout_widget(widget)
                            widget.deleteLater()

            def _add_loading_indicator(position: int):
                from PyQt6.QtCore import Qt
                from PyQt6.QtWidgets import QLabel

                loading_label = QLabel(tr("ui.loading_placeholder"))
                loading_label.setObjectName("loading_indicator")
                loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                loading_label.setStyleSheet(QSS_LOADING_LABEL)
                self._place_layout_widget(
                    loading_label,
                    position,
                    column_span=self._mod_list_column_count(),
                    alignment=Qt.AlignmentFlag.AlignCenter,
                )

            if not self.app_state.mods_loaded or (
                self.app_state.gamebanana_loading and len(current_page_mods) == 0
            ):
                _remove_loading_indicators()
                _add_loading_indicator(0)
                if (
                    not getattr(self.app, "_mods_display_ready_emitted", False)
                ) and hasattr(self.app, "mods_display_ready"):
                    self.app._mods_display_ready_emitted = True
                    self.app.mods_display_ready.emit()
                self._update_display_in_progress = False
                return
            _remove_loading_indicators()

            def get_mod_cache_key(mod):
                key = get_mod_id(mod)
                if key and key.startswith("gb_"):
                    return key
                if key:
                    return f"local_{key}"
                mod_name = getattr(mod, "name", "unknown")
                return f"name_{mod_name}"

            current_page_cache_keys = {
                get_mod_cache_key(mod) for mod in current_page_mods if mod is not None
            }
            existing_widgets_in_layout = {}
            for i in range(self.app.mod_list_layout.count()):
                item = self.app.mod_list_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, ModCardWidget):
                        if hasattr(widget, "mod_data") and widget.mod_data:
                            cache_key = get_mod_cache_key(widget.mod_data)
                            existing_widgets_in_layout[cache_key] = (widget, i)
                            if cache_key not in current_page_cache_keys:
                                widget.hide()
                        else:
                            widget.hide()
            self.ui_widget_updates_enabled.emit("mod_list_widget", False)
            widgets_shown = 0
            widgets_created = 0
            batch_size = 15
            target_position = 0
            mods_to_process = [
                (idx, mod)
                for idx, mod in enumerate(current_page_mods)
                if mod is not None
            ]
            try:

                def finish_widget_processing():
                    widgets_to_hide = []
                    for i in range(self.app.mod_list_layout.count()):
                        item = self.app.mod_list_layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            if isinstance(widget, ModCardWidget):
                                widget_cache_key = (
                                    get_mod_cache_key(widget.mod_data)
                                    if hasattr(widget, "mod_data") and widget.mod_data
                                    else None
                                )
                                if (
                                    widget_cache_key
                                    and widget_cache_key not in current_page_cache_keys
                                ):
                                    widgets_to_hide.append(widget)
                    for widget in widgets_to_hide:
                        try:
                            self._remove_layout_widget(widget)
                            widget.hide()
                        except Exception as e:
                            logger.debug(f"Error removing widget from layout: {e}")
                    for i in range(self.app.mod_list_layout.count()):
                        item = self.app.mod_list_layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            if isinstance(widget, ModCardWidget):
                                widget_cache_key = (
                                    get_mod_cache_key(widget.mod_data)
                                    if hasattr(widget, "mod_data") and widget.mod_data
                                    else None
                                )
                                if (
                                    widget_cache_key
                                    and widget_cache_key in current_page_cache_keys
                                ) or not widget_cache_key:
                                    widget.show()
                    _remove_loading_indicators()
                    if self.app_state.gamebanana_loading and current_page_mods:
                        _add_loading_indicator(target_position)
                    self.ui_widget_updates_enabled.emit("mod_list_widget", True)
                    self._update_display_in_progress = False
                    self._flush_pending_display()
                    if (
                        not getattr(self.app, "_mods_display_ready_emitted", False)
                    ) and hasattr(self.app, "mods_display_ready"):
                        self.app._mods_display_ready_emitted = True
                        self.app.mods_display_ready.emit()
                    self._maybe_load_more_for_short_viewport()
                    self._update_virtual_visibility()

                def process_batch(batch_start: int):
                    nonlocal target_position, widgets_shown, widgets_created
                    batch_end = min(batch_start + batch_size, len(mods_to_process))
                    for batch_idx in range(batch_start, batch_end):
                        idx, mod = mods_to_process[batch_idx]
                        if mod is None:
                            continue
                        try:
                            cache_key = get_mod_cache_key(mod)
                            if cache_key in self.card_widget_cache:
                                card = self.card_widget_cache[cache_key]
                                if hasattr(card, "mod_data"):
                                    card.mod_data = mod
                                    if hasattr(card, "_update_style"):
                                        card._update_style()
                                    if hasattr(card, "update_mod_data"):
                                        card.update_mod_data()
                                    if hasattr(card, "update_installation_status"):
                                        card.update_installation_status()
                                self._place_layout_widget(card, target_position)
                                if hasattr(card, "update_action_button_state"):
                                    card.update_action_button_state()
                                widgets_shown += 1
                                target_position += 1
                            else:
                                parent_widget = (
                                    self.app.mod_list_widget
                                    if hasattr(self.app, "mod_list_widget")
                                    else self.app
                                )
                                card = SearchModCardWidget(
                                    mod, parent=parent_widget, parent_app=self.app
                                )
                                card.download_requested.connect(
                                    self.mod_ops.on_mod_download_requested
                                )
                                card.uninstall_requested.connect(
                                    self.mod_ops.on_mod_uninstall_requested
                                )
                                card.clicked.connect(self.on_mod_clicked)
                                card.details_requested.connect(self.show_details)
                                if hasattr(card, "update_action_button_state"):
                                    card.update_action_button_state()
                                self._place_layout_widget(card, target_position)
                                self.card_widget_cache[cache_key] = card
                                widgets_created += 1
                                widgets_shown += 1
                                target_position += 1
                        except Exception as e:
                            logger.error(
                                f"Error processing card for mod {(mod.name if mod else 'unknown')} at index {idx}: {e}",
                                exc_info=True,
                            )
                            continue
                    return batch_end

                current_batch_start = 0
                while current_batch_start < len(mods_to_process):
                    batch_end = process_batch(current_batch_start)
                    current_batch_start = batch_end
                finish_widget_processing()
            except Exception as e:
                logger.error(
                    f"SearchDisplayController: Error in batch processing: {e}",
                    exc_info=True,
                )
                self.ui_widget_updates_enabled.emit("mod_list_widget", True)
                self._update_display_in_progress = False
                self._flush_pending_display()
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in update_display: {e}", exc_info=True
            )
        finally:
            if self._update_display_in_progress:
                self._update_display_in_progress = False
                self._flush_pending_display()

    def _show_bottom_loading_indicator(self):
        """Append a Loading... label at the bottom of the current card list without redrawing existing cards."""
        if not hasattr(self.app, "mod_list_layout"):
            return
        layout = self.app.mod_list_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if (
                item
                and item.widget()
                and getattr(item.widget(), "objectName", lambda: "")()
                == "loading_indicator"
            ):
                return
        from PyQt6.QtWidgets import QLabel

        loading_label = QLabel(tr("ui.loading_placeholder"))
        loading_label.setObjectName("loading_indicator")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_label.setStyleSheet(QSS_LOADING_LABEL)
        self._place_layout_widget(
            loading_label,
            layout.count(),
            column_span=self._mod_list_column_count(),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

    def _maybe_load_more_for_short_viewport(self):
        if self.app_state.gamebanana_loading:
            return
        if self._has_active_tag_filters():
            return
        scroll = getattr(self.app, "mods_browser_scroll", None)
        if not scroll or not hasattr(self.app, "mod_list_widget"):
            return
        try:
            viewport = scroll.viewport()
            viewport_height = viewport.height() if viewport else 0
            content_height = self.app.mod_list_widget.sizeHint().height()
        except Exception:
            viewport_height = 0
            content_height = 0
        if content_height <= viewport_height + 60:
            self._load_more_gamebanana_mods_if_needed()

    def _update_virtual_visibility(self):
        """Suppress repaints for cards far outside the viewport.

        Uses setUpdatesEnabled() instead of setVisible() so the grid layout
        keeps its geometry (no size jumps). Cards are never hidden - only
        their painting is suspended when they are outside the buffer zone.
        """
        scroll = getattr(self.app, "mods_browser_scroll", None)
        if not scroll:
            return
        try:
            viewport = scroll.viewport()
            vp_height = viewport.height() if viewport else 0
        except Exception:
            return
        if vp_height <= 0:
            return
        try:
            scroll_y = scroll.verticalScrollBar().value()
        except Exception:
            return
        buffer = vp_height * 2
        top = scroll_y - buffer
        bottom = scroll_y + vp_height + buffer
        container = getattr(self.app, "mod_list_widget", None)
        if not container:
            return
        for card in self._iter_layout_cards():
            try:
                pos = card.mapTo(container, card.rect().topLeft())
                card_h = card.sizeHint().height() or card.height() or 200
                y = pos.y()
                in_range = (y + card_h) >= top and y <= bottom
                if card.updatesEnabled() != in_range:
                    card.setUpdatesEnabled(in_range)
                    if in_range:
                        card.update()
            except Exception as e:
                logger.debug(
                    f"_update_virtual_visibility: failed to update card visibility state: {e}",
                    exc_info=True,
                )

    def on_scroll_value_changed(self, value: int):
        scroll = getattr(self.app, "mods_browser_scroll", None)
        if not scroll:
            return
        try:
            bar = scroll.verticalScrollBar()
        except Exception:
            return
        if not bar:
            return
        self._virtual_scroll_debounce.call(self._update_virtual_visibility)
        if value >= max(0, bar.maximum() - 120):
            self._load_more_gamebanana_mods_if_needed()

    def _append_unique_gamebanana_mods(self, mods_list):
        if not mods_list:
            return
        existing_keys = {k for m in self.app_state.all_mods if (k := get_mod_id(m))}
        new_mods_to_add = [
            m for m in mods_list if (k := get_mod_id(m)) and k not in existing_keys
        ]
        if new_mods_to_add:
            self.app_state.extend_all_mods(new_mods_to_add)

    def _clear_current_gamebanana_mods(self):
        if not hasattr(self.app_state, "all_mods"):
            return
        self.app_state.all_mods = [
            m for m in self.app_state.all_mods if not m.is_gamebanana_mod()
        ]

    def _get_selected_sort(self):
        if hasattr(self.app, "sort_combo"):
            return self.app.sort_combo.currentData()
        return "relevant"

    def _get_selected_game(self) -> str:
        """Return the currently selected game from the combo box, defaulting to 'deltarune'."""
        if hasattr(self.app, "modgame_combo"):
            return self.app.modgame_combo.currentData() or "deltarune"
        return "deltarune"

    def _get_selected_gamebanana_game(self) -> str:
        mapped = self._map_modgame_to_gamebanana(self._get_selected_game())
        searchable = [entry.id for entry in get_search_game_entries()]
        return (
            mapped
            if mapped in searchable
            else (searchable[0] if searchable else "deltarune")
        )

    @staticmethod
    def _map_modgame_to_gamebanana(game: str) -> str:
        key = (game or "").lower()
        return key if key in get_gamebanana_game_ids() else ""

    def load_mods_for_selected_game(self):
        if not hasattr(self.app, "modgame_combo"):
            return
        gamebanana_game = self._get_selected_gamebanana_game()
        if not gamebanana_game:
            gamebanana_game = "deltarune"
        game_id = get_gamebanana_game_ids().get(gamebanana_game)
        if not game_id:
            return
        self._clear_current_gamebanana_mods()
        self.app_state.gamebanana_loaded_pages[game_id] = 0
        search_key = (self.app_state.search_text or "").strip().lower()
        if search_key:
            self.app_state.gamebanana_search_loaded_pages = {search_key: {game_id: 0}}
        self.app_state.filtered_mods = []
        self.update_display()
        self._load_more_gamebanana_mods_if_needed()

    def update_pagination(self):
        return

    def _flush_pending_display(self):
        if self._pending_display_update:
            self._pending_display_update = False
            self.update_display()

    @staticmethod
    def _refresh_card(widget) -> None:
        if hasattr(widget, "_update_style"):
            widget._update_style()
        if hasattr(widget, "update_mod_data"):
            widget.update_mod_data()
        if hasattr(widget, "update_installation_status"):
            widget.update_installation_status()
        if hasattr(widget, "update_action_button_state"):
            widget.update_action_button_state()

    def on_mod_clicked(self, mod):
        target_widget = None
        for widget in self._iter_layout_cards():
            if widget.mod_data == mod:
                target_widget = widget
                break
        if not target_widget or getattr(target_widget, "is_selected", False):
            return
        self.clear_all_selections(except_widget=target_widget)
        target_widget.set_selected(True)

    def show_details(self, mod_data):
        source_card = None
        for widget in self._iter_layout_cards():
            if widget.mod_data == mod_data:
                source_card = widget
                break
        show_mod_details_overlay(self.app, mod_data, source_card=source_card)

    def clear_all_selections(self, except_widget=None):
        for widget in self._iter_layout_cards():
            if widget is except_widget:
                continue
            if getattr(widget, "is_selected", False):
                widget.set_selected(False)

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
                            logger.warning(
                                f"SearchDisplayController: Error updating card for mod {mod_id}: {e}"
                            )
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in _update_cards_for_mods: {e}",
                exc_info=True,
            )

    def update_all_cards_labels(self):
        try:
            for cache_key, card in self.card_widget_cache.items():
                try:
                    if hasattr(card, "update_labels_text"):
                        card.update_labels_text()
                    if hasattr(card, "_update_style"):
                        card._update_style()
                except Exception as e:
                    logger.warning(
                        f"SearchDisplayController: Error updating labels for card {cache_key}: {e}"
                    )
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in update_all_cards_labels: {e}",
                exc_info=True,
            )

    def update_search_cards(self):
        try:
            self.update_display()
        except Exception as e:
            logger.error(
                f"SearchDisplayController: Error in update_search_cards: {e}",
                exc_info=True,
            )
