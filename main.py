import os
import json
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google import genai
from google.genai import types
from datetime import datetime, timedelta

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SHEET_CREDENTIALS = os.environ["G_SHEET_CREDENTIALS"]
LATITUDE = 34.05 
LONGITUDE = -118.25

# --- SETUP CLIENT ---
# We use the specific stable version 'gemini-1.5-flash-002' to avoid 404 errors
client = genai.Client(api_key=GEMINI_API_KEY)

def get_weather():
    """Fetches past 3 days and today's forecast."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=temperature_2m_max,precipitation_sum&past_days=3&forecast_days=1&timezone=auto"
    try:
        response = requests.get(url).json()
        return response.get('daily')
    except Exception as e:
        print(f"Weather API Error: {e}")
        return None

def send_telegram_alert(message):
    """Sends a push notification to your phone."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    print("🌿 Starting Plant Agent...")

    # 1. AUTHENTICATE GOOGLE SHEETS
    try:
        creds_dict = json.loads(SHEET_CREDENTIALS)
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        sheet_client = gspread.authorize(creds)
        sheet = sheet_client.open("ShakahariDB").worksheet("Plants")
        
        # Pull all data into a DataFrame
        data = sheet.get_all_records()
        print(f"✅ Loaded {len(data)} plants from database.")
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return

    # 2. GET CONTEXT (Weather)
    weather = get_weather()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if not weather:
        send_telegram_alert("⚠️ Plant Agent Error: Could not fetch weather data.")
        return

    # 3. BATCH PROCESSING (The Rate Limit Fix)
    # We construct ONE massive prompt containing all inventory.
    # This reduces API calls from N (number of plants) to 1.
    
    # Minify data to save tokens
    inventory_list = []
    for row in data:
        inventory_list.append({
            "name": row['Name'],
            "type": row['Type'],
            "location": row['Location'],
            "last_watered": row['Last Watered'],
            "notes": row['Notes']
        })

    prompt = f"""
    You are an expert botanist agent.
    
    CONTEXT:
    Date: {today}
    Weather (Past 3 days + Today):
    - Max Temps (C): {weather['temperature_2m_max']}
    - Rain (mm): {weather['precipitation_sum']}
    
    INVENTORY:
    {json.dumps(inventory_list)}
    
    INSTRUCTIONS:
    Analyze the weather and the inventory.
    Identify ONLY the plants that need water today.
    
    RULES:
    1. Outdoor plants: If rain_sum > 5mm in last 2 days, do NOT water.
    2. Indoor plants: Check 'last_watered' vs typical needs for that type.
    
    OUTPUT:
    Return pure JSON with this structure:
    {{ "tasks": [ {{ "name": "Plant Name", "reason": "Short reason" }} ] }}
    """

    try:
        print("🤔 Asking Gemini...")
        
        # Using the new google-genai SDK method signature
        response = client.models.generate_content(
            model='gemini-1.5-flash-002', # Specific stable version
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json' # Forces valid JSON output
            )
        )
        
        # Parse result
        result = json.loads(response.text)
        tasks = result.get('tasks', [])
        
        # 4. SEND NOTIFICATION
        if tasks:
            msg_lines = [f"🌿 *Plant Care Tasks ({today})*"]
            for t in tasks:
                msg_lines.append(f"💧 *{t['name']}*: {t['reason']}")
            
            final_msg = "\n\n".join(msg_lines)
            send_telegram_alert(final_msg)
            print(f"✅ Sent alerts for {len(tasks)} plants.")
        else:
            print("✅ Agent decided no watering is needed today.")
            
    except Exception as e:
        print(f"❌ Agent Error: {e}")
        send_telegram_alert(f"⚠️ Plant Agent Failed: {str(e)}")

if __name__ == "__main__":
    main()