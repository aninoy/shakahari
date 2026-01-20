import os
import json
import time
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

# --- SETUP CLIENT ---
# We switch to 'gemini-1.5-flash' which is stable and has higher rate limits
client = genai.Client(api_key=GEMINI_API_KEY)

def get_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=temperature_2m_max,precipitation_sum&past_days=3&forecast_days=1&timezone=auto"
    try:
        response = requests.get(url).json()
        return response['daily']
    except Exception as e:
        print(f"Weather API Error: {e}")
        return None

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    # 1. AUTHENTICATE & FETCH DATA
    print("Authenticating...")
    creds_dict = json.loads(SHEET_CREDENTIALS)
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    sheet_client = gspread.authorize(creds)
    sheet = sheet_client.open("MyPlantAgent").worksheet("Plants")
    
    # Fetch all records at once
    data = sheet.get_all_records()
    
    # 2. GET CONTEXT
    weather = get_weather()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if not weather:
        send_telegram_alert("⚠️ Error fetching weather data. Skipping plant check.")
        return

    # 3. BATCH PROCESSING (The Fix)
    # Instead of a loop, we construct one massive prompt with all plant data.
    
    # Simplify data for the prompt to save tokens
    plants_minified = []
    for row in data:
        plants_minified.append({
            "name": row['Name'],
            "type": row['Type'],
            "loc": row['Location'],
            "last_water": row['Last Watered'],
            "notes": row['Notes']
        })

    prompt = f"""
    You are a smart gardening assistant. 
    TODAY: {today}
    
    WEATHER REPORT (Past 3 days + Forecast):
    - Max Temps: {weather['temperature_2m_max']}
    - Rain (mm): {weather['precipitation_sum']}
    
    INVENTORY:
    {json.dumps(plants_minified, indent=2)}
    
    TASK:
    Analyze the weather and the inventory. Decide which plants need water TODAY.
    - Outdoor: heavily weighted by rain history.
    - Indoor: weighted by 'last_water' date and 'notes'.
    
    OUTPUT:
    Return a JSON object with a list of ONLY the plants that need water.
    Format: {{ "tasks": [ {{ "name": "Plant Name", "reason": "Reason for watering" }} ] }}
    """
    
    try:
        print("Asking Agent...")
        # Switch to stable model
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt,
            config={'response_mime_type': 'application/json'} # Force JSON output
        )
        
        # Parse Response
        result = json.loads(response.text)
        tasks = result.get('tasks', [])
        
        # 4. SEND NOTIFICATION
        if tasks:
            msg_lines = [f"🌿 *Plant Care Daily ({today})*"]
            for t in tasks:
                msg_lines.append(f"💧 *{t['name']}*: {t['reason']}")
            
            final_msg = "\n\n".join(msg_lines)
            send_telegram_alert(final_msg)
            print(f"Sent alerts for {len(tasks)} plants.")
        else:
            print("Agent decided no watering is needed today.")
            
    except Exception as e:
        print(f"Agent Error: {e}")
        # Optional: Send error to Telegram so you know it failed
        send_telegram_alert(f"⚠️ Plant Agent Failed: {str(e)}")

if __name__ == "__main__":
    main()