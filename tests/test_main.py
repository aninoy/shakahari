from datetime import datetime

import pytest

import main as main_module
from main import format_tasks, build_digest_keyboard


def test_format_tasks_is_compact_with_a_days_since_code_not_prose():
    tasks = [{
        "name": "Monstera", "action": "WATER", "priority": "HIGH",
        "reason": "Soil dry after 8 days, indoor heat accelerates drying",
        "days_since": 12, "threshold": 10,
    }]

    text = format_tasks(tasks, "All good")

    assert "Tap to log" not in text
    assert "/water_monstera" not in text
    assert "Soil dry" not in text
    assert "Monstera" in text
    assert "12d overdue" in text
    assert "🔁10d" in text


def test_format_tasks_shows_never_when_no_history_exists():
    tasks = [{"name": "Fern", "action": "CHECK", "priority": "LOW", "days_since": None, "threshold": 3}]

    text = format_tasks(tasks, "")

    assert "never" in text


def test_build_digest_keyboard_buttons_name_the_plant_with_no_skip_option():
    tasks = [
        {"name": "Monstera", "action": "WATER", "priority": "HIGH", "days_since": 12, "threshold": 10},
        {"name": "Pothos", "action": "ROTATE", "priority": "LOW", "days_since": 9, "threshold": 7},
    ]

    keyboard = build_digest_keyboard(tasks)
    rows = keyboard["inline_keyboard"]

    assert rows[0] == [{"text": "💧 Water Monstera", "callback_data": "t:WATER:Monstera"}]
    assert rows[1] == [{"text": "🔄 Rotate Pothos", "callback_data": "t:ROTATE:Pothos"}]
    task_rows = rows[:2]
    for row in task_rows:
        assert len(row) == 1


def test_build_digest_keyboard_adds_one_bulk_button_per_action_present():
    tasks = [
        {"name": "Monstera", "action": "WATER", "priority": "HIGH", "days_since": 12, "threshold": 10},
        {"name": "Fern", "action": "WATER", "priority": "LOW", "days_since": 15, "threshold": 10},
        {"name": "Pothos", "action": "ROTATE", "priority": "LOW", "days_since": 9, "threshold": 7},
    ]

    keyboard = build_digest_keyboard(tasks)
    rows = keyboard["inline_keyboard"]
    today = datetime.now().strftime("%Y-%m-%d")

    bulk_rows = [r for r in rows if r[0]["callback_data"].startswith("donetype:")]
    assert bulk_rows == [
        [{"text": "💧 Mark watering complete", "callback_data": f"donetype:WATER:{today}"}],
        [{"text": "🔄 Mark rotating complete", "callback_data": f"donetype:ROTATE:{today}"}],
    ]
    assert rows[-1] == [{"text": "✅ Mark everything above done", "callback_data": f"alldone:{today}"}]


class FakePlantDB:
    def __init__(self):
        self.mark_pending_calls = []

    def get_history_summary(self, limit_per_plant=5):
        return {}

    def get_inventory(self):
        return []

    def mark_pending(self, tasks):
        self.mark_pending_calls.append(tasks)


class FakeAgent:
    def get_tasks(self, weather, inventory, care_history):
        return [{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "Soil dry"}], "All good"


@pytest.fixture
def fake_db(monkeypatch):
    db = FakePlantDB()
    monkeypatch.setattr(main_module, "PlantDB", lambda: db)
    monkeypatch.setattr(main_module, "get_forecast", lambda: {"summary": "sunny"})
    monkeypatch.setattr(main_module, "PlantAgent", FakeAgent)
    return db


def test_main_marks_pending_when_the_digest_sends(fake_db, monkeypatch, capsys):
    monkeypatch.setattr(main_module, "send_message", lambda message, reply_markup=None: True)

    main_module.main()

    assert len(fake_db.mark_pending_calls) == 1
    assert "✅ Sent 1 care recommendations." in capsys.readouterr().out


def test_main_skips_mark_pending_when_the_digest_fails_to_send(fake_db, monkeypatch, capsys):
    """Marking tasks pending after a failed send would hide them from tomorrow's run
    while no digest was ever shown -- a silent false success."""
    monkeypatch.setattr(main_module, "send_message", lambda message, reply_markup=None: False)

    main_module.main()

    assert fake_db.mark_pending_calls == []
    out = capsys.readouterr().out
    assert "✅ Sent" not in out
    assert "❌" in out
