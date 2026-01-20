import os
import json
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google import genai
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SHEET_CREDENTIALS = os.environ["G_SHEET_CREDENTIALS"]
LATITUDE = 34.05 
LONGITUDE = -118.25

# --- SETUP NEW CLIENT ---
# The new SDK uses a Client object rather than global configuration
client = genai.Client(api_key=GEMINI_API_KEY)

def get_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=temperature_2m_max,precipitation_sum&past_days=3&forecast_days=1&timezone=auto"
    response = requests.get(url).json()
    return response['daily']

def get_telegram_updates():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        response = requests.get(url)
        if response.status_code != 200: return []
        updates = response.json()
        if 'result' not in updates: return []
        
        valid_updates = []
        yesterday = datetime.now() - timedelta(days=1)
        
        for u in updates['result']:
            if 'message' in u and 'text' in u['message']:
                # Telegram timestamps are integers
                msg_date = datetime.fromtimestamp(u['message']['date'])
                text = u['message']['text'].lower()
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
    sheet_client = gspread.authorize(creds)
    sheet = sheet_client.open("ShakahariDB").worksheet("Plants")
    
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    # 2. CHECK UPDATES
    updates = get_telegram_updates()
    if updates:
        print(f"User feedback received: {updates}")
        # Placeholder: Logic to update DB dates would go here

    # 3. GET CONTEXT
    weather = get_weather()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 4. RUN AGENT LOOP
    tasks = []
    
    for index, row in df.iterrows():
        plant_name = row['Name']
        
        # Construct the Prompt
        prompt = f"""
        You are a smart gardening assistant.
        TODAY: {today}
        
        PLANT: {plant_name} ({row['Type']}, {row['Location']})
        LAST WATERED: {row['Last Watered']}
        NOTES: {row['Notes']}
        
        WEATHER (Past 3 days + Today):
        Max Temps: {weather['temperature_2m_max']}
        Rain (mm): {weather['precipitation_sum']}
        
        TASK:
        Decide if this plant needs water today.
        
        OUTPUT FORMAT:
        Return ONLY a JSON string: {{ "action": "WATER" or "WAIT", "reason": "Short explanation" }}
        """
        
        try:
            # --- NEW SDK CALL ---
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=prompt
            )
            
            # Parsing logic (strips markdown code blocks if the model adds them)
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            decision = json.loads(clean_text)
            
            if decision['action'] == "WATER":
                tasks.append(f"💧 *{plant_name}*: {decision['reason']}")
                
        except Exception as e:
            print(f"Error processing {plant_name}: {e}")

    # 5. SEND NOTIFICATION
    if tasks:
        msg = f"🌿 *Plant Care Daily ({today})*\n\n" + "\n".join(tasks)
        send_telegram_alert(msg)
        print("Alert sent.")
    else:
        print("No watering needed today.")

if __name__ == "__main__":
    main()