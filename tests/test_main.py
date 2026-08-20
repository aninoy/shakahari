from datetime import datetime

import pytest

import main as main_module
from main import format_tasks, build_digest_keyboard


def test_format_tasks_has_no_tap_to_log_text():
    tasks = [{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "Soil dry"}]

    text = format_tasks(tasks, "All good")

    assert "Tap to log" not in text
    assert "/water_monstera" not in text
    assert "Monstera" in text
    assert "Soil dry" in text


def test_build_digest_keyboard_has_one_row_per_task_plus_mark_all_done():
    tasks = [
        {"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "Soil dry"},
        {"name": "Pothos", "action": "ROTATE", "priority": "LOW", "reason": "Leaning"},
    ]

    keyboard = build_digest_keyboard(tasks)
    rows = keyboard["inline_keyboard"]

    assert len(rows) == 3
    assert rows[0][0] == {"text": "💧 Watered", "callback_data": "t:WATER:Monstera"}
    assert rows[0][1] == {"text": "⏭ Skip today", "callback_data": "skip:WATER:Monstera"}
    assert rows[1][0] == {"text": "🔄 Rotated", "callback_data": "t:ROTATE:Pothos"}
    today = datetime.now().strftime("%Y-%m-%d")
    assert rows[2] == [{"text": "✅ Mark everything above done", "callback_data": f"alldone:{today}"}]


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
