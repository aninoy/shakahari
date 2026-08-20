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
