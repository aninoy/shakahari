"""The context-aware interval engine.

These tests pin the behaviour that replaces agent.MIN_ACTION_INTERVALS: each
modifier in isolation, the suppression rules, and the clamps that stop any
combination from producing an absurd interval.
"""
import pytest

from src.intervals import (
    effective_interval, ET0_REFERENCE, CLAMPS, MANUAL, SPRINKLER, DRIP, ESTABLISHED,
)
from src.weather import GROWING, SHOULDER, DORMANT

BASE_CLIMATE = {
    "et0_mean_3d": ET0_REFERENCE,   # neutral: no evaporative adjustment
    "rain_past_3d": 0.0,
    "rain_next_2d": 0.0,
    "humidity_mean": 50,
    "temp_max_next_2d": 25.0,
    "daylight_hours": 12.5,
    "season": GROWING,
}

CARE = {"min_watering_days": 5, "max_watering_days": 10}


def climate(**overrides):
    out = dict(BASE_CLIMATE)
    out.update(overrides)
    return out


def plant(**overrides):
    out = {
        "name": "Testus plantus",
        "environment": "indoor",
        "watering": MANUAL,
        "fertilizer": "ALLPURPOSE",
    }
    out.update(overrides)
    return out


def days(action, p=None, c=None, care=CARE):
    result = effective_interval(action, p or plant(), care, c or climate())
    return None if result is None else result["days"]


# --- baseline -------------------------------------------------------------

def test_neutral_conditions_return_the_plants_own_watering_guideline():
    assert days("WATER") == CARE["max_watering_days"]


def test_fertilize_base_comes_from_the_plants_product_not_a_global_constant():
    """The whole point: Snake Plant and Monstera no longer share one number."""
    succulent = days("FERTILIZE", plant(fertilizer="SUCCULENT"))
    houseplant = days("FERTILIZE", plant(fertilizer="ALLPURPOSE"))

    assert succulent == 120
    assert houseplant == 14
    assert succulent > houseplant


def test_unmapped_fertilizer_still_gets_a_usable_interval():
    """A plant in the '❓ Not set' group must still be schedulable."""
    assert days("FERTILIZE", plant(fertilizer=None)) > 0


# --- irrigation -----------------------------------------------------------

@pytest.mark.parametrize("method", [SPRINKLER, DRIP])
def test_irrigated_plants_never_generate_watering_or_misting(method):
    """Azalea, Camellia, Spider Plant and all five trees are on the system --
    every watering reminder they ever got was noise."""
    p = plant(environment="outdoor", watering=method)
    assert effective_interval("WATER", p, CARE, climate()) is None
    assert effective_interval("MIST", p, CARE, climate()) is None


@pytest.mark.parametrize("method", [SPRINKLER, DRIP])
def test_irrigated_plants_still_need_feeding_and_checking(method):
    p = plant(environment="outdoor", watering=method)
    assert days("FERTILIZE", p) > 0
    assert days("CHECK", p) > 0


def test_in_ground_plants_are_not_asked_to_be_rotated_repotted_or_moved():
    """You cannot rotate an avocado tree."""
    tree = plant(environment="outdoor", watering=SPRINKLER)
    for action in ("ROTATE", "REPOT", "MOVE"):
        assert effective_interval(action, tree, CARE, climate()) is None


def test_blank_watering_is_treated_as_manual():
    """The one inferred default in the design, and it errs toward reminding."""
    assert days("WATER", plant(watering="")) == days("WATER", plant(watering=MANUAL))
    assert days("WATER", plant(watering=None)) == days("WATER", plant(watering=MANUAL))


def test_established_trees_damp_the_evaporative_response():
    """Deep roots buffer a hot week in a way a pot does not."""
    hot = climate(et0_mean_3d=ET0_REFERENCE * 2)
    potted = days("WATER", plant(environment="outdoor", watering=MANUAL), hot)
    rooted = days("WATER", plant(environment="outdoor", watering=ESTABLISHED), hot)

    neutral_potted = days("WATER", plant(environment="outdoor", watering=MANUAL))
    assert potted < neutral_potted            # heat shortens the potted plant
    assert rooted > potted                    # but the tree far less so


# --- evaporative demand ---------------------------------------------------

def test_high_evaporative_demand_shortens_watering():
    hot_dry = climate(et0_mean_3d=ET0_REFERENCE * 1.5)
    assert days("WATER", None, hot_dry) < CARE["max_watering_days"]


def test_low_evaporative_demand_stretches_watering():
    cool = climate(et0_mean_3d=ET0_REFERENCE * 0.5)
    assert days("WATER", None, cool) > CARE["max_watering_days"]


def test_the_evaporative_multiplier_is_clamped_at_both_ends():
    """No weather reading should be able to halve or triple an interval."""
    absurd_hot = days("WATER", None, climate(et0_mean_3d=ET0_REFERENCE * 100))
    absurd_cold = days("WATER", None, climate(et0_mean_3d=0.001))

    assert absurd_hot >= CLAMPS["WATER"][0]
    assert absurd_cold <= CLAMPS["WATER"][1]
    assert absurd_hot >= int(CARE["max_watering_days"] * 0.6)
    assert absurd_cold <= int(CARE["max_watering_days"] * 1.5) + 1


def test_missing_evaporative_data_falls_back_to_the_base_interval():
    assert days("WATER", None, climate(et0_mean_3d=None)) == CARE["max_watering_days"]


# --- rain -----------------------------------------------------------------

def test_recent_rain_defers_watering_for_outdoor_plants():
    wet = climate(rain_past_3d=20.0)
    outdoor = plant(environment="outdoor")
    assert days("WATER", outdoor, wet) > days("WATER", outdoor)


def test_forecast_rain_defers_watering_before_it_falls():
    """A backward-only window cannot express this, which is why forecast days
    were added to the request."""
    incoming = climate(rain_next_2d=12.0)
    outdoor = plant(environment="outdoor")
    assert days("WATER", outdoor, incoming) > days("WATER", outdoor)


def test_rain_does_not_touch_indoor_plants():
    """The old prompt asked Gemini to do this in prose and could not enforce it."""
    wet = climate(rain_past_3d=25.0, rain_next_2d=25.0)
    indoor = plant(environment="indoor")
    assert days("WATER", indoor, wet) == days("WATER", indoor)


def test_heavy_incoming_rain_defers_outdoor_fertilizing():
    """Feeding just before a downpour washes it away before uptake."""
    storm = climate(rain_next_2d=15.0)
    outdoor = plant(environment="outdoor")
    assert days("FERTILIZE", outdoor, storm) > days("FERTILIZE", outdoor)


# --- season ---------------------------------------------------------------

def test_fertilizing_is_suppressed_entirely_in_dormancy():
    """data/fertilizer.md: 'Cut back or stop entirely in winter (Nov-Feb)'.
    Enforced, not merely suggested to the model."""
    winter = climate(season=DORMANT, daylight_hours=10.0)
    result = effective_interval("FERTILIZE", plant(), CARE, winter)

    assert result is None or result.get("suppressed_reason")


def test_shoulder_season_stretches_feeding_rather_than_stopping_it():
    shoulder = days("FERTILIZE", None, climate(season=SHOULDER, daylight_hours=11.0))
    growing = days("FERTILIZE", None, climate(season=GROWING))

    assert shoulder is not None
    assert shoulder > growing


def test_dormancy_stretches_watering_without_stopping_it():
    winter = climate(season=DORMANT, daylight_hours=10.0)
    assert days("WATER", None, winter) > days("WATER")


def test_pruning_and_repotting_are_growing_season_work():
    winter = climate(season=DORMANT, daylight_hours=10.0)
    potted = plant(environment="indoor", watering=MANUAL)
    assert effective_interval("PRUNE", potted, CARE, winter) is None
    assert effective_interval("REPOT", potted, CARE, winter) is None


def test_unknown_season_does_not_suppress_anything():
    """No weather must never mean 'skip feeding' -- fail open, not silent."""
    unknown = climate(season=None, daylight_hours=None)
    assert effective_interval("FERTILIZE", plant(), CARE, unknown) is not None


# --- humidity -------------------------------------------------------------

def test_misting_is_dropped_entirely_in_humid_air():
    """LA is currently 67-80% RH; MIST: 2 was firing year-round regardless."""
    assert effective_interval("MIST", plant(), CARE, climate(humidity_mean=75)) is None
    assert effective_interval("MIST", plant(), CARE, climate(humidity_mean=30)) is not None


def test_misting_stays_frequent_in_a_dry_santa_ana():
    assert days("MIST", None, climate(humidity_mean=18)) <= 3


def test_very_dry_air_shortens_watering_modestly():
    arid = climate(humidity_mean=20)
    assert days("WATER", None, arid) < days("WATER")


# --- heat-driven MOVE -----------------------------------------------------

def test_a_heat_spike_makes_move_actionable_for_outdoor_pots():
    """MOVE stops being an arbitrary 14-day timer and becomes a real trigger."""
    heatwave = climate(temp_max_next_2d=38.0)
    potted = plant(environment="outdoor", watering=MANUAL)

    assert effective_interval("MOVE", potted, CARE, heatwave) is not None
    assert effective_interval("MOVE", potted, CARE, climate()) is None


def test_no_heat_spike_means_no_move_suggestion_indoors():
    assert effective_interval("MOVE", plant(environment="indoor"), CARE, climate()) is None


# --- clamps and robustness ------------------------------------------------

@pytest.mark.parametrize("action", ["WATER", "FERTILIZE", "MIST", "ROTATE", "CHECK"])
def test_every_interval_lands_inside_its_clamp_under_adversarial_weather(action):
    extremes = [
        climate(et0_mean_3d=0.0001, humidity_mean=0, rain_past_3d=500, rain_next_2d=500),
        climate(et0_mean_3d=999, humidity_mean=100, season=DORMANT, daylight_hours=9.0),
        climate(et0_mean_3d=None, humidity_mean=None, rain_past_3d=None,
                rain_next_2d=None, season=None, daylight_hours=None),
    ]
    low, high = CLAMPS[action]
    for c in extremes:
        result = effective_interval(action, plant(environment="outdoor"), CARE, c)
        if result is not None and not result.get("suppressed_reason"):
            assert low <= result["days"] <= high


def test_watering_can_never_be_recommended_more_often_than_the_hard_floor():
    reckless = climate(et0_mean_3d=999, humidity_mean=0, rain_past_3d=0, rain_next_2d=0)
    assert days("WATER", plant(environment="outdoor"), reckless) >= CLAMPS["WATER"][0]


def test_an_unknown_action_does_not_raise():
    assert effective_interval("FLURBLE", plant(), CARE, climate()) is None


def test_missing_care_guidelines_fall_back_to_a_sane_watering_base():
    result = effective_interval("WATER", plant(), {}, climate())
    assert result is not None and result["days"] > 0


# --- explainability -------------------------------------------------------

def test_the_result_shows_its_work_for_the_digest_line():
    """The digest renders '🔁10d→8d (high ET₀)', so adjustments must be labelled."""
    hot = climate(et0_mean_3d=ET0_REFERENCE * 1.5)
    result = effective_interval("WATER", plant(), CARE, hot)

    assert result["base"] == CARE["max_watering_days"]
    assert result["days"] != result["base"]
    assert result["adjustments"], "expected a labelled adjustment"
    label, delta = result["adjustments"][0]
    assert isinstance(label, str) and label
    assert isinstance(delta, int)


def test_no_adjustments_are_reported_when_nothing_moved_the_interval():
    result = effective_interval("WATER", plant(), CARE, climate())
    assert result["adjustments"] == []
    assert result["days"] == result["base"]


def test_low_maintenance_plantings_are_checked_far_less_often():
    """CHECK is the only action left for an irrigated tree. At the potted
    cadence, 8 such plants would swamp the digest with nothing to do."""
    potted = plant(environment="indoor", watering=MANUAL)
    tree = plant(environment="outdoor", watering=SPRINKLER)

    assert days("CHECK", tree) > days("CHECK", potted) * 3


def test_checking_an_established_tree_stays_within_the_clamp():
    tree = plant(environment="outdoor", watering=ESTABLISHED)
    low, high = CLAMPS["CHECK"]
    assert low <= days("CHECK", tree) <= high


# --- condition-driven actions ---------------------------------------------

@pytest.mark.parametrize("action", ["PRUNE", "REPOT"])
def test_occasional_actions_are_never_proposed_from_absent_history(action):
    """'Never repotted' is the normal state of a plant, not a backlog. These
    actions need positive evidence -- a heat spike, a note, the model spotting
    something -- not merely the absence of a log entry."""
    potted = plant(environment="indoor", watering=MANUAL)
    assert effective_interval(action, potted, CARE, climate(), days_since=None) is None


@pytest.mark.parametrize("action", ["WATER", "FERTILIZE", "ROTATE"])
def test_scheduled_actions_are_still_due_when_never_done(action):
    """A plant that has never been watered does need water."""
    potted = plant(environment="indoor", watering=MANUAL)
    assert effective_interval(action, potted, CARE, climate(), days_since=None) is not None


def test_pruning_is_scheduled_once_it_has_actually_been_done():
    """Spacing is still enforced -- it just isn't bootstrapped from nothing."""
    potted = plant(environment="indoor", watering=MANUAL)
    result = effective_interval("PRUNE", potted, CARE, climate(), days_since=90)
    assert result is not None and result["days"] == 30


def test_days_since_is_optional_so_existing_callers_keep_working():
    assert effective_interval("WATER", plant(), CARE, climate()) is not None


# --- misting in humid air --------------------------------------------------

def test_misting_is_suppressed_outright_in_humid_air():
    """72% RH in LA right now -- misting achieves nothing, so it should not be
    offered at a stretched interval; it should not be offered at all."""
    assert effective_interval("MIST", plant(), CARE, climate(humidity_mean=75)) is None


def test_misting_still_applies_in_genuinely_dry_air():
    result = effective_interval("MIST", plant(), CARE, climate(humidity_mean=25))
    assert result is not None and result["days"] <= 3


def test_unknown_humidity_leaves_misting_available():
    assert effective_interval("MIST", plant(), CARE, climate(humidity_mean=None)) is not None


# --- the plant's own documented minimum ------------------------------------

def test_watering_never_undercuts_the_plants_own_minimum():
    """plant_api already gives us min_watering_days. Under LA summer conditions
    the ET0 and dry-air modifiers compound to ~-46%, which pushed six real
    plants -- including two near-succulents -- below their documented floor."""
    summer = climate(et0_mean_3d=5.5, humidity_mean=32)
    succulent_care = {"min_watering_days": 14, "max_watering_days": 21}

    result = effective_interval("WATER", plant(environment="outdoor"), succulent_care, summer)

    assert result["days"] >= succulent_care["min_watering_days"]


def test_the_minimum_floor_does_not_stop_intervals_from_stretching():
    wet = climate(et0_mean_3d=ET0_REFERENCE * 0.5)
    care = {"min_watering_days": 5, "max_watering_days": 10}

    assert effective_interval("WATER", plant(), care, wet)["days"] > 10


def test_a_missing_minimum_is_simply_not_applied():
    assert effective_interval("WATER", plant(), {"max_watering_days": 10}, climate()) is not None


def test_a_nonsensical_minimum_above_the_maximum_does_not_invert_the_schedule():
    """Cache entries are third-party data; min > max must not produce a longer
    interval than the plant's own maximum."""
    result = effective_interval(
        "WATER", plant(), {"min_watering_days": 40, "max_watering_days": 10}, climate())
    assert result["days"] <= 10


# --- graded misting --------------------------------------------------------

def test_misting_is_stretched_in_middling_humidity_not_fired_every_two_days():
    """Between dry and humid, misting helps a little -- not every 2 days for
    every plant, which is a standing digest entry nobody acts on."""
    middling = effective_interval("MIST", plant(), CARE, climate(humidity_mean=48))
    arid = effective_interval("MIST", plant(), CARE, climate(humidity_mean=20))

    assert middling is not None
    assert middling["days"] > arid["days"]


def test_adjustments_that_changed_nothing_are_not_reported():
    """'🔁4d→2d (high ET₀, dry air)' should not credit a modifier worth 0 days."""
    result = effective_interval(
        "WATER", plant(environment="outdoor"),
        {"max_watering_days": 3}, climate(et0_mean_3d=ET0_REFERENCE * 1.4, humidity_mean=20))
    if result["adjustments"]:
        assert all(delta != 0 for _, delta in result["adjustments"])


def test_hand_typed_irrigation_phrases_resolve_rather_than_falling_back():
    """'drip irrigation' in the sheet must not silently become manual."""
    for value in ["drip irrigation", "Sprinkler system", "SPRINKLER", " drip "]:
        p = plant(environment="outdoor", watering=value)
        assert effective_interval("WATER", p, CARE, climate()) is None, value


def test_an_unrecognized_irrigation_value_still_errs_toward_reminding():
    p = plant(environment="outdoor", watering="who knows")
    assert effective_interval("WATER", p, CARE, climate()) is not None
