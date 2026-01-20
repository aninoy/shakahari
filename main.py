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
MODEL_ID = "gemini-2.5-flash" 
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SHEET_CREDENTIALS = os.environ["G_SHEET_CREDENTIALS"]
LATITUDE = 34.05
LONGITUDE = -118.25

client = genai.Client(api_key=GEMINI_API_KEY)

def get_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=temperature_2m_max,precipitation_sum&past_days=3&forecast_days=1&timezone=auto"
    try:
        response = requests.get(url).json()
        return response.get('daily')
    except Exception as e:
        print(f"Weather API Error: {e}")
        return None

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def process_mailbox(sheet, df):
    """Checks Telegram for 'Done' or 'Watered' messages and updates Sheet."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    updates = requests.get(url).json()
    
    if 'result' not in updates:
        return df # No updates

    changes_made = False
    
    # We only look at messages from the last 24 hours
    yesterday_ts = (datetime.now() - timedelta(days=1)).timestamp()

    for u in updates['result']:
        if 'message' not in u: continue
        
        msg = u['message']
        if msg['date'] < yesterday_ts: continue # Too old
        
        text = msg.get('text', '').lower()
        msg_date = datetime.fromtimestamp(msg['date']).strftime('%Y-%m-%d')
        
        # LOGIC 1: "Done" or "Done all" -> Updates all 'Pending' plants
        if text.strip() in ['done', 'done all', 'completed']:
            # Update dataframe where Status is 'Pending'
            mask = df['Status'] == 'Pending'
            if mask.any():
                df.loc[mask, 'Last Watered'] = msg_date
                df.loc[mask, 'Status'] = 'OK'
                changes_made = True
                print(f"✅ User confirmed ALL pending tasks on {msg_date}")

        # LOGIC 2: "Watered [Plant Name]" (Simple fuzzy match)
        elif 'watered' in text:
            # removing 'watered' to get the plant name
            target_plant = text.replace('watered', '').strip()
            
            # Find closest match in DF
            for index, row in df.iterrows():
                if target_plant in row['Name'].lower():
                    df.at[index, 'Last Watered'] = msg_date
                    df.at[index, 'Status'] = 'OK'
                    changes_made = True
                    print(f"✅ User confirmed watering {row['Name']}")

    if changes_made:
        # Push updates back to Google Sheet
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        print("💾 Google Sheet updated with user actions.")
        
    return df

def main():
    print(f"🌿 Starting Plant Agent ({MODEL_ID})...")

    # 1. LOAD DATABASE
    creds_dict = json.loads(SHEET_CREDENTIALS)
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    sheet_client = gspread.authorize(creds)
    worksheet = sheet_client.open("ShakahariDB").worksheet("Plants")
    
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)

    # 2. CHECK MAILBOX (User Feedback Loop)
    # This updates the 'df' variable with any actions you took yesterday
    df = process_mailbox(worksheet, df)

    # 3. GET WEATHER
    weather = get_weather()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 4. AGENT REASONING
    inventory = []
    for index, row in df.iterrows():
        inventory.append({
            "name": row['Name'],
            "type": row['Type'],
            "last": row['Last Watered'],
            "status": row.get('Status', 'OK') # Include status so agent knows what's pending
        })

    prompt = f"""
    ROLE: Expert Botanist.
    DATE: {today}
    
    WEATHER:
    Max Temps: {weather['temperature_2m_max']}
    Rain: {weather['precipitation_sum']}
    
    INVENTORY:
    {json.dumps(inventory)}
    
    TASK:
    Identify plants that need water TODAY.
    
    OUTPUT JSON:
    {{ "tasks": [ {{ "name": "PlantName", "reason": "Why" }} ] }}
    """

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        
        result = json.loads(response.text)
        tasks = result.get('tasks', [])
        
        if tasks:
            msg = [f"🌿 *Care Tasks ({today})*"]
            
            # Mark these as 'Pending' in the sheet so "Done" works tomorrow
            updates_needed = False
            
            for t in tasks:
                msg.append(f"💧 *{t['name']}*: {t['reason']}")
                
                # Update Status in DataFrame
                mask = df['Name'] == t['name']
                df.loc[mask, 'Status'] = 'Pending'
                updates_needed = True

            msg.append("\n_Reply 'Done' to confirm all, or 'Watered [Name]' for specific plants._")
            send_telegram_alert("\n".join(msg))
            
            if updates_needed:
                worksheet.update([df.columns.values.tolist()] + df.values.tolist())
                print("📝 Marked tasks as Pending in Sheet.")
                
        else:
            print("✅ No watering needed.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        send_telegram_alert(f"⚠️ Agent Error: {str(e)}")

if __name__ == "__main__":
    main()