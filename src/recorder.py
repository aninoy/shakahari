from datetime import datetime

from src.actions import CARE_ACTIONS, ACTION_ICONS
from src.callbacks import (
    decode_callback,
    encode_task_button,
    encode_log_select,
    encode_log_action,
    encode_log_back,
)
from src.config import TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET
from src.storage import PlantDB
from src.telegram_bot import answer_callback_query, edit_message_reply_markup, edit_message_text, send_message


def telegram_webhook(request):
    """HTTP Cloud Function entry point for the Telegram webhook."""
    if not TELEGRAM_WEBHOOK_SECRET:
        # Fail closed: with no configured secret there is nothing to authenticate
        # against, so refuse everything rather than accept everything.
        print("⚠️ Recorder: TELEGRAM_WEBHOOK_SECRET is not set — refusing all requests.")
        return ("Forbidden", 403)

    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TELEGRAM_WEBHOOK_SECRET:
        return ("Forbidden", 403)

    update = request.get_json(silent=True) or {}

    try:
        # The secret header proves Telegram sent this update, not that the owner did.
        # Anyone who finds the bot can message it, so only act on the owner's chat.
        if not _is_from_owner(update):
            print("⚠️ Recorder: ignoring update from a non-owner chat.")
            return ("OK", 200)

        if "callback_query" in update:
            _handle_callback(update["callback_query"])
        elif "message" in update and update["message"].get("text", "").strip() == "/log":
            _handle_log_command(update["message"])
    except Exception as e:
        print(f"⚠️ Recorder: failed to process update: {e}")

    return ("OK", 200)


def _is_from_owner(update):
    """True only if the update came from TELEGRAM_CHAT_ID. Compares as strings because
    env vars are strings while Telegram sends chat ids as JSON numbers."""
    if not TELEGRAM_CHAT_ID:
        print("⚠️ Recorder: TELEGRAM_CHAT_ID is not set — ignoring all updates.")
        return False

    if "callback_query" in update:
        chat = update["callback_query"].get("message", {}).get("chat", {})
    else:
        chat = update.get("message", {}).get("chat", {})

    chat_id = chat.get("id")
    return chat_id is not None and str(chat_id).strip() == str(TELEGRAM_CHAT_ID).strip()


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
    elif kind == "alldone":
        _handle_alldone(callback_id, chat_id, message_id, parsed)
    elif kind == "donetype":
        _handle_donetype(callback_id, chat_id, message_id, message, parsed)
    elif kind == "logsel":
        _handle_logsel(callback_id, chat_id, message_id, parsed)
    elif kind == "logact":
        _handle_logact(callback_id, chat_id, message_id, parsed)
    elif kind == "logback":
        _handle_logback(callback_id, chat_id, message_id)
    elif kind == "noop":
        answer_callback_query(callback_id)
    else:
        answer_callback_query(callback_id, text="Sorry — I couldn't read that button.", show_alert=True)


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


def _handle_alldone(callback_id, chat_id, message_id, parsed):
    # mark_all_done() acts on whatever is pending *now*, which may have become
    # pending after this digest was sent. Applying a stale digest's date to it
    # would write wrong dates into CareHistory, so only today's digest is honoured.
    if parsed["date"] != datetime.now().strftime('%Y-%m-%d'):
        answer_callback_query(
            callback_id,
            text="This digest is from a previous day — reply isn't supported anymore, check today's message instead.",
            show_alert=True,
        )
        return

    db = PlantDB()
    count = db.mark_all_done(date=parsed["date"])

    edit_message_reply_markup(chat_id, message_id, {"inline_keyboard": []})
    answer_callback_query(callback_id, text=f"✅ Marked {count} plant(s) done")


def _handle_donetype(callback_id, chat_id, message_id, message, parsed):
    # mark_action_done() acts on whatever is pending *now* for this action, which
    # may have changed since this digest was sent -- same staleness risk as alldone.
    if parsed["date"] != datetime.now().strftime('%Y-%m-%d'):
        answer_callback_query(
            callback_id,
            text="This digest is from a previous day — reply isn't supported anymore, check today's message instead.",
            show_alert=True,
        )
        return

    db = PlantDB()
    count = db.mark_action_done(parsed["action"], date=parsed["date"])

    new_markup = _replace_action_rows(message["reply_markup"], parsed["action"])
    edit_message_reply_markup(chat_id, message_id, new_markup)
    answer_callback_query(callback_id, text=f"✅ Marked {count} plant(s) done")


def _replace_task_row(current_markup, action, plant_name, new_row):
    """Returns a new keyboard with the row for (action, plant_name) replaced by new_row."""
    task_data = encode_task_button(action, plant_name)
    updated_rows = []
    for row in current_markup.get("inline_keyboard", []):
        row_data = [btn.get("callback_data") for btn in row]
        if task_data in row_data:
            updated_rows.append(new_row)
        else:
            updated_rows.append(row)
    return {"inline_keyboard": updated_rows}


def _replace_action_rows(current_markup, action):
    """Collapses every row for this action -- individual task buttons and the
    bulk "Mark X complete" button itself -- into inert done markers."""
    done_row = [{"text": "✓ Logged just now", "callback_data": "noop"}]
    task_prefix = f"t:{action}:"
    donetype_prefix = f"donetype:{action}:"
    updated_rows = []
    for row in current_markup.get("inline_keyboard", []):
        row_data = [btn.get("callback_data") or "" for btn in row]
        if any(cd.startswith(task_prefix) or cd.startswith(donetype_prefix) for cd in row_data):
            updated_rows.append(done_row)
        else:
            updated_rows.append(row)
    return {"inline_keyboard": updated_rows}


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
