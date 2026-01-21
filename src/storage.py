import json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.config import SHEET_CREDENTIALS, SHEET_NAME, WORKSHEET_NAME
from src.telegram_bot import get_recent_messages

class PlantDB:
    def __init__(self):
        try:
            creds_dict = json.loads(SHEET_CREDENTIALS)
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid G_SHEET_CREDENTIALS JSON: {e}")
        
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        try:
            spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            raise Exception(f"Spreadsheet '{SHEET_NAME}' not found. Did you share it with the service account?")
        
        try:
            self.worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            raise Exception(f"Worksheet '{WORKSHEET_NAME}' not found in '{SHEET_NAME}'")
        
        self.df = pd.DataFrame(self.worksheet.get_all_records())

    def get_inventory(self):
        return self.df

    def sync_from_mailbox(self):
        """Updates DB based on user replies (Watered X, Fertilized Y, or Done)."""
        messages = get_recent_messages()
        if not messages: return False

        changes = False
        for msg in messages:
            text = msg['text'] # lowercase
            date = msg['date']

            # CASE 1: "DONE" (Completes whatever was pending)
            if text.strip() in ['done', 'done all', 'completed']:
                # Update 'Last Watered' where Status was WATER or BOTH
                mask_water = self.df['Status'].isin(['PENDING_WATER', 'PENDING_BOTH'])
                if mask_water.any():
                    self.df.loc[mask_water, 'Last Watered'] = date
                
                # Update 'Last Fertilized' where Status was FERT or BOTH
                mask_fert = self.df['Status'].isin(['PENDING_FERT', 'PENDING_BOTH'])
                if mask_fert.any():
                    self.df.loc[mask_fert, 'Last Fertilized'] = date
                
                # Clear Status for all matches
                mask_all = self.df['Status'].str.startswith('PENDING', na=False)
                if mask_all.any():
                    self.df.loc[mask_all, 'Status'] = 'OK'
                    changes = True
                    print(f"✅ User confirmed ALL tasks on {date}")

            # CASE 2: Specific "Watered [Plant]"
            elif 'watered' in text:
                plant = text.replace('watered', '').strip()
                for idx, row in self.df.iterrows():
                    if plant in row['Name'].lower():
                        self.df.at[idx, 'Last Watered'] = date
                        # If status was BOTH, downgrade to PENDING_FERT, else OK
                        curr = row.get('Status', '')
                        if curr == 'PENDING_BOTH': self.df.at[idx, 'Status'] = 'PENDING_FERT'
                        elif curr == 'PENDING_WATER': self.df.at[idx, 'Status'] = 'OK'
                        changes = True

            # CASE 3: Specific "Fertilized [Plant]"
            elif 'fertilized' in text or 'fed' in text:
                plant = text.replace('fertilized', '').replace('fed', '').strip()
                for idx, row in self.df.iterrows():
                    if plant in row['Name'].lower():
                        self.df.at[idx, 'Last Fertilized'] = date
                        # If status was BOTH, downgrade to PENDING_WATER, else OK
                        curr = row.get('Status', '')
                        if curr == 'PENDING_BOTH': self.df.at[idx, 'Status'] = 'PENDING_WATER'
                        elif curr == 'PENDING_FERT': self.df.at[idx, 'Status'] = 'OK'
                        changes = True

        if changes:
            self.save()
        return changes

    def mark_pending(self, tasks):
        """Updates Status column based on Agent's recommended actions."""
        if not tasks: return
        
        for t in tasks:
            name = t['name']
            action = t['action'] # WATER, FERTILIZE, or BOTH
            
            # Map action to Status string
            status_map = {
                "WATER": "PENDING_WATER",
                "FERTILIZE": "PENDING_FERT",
                "BOTH": "PENDING_BOTH"
            }
            
            mask = self.df['Name'] == name
            if mask.any():
                self.df.loc[mask, 'Status'] = status_map.get(action, 'OK')
        
        self.save()

    def save(self):
        self.worksheet.update([self.df.columns.values.tolist()] + self.df.values.tolist())
        print("💾 Database saved.")