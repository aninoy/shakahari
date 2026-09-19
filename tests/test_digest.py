"""Grouped digest rendering and keyboard construction."""
from datetime import datetime

import pytest

from src.digest import format_digest, build_keyboard, NOT_SET_HEADING

TODAY = datetime.now().strftime("%Y-%m-%d")


def task(name, action, days_since=5, threshold=3, priority="MEDIUM",
         fertilizer=None, adjustments=None, base=None):
    return {
        "name": name, "action": action, "priority": priority,
        "days_since": days_since, "threshold": threshold,
        "fertilizer": fertilizer, "adjustments": adjustments or [],
        "base": base if base is not None else threshold,
    }


def _lines(text):
    return [l for l in text.split("\n") if l.strip()]


def _index_of(text, needle):
    for i, line in enumerate(_lines(text)):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found in:\n{text}")


# --- grouping -------------------------------------------------------------

def test_tasks_are_grouped_under_one_heading_per_action():
    """The original ask: complete one action across all its plants in one go,
    instead of scanning a plant-ordered list and regrouping mentally."""
    text = format_digest([
        task("Monstera", "WATER"),
        task("Pothos", "ROTATE"),
        task("Peace Lily", "WATER"),
    ], "")

    water_heading = _index_of(text, "WATER")
    rotate_heading = _index_of(text, "ROTATE")

    assert _index_of(text, "Monstera") > water_heading
    assert _index_of(text, "Peace Lily") > water_heading
    assert _index_of(text, "Peace Lily") < rotate_heading, "WATER block was split"


def test_each_action_appears_as_exactly_one_heading():
    text = format_digest([
        task("A", "WATER"), task("B", "WATER"), task("C", "WATER"),
    ], "")
    assert sum(1 for l in _lines(text) if "WATER" in l) == 1


def test_a_group_heading_reports_how_many_plants_it_covers():
    text = format_digest([task("A", "WATER"), task("B", "WATER")], "")
    assert "2" in _lines(text)[_index_of(text, "WATER")]


# --- fertilizer sub-grouping ----------------------------------------------

def test_fertilizing_is_subdivided_by_product():
    """One bottle per sub-group, so a bulk tap means one real-world act."""
    text = format_digest([
        task("Avocado", "FERTILIZE", fertilizer="CITRUS"),
        task("Bougainvillea", "FERTILIZE", fertilizer="BLOOM"),
        task("Orange", "FERTILIZE", fertilizer="CITRUS"),
    ], "")

    citrus = _index_of(text, "Citrus-tone")
    bloom = _index_of(text, "Bloom Booster")

    assert _index_of(text, "Avocado") > citrus
    assert _index_of(text, "Orange") > citrus
    assert _index_of(text, "Orange") < bloom, "Citrus-tone block was split"


def test_one_bottle_at_three_dilutions_stays_a_single_sub_group():
    """ALLPURPOSE / _HALF / SUCCULENT are the same product -- one trip to one
    shelf -- with the dilution annotated per plant instead."""
    text = format_digest([
        task("Monstera", "FERTILIZE", fertilizer="ALLPURPOSE"),
        task("Spider Plant", "FERTILIZE", fertilizer="ALLPURPOSE_HALF"),
        task("Snake Plant", "FERTILIZE", fertilizer="SUCCULENT"),
    ], "")

    assert sum(1 for l in _lines(text) if "All-Purpose" in l) == 1


def test_dilution_is_annotated_on_the_plant_line_that_needs_it():
    text = format_digest([
        task("Monstera", "FERTILIZE", fertilizer="ALLPURPOSE"),
        task("Spider Plant", "FERTILIZE", fertilizer="ALLPURPOSE_HALF"),
    ], "")

    spider = _lines(text)[_index_of(text, "Spider Plant")]
    monstera = _lines(text)[_index_of(text, "Monstera")]

    assert "½" in spider
    assert "½" not in monstera


def test_unmapped_plants_surface_in_a_visible_not_set_group():
    text = format_digest([task("Mint", "FERTILIZE", fertilizer=None)], "")
    assert NOT_SET_HEADING in text
    assert "Mint" in text


def test_not_set_sorts_last_even_when_it_is_the_most_overdue():
    """A misconfiguration must never push real work down the message."""
    text = format_digest([
        task("Mint", "FERTILIZE", fertilizer=None, days_since=900, threshold=14),
        task("Avocado", "FERTILIZE", fertilizer="CITRUS", days_since=20, threshold=120),
    ], "")

    assert _index_of(text, NOT_SET_HEADING) > _index_of(text, "Citrus-tone")


def test_only_fertilizing_is_subdivided():
    text = format_digest([task("Monstera", "WATER", fertilizer="ALLPURPOSE")], "")
    assert "All-Purpose" not in text


# --- ordering -------------------------------------------------------------

def test_the_most_overdue_group_comes_first():
    text = format_digest([
        task("Pothos", "ROTATE", days_since=8, threshold=7),      # 1.14x
        task("Monstera", "WATER", days_since=30, threshold=10),   # 3.0x
    ], "")
    assert _index_of(text, "WATER") < _index_of(text, "ROTATE")


def test_plants_are_ordered_by_urgency_within_their_group():
    text = format_digest([
        task("Mild", "WATER", days_since=11, threshold=10),
        task("Urgent", "WATER", days_since=40, threshold=10),
    ], "")
    assert _index_of(text, "Urgent") < _index_of(text, "Mild")


def test_never_done_sorts_as_maximally_overdue():
    text = format_digest([
        task("Done recently", "WATER", days_since=12, threshold=10),
        task("Never touched", "WATER", days_since=None, threshold=10),
    ], "")
    assert _index_of(text, "Never touched") < _index_of(text, "Done recently")


# --- line content ---------------------------------------------------------

def test_a_line_shows_days_since_and_the_effective_threshold():
    text = format_digest([task("Monstera", "WATER", days_since=12, threshold=10)], "")
    line = _lines(text)[_index_of(text, "Monstera")]
    assert "12d" in line and "10d" in line


def test_never_is_rendered_for_a_plant_with_no_history():
    text = format_digest([task("Fern", "CHECK", days_since=None, threshold=3)], "")
    assert "never" in _lines(text)[_index_of(text, "Fern")]


def test_an_adjusted_threshold_shows_its_work():
    """'🔁10d→8d (high ET₀)' -- so tuning drift stays visible."""
    text = format_digest([
        task("Monstera", "WATER", days_since=12, threshold=8, base=10,
             adjustments=[("high ET₀", -2)]),
    ], "")
    line = _lines(text)[_index_of(text, "Monstera")]

    assert "10d" in line and "8d" in line
    assert "high ET₀" in line


def test_an_unadjusted_threshold_shows_a_single_number():
    text = format_digest([task("Monstera", "WATER", days_since=12, threshold=10, base=10)], "")
    assert "→" not in _lines(text)[_index_of(text, "Monstera")]


def test_the_summary_and_date_head_the_message():
    text = format_digest([task("A", "WATER")], "All calm")
    assert TODAY in text
    assert "All calm" in text


def test_an_empty_task_list_does_not_crash():
    assert isinstance(format_digest([], "All healthy"), str)


# --- keyboard -------------------------------------------------------------

def test_every_task_keeps_its_own_named_button():
    kb = build_keyboard([task("Monstera", "WATER"), task("Pothos", "ROTATE")])
    payloads = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]

    assert "t:WATER:Monstera" in payloads
    assert "t:ROTATE:Pothos" in payloads


def test_each_action_present_gets_one_bulk_button():
    kb = build_keyboard([
        task("A", "WATER"), task("B", "WATER"), task("C", "ROTATE"),
    ])
    bulk = [b["callback_data"] for row in kb["inline_keyboard"] for b in row
            if b["callback_data"].startswith("donetype:")]

    assert bulk == [f"donetype:WATER:{TODAY}", f"donetype:ROTATE:{TODAY}"]


def test_fertilizing_gets_one_bulk_button_per_product_not_one_overall():
    """The bug being fixed: a single 'Mark fertilizing complete' claimed the
    azalea's acid feed and the bougainvillea's bloom booster in one tap."""
    kb = build_keyboard([
        task("Avocado", "FERTILIZE", fertilizer="CITRUS"),
        task("Bougainvillea", "FERTILIZE", fertilizer="BLOOM"),
    ])
    payloads = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]

    assert f"donefert:CITRUS:{TODAY}" in payloads
    assert f"donefert:BLOOM:{TODAY}" in payloads
    assert not any(p.startswith("donetype:FERTILIZE") for p in payloads)


def test_the_three_dilutions_share_one_bulk_button_per_code():
    """Grouped by bottle for display, but confirmed per code -- marking the
    half-strength plants done must not claim the full-strength ones."""
    kb = build_keyboard([
        task("Monstera", "FERTILIZE", fertilizer="ALLPURPOSE"),
        task("Spider Plant", "FERTILIZE", fertilizer="ALLPURPOSE_HALF"),
    ])
    payloads = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]

    assert f"donefert:ALLPURPOSE:{TODAY}" in payloads
    assert f"donefert:ALLPURPOSE_HALF:{TODAY}" in payloads


def test_unmapped_plants_get_no_bulk_fertilizer_button():
    """There is no bottle to confirm -- the per-plant button still works."""
    kb = build_keyboard([task("Mint", "FERTILIZE", fertilizer=None)])
    payloads = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]

    assert "t:FERTILIZE:Mint" in payloads
    assert not any(p.startswith("donefert:") for p in payloads)


def test_mark_everything_is_the_final_row():
    kb = build_keyboard([task("A", "WATER")])
    assert kb["inline_keyboard"][-1] == [
        {"text": "✅ Mark everything above done", "callback_data": f"alldone:{TODAY}"}
    ]


def test_task_buttons_are_one_per_row():
    kb = build_keyboard([task("A", "WATER"), task("B", "WATER")])
    for row in kb["inline_keyboard"]:
        assert len(row) == 1


def test_buttons_follow_the_same_group_order_as_the_message():
    """Tapping down the keyboard should track reading down the message."""
    tasks = [
        task("Pothos", "ROTATE", days_since=8, threshold=7),
        task("Monstera", "WATER", days_since=30, threshold=10),
    ]
    kb = build_keyboard(tasks)
    payloads = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]

    assert payloads.index("t:WATER:Monstera") < payloads.index("t:ROTATE:Pothos")


def test_an_empty_task_list_yields_just_the_mark_everything_row():
    kb = build_keyboard([])
    assert len(kb["inline_keyboard"]) == 1


# --- urgency ordering, refined --------------------------------------------

def test_priority_outranks_raw_overdue_ratio_between_groups():
    """A never-rotated plant is not more urgent than a plant 3x past due for
    water. 'Never' is a cold-start artifact, not urgency."""
    text = format_digest([
        task("Pothos", "ROTATE", days_since=None, threshold=7, priority="MEDIUM"),
        task("Monstera", "WATER", days_since=30, threshold=10, priority="HIGH"),
    ], "")

    assert _index_of(text, "WATER") < _index_of(text, "ROTATE")


def test_never_done_does_not_dominate_a_far_more_overdue_task():
    text = format_digest([
        task("Pothos", "ROTATE", days_since=None, threshold=7),
        task("Monstera", "WATER", days_since=300, threshold=10),
    ], "")

    assert _index_of(text, "WATER") < _index_of(text, "ROTATE")


def test_never_still_outranks_a_barely_overdue_task():
    text = format_digest([
        task("Barely", "WATER", days_since=11, threshold=10),
        task("Never", "WATER", days_since=None, threshold=10),
    ], "")

    assert _index_of(text, "Never") < _index_of(text, "Barely")


def test_priority_orders_plants_within_a_group_too():
    text = format_digest([
        task("Low", "WATER", days_since=20, threshold=10, priority="LOW"),
        task("High", "WATER", days_since=11, threshold=10, priority="HIGH"),
    ], "")

    assert _index_of(text, "High") < _index_of(text, "Low")


def test_an_unrecognized_priority_does_not_crash_the_ordering():
    text = format_digest([
        task("A", "WATER", priority="URGENT!!"),
        task("B", "WATER", priority=""),
    ], "")
    assert "A" in text and "B" in text
