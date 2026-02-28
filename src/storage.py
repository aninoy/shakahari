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
        
        print(f"📬 Checking mailbox... found {len(messages) if messages else 0} messages")
        
        if not messages:
            return False

        changes = False
        for msg in messages:
            raw_text = msg['text']
            text = raw_text.lower().strip()
            date = msg['date']
            
            print(f"📩 Processing: '{raw_text}' (date: {date})")

            # CASE 1: "DONE" - Clears all pending statuses
            if text in ['done', 'done all', 'completed']:
                mask_pending = self.df['Status'].str.startswith('PENDING', na=False)
                for idx, row in self.df[mask_pending].iterrows():
                    status = row['Status']
                    plant_name = row['Name']
                    
                    if 'WATER' in status:
                        self.df.at[idx, 'Last Watered'] = date
                        self.log_action(plant_name, 'WATER', 'Confirmed via Done')
                    if 'FERT' in status:
                        self.df.at[idx, 'Last Fertilized'] = date
                        self.log_action(plant_name, 'FERTILIZE', 'Confirmed via Done')
                    for action in ['MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
                        if action in status:
                            self.log_action(plant_name, action, 'Confirmed via Done')
                    
                    self.df.at[idx, 'Status'] = 'OK'
                    changes = True
                
                if changes:
                    print(f"✅ User confirmed ALL tasks on {date}")

            # CASE 2: Specific action(s) - supports slash commands and compound sentences
            else:
                # Track the last seen action to apply to subsequent plant names without explicit actions
                # e.g., "watered monstera, fiddle leaf fig" -> applies WATER to both
                last_action = None
                
                # Split on comma, semicolon, or "and" for compound messages
                import re
                parts = re.split(r'[,;]|\band\b', text)
                print(f"   Split into {len(parts)} part(s): {parts}")
                
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    
                    print(f"   Processing part: '{part}'")
                    matched = False
                    
                    # 2a. Check for slash commands (e.g. /water_monstera)
                    if part.startswith('/'):
                        # Parse command like /water_monstera -> action="water", plant="monstera"
                        cmd_parts = part[1:].split('_', 1)
                        if len(cmd_parts) == 2:
                            cmd_action, cmd_plant = cmd_parts
                            action = cmd_action.upper()
                            plant_query = cmd_plant.replace('_', ' ').strip()
                            
                            # Validate it's a known action
                            if action in ACTION_KEYWORDS.values() or action in [v.upper() for v in ACTION_KEYWORDS.values()] or action in [k.upper() for k in ACTION_KEYWORDS.keys()] or action in ['WATER', 'FERTILIZE', 'MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
                                last_action = action
                                print(f"      📱 Parsed slash command: action={action}, plant_query='{plant_query}'")
                            else:
                                print(f"      ⚠️ Unknown action in command: {action}")
                                action = None
                        else:
                            print(f"      ⚠️ Invalid command format: {part}")
                            action = None
                            plant_query = None

                    # 2b. Check for natural language keywords
                    else:
                        action = None
                        plant_query = part
                        for keyword, kw_action in ACTION_KEYWORDS.items():
                            if keyword in part:
                                action = kw_action
                                last_action = action
                                plant_query = part.replace(keyword, '').strip()
                                print(f"      Found keyword '{keyword}' -> action={action}, plant_query='{plant_query}'")
                                break
                    
                    # If no action found in this part, but we have a previous action, carry it over
                    if not action and last_action:
                        action = last_action
                        plant_query = part.strip()
                        print(f"      Carrying over previous action '{action}' for plant_query='{plant_query}'")
                    
                    if not action:
                        print(f"      ⚠️ No action keyword found and no previous action to carry over")
                        continue
                        
                    if not plant_query:
                        print(f"      ⚠️ No plant name found")
                        continue
                    
                    # Simplify plant query for matching if it came from a slash command
                    search_query = plant_query
                    
                    # Try to match plant name
                    found_plant = False
                    # Create a safe name for each row to match against slash commands
                    for idx, row in self.df.iterrows():
                        plant_name = row['Name']
                        safe_name = "".join(c if c.isalnum() else "_" for c in plant_name.lower())
                        safe_name = "_".join(filter(None, safe_name.split("_")))
                        
                        if search_query in plant_name.lower() or search_query == safe_name:
                            found_plant = True
                            print(f"      ✓ Matched plant: {plant_name}")
                            
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
                            print(f"      ✅ Marked {action} complete for {plant_name}")
                    
                    if not found_plant:
                        print(f"      ⚠️ No matching plant found for '{search_query}'")
                    
                    matched = True

        if changes:
            self.save()
        else:
            print("📭 No changes made to database")
        
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