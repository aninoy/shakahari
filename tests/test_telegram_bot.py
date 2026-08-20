import json

from src import telegram_bot as tb


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_send_message_posts_plain_text(monkeypatch):
    captured = {}

    def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(tb.requests, "post", fake_post)

    tb.send_message("hello")

    assert captured["url"] == f"{tb.BASE_URL}/sendMessage"
    assert captured["json"]["text"] == "hello"
    assert "reply_markup" not in captured["json"]


def test_send_message_attaches_keyboard_to_last_chunk_only(monkeypatch):
    calls = []

    def fake_post(url, json):
        calls.append(json)
        return FakeResponse()

    monkeypatch.setattr(tb.requests, "post", fake_post)

    line_a = "a" * 3990
    line_b = "b" * 3990
    keyboard = {"inline_keyboard": [[{"text": "Go", "callback_data": "t:WATER:Fern"}]]}

    tb.send_message(f"{line_a}\n{line_b}", reply_markup=keyboard)

    assert len(calls) == 2
    assert "reply_markup" not in calls[0]
    assert json.loads(calls[1]["reply_markup"]) == keyboard


def test_send_message_returns_true_when_every_chunk_sends(monkeypatch):
    monkeypatch.setattr(tb.requests, "post", lambda url, json: FakeResponse())

    assert tb.send_message("hello") is True


def test_send_message_returns_false_when_a_chunk_fails(monkeypatch):
    """Telegram rejects e.g. callback_data over its 64-byte limit, so the whole digest
    can fail to send. The caller must be able to tell instead of assuming success."""
    monkeypatch.setattr(
        tb.requests, "post",
        lambda url, json: FakeResponse(status_code=400, text='{"description":"BUTTON_DATA_INVALID"}'),
    )

    keyboard = {"inline_keyboard": [[{"text": "Watered", "callback_data": "t:WATER:Fern"}]]}
    assert tb.send_message("hello", reply_markup=keyboard) is False


def test_send_message_returns_false_when_only_a_later_chunk_fails(monkeypatch):
    """Failure is tracked per chunk -- a successful first chunk must not mask it."""
    responses = [FakeResponse(), FakeResponse(status_code=400, text="Bad Request")]
    monkeypatch.setattr(tb.requests, "post", lambda url, json: responses.pop(0))

    result = tb.send_message(("a" * 3990) + "\n" + ("b" * 3990))

    assert responses == []
    assert result is False


def test_answer_callback_query_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(tb.requests, "post", fake_post)

    tb.answer_callback_query("cbq123", text="Logged", show_alert=True)

    assert captured["url"] == f"{tb.BASE_URL}/answerCallbackQuery"
    assert captured["json"] == {"callback_query_id": "cbq123", "text": "Logged", "show_alert": True}


def test_edit_message_reply_markup_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(tb.requests, "post", fake_post)

    keyboard = {"inline_keyboard": [[{"text": "Done", "callback_data": "noop"}]]}
    tb.edit_message_reply_markup(chat_id=42, message_id=7, reply_markup=keyboard)

    assert captured["url"] == f"{tb.BASE_URL}/editMessageReplyMarkup"
    assert captured["json"]["chat_id"] == 42
    assert captured["json"]["message_id"] == 7
    assert json.loads(captured["json"]["reply_markup"]) == keyboard


def test_edit_message_text_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(tb.requests, "post", fake_post)

    tb.edit_message_text(chat_id=42, message_id=7, text="Logged!")

    assert captured["url"] == f"{tb.BASE_URL}/editMessageText"
    assert captured["json"]["text"] == "Logged!"
    assert "reply_markup" not in captured["json"]
