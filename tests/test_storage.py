import pandas as pd

from src.storage import PlantDB, HISTORY_HEADERS


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


# --- composite status parsing ---------------------------------------------

def test_fertilizer_confirmation_works_whatever_order_the_status_was_built_in():
    """mark_pending appends actions in whatever order Gemini emitted them, so
    'PENDING_WATER_FERTILIZE' is just as common as 'PENDING_FERTILIZE_WATER'.
    Substring matching on 'PENDING_FERTILIZE' silently misses the first."""
    for status in ["PENDING_FERTILIZE",
                   "PENDING_FERTILIZE_WATER",
                   "PENDING_WATER_FERTILIZE",
                   "PENDING_WATER_CHECK_FERTILIZE"]:
        db = make_db([{"Name": "Avocado", "Last Watered": "", "Last Fertilized": "",
                       "Status": status, "Fertilizer": "CITRUS"}])

        marked = db.mark_fertilizer_done("CITRUS", date="2026-09-19")

        assert marked == ["Avocado"], f"missed {status}"
        assert db.df.at[0, "Last Fertilized"] == "2026-09-19", f"missed {status}"
        assert "FERTILIZE" not in db.df.at[0, "Status"], f"stale status for {status}"


def test_mark_action_done_works_whatever_order_the_status_was_built_in():
    for status in ["PENDING_WATER", "PENDING_ROTATE_WATER", "PENDING_WATER_ROTATE"]:
        db = make_db([{"Name": "Monstera", "Last Watered": "", "Last Fertilized": "",
                       "Status": status}])

        assert db.mark_action_done("WATER", date="2026-09-19") == 1, f"missed {status}"
        assert db.df.at[0, "Last Watered"] == "2026-09-19"


def test_clearing_one_action_leaves_the_others_wherever_they_sat():
    db = make_db([{"Name": "Pothos", "Last Watered": "", "Last Fertilized": "",
                   "Status": "PENDING_WATER_CHECK_FERTILIZE"}])

    db.log_task_action("Pothos", "FERTILIZE", date="2026-09-19")

    assert db.df.at[0, "Status"] == "PENDING_WATER_CHECK"


def test_clearing_the_only_action_returns_the_row_to_ok():
    db = make_db([{"Name": "Pothos", "Last Watered": "", "Last Fertilized": "",
                   "Status": "PENDING_FERTILIZE"}])

    db.log_task_action("Pothos", "FERTILIZE", date="2026-09-19")

    assert db.df.at[0, "Status"] == "OK"


def test_an_action_name_that_is_a_substring_of_another_is_not_confused():
    """Guards the token parse: naive matching could see MOVE inside a longer
    composite or clear the wrong entry."""
    db = make_db([{"Name": "Pothos", "Last Watered": "", "Last Fertilized": "",
                   "Status": "PENDING_REPOT_MOVE"}])

    db.log_task_action("Pothos", "MOVE", date="2026-09-19")

    assert db.df.at[0, "Status"] == "PENDING_REPOT"


def test_mark_all_done_logs_every_action_in_a_composite_status():
    db = make_db([{"Name": "Pothos", "Last Watered": "", "Last Fertilized": "",
                   "Status": "PENDING_WATER_FERTILIZE_ROTATE"}])

    assert db.mark_all_done(date="2026-09-19") == 1

    logged = {r[2] for r in db.history_ws.appended_rows}
    assert logged == {"WATER", "FERTILIZE", "ROTATE"}
    assert db.df.at[0, "Last Watered"] == "2026-09-19"
    assert db.df.at[0, "Last Fertilized"] == "2026-09-19"
    assert db.df.at[0, "Status"] == "OK"


# --- history window -------------------------------------------------------

def test_history_summary_keeps_the_latest_of_each_action_not_the_latest_n_rows():
    """The interval engine reads days-since for six actions out of CareHistory.
    A flat 'most recent N rows' window drops PRUNE and REPOT as soon as a plant
    accrues a few waterings, making them permanently unreachable."""
    db = PlantDB.__new__(PlantDB)
    db.df = pd.DataFrame([{"Name": "Fig"}])
    db.history_ws = FakeWorksheet()
    db.history_ws.get_all_records = lambda: [
        {"Date": "2026-09-18", "Plant": "Fig", "Action": "WATER", "Notes": ""},
        {"Date": "2026-09-17", "Plant": "Fig", "Action": "WATER", "Notes": ""},
        {"Date": "2026-09-16", "Plant": "Fig", "Action": "MIST", "Notes": ""},
        {"Date": "2026-09-15", "Plant": "Fig", "Action": "WATER", "Notes": ""},
        {"Date": "2026-09-14", "Plant": "Fig", "Action": "ROTATE", "Notes": ""},
        {"Date": "2026-08-20", "Plant": "Fig", "Action": "PRUNE", "Notes": ""},
    ]

    summary = db.get_history_summary()
    actions = {r["Action"]: r["Date"] for r in summary["Fig"]}

    assert actions["PRUNE"] == "2026-08-20", "PRUNE fell out of the window"
    assert actions["WATER"] == "2026-09-18", "kept a stale WATER over the newest"
    assert actions["MIST"] == "2026-09-16"
    assert actions["ROTATE"] == "2026-09-14"


# --- per-request cost -----------------------------------------------------

class FakeHistoryWorksheet:
    """Tracks which read API the header check uses."""
    def __init__(self, first_row):
        self._first_row = first_row
        self.get_all_values_calls = 0
        self.row_values_calls = 0
        self.appended_rows = []

    def get_all_values(self):
        self.get_all_values_calls += 1
        return [self._first_row] + [["x"] * 4 for _ in range(795)]

    def row_values(self, n):
        self.row_values_calls += 1
        return self._first_row

    def append_row(self, row):
        self.appended_rows.append(row)


def test_the_header_check_does_not_download_the_whole_care_history():
    """PlantDB is constructed on every webhook request. Pulling 795 rows just
    to ask 'does this sheet have headers' was part of what OOM-killed the
    Cloud Function."""
    from src.storage import ensure_history_headers

    ws = FakeHistoryWorksheet(HISTORY_HEADERS)
    ensure_history_headers(ws)

    assert ws.get_all_values_calls == 0, "still downloading the entire sheet"
    assert ws.row_values_calls == 1
    assert ws.appended_rows == []


def test_headers_are_added_when_the_history_sheet_is_empty():
    from src.storage import ensure_history_headers

    ws = FakeHistoryWorksheet([])
    ensure_history_headers(ws)

    assert ws.appended_rows == [HISTORY_HEADERS]


def test_existing_headers_are_left_alone():
    from src.storage import ensure_history_headers

    ws = FakeHistoryWorksheet(HISTORY_HEADERS)
    ensure_history_headers(ws)

    assert ws.appended_rows == []
