"""The garden's clock.

Both runtimes are UTC: the Advisor on GitHub Actions and the Recorder on Cloud
Run. The garden is not. With naive datetime.now() the day boundary fell at
17:00 local, so a digest stamped with the morning's date was judged "from a
previous day" by every tap made that evening, and dated buttons stopped working
for seven hours a day.

Every date the app records or compares goes through here, so the Advisor, the
Recorder and the Sheet all agree on what day it is.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.config import TIMEZONE

DATE_FORMAT = "%Y-%m-%d"


def _utcnow():
    """Seam for tests; production always reads the real clock."""
    return datetime.now(timezone.utc)


def now():
    """Current time as an aware datetime in the garden's timezone."""
    return _utcnow().astimezone(ZoneInfo(TIMEZONE))


def today():
    """Today's date in the garden, as YYYY-MM-DD."""
    return now().strftime(DATE_FORMAT)


def days_since(date_str):
    """Whole days between a YYYY-MM-DD string and today, or None if unparseable.

    Compares calendar dates rather than elapsed hours, so an action logged
    earlier today reads as 0 days ago regardless of the time."""
    if not date_str or date_str == 'N/A':
        return None
    try:
        past = datetime.strptime(str(date_str).strip(), DATE_FORMAT).date()
    except (ValueError, TypeError):
        return None
    return (now().date() - past).days
