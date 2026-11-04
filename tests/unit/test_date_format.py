from datetime import UTC, datetime

import pytest
from PyQt6.QtCore import QLocale

from utils.date_format import (
    format_local_datetime,
    format_stored_date,
    format_timestamp,
)


@pytest.fixture
def region(qapp):
    saved = QLocale()
    yield lambda name: QLocale.setDefault(QLocale(name))
    QLocale.setDefault(saved)


def test_date_follows_the_system_region(region):
    moment = datetime(2026, 11, 4, 15, 30)
    region("en_US")
    us = format_local_datetime(moment)
    region("de_DE")
    de = format_local_datetime(moment)

    assert us.startswith("11/4/")
    assert de.startswith("04.11.")
    assert "15:30" in de


@pytest.mark.parametrize("stored", ["04.11.26 15:30", "2026-11-04 15:30:09", "2026-11-04 15:30"])
def test_stored_dates_are_shown_in_the_region_format(region, stored):
    region("de_DE")

    assert format_stored_date(stored) == format_local_datetime(datetime(2026, 11, 4, 15, 30))


@pytest.mark.parametrize("text", [None, "", "N/A", "yesterday"])
def test_text_that_is_not_a_stored_date_is_left_alone(region, text):
    assert format_stored_date(text) == text


def test_the_untouched_system_locale_gives_a_date(qapp):
    assert format_local_datetime(datetime(2026, 11, 4, 15, 30)).strip()


@pytest.mark.parametrize("timestamp", [-1e12, 1e18, float("inf")])
def test_a_timestamp_the_os_cannot_convert_shows_the_nearest_date(qapp, timestamp):
    assert format_timestamp(timestamp).strip()


def test_an_aware_date_is_converted_to_local_time(qapp):
    assert format_local_datetime(datetime(2026, 11, 4, 15, 30, tzinfo=UTC)).strip()
