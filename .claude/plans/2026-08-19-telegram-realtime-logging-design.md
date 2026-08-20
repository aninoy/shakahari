# Telegram Real-Time Logging — Design

## Problem

Shakahari's only way to record a care action (water, fertilize, rotate, ...)
is replying to Telegram — either tapping a `/water_plantname`-style link or
typing a sentence. Both paths are processed once a day, in the next cron
run, because `main.py:sync_from_mailbox()` only runs when the daily
GitHub Actions workflow fires.

This has made the app effectively unusable:

- Tapping a command sends it as your own outgoing message. Since the daily
  digest is long enough to span 2–3 Telegram messages, the chat jumps to the
  bottom to show your tap, and you have to scroll back up through the whole
  digest to find the next plant — repeating this for every task.
- Nothing confirms a reply was understood until the next morning, so there's
  no way to know a tap or a sentence actually landed.
- The freeform parser only matches plant names by substring and only
  recognizes a fixed set of keywords, so it silently drops anything it
  doesn't parse.
- Logging only works for tasks the agent already recommended. There's no way
  to log an ad-hoc action (e.g. you watered something on a whim) outside of
  hoping a sentence like "watered fern" parses correctly.

The combined effect: real-world care (a month of watering and fertilizing)
never made it back into the app, silently drifting the Sheet from reality
and undermining every recommendation the agent makes afterward.

## Goals

- Logging an action is confirmed within seconds, not the next day.
- Tapping a button never appends a new message to the chat — no scroll
  jumping, no losing your place.
- Logging works both for agent-recommended tasks and for ad-hoc actions on
  any plant, at any time.
- Plant matching is exact, not fuzzy substring matching.

## Non-goals

- No changes to the Gemini reasoning, weather integration, or Perenual
  lookups (`agent.py`, `weather.py`, `plant_api.py` are untouched).
- No changes to the Google Sheet schema (`Plants` / `CareHistory` tabs stay
  as they are) or to the daily cadence of the digest.
- No web dashboard. Telegram remains the only interface.

## Architecture

Today one job does everything, once a day. This splits it into two jobs
that run on the cadence each actually needs:

```
                    ┌─────────────────────────────┐
   GitHub Actions   │  ADVISOR (daily, unchanged   │
   cron (14:00 UTC) │  cadence)                    │
   ───────────────► │  weather + Sheet + Gemini    │
                     │  → sends digest w/ buttons   │
                     └───────────────┬─────────────┘
                                     │ writes "PENDING_*" status
                                     ▼
                          ┌─────────────────────┐
                          │   Google Sheet        │
                          │   (Plants, CareHistory)│
                          └─────────▲─────────────┘
                                     │ writes actions immediately
                     ┌───────────────┴─────────────┐
   Telegram webhook  │  RECORDER (event-driven,    │
   (button tap /     │  Google Cloud Function)     │
   /log command)     │  answers + edits instantly  │
   ───────────────►  └─────────────────────────────┘
```

- **Advisor** — the existing `main.py` on the existing GitHub Actions cron.
  Keeps computing recommendations exactly as it does today. The only change:
  it drops `sync_from_mailbox()` and sends the digest with inline buttons
  instead of `/water_plantname` text links.
- **Recorder** — a new Google Cloud Function, Python, invoked by a Telegram
  webhook on every incoming update (button tap or `/log` command). Reuses
  `src/storage.py` and `src/telegram_bot.py` directly rather than
  duplicating logic in a second language. Its only responsibilities: parse
  the update, write to the Sheet, confirm — in the same request.

Both jobs read/write the same Google Sheet as the single source of truth;
neither needs to know about the other.

## Interaction design

### Digest buttons (replaces `/water_plantname` links)

Each task in the digest gets its own button row instead of a text link:

```
🔴💧 Monstera — Soil dry after 8 days
[ 💧 Watered ]  [ ⏭ Skip today ]
```

Plus one row at the end: `[ ✅ Mark everything above done ]`.

Tapping a button sends a silent `callback_query` — no new chat message.
The Recorder:
1. Verifies the request (see Security).
2. Writes the action to the Sheet using the exact plant name and action
   carried in the button's `callback_data` (no substring matching).
3. Edits that task's button row in place to show `✓ logged just now` and
   calls `answerCallbackQuery` with a small toast (`🌿 Logged: Watered
   Monstera`) that fades on its own.

Because matching is exact and the write happens before any confirmation is
shown, there's no more "trusted it worked, but it didn't."

`callback_data` encodes `t:<ACTION>:<plant name>` (task button),
`skip:<ACTION>:<plant name>` (skip), or `alldone:<date>` (mark-all-done —
re-derived from whatever the Sheet currently shows as `PENDING_*`, mirroring
today's "Done" semantics). Plant names are short enough in practice to stay
well under Telegram's 64-byte `callback_data` limit; this is a known limit
worth remembering if an unusually long plant name is ever added.

"Skip today" only clears that specific `PENDING_<ACTION>` from `Status` —
it does **not** write to `CareHistory`. Skipping means "not doing this
today," not "did this," so the agent evaluates it fresh again tomorrow
rather than treating it as completed.

### `/log` — ad-hoc logging, independent of the digest

Addresses the actual pain reported: acting in real life without anything to
confirm against in Telegram.

1. User sends `/log`.
2. Recorder replies with one button per plant (`logsel:<plant name>`).
3. Tapping a plant edits the message to show action buttons
   (`logact:<plant name>:<ACTION>` for WATER/FERTILIZE/MIST/ROTATE/MOVE/
   PRUNE/REPOT/CHECK) plus a `‹ Back` button.
4. Tapping an action logs it (today's date), edits the message to a plain
   confirmation (no keyboard left), and answers with the same toast pattern.

Entirely stateless — every step's state lives in that step's
`callback_data`, so the Cloud Function needs no session storage.

### Freeform text — retired

The compound-sentence parser (comma/`and`-splitting, keyword matching,
action carry-over) is the most fragile part of the current system and is
now fully superseded by buttons + `/log`. Retiring it removes a second,
less reliable way to do the same thing. `get_recent_messages()` and the
mailbox-parsing branch of `sync_from_mailbox()` are deleted; a thin
`log_task_action()` (see below) is extracted from the reliable parts of
that logic and reused by both the button and `/log` handlers.

## Data flow / storage changes

None to the schema. `PlantDB` gains one shared method,
`log_task_action(plant_name, action, date)`, extracted from the existing
per-action logic in `sync_from_mailbox()` (update `Last Watered`/
`Last Fertilized` if applicable, append to `CareHistory`, clear that
specific `PENDING_*` action from `Status`). Both the per-task button
handler and the `/log` handler call this one method — no duplicated
Sheet-mutation logic between the two entry points.

`mark_pending()` (Advisor) and the `Status` column format are unchanged.

## Security

The Cloud Function is a public HTTPS URL. Telegram signs webhook requests
with a secret token in the `X-Telegram-Bot-Api-Secret-Token` header when
`setWebhook` is called with a `secret_token`. The Recorder rejects any
request whose header doesn't match the expected value (stored as a Cloud
Function environment variable) with `403` before touching the Sheet.

## Error handling

- If the Sheet write fails, the Recorder does **not** edit the message or
  show a success toast. It answers the callback query with an error toast
  (`show_alert=True`) and leaves the button live so the tap can be retried.
  Confirmation only ever reflects a write that actually happened.
- If Telegram delivers a webhook the Recorder can't parse (unexpected
  update shape), it logs and returns `200` (so Telegram doesn't retry
  indefinitely) without touching the Sheet.
- The Advisor's existing error handling (weather/DB/Gemini failures) is
  unchanged.

## Deployment

- New `src/recorder.py` holds the Cloud Function entry point
  (`functions_framework`-decorated HTTP handler) and imports `PlantDB` /
  `telegram_bot` directly from the existing `src/` package — one codebase,
  deployed twice (GitHub Actions runs `main.py`; GCP runs `src/recorder.py`
  as the Cloud Function). Same `requirements.txt`.
- Secrets (`TELEGRAM_TOKEN`, `G_SHEET_CREDENTIALS`, a new
  `TELEGRAM_WEBHOOK_SECRET`) are set as Cloud Function environment
  variables, separate from the GitHub Actions secrets already in place.
- One-time setup: deploy the function, then call Telegram's `setWebhook`
  with the function's URL and the secret token. `getUpdates` polling and a
  webhook are mutually exclusive — once the webhook is set, nothing may
  call `getUpdates` again (this is exactly what removing
  `sync_from_mailbox()` from the Advisor guarantees).

## Testing

No automated tests exist in the repo today (`test.py` is a manual script,
not a suite). This introduces `pytest` and a `tests/` directory, following
the repo's TDD policy for all new logic:

- `log_task_action()` and the `callback_data` encode/decode helpers are
  pure-ish functions (Sheet access mocked) — write the failing test first
  for each: exact-match update, unknown plant, unknown action, malformed
  `callback_data`.
- The Recorder's request handler is tested by feeding it sample Telegram
  update payloads (`callback_query` for a task button, `/log` flow steps,
  a bad/missing secret header) against a mocked `PlantDB`.
- Before relying on it for the real garden: deploy to the real bot, verify
  the digest renders with buttons, tap through a real task and `/log`, and
  confirm the Sheet updates and the toast/edit behavior match this design
  in the actual Telegram app.

## Open limitations (accepted for now)

- `callback_data`'s 64-byte limit means an unusually long plant name could
  break encoding. Not solved here (no plant in the current inventory is
  close to that limit) — would need a short-ID scheme if it ever comes up.
- Retiring freeform text logging means there's no way to log something by
  typing a sentence anymore — only buttons and `/log`. This was a deliberate
  trade for reliability; revisit if it turns out to be missed in practice.
