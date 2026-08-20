import json
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.config import SHEET_CREDENTIALS, SHEET_NAME, WORKSHEET_NAME

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

    def log_action(self, plant_name, action, date=None, notes=""):
        """Log a care action to history."""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        self.history_ws.append_row([date, plant_name, action, notes])

    def log_task_action(self, plant_name, action, date=None, notes=""):
        """Log a specific care action for an exact plant name (case-insensitive).
        Returns True if the plant was found and updated, False otherwise."""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        mask = self.df['Name'].str.lower() == plant_name.strip().lower()
        if not mask.any():
            return False

        idx = self.df[mask].index[0]

        if action == 'WATER':
            self.df.at[idx, 'Last Watered'] = date
        elif action == 'FERTILIZE':
            self.df.at[idx, 'Last Fertilized'] = date

        self.log_action(plant_name, action, date=date, notes=notes)
        self._clear_pending(idx, action)
        self.save()
        return True

    def mark_action_done(self, action, date=None):
        """Confirm one specific action across every plant currently pending it.
        Returns the number of plants updated."""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        mask_pending = self.df['Status'].str.contains(f'PENDING_{action}', na=False, regex=False)
        updated = 0
        for idx, row in self.df[mask_pending].iterrows():
            plant_name = row['Name']

            if action == 'WATER':
                self.df.at[idx, 'Last Watered'] = date
            elif action == 'FERTILIZE':
                self.df.at[idx, 'Last Fertilized'] = date

            self.log_action(plant_name, action, date=date, notes='Confirmed via Mark action complete')
            self._clear_pending(idx, action)
            updated += 1

        if updated:
            self.save()
        return updated

    def _clear_pending(self, idx, action):
        """Remove one action from a row's composite PENDING_ status string."""
        current = str(self.df.at[idx, 'Status'])
        if f'PENDING_{action}' not in current:
            return
        new_status = current.replace(f'PENDING_{action}', '').strip('_')
        if new_status and not new_status.startswith('PENDING'):
            new_status = f'PENDING_{new_status}'
        self.df.at[idx, 'Status'] = new_status if new_status else 'OK'

    def mark_all_done(self, date=None):
        """Confirm every plant's pending actions at once. Returns the number of plants updated."""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        mask_pending = self.df['Status'].str.startswith('PENDING', na=False)
        updated = 0
        for idx, row in self.df[mask_pending].iterrows():
            status = row['Status']
            plant_name = row['Name']

            if 'WATER' in status:
                self.df.at[idx, 'Last Watered'] = date
                self.log_action(plant_name, 'WATER', date=date, notes='Confirmed via Mark all done')
            if 'FERT' in status:
                self.df.at[idx, 'Last Fertilized'] = date
                self.log_action(plant_name, 'FERTILIZE', date=date, notes='Confirmed via Mark all done')
            for action in ['MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
                if action in status:
                    self.log_action(plant_name, action, date=date, notes='Confirmed via Mark all done')

            self.df.at[idx, 'Status'] = 'OK'
            updated += 1

        if updated:
            self.save()
        return updated

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
                
                # Check if this action is already pending (avoid duplicates like CHECK_CHECK)
                # Split current status into parts and check if action already exists
                current_actions = current.replace('PENDING_', '').split('_') if current.startswith('PENDING') else []
                
                if action in current_actions:
                    # Action already pending, skip
                    print(f"⏭️ {action} already pending for {name}, skipping")
                    continue
                
                # Build composite status if multiple actions
                if current.startswith('PENDING'):
                    new_status = f"{current}_{action}"
                else:
                    new_status = f"PENDING_{action}"
                
                self.df.loc[mask, 'Status'] = new_status
        
        self.save()

    def save(self):
        """Writes the DataFrame back to Google Sheets."""
        self.worksheet.update([self.df.columns.values.tolist()] + self.df.values.tolist())
        print("💾 Database saved.")