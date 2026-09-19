"""Climate signals derived from the Open-Meteo daily payload."""
import pytest

from src.weather import derive_climate, GROWING, SHOULDER, DORMANT

# Recorded from api.open-meteo.com for LA (34.05, -118.25) on 2026-09-19 with
# past_days=3&forecast_days=3. Index 3 is "today": 3 past days precede it.
LA_SEPTEMBER = {
    "time": ["2026-09-16", "2026-09-17", "2026-09-18",
             "2026-09-19", "2026-09-20", "2026-09-21"],
    "temperature_2m_max": [27.7, 26.6, 26.5, 27.8, 26.9, 26.6],
    "temperature_2m_min": [19.8, 19.4, 16.7, 17.2, 17.3, 18.6],
    "precipitation_sum": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "et0_fao_evapotranspiration": [3.84, 4.16, 4.06, 3.98, 3.37, 4.56],
    "relative_humidity_2m_mean": [67, 69, 73, 74, 80, 63],
    "daylight_duration": [44462.67, 44337.96, 44213.66, 44089.45, 43964.6, 43839.16],
}


def _payload(**overrides):
    out = {k: list(v) for k, v in LA_SEPTEMBER.items()}
    out.update(overrides)
    return out


def test_today_is_located_by_date_not_by_a_fixed_offset():
    """past_days/forecast_days could change; anchoring on the date string keeps
    the past/future split correct if they do."""
    c = derive_climate(LA_SEPTEMBER, today="2026-09-19")
    assert c["daylight_hours"] == pytest.approx(44089.45 / 3600, abs=0.01)


def test_rain_is_split_into_what_already_fell_and_what_is_coming():
    rainy = _payload(precipitation_sum=[12.0, 3.0, 0.0, 0.0, 8.0, 1.5])
    c = derive_climate(rainy, today="2026-09-19")

    assert c["rain_past_3d"] == pytest.approx(15.0)   # the 3 days before today
    assert c["rain_next_2d"] == pytest.approx(9.5)    # the 2 days after today


def test_evaporative_demand_averages_the_three_days_ending_today():
    c = derive_climate(LA_SEPTEMBER, today="2026-09-19")
    assert c["et0_mean_3d"] == pytest.approx((4.16 + 4.06 + 3.98) / 3, abs=0.01)


def test_heat_lookahead_covers_today_and_the_next_two_days():
    hot = _payload(temperature_2m_max=[27.0, 27.0, 27.0, 30.0, 38.5, 31.0])
    c = derive_climate(hot, today="2026-09-19")
    assert c["temp_max_next_2d"] == pytest.approx(38.5)


@pytest.mark.parametrize("hours,expected", [
    (14.0, GROWING),
    (12.25, GROWING),   # actual LA mid-September
    (11.6, GROWING),
    (11.0, SHOULDER),   # ~late February
    (10.6, SHOULDER),
    (10.2, DORMANT),    # ~mid-November
    (9.9, DORMANT),     # winter solstice
])
def test_season_comes_from_daylight_not_a_hardcoded_month_table(hours, expected):
    payload = _payload(daylight_duration=[hours * 3600] * 6)
    assert derive_climate(payload, today="2026-09-19")["season"] == expected


def test_september_in_la_is_growing_season():
    assert derive_climate(LA_SEPTEMBER, today="2026-09-19")["season"] == GROWING


def test_a_missing_variable_drops_its_signal_instead_of_failing_the_run():
    """Open-Meteo can drop a field; the digest must still go out, just without
    that modifier."""
    partial = _payload()
    del partial["et0_fao_evapotranspiration"]
    del partial["relative_humidity_2m_mean"]

    c = derive_climate(partial, today="2026-09-19")

    assert c["et0_mean_3d"] is None
    assert c["humidity_mean"] is None
    assert c["rain_past_3d"] == pytest.approx(0.0)
    assert c["season"] == GROWING


def test_none_payload_yields_an_all_unknown_climate_rather_than_raising():
    c = derive_climate(None)
    assert c["season"] is None
    assert c["et0_mean_3d"] is None
    assert c["rain_past_3d"] is None


def test_unknown_today_falls_back_without_crashing():
    c = derive_climate(LA_SEPTEMBER, today="2030-01-01")
    assert c["season"] in (GROWING, SHOULDER, DORMANT, None)


def test_nulls_inside_an_array_are_ignored_not_treated_as_zero():
    """A null ET0 day must not drag the mean toward zero and shorten watering."""
    gappy = _payload(et0_fao_evapotranspiration=[3.84, None, 4.06, 3.98, 3.37, 4.56])
    c = derive_climate(gappy, today="2026-09-19")
    assert c["et0_mean_3d"] == pytest.approx((4.06 + 3.98) / 2, abs=0.01)
