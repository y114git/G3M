from datetime import datetime
from unittest.mock import Mock

import pytest

from services.gamebanana_rss_service import (
    _MAX_RESPONSE_BYTES,
    fetch_gamebanana_rss,
    merge_gamebanana_feeds,
    parse_gamebanana_rss,
)


def test_rss_parser_preserves_mixed_gamebanana_item_types():
    items = parse_gamebanana_rss(
        b"""<rss><items>
        <item><title>A mod</title><link>https://gamebanana.com/mods/1</link>
        <image>https://images.gamebanana.com/a.jpg</image>
        <pubDate>Fri, 24 Jul 2026 06:37:01 +0000</pubDate></item>
        <item><title>A question</title><link>https://gamebanana.com/questions/2</link></item>
        <item><title>External</title><link>https://example.com/mods/3</link></item>
        </items></rss>""",
        game_id="game",
        game_name="Game",
    )

    assert [item.content_type for item in items] == ["mods", "questions"]
    assert items[0].published_at is not None
    assert items[1].published_at is None


def test_rss_parser_ignores_content_injected_around_document():
    items = parse_gamebanana_rss(
        b"""junk<script></script><rss><items><item>
        <title>Valid item</title><link>https://gamebanana.com/tools/7</link>
        </item></items></rss><script>cloudflare()</script>""",
        game_id="game",
        game_name="Game",
    )

    assert [(item.title, item.content_type) for item in items] == [
        ("Valid item", "tools")
    ]


def test_featured_feeds_are_interleaved_by_native_rank():
    def feed(game_id: str):
        return parse_gamebanana_rss(
            f"""<rss><items>
            <item><title>{game_id} one</title><link>https://gamebanana.com/wips/1</link></item>
            <item><title>{game_id} two</title><link>https://gamebanana.com/tuts/2</link></item>
            </items></rss>""".encode(),
            game_id=game_id,
            game_name=game_id.upper(),
        )

    merged = merge_gamebanana_feeds([feed("a"), feed("b")], "Featured")

    assert [item.rank for item in merged] == [0, 0, 1, 1]


def test_new_feeds_sort_missing_dates_last():
    dated = parse_gamebanana_rss(
        b"""<rss><items><item><title>New</title>
        <link>https://gamebanana.com/mods/1</link>
        <pubDate>Fri, 24 Jul 2026 06:37:01 +0000</pubDate>
        </item></items></rss>""",
        game_id="a",
        game_name="A",
    )
    undated = parse_gamebanana_rss(
        b"""<rss><items><item><title>Unknown</title>
        <link>https://gamebanana.com/mods/2</link>
        </item></items></rss>""",
        game_id="b",
        game_name="B",
    )

    merged = merge_gamebanana_feeds([undated, dated], "New")

    assert merged[0].published_at == datetime.fromisoformat("2026-07-24T06:37:01+00:00")


def test_rss_fetch_streams_bounded_response():
    response = Mock()
    response.iter_content.return_value = [
        b"<rss><items><item><title>Tool</title>",
        b"<link>https://gamebanana.com/tools/7</link></item></items></rss>",
    ]
    session = Mock()
    session.get.return_value = response

    items = fetch_gamebanana_rss(session, "New", "1", "Game")

    session.get.assert_called_once_with(
        "https://api.gamebanana.com/Rss/New?gameid=1",
        timeout=15,
        stream=True,
    )
    response.iter_content.assert_called_once_with(chunk_size=64 * 1024)
    assert [item.title for item in items] == ["Tool"]


def test_rss_fetch_stops_as_soon_as_response_is_too_large():
    response = Mock()
    response.iter_content.return_value = [
        b"x" * _MAX_RESPONSE_BYTES,
        b"x",
        b"must not be read",
    ]
    session = Mock()
    session.get.return_value = response

    with pytest.raises(ValueError, match="too large"):
        fetch_gamebanana_rss(session, "Featured", "1", "Game")
