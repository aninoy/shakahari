# Telegram Real-Time Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Shakahari's next-day, fragile-text-command logging with instant Telegram inline buttons (and a standing `/log` command for ad-hoc actions), confirmed within seconds via a real-time webhook instead of the daily batch cron.

**Architecture:** Split the current single daily job into two: the existing GitHub Actions **Advisor** (unchanged cadence — weather, Sheet, Gemini, sends the digest, now with buttons instead of text links) and a new event-driven **Recorder** (a Google Cloud Function invoked by a Telegram webhook on every button tap or `/log` message) that writes to the same Google Sheet immediately and confirms in the same request.

**Tech Stack:** Python 3.12, `functions-framework` (Google Cloud Functions gen2, HTTP trigger), `gspread`/`pandas` (existing Sheet access, unchanged), `pytest` (new — no test suite exists today), Telegram Bot API (`sendMessage`, `answerCallbackQuery`, `editMessageReplyMarkup`, `editMessageText`, `setWebhook`).

**Spec:** `.claude/plans/2026-08-19-telegram-realtime-logging-design.md`

## Global Constraints

- No changes to `src/agent.py`'s reasoning, `src/weather.py`, or `src/plant_api.py`.
- No changes to the Google Sheet schema (`Plants` / `CareHistory` tabs) or column names.
- Plant matching is exact (case-insensitive equality), never substring.
- A logging confirmation (toast / edited message) must only ever be shown **after** the underlying Sheet write has succeeded.
- The freeform natural-language reply parser is retired, not preserved as a fallback.
- All new logic is covered by a failing-test-first `pytest` cycle before being implemented (TDD, per repo policy).
- Run tests with `python -m pytest ...` (not bare `pytest`) so the repo root is on `sys.path` and `src.*` imports resolve without needing `__init__.py` changes.

---

## Task 1: Shared action constants (`src/actions.py`) + pytest setup

No test suite exists in this repo today (`test.py` is a manual script, not a suite). This task introduces `pytest` and extracts the action-type constants that Task 6's `/log` picker will need, deduplicating what `main.py` and `src/agent.py` currently each define separately.

**Files:**
- Create: `src/actions.py`
- Create: `tests/test_actions.py`
- Modify: `requirements.txt`
- Modify: `main.py:1-18` (remove local `ACTION_ICONS`, import from `src.actions`)
- Modify: `src/agent.py:8-18` (remove local `CARE_ACTIONS`, import from `src.actions`)

**Interfaces:**
- Produces: `src.actions.CARE_ACTIONS: list[str]`, `src.actions.ACTION_ICONS: dict[str, str]` — used by Tasks 6 and 7.

- [ ] **Step 1: Add test/runtime dependencies**

Modify `requirements.txt` to:

```
pandas
gspread
oauth2client
google-genai
requests
pytz
python-dotenv
pytest
functions-framework
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 3: Write the failing test**

Create `tests/test_actions.py`:

```python
from src.actions import CARE_ACTIONS, ACTION_ICONS


def test_care_actions_has_all_eight_action_types():
    assert CARE_ACTIONS == [
        "WATER", "FERTILIZE", "MIST", "ROTATE", "MOVE", "PRUNE", "REPOT", "CHECK",
    ]


def test_action_icons_covers_every_care_action():
    for action in CARE_ACTIONS:
        assert action in ACTION_ICONS
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.actions'`

- [ ] **Step 5: Create `src/actions.py`**

```python
"""Shared care-action constants used by the Advisor, the agent, and the Recorder."""

CARE_ACTIONS = [
    "WATER",
    "FERTILIZE",
    "MIST",
    "ROTATE",
    "MOVE",
    "PRUNE",
    "REPOT",
    "CHECK",
]

ACTION_ICONS = {
    "WATER": "💧",
    "FERTILIZE": "🧪",
    "MIST": "💨",
    "ROTATE": "🔄",
    "MOVE": "📍",
    "PRUNE": "✂️",
    "REPOT": "🪴",
    "CHECK": "🔍",
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_actions.py -v`
Expected: PASS

- [ ] **Step 7: Point `main.py` at the shared constants**

In `main.py`, replace:

```python
from src.telegram_bot import send_alert

# Action icons for Telegram messages
ACTION_ICONS = {
    'WATER': '💧',
    'FERTILIZE': '🧪',
    'MIST': '💨',
    'ROTATE': '🔄',
    'MOVE': '📍',
    'PRUNE': '✂️',
    'REPOT': '🪴',
    'CHECK': '🔍',
}
```

with:

```python
from src.telegram_bot import send_alert
from src.actions import ACTION_ICONS
```

(The `send_alert` → `send_message` rename happens in Task 4 — don't touch that here.)

- [ ] **Step 8: Point `src/agent.py` at the shared constants**

In `src/agent.py`, replace:

```python
# Predefined action types for consistency
CARE_ACTIONS = [
    "WATER",      # Water the plant
    "FERTILIZE",  # Apply fertilizer
    "MIST",       # Mist leaves for humidity
    "ROTATE",     # Rotate for even growth
    "MOVE",       # Relocate (light/temp issues)
    "PRUNE",      # Remove dead/leggy growth
    "REPOT",      # Needs larger container
    "CHECK",      # General inspection needed
]
```

with:

```python
from src.actions import CARE_ACTIONS
```

(place this import alongside the existing imports at the top of the file, and delete the old list literal from its original position)

- [ ] **Step 9: Confirm nothing broke**

Run: `python -m pytest tests/ -v` — expect all PASS.
Run: `python -c "import main; import src.agent"` — expect no import errors.

- [ ] **Step 10: Commit**

```bash
git add src/actions.py tests/test_actions.py requirements.txt main.py src/agent.py
git commit -m "Extract shared CARE_ACTIONS/ACTION_ICONS into src/actions.py"
```

---

## Task 2: `callback_data` encode/decode (`src/callbacks.py`)

Pure functions with no I/O — the deterministic replacement for today's fuzzy plant-name matching. Every button in the digest and the `/log` flow is built and parsed through these.

**Files:**
- Create: `src/callbacks.py`
- Create: `tests/test_callbacks.py`

**Interfaces:**
- Produces: `encode_task_button(action, plant_name) -> str`, `encode_skip_button(action, plant_name) -> str`, `encode_alldone(date) -> str`, `encode_log_select(plant_name) -> str`, `encode_log_action(plant_name, action) -> str`, `encode_log_back() -> str`, `decode_callback(data) -> dict`. Used by Tasks 5, 6, and 7.
- `decode_callback` returns one of:
  - `{"kind": "task", "action": str, "plant": str}`
  - `{"kind": "skip", "action": str, "plant": str}`
  - `{"kind": "alldone", "date": str}`
  - `{"kind": "logsel", "plant": str}`
  - `{"kind": "logact", "plant": str, "action": str}`
  - `{"kind": "logback"}`
  - `{"kind": "unknown"}` (malformed or unrecognized data — callers must no-op safely on this)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_callbacks.py`:

```python
from src.callbacks import (
    encode_task_button,
    encode_skip_button,
    encode_alldone,
    encode_log_select,
    encode_log_action,
    encode_log_back,
    decode_callback,
)


def test_encode_task_button():
    assert encode_task_button("WATER", "Monstera") == "t:WATER:Monstera"


def test_encode_skip_button():
    assert encode_skip_button("WATER", "Monstera") == "skip:WATER:Monstera"


def test_encode_alldone():
    assert encode_alldone("2026-08-19") == "alldone:2026-08-19"


def test_encode_log_select():
    assert encode_log_select("Peace Lily") == "logsel:Peace Lily"


def test_encode_log_action():
    assert encode_log_action("Peace Lily", "FERTILIZE") == "logact:Peace Lily:FERTILIZE"


def test_encode_log_back():
    assert encode_log_back() == "logback"


def test_decode_task_button():
    assert decode_callback("t:WATER:Monstera") == {"kind": "task", "action": "WATER", "plant": "Monstera"}


def test_decode_skip_button():
    assert decode_callback("skip:ROTATE:Pothos") == {"kind": "skip", "action": "ROTATE", "plant": "Pothos"}


def test_decode_alldone():
    assert decode_callback("alldone:2026-08-19") == {"kind": "alldone", "date": "2026-08-19"}


def test_decode_log_select():
    assert decode_callback("logsel:Fiddle Leaf Fig") == {"kind": "logsel", "plant": "Fiddle Leaf Fig"}


def test_decode_log_action():
    assert decode_callback("logact:Fiddle Leaf Fig:MIST") == {
        "kind": "logact", "plant": "Fiddle Leaf Fig", "action": "MIST",
    }


def test_decode_log_back():
    assert decode_callback("logback") == {"kind": "logback"}


def test_decode_unknown_falls_back_gracefully():
    assert decode_callback("garbage:data:here:too:many:parts") == {"kind": "unknown"}
    assert decode_callback("") == {"kind": "unknown"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_callbacks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.callbacks'`

- [ ] **Step 3: Implement `src/callbacks.py`**

```python
"""Encode/decode Telegram callback_data for digest buttons and the /log flow.

Plant names are embedded directly (no substring matching, no ID lookup) —
this is what makes plant matching exact instead of fuzzy. Assumes plant
names never contain ':' (documented limitation, see design spec).
"""


def encode_task_button(action, plant_name):
    return f"t:{action}:{plant_name}"


def encode_skip_button(action, plant_name):
    return f"skip:{action}:{plant_name}"


def encode_alldone(date):
    return f"alldone:{date}"


def encode_log_select(plant_name):
    return f"logsel:{plant_name}"


def encode_log_action(plant_name, action):
    return f"logact:{plant_name}:{action}"


def encode_log_back():
    return "logback"


def decode_callback(data):
    parts = data.split(":")
    kind = parts[0] if parts else ""

    if kind == "t" and len(parts) == 3:
        return {"kind": "task", "action": parts[1], "plant": parts[2]}
    if kind == "skip" and len(parts) == 3:
        return {"kind": "skip", "action": parts[1], "plant": parts[2]}
    if kind == "alldone" and len(parts) == 2:
        return {"kind": "alldone", "date": parts[1]}
    if kind == "logsel" and len(parts) == 2:
        return {"kind": "logsel", "plant": parts[1]}
    if kind == "logact" and len(parts) == 3:
        return {"kind": "logact", "plant": parts[1], "action": parts[2]}
    if kind == "logback" and len(parts) == 1:
        return {"kind": "logback"}

    return {"kind": "unknown"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_callbacks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/callbacks.py tests/test_callbacks.py
git commit -m "Add callback_data encode/decode for digest buttons and /log flow"
```

---

## Task 3: `PlantDB` exact-match logging methods (`src/storage.py`)

Replaces the fuzzy, freeform-text `sync_from_mailbox()` path with three exact-match methods the Recorder will call directly. This is the extraction the design spec calls "one reliable way to log."

**Files:**
- Modify: `src/storage.py`
- Create: `tests/test_storage.py`

**Interfaces:**
- Produces on `PlantDB`: `log_task_action(plant_name, action, date=None, notes="") -> bool` (True if plant found and logged), `clear_pending_action(plant_name, action) -> bool` (True if plant found; clears without logging history), `mark_all_done(date=None) -> int` (returns count of plants updated). Used by Tasks 5 and 6.
- Removes from `PlantDB`: `sync_from_mailbox()`. Removes module-level `ACTION_KEYWORDS`.
- Consumes (unchanged, already on `PlantDB`): `log_action(plant_name, action, date=None, notes="")`, `save()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_storage.py`:

```python
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


def test_clear_pending_action_does_not_write_history():
    db = make_db([{"Name": "Fern", "Last Watered": "", "Last Fertilized": "", "Status": "PENDING_WATER"}])

    found = db.clear_pending_action("Fern", "WATER")

    assert found is True
    assert db.df.at[0, "Status"] == "OK"
    assert db.history_ws.appended_rows == []


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL with `AttributeError: 'PlantDB' object has no attribute 'log_task_action'`

- [ ] **Step 3: Remove the freeform mailbox parser**

In `src/storage.py`, delete the module-level `ACTION_KEYWORDS` dict (the block starting `# Action keywords for parsing user replies`) and delete the entire `sync_from_mailbox(self)` method (from `def sync_from_mailbox(self):` through its closing `return changes`).

- [ ] **Step 4: Add the three replacement methods**

In `src/storage.py`, add these methods to `PlantDB` (place them where `sync_from_mailbox` used to be, right after `log_action`):

```python
    def log_task_action(self, plant_name, action, date=None, notes=""):
        """Log a specific care action for an exact plant name (case-insensitive).
        Returns True if the plant was found and updated, False otherwise."""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        mask = self.df['Name'].str.lower() == plant_name.strip().lower()
        if not mask.any():
            return False

        idx = self.df[mask].index[0]

        if action == 'WATER':
            self.df.at[idx, 'Last Watered'] = date
        elif action == 'FERTILIZE':
            self.df.at[idx, 'Last Fertilized'] = date

        self.log_action(plant_name, action, date=date, notes=notes)
        self._clear_pending(idx, action)
        self.save()
        return True

    def clear_pending_action(self, plant_name, action):
        """Clear a pending action for an exact plant name WITHOUT logging it as done.
        Returns True if the plant was found, False otherwise."""
        mask = self.df['Name'].str.lower() == plant_name.strip().lower()
        if not mask.any():
            return False

        idx = self.df[mask].index[0]
        self._clear_pending(idx, action)
        self.save()
        return True

    def _clear_pending(self, idx, action):
        """Remove one action from a row's composite PENDING_ status string."""
        current = str(self.df.at[idx, 'Status'])
        if f'PENDING_{action}' not in current:
            return
        new_status = current.replace(f'PENDING_{action}', '').strip('_')
        self.df.at[idx, 'Status'] = new_status if new_status.startswith('PENDING') else 'OK'

    def mark_all_done(self, date=None):
        """Confirm every plant's pending actions at once. Returns the number of plants updated."""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        mask_pending = self.df['Status'].str.startswith('PENDING', na=False)
        updated = 0
        for idx, row in self.df[mask_pending].iterrows():
            status = row['Status']
            plant_name = row['Name']

            if 'WATER' in status:
                self.df.at[idx, 'Last Watered'] = date
                self.log_action(plant_name, 'WATER', date=date, notes='Confirmed via Mark all done')
            if 'FERT' in status:
                self.df.at[idx, 'Last Fertilized'] = date
                self.log_action(plant_name, 'FERTILIZE', date=date, notes='Confirmed via Mark all done')
            for action in ['MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
                if action in status:
                    self.log_action(plant_name, action, date=date, notes='Confirmed via Mark all done')

            self.df.at[idx, 'Status'] = 'OK'
            updated += 1

        if updated:
            self.save()
        return updated
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "Replace freeform mailbox parser with exact-match logging methods"
```

---

## Task 4: Telegram Bot API helpers (`src/telegram_bot.py`)

Renames `send_alert` to `send_message` (adding optional `reply_markup`), adds the three new calls the Recorder needs (`answer_callback_query`, `edit_message_reply_markup`, `edit_message_text`), and removes `get_recent_messages` (the `getUpdates` polling this replaces).

**Files:**
- Modify: `src/telegram_bot.py`
- Create: `tests/test_telegram_bot.py`
- Modify: `main.py` (update the one import + one call site so the repo still imports cleanly after this task)

**Interfaces:**
- Produces: `send_message(message, reply_markup=None)`, `answer_callback_query(callback_query_id, text="", show_alert=False)`, `edit_message_reply_markup(chat_id, message_id, reply_markup)`, `edit_message_text(chat_id, message_id, text, reply_markup=None)`. Used by Tasks 5, 6, 7.
- Removes: `send_alert` (renamed), `get_recent_messages` (no longer needed — the webhook replaces polling).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_telegram_bot.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: FAIL (`AttributeError: module 'src.telegram_bot' has no attribute 'send_message'`, etc.)

- [ ] **Step 3: Replace `src/telegram_bot.py`**

Replace the entire file contents with:

```python
import json
import requests
from src.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_message(message, reply_markup=None):
    """Sends a message to your phone. Chunks messages over 4000 chars.
    reply_markup (an inline keyboard dict) is attached only to the final chunk."""
    url = f"{BASE_URL}/sendMessage"

    MAX_LENGTH = 4000
    chunks = []
    current_chunk = ""

    for line in message.split('\n'):
        if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ('\n' + line if current_chunk else line)

    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            print(f"⚠️ Telegram Send Error: {e}")
            if 'response' in locals() and hasattr(response, 'text'):
                print(f"   Telegram API Response: {response.text}")


def answer_callback_query(callback_query_id, text="", show_alert=False):
    """Acknowledges a button tap so Telegram stops showing a loading spinner."""
    url = f"{BASE_URL}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Telegram Callback Answer Error: {e}")


def edit_message_reply_markup(chat_id, message_id, reply_markup):
    """Replaces the inline keyboard on an existing message without touching its text."""
    url = f"{BASE_URL}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": json.dumps(reply_markup),
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Telegram Edit Markup Error: {e}")


def edit_message_text(chat_id, message_id, text, reply_markup=None):
    """Replaces the text (and optionally the keyboard) of an existing message."""
    url = f"{BASE_URL}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Telegram Edit Text Error: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: PASS

- [ ] **Step 5: Update `main.py`'s import and call site**

In `main.py`, change:

```python
from src.telegram_bot import send_alert
```

to:

```python
from src.telegram_bot import send_message
```

And change the call inside `main()`:

```python
        send_alert(message)
```

to:

```python
        send_message(message)
```

(This is a mechanical rename only — Task 7 adds the `reply_markup` argument.)

- [ ] **Step 6: Confirm nothing broke**

Run: `python -m pytest tests/ -v` — expect all PASS.
Run: `python -c "import main"` — expect no import errors.

- [ ] **Step 7: Commit**

```bash
git add src/telegram_bot.py tests/test_telegram_bot.py main.py
git commit -m "Rename send_alert to send_message, add callback/edit helpers"
```

---

## Task 5: Recorder — digest button handling (Cloud Function, part 1)

The core of the Recorder: a webhook entry point that verifies the request, then handles a digest task button, a skip button, or the mark-all-done button — editing the message in place and confirming only after the Sheet write succeeds.

**Files:**
- Modify: `src/config.py` (add `TELEGRAM_WEBHOOK_SECRET`)
- Create: `src/recorder.py`
- Create: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `PlantDB.log_task_action`, `PlantDB.clear_pending_action`, `PlantDB.mark_all_done` (Task 3); `answer_callback_query`, `edit_message_reply_markup`, `edit_message_text`, `send_message` (Task 4); `decode_callback`, `encode_task_button`, `encode_skip_button` (Task 2).
- Produces: `telegram_webhook(request) -> (str, int)` — the Cloud Function's HTTP entry point. `request` duck-types Flask's `Request`: `.headers.get(name)` and `.get_json(silent=True)`. Used by Task 8 (deployment) and Task 6 (extended in place).

- [ ] **Step 1: Add the webhook secret to config**

In `src/config.py`, add this line alongside the other `os.environ.get(...)` assignments:

```python
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_recorder.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.recorder'`

- [ ] **Step 4: Implement `src/recorder.py`**

```python
from src.callbacks import decode_callback, encode_task_button, encode_skip_button
from src.config import TELEGRAM_WEBHOOK_SECRET
from src.storage import PlantDB
from src.telegram_bot import answer_callback_query, edit_message_reply_markup, edit_message_text, send_message


def telegram_webhook(request):
    """HTTP Cloud Function entry point for the Telegram webhook."""
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TELEGRAM_WEBHOOK_SECRET:
        return ("Forbidden", 403)

    update = request.get_json(silent=True) or {}

    try:
        if "callback_query" in update:
            _handle_callback(update["callback_query"])
    except Exception as e:
        print(f"⚠️ Recorder: failed to process update: {e}")

    return ("OK", 200)


def _handle_callback(callback_query):
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query["message"]
    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    parsed = decode_callback(data)
    kind = parsed["kind"]

    if kind == "task":
        _handle_task(callback_id, chat_id, message_id, message, parsed)
    elif kind == "skip":
        _handle_skip(callback_id, chat_id, message_id, message, parsed)
    elif kind == "alldone":
        _handle_alldone(callback_id, chat_id, message_id, parsed)
    else:
        answer_callback_query(callback_id)


def _handle_task(callback_id, chat_id, message_id, message, parsed):
    db = PlantDB()
    found = db.log_task_action(parsed["plant"], parsed["action"])

    if not found:
        answer_callback_query(callback_id, text=f"Couldn't find '{parsed['plant']}'", show_alert=True)
        return

    done_row = [{"text": "✓ Logged just now", "callback_data": "noop"}]
    new_markup = _replace_task_row(message["reply_markup"], parsed["action"], parsed["plant"], done_row)
    edit_message_reply_markup(chat_id, message_id, new_markup)
    answer_callback_query(callback_id, text=f"🌿 Logged: {parsed['action'].title()} {parsed['plant']}")


def _handle_skip(callback_id, chat_id, message_id, message, parsed):
    db = PlantDB()
    db.clear_pending_action(parsed["plant"], parsed["action"])

    skipped_row = [{"text": "⏭ Skipped for today", "callback_data": "noop"}]
    new_markup = _replace_task_row(message["reply_markup"], parsed["action"], parsed["plant"], skipped_row)
    edit_message_reply_markup(chat_id, message_id, new_markup)
    answer_callback_query(callback_id, text=f"Skipped {parsed['plant']} for today")


def _handle_alldone(callback_id, chat_id, message_id, parsed):
    db = PlantDB()
    count = db.mark_all_done(date=parsed["date"])

    edit_message_reply_markup(chat_id, message_id, {"inline_keyboard": []})
    answer_callback_query(callback_id, text=f"✅ Marked {count} plant(s) done")


def _replace_task_row(current_markup, action, plant_name, new_row):
    """Returns a new keyboard with the row for (action, plant_name) replaced by new_row."""
    task_data = encode_task_button(action, plant_name)
    skip_data = encode_skip_button(action, plant_name)
    updated_rows = []
    for row in current_markup.get("inline_keyboard", []):
        row_data = [btn.get("callback_data") for btn in row]
        if task_data in row_data or skip_data in row_data:
            updated_rows.append(new_row)
        else:
            updated_rows.append(row)
    return {"inline_keyboard": updated_rows}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/recorder.py tests/test_recorder.py
git commit -m "Add Recorder webhook: digest task/skip/mark-all-done handling"
```

---

## Task 6: Recorder — `/log` ad-hoc flow (Cloud Function, part 2)

Extends `src/recorder.py` with the plant-picker → action-picker flow, addressing the actual reported pain: logging something that was never on the digest.

**Files:**
- Modify: `src/recorder.py`
- Modify: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `CARE_ACTIONS`, `ACTION_ICONS` (Task 1); `encode_log_select`, `encode_log_action`, `encode_log_back` (Task 2); `PlantDB.get_inventory()` (existing, unchanged).
- Produces: extends `telegram_webhook` to also handle a `/log` text message and the `logsel`/`logact`/`logback` callback kinds.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recorder.py` (keep existing imports; add `import pandas as pd` near the top):

```python
import pandas as pd


def test_log_command_sends_plant_picker(monkeypatch):
    monkeypatch.setattr(recorder, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    class FakeInventoryDB(FakePlantDB):
        def get_inventory(self):
            return pd.DataFrame([{"Name": "Monstera"}, {"Name": "Pothos"}])

    monkeypatch.setattr(recorder, "PlantDB", FakeInventoryDB)
    sent = []
    monkeypatch.setattr(recorder, "send_message", lambda text, reply_markup=None: sent.append((text, reply_markup)))

    request = FakeRequest({"message": {"chat": {"id": 1}, "text": "/log"}}, secret="test-secret")

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: FAIL — the four new tests fail (`/log` isn't handled, `logsel`/`logact`/`logback` fall through to the `else: answer_callback_query(callback_id)` no-op branch, so `edits`/`sent` stay empty and the list-index assertions raise `IndexError`).

- [ ] **Step 3: Extend `src/recorder.py`**

Update the imports at the top of `src/recorder.py`:

```python
from src.actions import CARE_ACTIONS, ACTION_ICONS
from src.callbacks import (
    decode_callback,
    encode_task_button,
    encode_skip_button,
    encode_log_select,
    encode_log_action,
    encode_log_back,
)
from src.config import TELEGRAM_WEBHOOK_SECRET
from src.storage import PlantDB
from src.telegram_bot import answer_callback_query, edit_message_reply_markup, edit_message_text, send_message
```

Update `telegram_webhook` to also route `/log` messages:

```python
def telegram_webhook(request):
    """HTTP Cloud Function entry point for the Telegram webhook."""
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TELEGRAM_WEBHOOK_SECRET:
        return ("Forbidden", 403)

    update = request.get_json(silent=True) or {}

    try:
        if "callback_query" in update:
            _handle_callback(update["callback_query"])
        elif "message" in update and update["message"].get("text", "").strip() == "/log":
            _handle_log_command(update["message"])
    except Exception as e:
        print(f"⚠️ Recorder: failed to process update: {e}")

    return ("OK", 200)
```

Extend `_handle_callback`'s dispatch:

```python
    if kind == "task":
        _handle_task(callback_id, chat_id, message_id, message, parsed)
    elif kind == "skip":
        _handle_skip(callback_id, chat_id, message_id, message, parsed)
    elif kind == "alldone":
        _handle_alldone(callback_id, chat_id, message_id, parsed)
    elif kind == "logsel":
        _handle_logsel(callback_id, chat_id, message_id, parsed)
    elif kind == "logact":
        _handle_logact(callback_id, chat_id, message_id, parsed)
    elif kind == "logback":
        _handle_logback(callback_id, chat_id, message_id)
    else:
        answer_callback_query(callback_id)
```

Add the new handlers and keyboard builders (place after `_replace_task_row`):

```python
def _handle_log_command(message):
    db = PlantDB()
    plant_names = db.get_inventory()["Name"].tolist()
    send_message("Which plant?", reply_markup=_build_plant_picker(plant_names))


def _handle_logsel(callback_id, chat_id, message_id, parsed):
    edit_message_text(
        chat_id, message_id,
        f"What did you do for {parsed['plant']}?",
        reply_markup=_build_action_picker(parsed["plant"]),
    )
    answer_callback_query(callback_id)


def _handle_logact(callback_id, chat_id, message_id, parsed):
    db = PlantDB()
    found = db.log_task_action(parsed["plant"], parsed["action"])

    if not found:
        answer_callback_query(callback_id, text=f"Couldn't find '{parsed['plant']}'", show_alert=True)
        return

    edit_message_text(chat_id, message_id, f"✅ Logged {parsed['action'].title()} for {parsed['plant']}")
    answer_callback_query(callback_id, text=f"🌿 Logged: {parsed['action'].title()} {parsed['plant']}")


def _handle_logback(callback_id, chat_id, message_id):
    db = PlantDB()
    plant_names = db.get_inventory()["Name"].tolist()
    edit_message_text(chat_id, message_id, "Which plant?", reply_markup=_build_plant_picker(plant_names))
    answer_callback_query(callback_id)


def _build_plant_picker(plant_names):
    rows = [[{"text": name, "callback_data": encode_log_select(name)}] for name in plant_names]
    return {"inline_keyboard": rows}


def _build_action_picker(plant_name):
    rows = []
    row = []
    for action in CARE_ACTIONS:
        icon = ACTION_ICONS.get(action, "📋")
        row.append({"text": f"{icon} {action.title()}", "callback_data": encode_log_action(plant_name, action)})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "‹ Back", "callback_data": encode_log_back()}])
    return {"inline_keyboard": rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recorder.py -v`
Expected: PASS (all tests, including Task 5's)

- [ ] **Step 5: Commit**

```bash
git add src/recorder.py tests/test_recorder.py
git commit -m "Add /log ad-hoc flow to Recorder: plant picker, action picker, confirm"
```

---

## Task 7: Advisor digest — inline keyboard instead of tap-to-log text

Removes the `/water_plantname` text links and the mailbox sync from `main.py`, replacing them with `build_digest_keyboard()` and dropping the now-retired `sync_from_mailbox()` call.

**Files:**
- Modify: `main.py`
- Create: `tests/test_main.py`

**Interfaces:**
- Produces: `build_digest_keyboard(tasks) -> dict` (a `{"inline_keyboard": [...]}` structure). `format_tasks(tasks, summary)` keeps its existing signature but no longer emits tap-to-log lines.
- Consumes: `encode_task_button`, `encode_skip_button`, `encode_alldone` (Task 2); `send_message` (Task 4, already wired in Task 4 Step 5).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
from datetime import datetime

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL — `format_tasks` still emits "Tap to log" lines; `build_digest_keyboard` doesn't exist.

- [ ] **Step 3: Rewrite `main.py`**

Replace the entire file contents with:

```python
from datetime import datetime
from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_message
from src.actions import ACTION_ICONS
from src.callbacks import encode_task_button, encode_skip_button, encode_alldone

# Priority indicators
PRIORITY_MARKERS = {
    'HIGH': '🔴',
    'MEDIUM': '🟡',
    'LOW': '🟢',
}

# Past-tense labels for digest confirmation buttons
ACTION_PAST_TENSE = {
    'WATER': 'Watered',
    'FERTILIZE': 'Fertilized',
    'MIST': 'Misted',
    'ROTATE': 'Rotated',
    'MOVE': 'Moved',
    'PRUNE': 'Pruned',
    'REPOT': 'Repotted',
    'CHECK': 'Checked',
}


def format_tasks(tasks, summary):
    """Format tasks into a readable Telegram message grouped by action type."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🌿 <b>Plant Care Tasks ({today})</b>"]

    if summary:
        lines.append(f"<i>{summary}</i>")

    by_action = {}
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        if action not in by_action:
            by_action[action] = []
        by_action[action].append(t)

    lines.append("")
    for action in ['WATER', 'FERTILIZE', 'MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
        if action in by_action:
            icon = ACTION_ICONS.get(action, '📋')
            plant_names = [t.get('name', '?') for t in by_action[action]]
            lines.append(f"{icon} <b>{action}</b>: {', '.join(plant_names)}")

    lines.append("\n—")
    lines.append("<b>Details:</b>")
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        icon = ACTION_ICONS.get(action, '📋')
        name = t.get('name', 'Unknown')
        reason = t.get('reason', '')
        priority = t.get('priority', '').upper()
        priority_marker = PRIORITY_MARKERS.get(priority, '')
        lines.append(f"{priority_marker}{icon} <b>{name}</b>: {reason}")

    return "\n".join(lines)


def build_digest_keyboard(tasks):
    """Builds one button row per task (confirm / skip) plus a final mark-all-done row."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        name = t.get('name', 'Unknown')
        icon = ACTION_ICONS.get(action, '📋')
        label = ACTION_PAST_TENSE.get(action, action.title())
        rows.append([
            {"text": f"{icon} {label}", "callback_data": encode_task_button(action, name)},
            {"text": "⏭ Skip today", "callback_data": encode_skip_button(action, name)},
        ])
    rows.append([{"text": "✅ Mark everything above done", "callback_data": encode_alldone(today)}])
    return {"inline_keyboard": rows}


def main():
    print(f"🌿 Starting Plant Care Advisor ({MODEL_ID})...")

    # 1. Connect to the Sheet
    try:
        db = PlantDB()
    except Exception as e:
        print(f"❌ DB Init Failed: {e}")
        return

    # 2. Get Weather Context
    weather = get_forecast()
    if not weather:
        print("⚠️ Continuing without weather data...")

    # 3. Get Care History for context
    care_history = db.get_history_summary(limit_per_plant=5)

    # 4. Agent Reasoning
    agent = PlantAgent()
    tasks, summary = agent.get_tasks(weather, db.get_inventory(), care_history)

    # 5. Notify & Update Status
    if tasks:
        message = format_tasks(tasks, summary)
        keyboard = build_digest_keyboard(tasks)
        send_message(message, reply_markup=keyboard)
        db.mark_pending(tasks)
        print(f"✅ Sent {len(tasks)} care recommendations.")
    else:
        print("✅ No tasks today. All plants healthy!")


if __name__ == "__main__":
    main()
```

Note: this also removes the `db.sync_from_mailbox()` call entirely (per Global Constraints — the Recorder now owns all reply processing) and the duplicate "# 4." comment numbering from the original file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all PASS (Tasks 1–7's tests together)

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Replace digest tap-to-log links with inline buttons"
```

---

## Task 8: Deployment — Cloud Function entry point, docs, webhook registration

Makes the Recorder deployable and documents the one-time GCP + Telegram setup. No new automated test — the deliverable is verified by actually deploying and checking `getWebhookInfo`.

**Files:**
- Modify: `main.py` (add a re-exported entry point so Cloud Functions' buildpack finds `telegram_webhook` in the conventional `main.py`)
- Modify: `README.md` (Usage Guide + a new deployment section)

- [ ] **Step 1: Re-export the Cloud Function entry point from `main.py`**

Google Cloud Functions' Python buildpack looks for the target function in `main.py` at the deployment source root by default. Since `main.py` is also the Advisor's script, add one import so `telegram_webhook` is importable from there without touching the Advisor's own logic. At the top of `main.py`, add:

```python
from src.recorder import telegram_webhook  # noqa: F401 -- Cloud Function entry point, unused by the Advisor
```

Run: `python -m pytest tests/ -v` and `python -c "import main"` — expect no errors (this import must not have side effects at import time, and it doesn't: `src/recorder.py` only defines functions).

- [ ] **Step 2: Update the README's Usage Guide**

In `README.md`, replace the "Interacting with the Bot" subsection (1-Tap Logging / Natural Language Replies / Composite Replies) with a description of the new flow:

```markdown
### Interacting with the Bot

Every task in the daily digest has its own buttons:

- **Tap the action button** (e.g. "💧 Watered") to log it instantly — the
  button changes to a checkmark and a toast confirms it, all within the
  same message. Nothing new is added to the chat, so you never lose your
  scroll position.
- **Tap "⏭ Skip today"** to clear that task without logging it as done —
  the agent will reconsider it fresh tomorrow.
- **Tap "✅ Mark everything above done"** to confirm every pending task at once.

**Logging anything else:** send `/log` at any time to log an action that
wasn't on the digest — pick a plant, then pick what you did. This works
independently of whatever the agent last recommended.

> Both paths are handled instantly by a Cloud Function webhook (see
> "Real-time logging setup" below) — not the daily cron job.
```

- [ ] **Step 3: Add a deployment section to the README**

Add a new section to `README.md`, after the existing "Repository Configuration" step:

```markdown
### 6. Real-Time Logging Setup (Google Cloud Function)

Digest buttons and `/log` need to be acknowledged within seconds, which the
once-a-day GitHub Actions cron can't do. A small always-on Cloud Function
handles this instead — Google's free tier (2M invocations/month) comfortably
covers a personal bot's traffic.

1. **Generate a webhook secret** (any random string) and add it to your
   `.env` as `TELEGRAM_WEBHOOK_SECRET`, and to your shell environment before
   deploying.

2. **Deploy the function** (from the repo root):

   ```bash
   gcloud functions deploy shakahari-recorder \
     --gen2 \
     --runtime=python312 \
     --region=us-west1 \
     --source=. \
     --entry-point=telegram_webhook \
     --trigger-http \
     --allow-unauthenticated \
     --set-env-vars=TELEGRAM_TOKEN="$TELEGRAM_TOKEN",TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID",G_SHEET_CREDENTIALS="$G_SHEET_CREDENTIALS",TELEGRAM_WEBHOOK_SECRET="$TELEGRAM_WEBHOOK_SECRET"
   ```

   Note the `httpsTrigger.url` printed at the end — you'll need it next.

3. **Register the webhook with Telegram:**

   ```bash
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
     -d "url=${CLOUD_FUNCTION_URL}" \
     -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
   ```

4. **Verify it's registered:**

   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
   ```

   Expect the response's `"url"` to match your function's URL and
   `"last_error_message"` to be absent.

> A webhook and `getUpdates` polling are mutually exclusive — once this is
> registered, nothing in this repo calls `getUpdates` anymore (the Advisor's
> `sync_from_mailbox()` was removed for exactly this reason).
```

- [ ] **Step 4: Commit**

```bash
git add main.py README.md
git commit -m "Document and wire up Cloud Function deployment for the Recorder"
```

---

## Task 9: Manual end-to-end verification against the real bot

The design spec calls for verifying real Telegram behavior before trusting this for the actual garden — none of the automated tests exercise real network calls or the real Telegram client UI.

**Files:** none (verification only)

- [ ] **Step 1:** Follow Task 8's deployment steps against your real bot and Sheet (or a scratch copy of the Sheet if you'd rather not risk the real data on the first pass).
- [ ] **Step 2:** Run `python main.py` locally to send a real digest. Confirm it arrives with button rows (no `/water_plantname` text links) and fits in a single Telegram message.
- [ ] **Step 3:** Tap a task's action button. Confirm: no new message appears in the chat, the tapped row collapses to "✓ Logged just now" within ~1 second, a toast appears, and the Sheet's `Last Watered`/`CareHistory` reflect the change immediately.
- [ ] **Step 4:** Tap "⏭ Skip today" on another task. Confirm the row updates to "⏭ Skipped for today" and no `CareHistory` row was added for it.
- [ ] **Step 5:** Tap "✅ Mark everything above done". Confirm all remaining rows disappear and every remaining pending plant is logged in `CareHistory`.
- [ ] **Step 6:** Send `/log`. Tap through: pick a plant not on today's digest, pick an action, confirm the Sheet updates and the message shows the confirmation text. Tap "‹ Back" partway through and confirm it returns to the plant list correctly.
- [ ] **Step 7:** Trigger the GitHub Actions workflow manually (`workflow_dispatch`) and confirm it still runs cleanly with `sync_from_mailbox()` gone — no errors about missing methods, no attempt to call `getUpdates`.
- [ ] **Step 8:** If anything above doesn't match, fix it and re-run the relevant steps before considering this done — this task is the actual acceptance gate for the whole plan, not the `pytest` runs.
