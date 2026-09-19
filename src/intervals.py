"""Context-aware care intervals.

Replaces the flat MIN_ACTION_INTERVALS table that used to live in agent.py.
Every interval is computed per plant from real signals -- evaporative demand,
rain behind and ahead, humidity, season, environment, irrigation method and
fertilizer product -- and carries the labelled adjustments that produced it so
the digest can show its work.

Pure functions, no I/O. The same numbers go into the Gemini prompt and into the
post-filter, so the model and the safety net can no longer disagree.
"""

from src.fertilizers import interval_of
from src.weather import GROWING, SHOULDER, DORMANT

# Irrigation methods, from the Plants sheet's `Watering` column.
MANUAL = "manual"
SPRINKLER = "sprinkler"
DRIP = "drip"
ESTABLISHED = "established"

IRRIGATED = {SPRINKLER, DRIP}
# In-ground plantings: nothing to rotate, repot or carry into the shade.
IN_GROUND = {SPRINKLER, DRIP, ESTABLISHED}

# Reference evaporative demand for Los Angeles, mm/day. Roughly the annual
# mean; days above it dry pots out faster than the plant's nominal schedule.
ET0_REFERENCE = 3.3

# How far weather alone may scale a base interval, before clamping.
ET0_MULTIPLIER_RANGE = (0.6, 1.5)
# Deep-rooted plantings feel only this fraction of the evaporative swing.
ESTABLISHED_DAMPING = 0.3

DRY_AIR_RH = 35          # below this, indoor air pulls water out noticeably
HUMID_AIR_RH = 60        # above this, misting achieves very little
MIST_HUMID_MULTIPLIER = 4.0

RAIN_PAST_THRESHOLD_MM = 10.0    # a real soaking in the last three days
RAIN_AHEAD_THRESHOLD_MM = 5.0    # enough incoming rain to wait for
FERT_RAIN_AHEAD_MM = 10.0        # enough to wash feed away before uptake
HEAT_SPIKE_C = 35.0              # move outdoor pots into shade above this
# In-ground plantings need eyeballing, but nothing like a pot does.
LOW_MAINTENANCE_CHECK_MULTIPLIER = 5.0

DEFAULT_WATER_DAYS = 7           # only used when plant_api gives us nothing
DEFAULT_FERTILIZE_DAYS = 14      # unmapped plants still need a schedule

BASE_INTERVALS = {
    "MIST": 2,
    "ROTATE": 7,
    "PRUNE": 30,
    "REPOT": 180,
    "MOVE": 14,
    "CHECK": 3,
}

# Hard floors and ceilings. Whatever the modifiers do, the result lands here --
# these are the surviving descendant of the old MIN_ACTION_INTERVALS.
CLAMPS = {
    "WATER": (2, 45),
    "FERTILIZE": (7, 240),
    "MIST": (2, 30),
    "ROTATE": (7, 30),
    "MOVE": (3, 60),
    "PRUNE": (30, 365),
    "REPOT": (180, 1095),
    "CHECK": (3, 30),
}

# Actions that only make sense while the plant is actively growing.
GROWING_SEASON_ONLY = {"PRUNE", "REPOT"}


def _watering_method(plant):
    """Blank means manual: assume you water it, and err toward reminding."""
    raw = plant.get("watering")
    if raw is None:
        return MANUAL
    value = str(raw).strip().lower()
    return value or MANUAL


def _is_outdoor(plant):
    return str(plant.get("environment", "")).strip().lower().startswith("outdoor")


def _clamp(action, days):
    low, high = CLAMPS.get(action, (1, 3650))
    return max(low, min(high, days))


def _suppressed(action, reason, base):
    return {
        "action": action,
        "days": None,
        "base": base,
        "adjustments": [],
        "suppressed_reason": reason,
    }


def _base_for(action, plant, care):
    if action == "WATER":
        return care.get("max_watering_days") or DEFAULT_WATER_DAYS
    if action == "FERTILIZE":
        return interval_of(plant.get("fertilizer")) or DEFAULT_FERTILIZE_DAYS
    return BASE_INTERVALS.get(action)


def _et0_multiplier(climate, method):
    """Scale inversely with evaporative demand: thirsty air, shorter interval."""
    et0 = climate.get("et0_mean_3d")
    if not et0 or et0 <= 0:
        return None, None

    low, high = ET0_MULTIPLIER_RANGE
    multiplier = max(low, min(high, ET0_REFERENCE / et0))

    if method == ESTABLISHED:
        # Deep roots draw on a far larger reservoir than a pot; let the swing
        # through only partially rather than ignoring it.
        multiplier = 1.0 + (multiplier - 1.0) * ESTABLISHED_DAMPING

    if abs(multiplier - 1.0) < 0.05:
        return None, None

    label = "high ET₀" if multiplier < 1.0 else "low ET₀"
    return multiplier, label


def _water_interval(plant, care, climate, method):
    base = _base_for("WATER", plant, care)
    days = float(base)
    adjustments = []

    multiplier, label = _et0_multiplier(climate, method)
    if multiplier:
        before = days
        days *= multiplier
        adjustments.append((label, int(round(days - before))))

    if _is_outdoor(plant):
        # Rain only reaches plants that are actually outside. The old prompt
        # asked the model to respect this and had no way to enforce it.
        past = climate.get("rain_past_3d") or 0.0
        if past >= RAIN_PAST_THRESHOLD_MM:
            before = days
            days += min(past / RAIN_PAST_THRESHOLD_MM, 3.0) * 2.0
            adjustments.append(("recent rain", int(round(days - before))))

        ahead = climate.get("rain_next_2d") or 0.0
        if ahead >= RAIN_AHEAD_THRESHOLD_MM:
            before = days
            days += min(ahead / RAIN_AHEAD_THRESHOLD_MM, 3.0) * 1.5
            adjustments.append(("rain coming", int(round(days - before))))

    humidity = climate.get("humidity_mean")
    if humidity is not None and humidity < DRY_AIR_RH:
        before = days
        days *= 0.9
        adjustments.append(("dry air", int(round(days - before))))

    if climate.get("season") == DORMANT:
        before = days
        days *= 1.4
        adjustments.append(("dormant", int(round(days - before))))

    return base, days, adjustments


def _fertilize_interval(plant, climate):
    base = _base_for("FERTILIZE", plant, None)
    days = float(base)
    adjustments = []

    if climate.get("season") == SHOULDER:
        before = days
        days *= 1.5
        adjustments.append(("shoulder season", int(round(days - before))))

    if _is_outdoor(plant):
        ahead = climate.get("rain_next_2d") or 0.0
        if ahead >= FERT_RAIN_AHEAD_MM:
            before = days
            days += 5.0
            adjustments.append(("rain would wash it off", int(round(days - before))))

    return base, days, adjustments


def _mist_interval(climate):
    base = BASE_INTERVALS["MIST"]
    days = float(base)
    adjustments = []

    humidity = climate.get("humidity_mean")
    if humidity is not None and humidity >= HUMID_AIR_RH:
        before = days
        days *= MIST_HUMID_MULTIPLIER
        adjustments.append(("humid air", int(round(days - before))))

    return base, days, adjustments


def _simple_interval(action, plant, climate, method):
    base = BASE_INTERVALS[action]
    days = float(base)
    adjustments = []

    if action == "CHECK" and method in IN_GROUND:
        # An irrigated tree's only remaining action is CHECK. At the potted
        # cadence the eight in-ground plants would fill the digest with
        # nothing to actually do.
        before = days
        days *= LOW_MAINTENANCE_CHECK_MULTIPLIER
        adjustments.append(("established planting", int(round(days - before))))

    if action in ("ROTATE", "CHECK") and climate.get("season") == DORMANT:
        before = days
        days *= 1.5
        adjustments.append(("dormant", int(round(days - before))))

    return base, days, adjustments


def explain_interval(action, plant, care, climate):
    """Full result for `action` on `plant`, including why it was suppressed.

    Callers that just want a schedule should use `effective_interval`; this one
    exists for diagnostics -- the dry-run harness prints the suppression reasons
    so "no watering tasks today" can be distinguished from "watering is off".
    Returns None only for an action this engine knows nothing about."""
    action = (action or "").upper()
    care = care or {}
    climate = climate or {}
    method = _watering_method(plant)
    season = climate.get("season")

    if action not in CLAMPS:
        return None

    # --- suppression: the action is meaningless for this plant ---
    if action in ("WATER", "MIST") and method in IRRIGATED:
        return _suppressed(action, f"on the {method}", _base_for(action, plant, care))

    if action in ("ROTATE", "REPOT", "MOVE") and method in IN_GROUND:
        return _suppressed(action, "in ground", BASE_INTERVALS.get(action))

    if action == "MOVE":
        # MOVE is a response to a heat spike, not a recurring chore. Only
        # outdoor pots can actually be carried into the shade.
        heat = climate.get("temp_max_next_2d")
        if not _is_outdoor(plant) or heat is None or heat < HEAT_SPIKE_C:
            return _suppressed(action, "no heat spike", BASE_INTERVALS["MOVE"])

    # Season gates fail open: unknown weather must never silently stop feeding.
    if action == "FERTILIZE" and season == DORMANT:
        return _suppressed(action, "dormant season", _base_for(action, plant, care))

    if action in GROWING_SEASON_ONLY and season in (DORMANT, SHOULDER):
        return _suppressed(action, "outside growing season", BASE_INTERVALS.get(action))

    # --- computation ---
    if action == "WATER":
        base, days, adjustments = _water_interval(plant, care, climate, method)
    elif action == "FERTILIZE":
        base, days, adjustments = _fertilize_interval(plant, climate)
    elif action == "MIST":
        base, days, adjustments = _mist_interval(climate)
    else:
        base, days, adjustments = _simple_interval(action, plant, climate, method)

    final = _clamp(action, int(round(days)))

    # Clamping can erase a small adjustment entirely; don't claim one happened.
    if final == base:
        adjustments = []

    return {
        "action": action,
        "days": final,
        "base": base,
        "adjustments": adjustments,
        "suppressed_reason": None,
    }


def effective_interval(action, plant, care, climate):
    """Days that should pass before `action` is worth doing again for `plant`.

    Returns None when the action does not apply at all -- an irrigated plant
    needs no watering, a tree in the ground cannot be rotated, nothing gets fed
    in dormancy. Otherwise returns the computed days alongside the base it
    started from and the labelled adjustments that moved it, so the digest can
    render '🔁10d→8d (high ET₀)'."""
    result = explain_interval(action, plant, care, climate)
    if result is None or result.get("suppressed_reason"):
        return None
    return result
