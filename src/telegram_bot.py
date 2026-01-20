import requests
from datetime import datetime, timedelta
from src.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_alert(message):
    """Sends a push notification to your phone."""
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"⚠️ Telegram Send Error: {e}")

def get_recent_messages(hours=24):
    """Fetches text messages sent to the bot in the last N hours."""
    url = f"{BASE_URL}/getUpdates"
    try:
        response = requests.get(url)
        if response.status_code != 200: return []
        
        updates = response.json().get('result', [])
        valid_msgs = []
        cutoff = datetime.now() - timedelta(hours=hours)
        
        for u in updates:
            if 'message' in u:
                msg = u['message']
                # Telegram timestamp is integer seconds
                msg_time = datetime.fromtimestamp(msg['date'])
                
                if msg_time > cutoff and 'text' in msg:
                    valid_msgs.append({
                        "text": msg['text'].lower(),
                        "date": msg_time.strftime('%Y-%m-%d')
                    })
        return valid_msgs
    except Exception as e:
        print(f"⚠️ Telegram Fetch Error: {e}")
        return []