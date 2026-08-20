import pytest

from src import recorder


class FakeRequest:
    def __init__(self, body, secret="test-secret"):
        self._body = body
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}

    def get_json(self, silent=True):
        return self._body


class FakePlantDB:
    instances = []

    def __init__(self):
        self.log_calls = []
        self.skip_calls = []
        self.alldone_calls = []
        FakePlantDB.instances.append(self)

    def log_task_action(self, plant_name, action, date=None):
        self.log_calls.append((plant_name, action))
        return plant_name != "Unknown Plant"

    def clear_pending_action(self, plant_name, action):
        self.skip_calls.append((plant_name, action))
        return True

    def mark_all_done(self, date=None):
        self.alldone_calls.append(date)
        return 2


@pytest.fixture(autouse=True)
def _reset_fake_db():
    FakePlantDB.instances = []
    yield


def _callback_update(data, chat_id=1, message_id=2, markup=None):
    return {
        "callback_query": {
            "id": "cbq-1",
            "data": data,
            "message": {
                "chat": {"id": chat_id},
                "message_id": message_id,
                "reply_markup": markup or {"inline_keyboard": []},
            },
        }
    }


def test_webhook_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    request = FakeRequest({"callback_query": {}}, secret="wrong")

    body, status = recorder.telegram_webhook(request)

    assert status == 403


def test_task_button_logs_action_and_confirms(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)

    edits = []
    answers = []
    monkeypatch.setattr(
        recorder, "edit_message_reply_markup",
        lambda chat_id, message_id, reply_markup: edits.append((chat_id, message_id, reply_markup)),
    )
    monkeypatch.setattr(
        recorder, "answer_callback_query",
        lambda callback_id, text="", show_alert=False: answers.append((callback_id, text, show_alert)),
    )

    markup = {"inline_keyboard": [
        [{"text": "Watered", "callback_data": "t:WATER:Monstera"}, {"text": "Skip", "callback_data": "skip:WATER:Monstera"}],
        [{"text": "Mark all done", "callback_data": "alldone:2026-08-19"}],
    ]}
    request = FakeRequest(_callback_update("t:WATER:Monstera", markup=markup), secret="test-secret")

    body, status = recorder.telegram_webhook(request)

    assert status == 200
    assert FakePlantDB.instances[-1].log_calls == [("Monstera", "WATER")]
    assert edits[-1][2]["inline_keyboard"][0] == [{"text": "✓ Logged just now", "callback_data": "noop"}]
    assert edits[-1][2]["inline_keyboard"][1] == markup["inline_keyboard"][1]
    assert answers[-1][0] == "cbq-1"


def test_task_button_shows_error_when_plant_not_found(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)

    edits = []
    answers = []
    monkeypatch.setattr(recorder, "edit_message_reply_markup", lambda *a, **k: edits.append((a, k)))
    monkeypatch.setattr(
        recorder, "answer_callback_query",
        lambda callback_id, text="", show_alert=False: answers.append((callback_id, text, show_alert)),
    )

    markup = {"inline_keyboard": [[{"text": "Watered", "callback_data": "t:WATER:Unknown Plant"}]]}
    request = FakeRequest(_callback_update("t:WATER:Unknown Plant", markup=markup), secret="test-secret")

    recorder.telegram_webhook(request)

    assert edits == []
    assert answers[-1][2] is True


def test_skip_button_clears_without_logging(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    edits = []
    monkeypatch.setattr(
        recorder, "edit_message_reply_markup",
        lambda chat_id, message_id, reply_markup: edits.append(reply_markup),
    )
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    markup = {"inline_keyboard": [[
        {"text": "Watered", "callback_data": "t:WATER:Pothos"},
        {"text": "Skip", "callback_data": "skip:WATER:Pothos"},
    ]]}
    request = FakeRequest(_callback_update("skip:WATER:Pothos", markup=markup), secret="test-secret")

    recorder.telegram_webhook(request)

    assert FakePlantDB.instances[-1].skip_calls == [("Pothos", "WATER")]
    assert edits[-1]["inline_keyboard"][0] == [{"text": "⏭ Skipped for today", "callback_data": "noop"}]


def test_alldone_clears_entire_keyboard(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    edits = []
    monkeypatch.setattr(
        recorder, "edit_message_reply_markup",
        lambda chat_id, message_id, reply_markup: edits.append(reply_markup),
    )
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    request = FakeRequest(_callback_update("alldone:2026-08-19"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert FakePlantDB.instances[-1].alldone_calls == ["2026-08-19"]
    assert edits[-1] == {"inline_keyboard": []}


def test_unknown_callback_data_is_a_noop(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    answers = []
    monkeypatch.setattr(
        recorder, "answer_callback_query",
        lambda callback_id, text="", show_alert=False: answers.append(callback_id),
    )

    request = FakeRequest(_callback_update("garbage"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert FakePlantDB.instances == []
    assert answers == ["cbq-1"]


def test_malformed_callback_query_returns_200_without_crashing(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    # Missing "message" entirely -- something a well-formed digest button never sends,
    # but the webhook must not 500 (Telegram would retry indefinitely) if it ever does.
    request = FakeRequest({"callback_query": {"id": "cbq-2", "data": "t:WATER:Monstera"}}, secret="test-secret")

    body, status = recorder.telegram_webhook(request)

    assert status == 200
