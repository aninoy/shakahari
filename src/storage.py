import json
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.config import SHEET_CREDENTIALS, SHEET_NAME, WORKSHEET_NAME

# Action keywords for parsing user replies
ACTION_KEYWORDS = {
    'watered': 'WATER',
    'fertilized': 'FERTILIZE',
    'fed': 'FERTILIZE',
    'misted': 'MIST',
    'rotated': 'ROTATE',
    'moved': 'MOVE',
    'pruned': 'PRUNE',
    'repotted': 'REPOT',
    'checked': 'CHECK',
}

HISTORY_WORKSHEET = "CareHistory"
HISTORY_HEADERS = ["Date", "Plant", "Action", "Notes"]


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
            self.spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            raise Exception(f"Spreadsheet '{SHEET_NAME}' not found. Did you share it with the service account?")
        
        # Main Plants worksheet
        try:
            self.worksheet = self.spreadsheet.worksheet(WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            raise Exception(f"Worksheet '{WORKSHEET_NAME}' not found in '{SHEET_NAME}'")
        
        self.df = pd.DataFrame(self.worksheet.get_all_records())
        
        # CareHistory worksheet (create if missing, add headers if empty)
        try:
            self.history_ws = self.spreadsheet.worksheet(HISTORY_WORKSHEET)
            # Check if headers exist, add if empty
            if not self.history_ws.get_all_values():
                print(f"📝 Adding headers to '{HISTORY_WORKSHEET}'...")
                self.history_ws.append_row(HISTORY_HEADERS)
        except gspread.WorksheetNotFound:
            print(f"📝 Creating '{HISTORY_WORKSHEET}' worksheet...")
            self.history_ws = self.spreadsheet.add_worksheet(
                title=HISTORY_WORKSHEET, rows=1000, cols=4
            )
            self.history_ws.append_row(HISTORY_HEADERS)

    def get_inventory(self):
        """Returns the full plant inventory DataFrame."""
        return self.df

    def get_recent_history(self, plant_name=None, limit=5):
        """Fetch recent care history for a plant or all plants."""
        records = self.history_ws.get_all_records()
        if not records:
            return []
        
        df = pd.DataFrame(records)
        
        if plant_name:
            df = df[df['Plant'].str.lower() == plant_name.lower()]
        
        # Sort by date descending and limit
        df = df.sort_values('Date', ascending=False).head(limit)
        return df.to_dict('records')

    def get_history_summary(self, limit_per_plant=3):
        """Get recent care summary for all plants (for agent context)."""
        records = self.history_ws.get_all_records()
        if not records:
            return {}
        
        df = pd.DataFrame(records)
        summary = {}
        
        for plant in self.df['Name'].unique():
            plant_history = df[df['Plant'] == plant].sort_values('Date', ascending=False).head(limit_per_plant)
            if not plant_history.empty:
                summary[plant] = plant_history[['Date', 'Action']].to_dict('records')
        
        return summary

    def log_action(self, plant_name, action, notes=""):
        """Log a care action to history."""
        date = datetime.now().strftime('%Y-%m-%d')
        self.history_ws.append_row([date, plant_name, action, notes])

    def sync_from_mailbox(self):
        """Updates DB based on user replies - handles all action types."""
        from src.telegram_bot import get_recent_messages
        messages = get_recent_messages()
        if not messages:
            return False

        changes = False
        for msg in messages:
            text = msg['text'].lower().strip()
            date = msg['date']

            # CASE 1: "DONE" - Clears all pending statuses
            if text in ['done', 'done all', 'completed']:
                # Process all pending plants
                mask_pending = self.df['Status'].str.startswith('PENDING', na=False)
                for idx, row in self.df[mask_pending].iterrows():
                    status = row['Status']
                    plant_name = row['Name']
                    
                    # Log each action to history
                    if 'WATER' in status:
                        self.df.at[idx, 'Last Watered'] = date
                        self.log_action(plant_name, 'WATER', 'Confirmed via Done')
                    if 'FERT' in status:
                        self.df.at[idx, 'Last Fertilized'] = date
                        self.log_action(plant_name, 'FERTILIZE', 'Confirmed via Done')
                    # Log other actions
                    for action in ['MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
                        if action in status:
                            self.log_action(plant_name, action, 'Confirmed via Done')
                    
                    self.df.at[idx, 'Status'] = 'OK'
                    changes = True
                
                if changes:
                    print(f"✅ User confirmed ALL tasks on {date}")

            # CASE 2: Specific action - "[Action] [Plant]" (e.g., "Watered Fern")
            else:
                for keyword, action in ACTION_KEYWORDS.items():
                    if keyword in text:
                        plant = text.replace(keyword, '').strip()
                        for idx, row in self.df.iterrows():
                            if plant and plant in row['Name'].lower():
                                plant_name = row['Name']
                                
                                # Update date columns for water/fertilize
                                if action == 'WATER':
                                    self.df.at[idx, 'Last Watered'] = date
                                elif action == 'FERTILIZE':
                                    self.df.at[idx, 'Last Fertilized'] = date
                                
                                # Log to history
                                self.log_action(plant_name, action)
                                
                                # Clear this specific pending action
                                curr_status = str(row.get('Status', ''))
                                if f'PENDING_{action}' in curr_status:
                                    new_status = curr_status.replace(f'PENDING_{action}', '').strip('_')
                                    self.df.at[idx, 'Status'] = new_status if new_status.startswith('PENDING') else 'OK'
                                    changes = True
                                    print(f"✅ Marked {action} complete for {plant_name}")
                        break

        if changes:
            self.save()
        return changes

    def mark_pending(self, tasks):
        """Updates Status column based on Agent's recommended actions."""
        if not tasks:
            return
        
        for t in tasks:
            name = t['name']
            action = t['action'].upper()
            
            mask = self.df['Name'] == name
            if mask.any():
                current = str(self.df.loc[mask, 'Status'].values[0])
                
                # Build composite status if multiple actions
                if current.startswith('PENDING') and f'PENDING_{action}' not in current:
                    new_status = f"{current}_{action}"
                else:
                    new_status = f"PENDING_{action}"
                
                self.df.loc[mask, 'Status'] = new_status
        
        self.save()

    def save(self):
        """Writes the DataFrame back to Google Sheets."""
        self.worksheet.update([self.df.columns.values.tolist()] + self.df.values.tolist())
        print("💾 Database saved.")