import pandas as pd

from src.storage import PlantDB


class FakeWorksheet:
    def __init__(self):
        self.appended_rows = []
        self.updated = None

    def append_row(self, row):
        self.appended_rows.append(row)

    def update(self, values):
        self.updated = values


def make_db(rows):
    db = PlantDB.__new__(PlantDB)
    db.df = pd.DataFrame(rows)
    db.history_ws = FakeWorksheet()
    db.worksheet = FakeWorksheet()
    return db


def test_log_task_action_updates_last_watered_and_history():
    db = make_db([
        {"Name": "Monstera", "Last Watered": "2026-08-10", "Last Fertilized": "", "Status": "PENDING_WATER"},
    ])

    found = db.log_task_action("Monstera", "WATER", date="2026-08-19")

    assert found is True
    assert db.df.at[0, "Last Watered"] == "2026-08-19"
    assert db.df.at[0, "Status"] == "OK"
    assert db.history_ws.appended_rows == [["2026-08-19", "Monstera", "WATER", ""]]


def test_log_task_action_is_case_insensitive_exact_match():
    db = make_db([{"Name": "Monstera", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"}])

    found = db.log_task_action("monstera", "WATER", date="2026-08-19")

    assert found is True


def test_log_task_action_does_not_match_substring():
    db = make_db([
        {"Name": "Monstera Deliciosa", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"},
    ])

    found = db.log_task_action("Monstera", "WATER", date="2026-08-19")

    assert found is False
    assert db.history_ws.appended_rows == []


def test_log_task_action_keeps_other_pending_actions():
    db = make_db([
        {"Name": "Pothos", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER_ROTATE"},
    ])

    db.log_task_action("Pothos", "WATER", date="2026-08-19")

    assert db.df.at[0, "Status"] == "PENDING_ROTATE"


def test_mark_action_done_logs_every_plant_pending_that_action():
    db = make_db([
        {"Name": "Monstera", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"},
        {"Name": "Pothos", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_ROTATE"},
        {"Name": "Fern", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER_ROTATE"},
    ])

    updated = db.mark_action_done("WATER", date="2026-08-20")

    assert updated == 2
    assert db.df.at[0, "Status"] == "OK"
    assert db.df.at[0, "Last Watered"] == "2026-08-20"
    assert db.df.at[1, "Status"] == "PENDING_ROTATE"  # untouched -- different action
    assert db.df.at[2, "Status"] == "PENDING_ROTATE"  # WATER cleared, ROTATE remains
    assert db.df.at[2, "Last Watered"] == "2026-08-20"
    logged = {(r[1], r[2]) for r in db.history_ws.appended_rows}
    assert ("Monstera", "WATER") in logged
    assert ("Fern", "WATER") in logged
    assert ("Pothos", "WATER") not in logged


def test_mark_action_done_returns_zero_and_skips_save_when_nothing_pending():
    db = make_db([{"Name": "Fern", "Last Watered": "", "Last Fertilized": "", "Status": "OK"}])

    updated = db.mark_action_done("WATER", date="2026-08-20")

    assert updated == 0
    assert db.worksheet.updated is None


def test_mark_all_done_logs_every_pending_plant():
    db = make_db([
        {"Name": "Monstera", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"},
        {"Name": "Pothos", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_ROTATE"},
        {"Name": "Fern", "Last Watered": "", "Last Fertilized": "", "Status": "OK"},
    ])

    updated = db.mark_all_done(date="2026-08-19")

    assert updated == 2
    assert db.df.at[0, "Status"] == "OK"
    assert db.df.at[1, "Status"] == "OK"
    assert db.df.at[2, "Status"] == "OK"
    logged_actions = {(r[1], r[2]) for r in db.history_ws.appended_rows}
    assert ("Monstera", "WATER") in logged_actions
    assert ("Pothos", "ROTATE") in logged_actions


# --- per-product fertilizer confirmation -----------------------------------

def _fert_rows():
    return [
        {"Name": "Avocado", "Last Watered": "", "Last Fertilized": "",
         "Status": "PENDING_FERTILIZE", "Fertilizer": "CITRUS"},
        {"Name": "Orange", "Last Watered": "", "Last Fertilized": "",
         "Status": "PENDING_FERTILIZE_CHECK", "Fertilizer": "citrus-tone"},
        {"Name": "Bougainvillea", "Last Watered": "", "Last Fertilized": "",
         "Status": "PENDING_FERTILIZE", "Fertilizer": "BLOOM"},
        {"Name": "Monstera", "Last Watered": "", "Last Fertilized": "",
         "Status": "PENDING_WATER", "Fertilizer": "CITRUS"},
    ]


def test_mark_fertilizer_done_only_touches_that_product():
    """The bug being fixed: one 'fertilizing complete' tap used to claim every
    product at once."""
    db = make_db(_fert_rows())

    marked = db.mark_fertilizer_done("CITRUS", date="2026-09-19")

    assert sorted(marked) == ["Avocado", "Orange"]
    assert db.df.at[2, "Last Fertilized"] == ""       # Bougainvillea untouched
    assert db.df.at[2, "Status"] == "PENDING_FERTILIZE"


def test_mark_fertilizer_done_returns_names_so_the_recorder_can_edit_those_rows():
    db = make_db(_fert_rows())
    marked = db.mark_fertilizer_done("BLOOM", date="2026-09-19")
    assert marked == ["Bougainvillea"]


def test_mark_fertilizer_done_normalizes_the_sheet_value():
    """'citrus-tone' typed by hand must match the CITRUS code."""
    db = make_db(_fert_rows())
    assert "Orange" in db.mark_fertilizer_done("CITRUS", date="2026-09-19")


def test_mark_fertilizer_done_ignores_plants_not_pending_fertilize():
    db = make_db(_fert_rows())
    db.mark_fertilizer_done("CITRUS", date="2026-09-19")
    assert db.df.at[3, "Status"] == "PENDING_WATER"   # Monstera, pending WATER only
    assert db.df.at[3, "Last Fertilized"] == ""


def test_mark_fertilizer_done_keeps_other_pending_actions_on_the_same_plant():
    db = make_db(_fert_rows())
    db.mark_fertilizer_done("CITRUS", date="2026-09-19")
    assert db.df.at[1, "Status"] == "PENDING_CHECK"   # Orange keeps its CHECK


def test_mark_fertilizer_done_records_the_product_in_history():
    """CareHistory should say which bottle was actually applied."""
    db = make_db(_fert_rows())
    db.mark_fertilizer_done("BLOOM", date="2026-09-19")

    row = db.history_ws.appended_rows[0]
    assert row[:3] == ["2026-09-19", "Bougainvillea", "FERTILIZE"]
    assert "Bloom Booster" in row[3]


def test_mark_fertilizer_done_with_no_matches_writes_nothing():
    db = make_db(_fert_rows())
    assert db.mark_fertilizer_done("ACID", date="2026-09-19") == []
    assert db.history_ws.appended_rows == []
    assert db.worksheet.updated is None


def test_mark_fertilizer_done_survives_a_sheet_without_the_column():
    """Runs against a sheet where the Fertilizer column hasn't been added yet."""
    db = make_db([
        {"Name": "Monstera", "Last Watered": "", "Last Fertilized": "",
         "Status": "PENDING_FERTILIZE"},
    ])
    assert db.mark_fertilizer_done("CITRUS", date="2026-09-19") == []
