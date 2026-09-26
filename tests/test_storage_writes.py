"""Write-path behaviour: targeted cell updates and append idempotency.

Every tap used to rewrite all 190 cells of the Plants sheet from a snapshot
taken when the request started. Two taps that overlapped lost one's changes --
and because CareHistory is appended immediately while Plants is only written at
save(), the loser left history saying the action happened and Plants still
saying it was pending.
"""
import pandas as pd
import pytest

from src.storage import PlantDB, HISTORY_HEADERS


class RecordingWorksheet:
    def __init__(self, history=None):
        self.batch_updates = []
        self.full_updates = []
        self.appended_rows = []
        self._history = list(history or [])

    # --- Plants ---
    def batch_update(self, data, **kwargs):
        self.batch_updates.append(data)

    def update(self, values, *a, **k):
        self.full_updates.append(values)

    # --- CareHistory ---
    def append_row(self, row):
        self.appended_rows.append(row)
        self._history.append(row)

    def col_values(self, n):
        return [HISTORY_HEADERS[n - 1]] + [str(r[n - 1]) for r in self._history]

    def get(self, a1):
        return [[str(c) for c in r] for r in self._history]

    def row_values(self, n):
        return HISTORY_HEADERS


def make_db(rows, history=None):
    db = PlantDB.__new__(PlantDB)
    db.df = pd.DataFrame(rows)
    db.worksheet = RecordingWorksheet()
    db.history_ws = RecordingWorksheet(history)
    db._reset_write_state()
    return db


def plants():
    return [
        {"Name": "Monstera", "Last Watered": "2026-09-01", "Last Fertilized": "",
         "Status": "PENDING_WATER_ROTATE", "Fertilizer": "ALLPURPOSE"},
        {"Name": "Avocado", "Last Watered": "", "Last Fertilized": "",
         "Status": "PENDING_FERTILIZE", "Fertilizer": "CITRUS"},
    ]


def _cells(ws):
    """Flatten batch updates into {range: value}."""
    out = {}
    for batch in ws.batch_updates:
        for entry in batch:
            out[entry["range"]] = entry["values"][0][0]
    return out


# --- targeted writes ------------------------------------------------------

def test_a_tap_writes_only_the_cells_it_changed():
    db = make_db(plants())

    db.log_task_action("Monstera", "WATER", date="2026-09-26")

    assert db.worksheet.full_updates == [], "still rewriting the whole sheet"
    cells = _cells(db.worksheet)
    # Monstera is df row 0 -> sheet row 2 (row 1 is the header).
    assert cells == {"B2": "2026-09-26", "D2": "PENDING_ROTATE"}


def test_touching_one_plant_leaves_every_other_row_unwritten():
    """This is what stops two taps on different plants from clobbering each
    other: their writes no longer overlap at all."""
    db = make_db(plants())

    db.log_task_action("Avocado", "FERTILIZE", date="2026-09-26")

    assert all(not r.endswith("2") for r in _cells(db.worksheet)), "wrote Monstera's row"
    assert set(_cells(db.worksheet)) == {"C3", "D3"}


def test_saving_with_nothing_changed_makes_no_api_call():
    db = make_db(plants())

    db.save()

    assert db.worksheet.batch_updates == []
    assert db.worksheet.full_updates == []


def test_a_bulk_confirmation_batches_every_row_into_one_write():
    db = make_db([
        {"Name": "A", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"},
        {"Name": "B", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"},
    ])

    db.mark_action_done("WATER", date="2026-09-26")

    assert len(db.worksheet.batch_updates) == 1, "one batch, not one call per row"
    assert set(_cells(db.worksheet)) == {"B2", "D2", "B3", "D3"}


def test_column_letters_follow_the_sheets_own_column_order():
    """The mapping is positional, so a reordered sheet must still write the
    right cells rather than silently corrupting neighbours."""
    rows = [{"Status": "PENDING_WATER", "Name": "Monstera",
             "Last Fertilized": "", "Last Watered": ""}]
    db = make_db(rows)

    db.log_task_action("Monstera", "WATER", date="2026-09-26")

    cells = _cells(db.worksheet)
    assert cells["D2"] == "2026-09-26"   # 'Last Watered' is the 4th column here
    assert cells["A2"] == "OK"           # 'Status' is the 1st


def test_mark_pending_also_writes_only_the_status_cells():
    db = make_db(plants())

    db.mark_pending([{"name": "Monstera", "action": "CHECK"}])

    assert set(_cells(db.worksheet)) == {"D2"}
    assert _cells(db.worksheet)["D2"] == "PENDING_WATER_ROTATE_CHECK"


# --- append idempotency ---------------------------------------------------

def test_the_same_action_logged_twice_in_a_day_appends_once():
    """Telegram retries any delivery that times out, and the handler is not
    idempotent -- a retry would otherwise duplicate the history row."""
    db = make_db(plants())

    db.log_task_action("Monstera", "WATER", date="2026-09-26")
    db.log_task_action("Monstera", "WATER", date="2026-09-26")

    waters = [r for r in db.history_ws.appended_rows if r[2] == "WATER"]
    assert len(waters) == 1


def test_a_retry_is_deduped_against_rows_already_on_the_sheet():
    db = make_db(plants(), history=[["2026-09-26", "Monstera", "WATER", ""]])

    db.log_task_action("Monstera", "WATER", date="2026-09-26")

    assert db.history_ws.appended_rows == []


def test_the_same_action_on_a_different_day_still_logs():
    db = make_db(plants(), history=[["2026-09-25", "Monstera", "WATER", ""]])

    db.log_task_action("Monstera", "WATER", date="2026-09-26")

    assert len(db.history_ws.appended_rows) == 1


def test_different_actions_on_the_same_day_all_log():
    db = make_db([{"Name": "A", "Last Watered": "", "Last Fertilized": "",
                   "Status": "PENDING_WATER_ROTATE_CHECK"}])

    db.mark_all_done(date="2026-09-26")

    logged = sorted(r[2] for r in db.history_ws.appended_rows)
    assert logged == ["CHECK", "ROTATE", "WATER"]


def test_dedupe_is_case_and_whitespace_insensitive_on_the_plant_name():
    db = make_db(plants(), history=[["2026-09-26", " monstera ", "WATER", ""]])

    db.log_task_action("Monstera", "WATER", date="2026-09-26")

    assert db.history_ws.appended_rows == []


def test_the_plants_sheet_is_still_updated_even_when_the_log_is_deduped():
    """A retry must not skip the Status clear just because the history row
    already exists -- that is exactly the divergence being fixed."""
    db = make_db(plants(), history=[["2026-09-26", "Monstera", "WATER", ""]])

    assert db.log_task_action("Monstera", "WATER", date="2026-09-26") is True
    assert _cells(db.worksheet)["D2"] == "PENDING_ROTATE"
