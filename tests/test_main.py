import pytest

import main as main_module


class FakePlantDB:
    def __init__(self):
        self.mark_pending_calls = []

    def get_history_summary(self, limit_per_plant=None):
        return {}

    def get_inventory(self):
        return []

    def mark_pending(self, tasks):
        self.mark_pending_calls.append(tasks)


class FakeAgent:
    tasks = [{"name": "Monstera", "action": "WATER", "priority": "HIGH",
              "reason": "Soil dry", "days_since": 12, "threshold": 10,
              "base": 10, "adjustments": [], "fertilizer": None}]

    def get_tasks(self, weather, inventory, care_history):
        return list(self.tasks), "All good"


@pytest.fixture
def fake_db(monkeypatch):
    """Patches the lazy-import seam.

    main.py defers the Advisor's imports so the Cloud Function entry point
    doesn't drag the Gemini SDK into a memory-constrained container, so the
    fakes go in through _advisor() rather than module globals."""
    from src.digest import format_digest, build_keyboard
    db = FakePlantDB()
    state = {"sent": None}

    def fake_send(message, reply_markup=None):
        state["sent"] = (message, reply_markup)
        return state.get("send_result", True)

    monkeypatch.setattr(main_module, "_advisor", lambda: (
        "fake-model", lambda: db, lambda: {"summary": "sunny"}, FakeAgent,
        fake_send, format_digest, build_keyboard,
    ))
    db.state = state
    return db


def test_main_marks_pending_when_the_digest_sends(fake_db, capsys):
    main_module.main()

    assert len(fake_db.mark_pending_calls) == 1
    assert "✅ Sent 1 care recommendations." in capsys.readouterr().out


def test_main_skips_mark_pending_when_the_digest_fails_to_send(fake_db, capsys):
    """Marking tasks pending after a failed send would hide them from tomorrow's
    run while no digest was ever shown -- a silent false success."""
    fake_db.state["send_result"] = False

    main_module.main()

    assert fake_db.mark_pending_calls == []
    out = capsys.readouterr().out
    assert "✅ Sent" not in out
    assert "❌" in out


def test_main_sends_the_grouped_digest_with_its_keyboard(fake_db):
    main_module.main()

    text, markup = fake_db.state["sent"]
    assert "WATER" in text and "Monstera" in text
    payloads = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
    assert "t:WATER:Monstera" in payloads


def test_main_reports_a_quiet_day_without_sending(fake_db, monkeypatch, capsys):
    monkeypatch.setattr(FakeAgent, "tasks", [])

    main_module.main()

    assert fake_db.state["sent"] is None
    assert "No tasks today" in capsys.readouterr().out


def test_the_webhook_entry_point_is_importable_from_main():
    """functions-framework resolves --entry-point=telegram_webhook from here."""
    assert callable(main_module.telegram_webhook)
