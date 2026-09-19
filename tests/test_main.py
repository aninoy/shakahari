import pytest

import main as main_module


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


def test_main_sends_the_grouped_digest_with_its_keyboard(fake_db, monkeypatch):
    """main() is orchestration only -- formatting lives in src/digest.py."""
    sent = {}
    monkeypatch.setattr(
        main_module, "send_message",
        lambda message, reply_markup=None: sent.update(text=message, markup=reply_markup) or True,
    )

    main_module.main()

    assert "WATER" in sent["text"]
    assert "Monstera" in sent["text"]
    payloads = [b["callback_data"] for row in sent["markup"]["inline_keyboard"] for b in row]
    assert "t:WATER:Monstera" in payloads


def test_main_reports_a_quiet_day_without_sending(fake_db, monkeypatch, capsys):
    monkeypatch.setattr(main_module.PlantAgent, "get_tasks",
                        lambda self, w, i, c: ([], "All healthy"), raising=False)
    monkeypatch.setattr(main_module, "send_message",
                        lambda *a, **k: pytest.fail("nothing should be sent"))

    main_module.main()

    assert "No tasks today" in capsys.readouterr().out
