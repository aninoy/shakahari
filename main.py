import os
import json
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SHEET_CREDENTIALS = os.environ["G_SHEET_CREDENTIALS"] # This will be the JSON string
LATITUDE = 34.05 # Example: Los Angeles (Update this)
LONGITUDE = -118.25

# --- SETUP ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-exp')

def get_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=temperature_2m_max,precipitation_sum&past_days=3&forecast_days=1&timezone=auto"
    response = requests.get(url).json()
    return response['daily']

def get_telegram_updates():
    """Check for 'Done' messages in the last 24h to update DB."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        updates = requests.get(url).json()
        if 'result' not in updates: return []
        
        valid_updates = []
        yesterday = datetime.now() - timedelta(days=1)
        
        for u in updates['result']:
            if 'message' in u and 'text' in u['message']:
                msg_date = datetime.fromtimestamp(u['message']['date'])
                text = u['message']['text'].lower()
                # Simple logic: If you typed "done" or "watered", we assume you did yesterday's tasks
                if msg_date > yesterday and ("done" in text or "watered" in text):
                    valid_updates.append(text)
        return valid_updates
    except Exception as e:
        print(f"Telegram error: {e}")
        return []

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    # 1. AUTHENTICATE GOOGLE SHEETS
    creds_dict = json.loads(SHEET_CREDENTIALS)
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("MyPlantAgent").worksheet("Plants") # Make sure Sheet Name matches
    
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    # 2. PROCESS USER FEEDBACK (Did you water yesterday?)
    updates = get_telegram_updates()
    if updates:
        # If user said 'done', set 'Last Watered' to Today for pending plants
        # (This is a simplified logic; you can make Gemini parse 'Watered the fern' later)
        print(f"User feedback received: {updates}")
        # For V1, we will just acknowledge it. 
        # Ideally, you'd parse "Watered Monstera" and update specific rows here.

    # 3. GET CONTEXT
    weather = get_weather()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 4. RUN AGENT LOOP
    tasks = []
    
    for index, row in df.iterrows():
        plant_name = row['Name']
        last_watered = row['Last Watered']
        plant_type = row['Type']
        
        # Construct the Prompt
        prompt = f"""
        You are a smart gardening assistant.
        TODAY: {today}
        
        PLANT: {plant_name} ({plant_type}, {row['Location']})
        LAST WATERED: {last_watered}
        NOTES: {row['Notes']}
        
        WEATHER (Past 3 days + Today):
        Max Temps: {weather['temperature_2m_max']}
        Rain (mm): {weather['precipitation_sum']}
        
        TASK:
        Decide if this plant needs water today.
        - Outdoor plants: Skip if it rained recently (>5mm) or is about to rain.
        - Indoor plants: Check days elapsed since last water vs. notes.
        
        OUTPUT FORMAT:
        Return ONLY a JSON string: {{ "action": "WATER" or "WAIT", "reason": "Short explanation" }}
        """
        
        try:
            response = model.generate_content(prompt)
            # Clean response to ensure pure JSON
            clean_text = response.text.replace('```json', '').replace('```', '')
            decision = json.loads(clean_text)
            
            if decision['action'] == "WATER":
                tasks.append(f"💧 *{plant_name}*: {decision['reason']}")
                # Optional: Update Sheet to 'Pending' status if you add a status column
                
        except Exception as e:
            print(f"Error processing {plant_name}: {e}")

    # 5. SEND NOTIFICATION
    if tasks:
        msg = f"🌿 *Plant Care Daily ({today})*\n\n" + "\n".join(tasks)
        send_telegram_alert(msg)
    else:
        print("No watering needed today.")

if __name__ == "__main__":
    main()