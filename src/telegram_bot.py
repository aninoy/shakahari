import requests
from datetime import datetime, timedelta
from src.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_alert(message):
    """Sends a push notification to your phone. Chunks messages over 4000 chars."""
    url = f"{BASE_URL}/sendMessage"
    
    # Telegram message limit is 4096 chars. Split safely if needed.
    MAX_LENGTH = 4000
    
    # Simple split by lines to avoid breaking formatting
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
        
    for chunk in chunks:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            print(f"⚠️ Telegram Send Error: {e}")
            if 'response' in locals() and hasattr(response, 'text'):
                print(f"   Telegram API Response: {response.text}")

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