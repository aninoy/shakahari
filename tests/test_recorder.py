from datetime import datetime

import pandas as pd
import pytest

from src import recorder


# The owner's chat id as config holds it (env vars are always strings)...
OWNER_CHAT_ID = "424242"
# ...and as Telegram sends it inside an update (a JSON number).
OWNER_CHAT_ID_FROM_TELEGRAM = 424242
# Any other Telegram user who discovers the bot.
STRANGER_CHAT_ID = 999999


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
def _reset_fake_db(monkeypatch):
    FakePlantDB.instances = []
    monkeypatch.setattr(recorder, "TELEGRAM_CHAT_ID", OWNER_CHAT_ID)
    yield


def _callback_update(data, chat_id=OWNER_CHAT_ID_FROM_TELEGRAM, message_id=2, markup=None):
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


def _message_update(text, chat_id=OWNER_CHAT_ID_FROM_TELEGRAM):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def test_webhook_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    request = FakeRequest({"callback_query": {}}, secret="wrong")

    body, status = recorder.telegram_webhook(request)

    assert status == 403


@pytest.mark.parametrize("unset_value", [None, ""])
def test_webhook_refuses_every_request_when_secret_is_unset(monkeypatch, unset_value):
    """A missing TELEGRAM_WEBHOOK_SECRET must fail closed. Without this, a request
    carrying no secret header compares None != None -> False and gets processed,
    turning the function into a public, unauthenticated Sheet-writing endpoint."""
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", unset_value)
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)

    assert recorder.telegram_webhook(FakeRequest({"callback_query": {}}, secret=None))[1] == 403
    assert recorder.telegram_webhook(FakeRequest({"callback_query": {}}, secret=""))[1] == 403
    assert recorder.telegram_webhook(FakeRequest({"callback_query": {}}, secret="anything"))[1] == 403


def test_callback_from_another_chat_is_ignored(monkeypatch):
    """The secret header only proves Telegram sent the update, not that the owner did.
    A stranger's button tap must not reach the Sheet."""
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    answers = []
    edits = []
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: answers.append((a, k)))
    monkeypatch.setattr(recorder, "edit_message_reply_markup", lambda *a, **k: edits.append((a, k)))

    markup = {"inline_keyboard": [[{"text": "Watered", "callback_data": "t:WATER:Monstera"}]]}
    request = FakeRequest(
        _callback_update("t:WATER:Monstera", chat_id=STRANGER_CHAT_ID, markup=markup),
        secret="test-secret",
    )

    body, status = recorder.telegram_webhook(request)

    # Same 200 the owner gets, so a prober learns nothing from the response.
    assert status == 200
    assert FakePlantDB.instances == []
    assert answers == []
    assert edits == []


def test_log_command_from_another_chat_is_ignored(monkeypatch):
    """A stranger's /log must not read the inventory nor push a picker into the owner's chat."""
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    sent = []
    monkeypatch.setattr(recorder, "send_message", lambda text, reply_markup=None: sent.append(text))

    request = FakeRequest(_message_update("/log", chat_id=STRANGER_CHAT_ID), secret="test-secret")

    body, status = recorder.telegram_webhook(request)

    assert status == 200
    assert FakePlantDB.instances == []
    assert sent == []


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


def test_skip_button_shows_error_when_plant_not_found(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)

    class NotFoundPlantDB(FakePlantDB):
        def clear_pending_action(self, plant_name, action):
            self.skip_calls.append((plant_name, action))
            return False

    monkeypatch.setattr(recorder, "PlantDB", NotFoundPlantDB)

    edits = []
    answers = []
    monkeypatch.setattr(recorder, "edit_message_reply_markup", lambda *a, **k: edits.append((a, k)))
    monkeypatch.setattr(
        recorder, "answer_callback_query",
        lambda callback_id, text="", show_alert=False: answers.append((callback_id, text, show_alert)),
    )

    markup = {"inline_keyboard": [[{"text": "Skip", "callback_data": "skip:WATER:Unknown Plant"}]]}
    request = FakeRequest(_callback_update("skip:WATER:Unknown Plant", markup=markup), secret="test-secret")

    recorder.telegram_webhook(request)

    assert edits == []
    assert answers[-1][2] is True


def test_alldone_clears_entire_keyboard(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    edits = []
    monkeypatch.setattr(
        recorder, "edit_message_reply_markup",
        lambda chat_id, message_id, reply_markup: edits.append(reply_markup),
    )
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    today = datetime.now().strftime("%Y-%m-%d")
    request = FakeRequest(_callback_update(f"alldone:{today}"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert FakePlantDB.instances[-1].alldone_calls == [today]
    assert edits[-1] == {"inline_keyboard": []}


def test_alldone_from_a_previous_days_digest_is_refused(monkeypatch):
    """mark_all_done() is scoped to whatever the Sheet shows as pending *now*, so
    honouring a stale digest's baked-in date would stamp today's pending work with
    an old date. Refuse instead of corrupting care-history dates."""
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    edits = []
    answers = []
    monkeypatch.setattr(recorder, "edit_message_reply_markup", lambda *a, **k: edits.append((a, k)))
    monkeypatch.setattr(
        recorder, "answer_callback_query",
        lambda callback_id, text="", show_alert=False: answers.append((text, show_alert)),
    )

    request = FakeRequest(_callback_update("alldone:2020-01-01"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert FakePlantDB.instances == []  # never even opened the Sheet
    assert edits == []
    assert "previous day" in answers[-1][0]
    assert answers[-1][1] is True


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
    # From the owner (so it gets past the sender check) but missing "message_id" --
    # something a well-formed digest button never sends, but the webhook must not
    # 500 (Telegram would retry indefinitely) if it ever does.
    request = FakeRequest(
        {"callback_query": {
            "id": "cbq-2",
            "data": "t:WATER:Monstera",
            "message": {"chat": {"id": OWNER_CHAT_ID_FROM_TELEGRAM}},
        }},
        secret="test-secret",
    )

    body, status = recorder.telegram_webhook(request)

    assert status == 200


def test_log_command_sends_plant_picker(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    class FakeInventoryDB(FakePlantDB):
        def get_inventory(self):
            return pd.DataFrame([{"Name": "Monstera"}, {"Name": "Pothos"}])

    monkeypatch.setattr(recorder, "PlantDB", FakeInventoryDB)
    sent = []
    monkeypatch.setattr(recorder, "send_message", lambda text, reply_markup=None: sent.append((text, reply_markup)))

    request = FakeRequest(_message_update("/log"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert sent[0][0] == "Which plant?"
    assert sent[0][1]["inline_keyboard"] == [
        [{"text": "Monstera", "callback_data": "logsel:Monstera"}],
        [{"text": "Pothos", "callback_data": "logsel:Pothos"}],
    ]


def test_logsel_shows_action_picker(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    edits = []
    monkeypatch.setattr(
        recorder, "edit_message_text",
        lambda chat_id, message_id, text, reply_markup=None: edits.append((text, reply_markup)),
    )
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    request = FakeRequest(_callback_update("logsel:Monstera"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert edits[0][0] == "What did you do for Monstera?"
    labels = [btn["text"] for row in edits[0][1]["inline_keyboard"] for btn in row]
    assert "💧 Water" in labels
    assert "‹ Back" in labels


def test_logact_logs_and_confirms(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(recorder, "PlantDB", FakePlantDB)
    edits = []
    monkeypatch.setattr(
        recorder, "edit_message_text",
        lambda chat_id, message_id, text, reply_markup=None: edits.append(text),
    )
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    request = FakeRequest(_callback_update("logact:Monstera:MIST"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert FakePlantDB.instances[-1].log_calls == [("Monstera", "MIST")]
    assert edits[0] == "✅ Logged Mist for Monstera"


def test_logback_shows_plant_picker_again(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    class FakeInventoryDB(FakePlantDB):
        def get_inventory(self):
            return pd.DataFrame([{"Name": "Fern"}])

    monkeypatch.setattr(recorder, "PlantDB", FakeInventoryDB)
    edits = []
    monkeypatch.setattr(
        recorder, "edit_message_text",
        lambda chat_id, message_id, text, reply_markup=None: edits.append((text, reply_markup)),
    )
    monkeypatch.setattr(recorder, "answer_callback_query", lambda *a, **k: None)

    request = FakeRequest(_callback_update("logback"), secret="test-secret")

    recorder.telegram_webhook(request)

    assert edits[0][0] == "Which plant?"
    assert edits[0][1]["inline_keyboard"] == [[{"text": "Fern", "callback_data": "logsel:Fern"}]]
