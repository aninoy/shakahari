"""Weather fetch and the climate signals the interval engine reasons over."""
from datetime import datetime

import requests

from src.config import LATITUDE, LONGITUDE

# Season labels, derived from daylight rather than a month table so the
# thresholds stay correct for whatever latitude the garden is at.
GROWING = "GROWING"
SHOULDER = "SHOULDER"
DORMANT = "DORMANT"

# Daylight hours at the season boundaries. For LA these land DORMANT at roughly
# mid-November through mid-February, matching data/fertilizer.md's "cut back or
# stop entirely in winter".
GROWING_MIN_DAYLIGHT_HOURS = 11.5
DORMANT_MAX_DAYLIGHT_HOURS = 10.5

PAST_DAYS = 3
FORECAST_DAYS = 3

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "relative_humidity_2m_mean",
    "daylight_duration",
]

UNKNOWN_CLIMATE = {
    "et0_mean_3d": None,
    "rain_past_3d": None,
    "rain_next_2d": None,
    "humidity_mean": None,
    "temp_max_next_2d": None,
    "daylight_hours": None,
    "season": None,
}


def get_forecast():
    """Fetches the past 3 days plus today and the next 2 days.

    Forecast days matter as much as past days: rain that is *coming* should
    defer watering and fertilizing, which a purely backward-looking window
    cannot express."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&daily={','.join(DAILY_VARS)}"
        f"&past_days={PAST_DAYS}&forecast_days={FORECAST_DAYS}&timezone=auto"
    )
    try:
        response = requests.get(url).json()
        return response.get('daily')
    except Exception as e:
        print(f"⚠️ Weather API Error: {e}")
        return None


def _series(daily, key):
    value = daily.get(key)
    return value if isinstance(value, list) else None


def _mean(values):
    """Mean of the non-null entries, or None if there are none.

    Nulls are skipped rather than coerced to 0 -- a gap in the ET0 series would
    otherwise read as a day of zero evaporative demand and stretch watering."""
    present = [v for v in values if isinstance(v, (int, float))]
    if not present:
        return None
    return sum(present) / len(present)


def _total(values):
    present = [v for v in values if isinstance(v, (int, float))]
    if not present:
        return None
    return sum(present)


def _max(values):
    present = [v for v in values if isinstance(v, (int, float))]
    if not present:
        return None
    return max(present)


def _today_index(daily, today):
    """Locate today in the series by date string.

    Anchoring on the date rather than assuming index == PAST_DAYS keeps the
    past/future split correct if the request window ever changes."""
    times = _series(daily, "time") or []
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    if today in times:
        return times.index(today)
    # Window doesn't contain today (stale cache, clock skew): fall back to the
    # documented offset, clamped into range.
    if not times:
        return None
    return min(PAST_DAYS, len(times) - 1)


def _season(daylight_hours):
    if daylight_hours is None:
        return None
    if daylight_hours >= GROWING_MIN_DAYLIGHT_HOURS:
        return GROWING
    if daylight_hours <= DORMANT_MAX_DAYLIGHT_HOURS:
        return DORMANT
    return SHOULDER


def derive_climate(daily, today=None):
    """Condense the raw daily payload into the signals intervals.py consumes.

    Every field degrades independently: a variable Open-Meteo didn't return
    becomes None, which drops that one modifier rather than failing the run."""
    if not daily:
        return dict(UNKNOWN_CLIMATE)

    idx = _today_index(daily, today)
    if idx is None:
        return dict(UNKNOWN_CLIMATE)

    climate = dict(UNKNOWN_CLIMATE)

    et0 = _series(daily, "et0_fao_evapotranspiration")
    if et0:
        # The three days ending today -- recent demand, not a forecast.
        climate["et0_mean_3d"] = _mean(et0[max(0, idx - 2):idx + 1])

    rain = _series(daily, "precipitation_sum")
    if rain:
        climate["rain_past_3d"] = _total(rain[max(0, idx - 3):idx])
        climate["rain_next_2d"] = _total(rain[idx + 1:idx + 3])

    humidity = _series(daily, "relative_humidity_2m_mean")
    if humidity:
        climate["humidity_mean"] = _mean(humidity[max(0, idx - 2):idx + 1])

    temp_max = _series(daily, "temperature_2m_max")
    if temp_max:
        climate["temp_max_next_2d"] = _max(temp_max[idx:idx + 3])

    daylight = _series(daily, "daylight_duration")
    if daylight and idx < len(daylight):
        seconds = daylight[idx]
        if isinstance(seconds, (int, float)):
            climate["daylight_hours"] = seconds / 3600.0

    climate["season"] = _season(climate["daylight_hours"])
    return climate
