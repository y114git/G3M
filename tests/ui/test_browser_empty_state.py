from unittest.mock import Mock

from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.config import SEARCH_EXHAUSTED_PAGE_SENTINEL
from controllers.search_display_controller import SearchDisplayController
from models.game_modes import get_gamebanana_game_ids
from services.localization_service import tr


def test_empty_browser_keeps_query_and_updates_loading_message(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QVBoxLayout(host.mod_list_widget)
    app_state.mods_loaded = True
    app_state.gamebanana_loading = False
    app_state.filtered_mods = []
    app_state.search_text = "unmatched query"
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    controller._sync_mod_grid_metrics = Mock()
    controller._finalize_mod_list_layout_refresh = Mock()
    controller._do_update_display()
    labels = host.mod_list_widget.findChildren(QLabel)
    assert len(labels) == 1
    assert labels[0].text() == tr("ui.no_search_results")
    assert app_state.search_text == "unmatched query"
    controller._show_bottom_loading_indicator()
    assert labels[0].text() == tr("ui.loading_placeholder")
    controller.cleanup()


def test_loading_indicator_is_centered_on_a_themed_full_grid_row(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    host.mod_list_columns = 4
    for column in range(4):
        host.mod_list_layout.addWidget(QLabel(str(column)), 0, column)
    app_state.local_config.update(
        {
            "custom_secondary_text_color": "#abc123",
            "custom_border_color": "#123abc",
        }
    )
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)

    controller._show_bottom_loading_indicator()

    indicator = next(controller._iter_loading_indicators())
    row, column, row_span, column_span = host.mod_list_layout.getItemPosition(
        host.mod_list_layout.indexOf(indicator)
    )
    assert (row, column, row_span, column_span) == (1, 0, 1, 4)
    assert "color: #abc123" in indicator.styleSheet()
    assert "border: 2px solid #123abc" in indicator.styleSheet()
    controller.cleanup()


def test_loading_indicator_is_removed_only_when_a_card_reaches_its_row(
    qtbot, app_state
):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    host.mod_list_columns = 4
    indicator = QLabel("Loading...", host.mod_list_widget)
    indicator.setObjectName("loading_indicator")
    host.mod_list_layout.addWidget(indicator, 1, 0, 1, 4)
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)

    controller._remove_loading_indicator_at_position(4)

    assert host.mod_list_layout.indexOf(indicator) == -1
    controller.cleanup()


def test_pagination_keeps_visible_cards_when_filtering_is_temporarily_empty(
    qtbot, app_state
):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    app_state.mods_loaded = True
    app_state.gamebanana_loading = True
    app_state.filtered_mods = []
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    visible_card = Mock()
    visible_card.isVisible.return_value = True
    controller._iter_layout_cards = Mock(return_value=iter([visible_card]))
    controller._sync_mod_grid_metrics = Mock()
    controller._show_bottom_loading_indicator = Mock()
    controller._remove_centered_loading_indicator = Mock()

    controller._do_update_display()

    controller._show_bottom_loading_indicator.assert_called_once_with()
    controller._remove_centered_loading_indicator.assert_called_once_with()
    controller.cleanup()


def test_append_only_updates_keep_existing_card_widgets(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)

    assert controller._is_append_only_card_update({"first"}, {"first", "second"})
    assert not controller._is_append_only_card_update({"first"}, {"second"})
    controller.cleanup()


def test_virtual_visibility_reenables_each_card_after_a_layout_change(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    card = Mock()
    card.updatesEnabled.return_value = False
    controller._iter_layout_cards = Mock(return_value=iter([card]))

    controller._update_virtual_visibility()

    card.setUpdatesEnabled.assert_called_once_with(True)
    card.update.assert_called_once_with()
    controller.cleanup()


def test_layout_refresh_skips_card_creation_in_progress(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    controller._update_display_in_progress = True
    controller._queue_layout_refresh = Mock()
    controller._sync_mod_grid_metrics = Mock()

    controller.refresh_visible_layout()

    controller._queue_layout_refresh.assert_not_called()
    controller._sync_mod_grid_metrics.assert_not_called()
    controller.cleanup()


def test_initial_loading_indicator_is_centered_in_the_scroll_view(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.mod_list_widget = QWidget()
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    host.mods_browser_scroll = QScrollArea(host)
    host.mods_browser_scroll.resize(600, 400)
    host.mods_browser_scroll.setWidget(host.mod_list_widget)
    host.show()
    qtbot.waitUntil(lambda: host.mods_browser_scroll.viewport().height() > 0)
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)

    assert controller._show_centered_loading_indicator()

    indicator = controller._centered_loading_indicator
    viewport = host.mods_browser_scroll.viewport()
    assert abs(indicator.geometry().center().x() - viewport.rect().center().x()) <= 1
    assert abs(indicator.geometry().center().y() - viewport.rect().center().y()) <= 1
    controller.cleanup()


def test_incomplete_grid_row_stays_buffered_until_the_last_page(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    host.mod_list_columns = 4
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    mods = [object() for _ in range(5)]
    controller._has_pending_gamebanana_pages = Mock(return_value=True)

    assert controller._mods_for_complete_grid_rows(mods) == mods[:4]

    controller._has_pending_gamebanana_pages.return_value = False
    assert controller._mods_for_complete_grid_rows(mods) == mods
    host.mod_list_columns = 100
    controller._has_pending_gamebanana_pages.return_value = True
    assert controller._mods_for_complete_grid_rows(mods) == mods
    controller.cleanup()


def test_pending_gamebanana_pages_require_a_completed_fetch(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    game_id = get_gamebanana_game_ids()["deltarune"]

    assert not controller._has_pending_gamebanana_pages()
    app_state.gamebanana_loaded_pages[game_id] = 0
    assert not controller._has_pending_gamebanana_pages()
    app_state.gamebanana_loaded_pages[game_id] = 1
    assert controller._has_pending_gamebanana_pages()
    app_state.gamebanana_loaded_pages[game_id] = SEARCH_EXHAUSTED_PAGE_SENTINEL
    assert not controller._has_pending_gamebanana_pages()
    app_state.search_text = "query"
    del app_state.gamebanana_search_loaded_pages
    assert not controller._has_pending_gamebanana_pages()
    controller.cleanup()


def test_grid_metric_cache_keeps_the_calculated_column_count(qtbot, app_state):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QGridLayout(host.mod_list_widget)
    host.mod_list_columns = 1
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    controller._get_mod_list_available_width = Mock(return_value=1500)

    assert controller._sync_mod_grid_metrics()
    columns = host.mod_list_columns
    host.mod_list_columns = 1

    assert not controller._sync_mod_grid_metrics()
    assert host.mod_list_columns == columns
    assert columns > 1
    controller.cleanup()


def test_failed_search_can_retry_without_exhausting_query(
    qtbot, app_state, monkeypatch
):
    host = QWidget()
    qtbot.addWidget(host)
    host.mod_list_widget = QWidget(host)
    host.mod_list_layout = QVBoxLayout(host.mod_list_widget)
    app_state.mods_loaded = True
    app_state.gamebanana_loading = False
    app_state.filtered_mods = []
    app_state.search_text = "unmatched query"
    controller = SearchDisplayController(app_state, Mock(), Mock(), Mock(), host)
    controller._sync_mod_grid_metrics = Mock()
    controller._finalize_mod_list_layout_refresh = Mock()
    controller._get_selected_gamebanana_game = Mock(return_value="deltarune")
    controller._get_selected_sort = Mock(return_value="relevant")
    controller.update_filtered_mods = Mock()
    request = Mock(side_effect=[None, {"_aRecords": []}])
    monkeypatch.setattr(
        "workers.gamebanana.search_worker.GameBananaAPI.search_mods", request
    )
    controller._load_search_results_if_needed()
    qtbot.waitUntil(lambda: bool(controller._search_error))
    qtbot.waitUntil(lambda: not controller._load_more_threads)
    controller._do_update_display()
    assert app_state.gamebanana_search_loaded_pages["unmatched query"] == {}
    assert app_state.search_text == "unmatched query"
    controller._load_search_results_if_needed()
    assert request.call_count == 1
    retry = next(
        w for w in controller._iter_loading_indicators() if isinstance(w, QPushButton)
    )
    retry.click()
    qtbot.waitUntil(lambda: controller.update_filtered_mods.called)
    assert request.call_count == 2
    assert not controller._search_error
    assert not app_state.gamebanana_loading
    assert app_state.search_text == "unmatched query"
    controller.cleanup()
