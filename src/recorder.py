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
