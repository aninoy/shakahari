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
