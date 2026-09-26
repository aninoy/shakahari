"""One clock for the whole app, anchored to the garden's timezone.

Both runtimes (GitHub Actions and Cloud Run) are UTC, but the garden is in
Pacific. With naive datetime.now(), a digest built at 07:00 Pacific stamps the
Pacific date, while a tap at 18:00 Pacific compares against the *next* UTC
date -- so every dated button was refused for the seven hours between 17:00
Pacific and midnight.
"""
from datetime import datetime, timezone

import pytest

from src import clock


def test_today_follows_the_garden_not_the_server_clock(monkeypatch):
    """18:00 Pacific on the 25th is already the 26th in UTC. The garden says
    the 25th, and the garden is what the user is standing in."""
    utc_evening = datetime(2026, 9, 26, 1, 39, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "_utcnow", lambda: utc_evening)

    assert utc_evening.strftime("%Y-%m-%d") == "2026-09-26"   # server clock
    assert clock.today() == "2026-09-25"                       # garden clock


def test_today_matches_utc_when_the_dates_genuinely_agree(monkeypatch):
    morning = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)   # 07:00 Pacific
    monkeypatch.setattr(clock, "_utcnow", lambda: morning)

    assert clock.today() == "2026-09-25"


def test_now_is_timezone_aware():
    assert clock.now().tzinfo is not None


def test_today_is_a_plain_iso_date_string():
    value = clock.today()
    assert len(value) == 10
    datetime.strptime(value, "%Y-%m-%d")


def test_days_since_counts_whole_garden_days(monkeypatch):
    monkeypatch.setattr(clock, "_utcnow",
                        lambda: datetime(2026, 9, 26, 1, 39, tzinfo=timezone.utc))

    assert clock.days_since("2026-09-25") == 0      # still "today" in the garden
    assert clock.days_since("2026-09-24") == 1
    assert clock.days_since("2026-09-15") == 10


@pytest.mark.parametrize("value", ["", None, "N/A", "not a date", "2026-13-99"])
def test_days_since_tolerates_junk(value):
    assert clock.days_since(value) is None


def test_the_timezone_database_is_actually_available():
    """zoneinfo needs tzdata present in the container; without it this raises
    and every date in the app would be wrong."""
    assert clock.now().utcoffset() is not None
