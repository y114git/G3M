"""Small, neutral client for GameBanana's public RSS feeds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from defusedxml import ElementTree

from config.config import NETWORK_TIMEOUT_MEDIUM

_FEED_URL = "https://api.gamebanana.com/Rss/{feed}?gameid={game_id}"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class GameBananaFeedItem:
    title: str
    url: str
    image_url: str
    published_at: datetime | None
    content_type: str
    game_id: str
    game_name: str
    rank: int


def parse_gamebanana_rss(
    payload: bytes,
    *,
    game_id: str,
    game_name: str,
) -> list[GameBananaFeedItem]:
    """Parse all item types exposed by the feed without treating them as mods."""
    root = ElementTree.fromstring(_extract_rss_document(payload))
    items: list[GameBananaFeedItem] = []
    for rank, node in enumerate(root.findall(".//item")):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        if not title or not _is_gamebanana_item_url(url):
            continue
        items.append(
            GameBananaFeedItem(
                title=title,
                url=url,
                image_url=_safe_image_url(node.findtext("image")),
                published_at=_parse_date(node.findtext("pubDate")),
                content_type=_content_type_from_url(url),
                game_id=game_id,
                game_name=game_name,
                rank=rank,
            )
        )
    return items


def fetch_gamebanana_rss(
    session: requests.Session,
    feed: str,
    game_id: str,
    game_name: str,
) -> list[GameBananaFeedItem]:
    normalized_feed = feed.capitalize()
    if normalized_feed not in {"New", "Featured"}:
        raise ValueError(f"Unsupported GameBanana RSS feed: {feed}")
    response = session.get(
        _FEED_URL.format(feed=normalized_feed, game_id=int(game_id)),
        timeout=NETWORK_TIMEOUT_MEDIUM,
        stream=True,
    )
    try:
        response.raise_for_status()
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            payload.extend(chunk)
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ValueError("GameBanana RSS response is too large")
    finally:
        response.close()
    return parse_gamebanana_rss(
        bytes(payload), game_id=game_id, game_name=game_name
    )


def merge_gamebanana_feeds(
    feeds: list[list[GameBananaFeedItem]],
    feed: str,
    *,
    limit: int = 60,
) -> list[GameBananaFeedItem]:
    items = [item for game_items in feeds for item in game_items]
    if feed.casefold() == "new":
        items.sort(
            key=lambda item: (
                item.published_at is not None,
                item.published_at or datetime.min,
            ),
            reverse=True,
        )
    else:
        items.sort(key=lambda item: (item.rank, item.game_name.casefold()))
    return items[:limit]


def _is_gamebanana_item_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in {
        "gamebanana.com",
        "www.gamebanana.com",
    }


def _extract_rss_document(payload: bytes) -> bytes:
    """Discard content injected before or after the single RSS document."""
    start = payload.find(b"<rss")
    end = payload.find(b"</rss>", start)
    if start < 0 or end < 0:
        raise ValueError("GameBanana response does not contain a complete RSS feed")
    return payload[start : end + len(b"</rss>")]


def _content_type_from_url(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    return path_parts[0].casefold() if path_parts else "content"


def _safe_image_url(value: str | None) -> str:
    url = (value or "").strip()
    parsed = urlparse(url)
    return (
        url
        if parsed.scheme == "https"
        and parsed.hostname
        and (
            parsed.hostname == "images.gamebanana.com"
            or parsed.hostname.endswith(".gamebanana.com")
        )
        else ""
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, OverflowError):
        return None
