"""GameBanana community feed."""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import override

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models.game_modes import get_search_game_entries
from services.gamebanana_rss_service import (
    GameBananaFeedItem,
    fetch_gamebanana_rss,
    merge_gamebanana_feeds,
)
from services.localization_service import tr
from ui.common.styling import load_mod_icon_universal
from ui.utils.thread_lifetime import ManagedQThread, retire_qthread
from utils.native_integration import open_url_native
from utils.network_utils import get_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _FeedGame:
    id: str
    name: str
    gamebanana_id: int


class _CommunityFeedWorker(ManagedQThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal()
    progress = pyqtSignal(int, int)

    def __init__(self, app_state, games: list[_FeedGame], feed: str) -> None:
        super().__init__()
        self._app_state = app_state
        self._games = games
        self._feed = feed

    def run(self) -> None:
        feeds: list[list[GameBananaFeedItem]] = []
        errors: list[str] = []
        try:
            session = get_session(self._app_state)
            for index, game in enumerate(self._games, start=1):
                if self.isInterruptionRequested():
                    return
                try:
                    feeds.append(
                        fetch_gamebanana_rss(
                            session,
                            self._feed,
                            str(game.gamebanana_id),
                            game.name,
                        )
                    )
                except Exception as error:
                    errors.append(str(error))
                    logger.warning(
                        "Could not load GameBanana RSS feed for game %s: %s",
                        game.gamebanana_id,
                        error,
                    )
                self.progress.emit(index, len(self._games))
            if not self.isInterruptionRequested():
                if not feeds and errors:
                    self.failed.emit()
                else:
                    self.loaded.emit(
                        (merge_gamebanana_feeds(feeds, self._feed), len(errors))
                    )
        except Exception as error:
            if not self.isInterruptionRequested():
                logger.warning("Could not load GameBanana RSS feed: %s", error)
                self.failed.emit()


class _FeedCard(QFrame):
    def __init__(self, item: GameBananaFeedItem, parent=None) -> None:
        super().__init__(parent)
        self.item = item
        self.setObjectName("communityFeedCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(14)

        self.image_label = QLabel()
        self.image_label.setFixedSize(112, 70)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.image_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        self.title_label = QLabel(item.title)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        text_layout.addWidget(self.title_label)

        self.meta_label = QLabel()
        self.meta_label.setTextFormat(Qt.TextFormat.PlainText)
        self.meta_label.setObjectName("communityFeedMeta")
        text_layout.addWidget(self.meta_label)
        row.addLayout(text_layout, 1)

        self.open_button = QPushButton()
        self.open_button.clicked.connect(lambda: open_url_native(item.url))
        row.addWidget(self.open_button)

        if item.image_url:
            load_mod_icon_universal(
                self.image_label,
                SimpleNamespace(icon=item.image_url, icon_path=None),
                size=(112, 70),
                border_radius=4,
            )
        self.relocalize_ui()

    def relocalize_ui(self) -> None:
        type_key = f"community_feed.types.{self.item.content_type}"
        content_type = tr(type_key)
        if content_type in ("", type_key, f"[{type_key}]"):
            content_type = self.item.content_type.replace("_", " ").title()
        date_text = (
            self.item.published_at.astimezone().strftime("%Y-%m-%d %H:%M")
            if self.item.published_at
            else tr("community_feed.featured")
        )
        self.meta_label.setText(
            tr(
                "community_feed.item_meta",
                game=self.item.game_name,
                type=content_type,
                date=date_text,
            )
        )
        self.open_button.setText(tr("community_feed.open"))


class CommunityDialog(QDialog):
    _feed_cache: dict[
        tuple[str, tuple[int, ...]], tuple[float, list[GameBananaFeedItem]]
    ] = {}
    _cache_ttl_seconds = 300

    def __init__(self, parent, app_state) -> None:
        super().__init__(parent)
        self._app_state = app_state
        self._worker: _CommunityFeedWorker | None = None
        self._loaded_once = False
        self._cards: list[_FeedCard] = []
        self._games = [
            _FeedGame(entry.id, entry.display_name, entry.gamebanana_id)
            for entry in get_search_game_entries()
        ]
        self.setModal(True)
        self.resize(820, 650)
        self._build_ui()
        self.relocalize_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        filters = QHBoxLayout()
        self.game_label = QLabel()
        self.game_combo = QComboBox()
        self.game_combo.addItem("", None)
        for game in self._games:
            self.game_combo.addItem(game.name, game.id)
        self.feed_label = QLabel()
        self.feed_combo = QComboBox()
        self.feed_combo.addItem("", "New")
        self.feed_combo.addItem("", "Featured")
        self.refresh_button = QPushButton()
        self.game_combo.currentIndexChanged.connect(self._reload_if_shown)
        self.feed_combo.currentIndexChanged.connect(self._reload_if_shown)
        self.refresh_button.clicked.connect(lambda: self.reload(use_cache=False))
        filters.addWidget(self.game_label)
        filters.addWidget(self.game_combo, 1)
        filters.addSpacing(8)
        filters.addWidget(self.feed_label)
        filters.addWidget(self.feed_combo, 1)
        filters.addWidget(self.refresh_button)
        root.addLayout(filters)

        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.feed_widget = QWidget()
        self.feed_layout = QVBoxLayout(self.feed_widget)
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(9)
        self.feed_layout.addStretch(1)
        self.scroll_area.setWidget(self.feed_widget)
        root.addWidget(self.scroll_area, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

    @override
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self.reload(use_cache=True)

    @override
    def closeEvent(self, event) -> None:
        self._stop_worker()
        super().closeEvent(event)

    @override
    def done(self, result: int) -> None:
        self._stop_worker()
        super().done(result)

    def _selected_games(self) -> list[_FeedGame]:
        game_id = self.game_combo.currentData()
        return (
            self._games
            if game_id is None
            else [game for game in self._games if game.id == game_id]
        )

    def _reload_if_shown(self) -> None:
        if self._loaded_once:
            self.reload(use_cache=True)

    def reload(self, *, use_cache: bool = False) -> None:
        games = self._selected_games()
        self._clear_cards()
        self._stop_worker()
        if not games:
            self.status_label.setText(tr("community_feed.no_games"))
            return
        cache_key = (
            str(self.feed_combo.currentData()),
            tuple(game.gamebanana_id for game in games),
        )
        cached = self._feed_cache.get(cache_key)
        if (
            use_cache
            and cached is not None
            and time.monotonic() - cached[0] < self._cache_ttl_seconds
        ):
            self._display_items(cached[1])
            return
        self._set_loading(0, len(games))
        worker = _CommunityFeedWorker(
            self._app_state, games, str(self.feed_combo.currentData())
        )
        self._worker = worker
        worker.loaded.connect(self._on_loaded)
        worker.failed.connect(self._on_failed)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_loaded(self, result: tuple[list[GameBananaFeedItem], int]) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        items, failed_count = result
        games = self._selected_games()
        cache_key = (
            str(self.feed_combo.currentData()),
            tuple(game.gamebanana_id for game in games),
        )
        if not failed_count:
            self._feed_cache[cache_key] = (time.monotonic(), items)
        self._display_items(items, failed_count=failed_count)

    def _display_items(
        self, items: list[GameBananaFeedItem], *, failed_count: int = 0
    ) -> None:
        if failed_count:
            status = tr(
                "community_feed.partial_results",
                count=len(items),
                failed=failed_count,
            )
        else:
            status = (
                tr("community_feed.results", count=len(items))
                if items
                else tr("community_feed.empty")
            )
        self.status_label.setText(status)
        for item in items:
            card = _FeedCard(item, self.feed_widget)
            self._cards.append(card)
            self.feed_layout.insertWidget(self.feed_layout.count() - 1, card)

    def _on_failed(self) -> None:
        worker = self.sender()
        if worker is self._worker:
            self.status_label.setText(tr("community_feed.load_failed"))

    def _on_progress(self, current: int, total: int) -> None:
        worker = self.sender()
        if worker is self._worker:
            self._set_loading(current, total)

    def _set_loading(self, current: int, total: int) -> None:
        self.status_label.setText(
            tr("community_feed.loading_progress", current=current, total=total)
            if total > 1
            else tr("community_feed.loading")
        )

    def _on_finished(self) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        retire_qthread(worker)

    def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        with contextlib.suppress(RuntimeError):
            worker.requestInterruption()
        retire_qthread(worker)

    def _clear_cards(self) -> None:
        for card in self._cards:
            self.feed_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def relocalize_ui(self) -> None:
        self.setWindowTitle(tr("community_feed.title"))
        self.game_label.setText(tr("community_feed.game"))
        self.feed_label.setText(tr("community_feed.feed"))
        self.game_combo.setItemText(0, tr("community_feed.all_games"))
        self.feed_combo.setItemText(0, tr("community_feed.new"))
        self.feed_combo.setItemText(1, tr("community_feed.featured"))
        self.refresh_button.setText(tr("community_feed.refresh"))
        self.close_button.setText(tr("buttons.close"))
        for card in self._cards:
            card.relocalize_ui()
