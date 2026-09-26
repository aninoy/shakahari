import json
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.config import SHEET_CREDENTIALS, SHEET_NAME, WORKSHEET_NAME
from src.fertilizers import normalize, product_of
from src import clock

HISTORY_WORKSHEET = "CareHistory"
HISTORY_HEADERS = ["Date", "Plant", "Action", "Notes"]

PENDING_PREFIX = "PENDING_"


def pending_actions(status):
    """The set of actions a composite Status string is pending.

    Status strings are built by appending, so the same pending set can appear
    as PENDING_WATER_FERTILIZE or PENDING_FERTILIZE_WATER depending only on the
    order the agent emitted its tasks. Substring matching on PENDING_{action}
    therefore finds the action only when it happens to come first -- parse into
    tokens instead so order cannot matter."""
    text = str(status or "")
    if not text.startswith(PENDING_PREFIX):
        return set()
    return {part for part in text[len(PENDING_PREFIX):].split("_") if part}


def _compose_status(actions):
    return PENDING_PREFIX + "_".join(actions) if actions else "OK"


def _is_pending(status, action):
    return action in pending_actions(status)


def ensure_history_headers(worksheet):
    """Add the header row if the sheet is empty.

    Reads only row 1. The previous get_all_values() pulled the entire care
    history -- hundreds of rows -- on every webhook request just to answer
    "is this empty", which was part of what exhausted the Cloud Function's
    memory."""
    try:
        first_row = worksheet.row_values(1)
    except Exception:
        first_row = []
    if not any(str(cell).strip() for cell in first_row):
        print(f"📝 Adding headers to '{HISTORY_WORKSHEET}'...")
        worksheet.append_row(HISTORY_HEADERS)


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
            ensure_history_headers(self.history_ws)
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

    def get_history_summary(self, limit_per_plant=None):
        """Most recent occurrence of each action, per plant.

        Deliberately per-action rather than "the latest N rows": the interval
        engine reads days-since for six actions out of CareHistory, and a flat
        row window drops PRUNE and REPOT as soon as a plant accrues a few
        waterings -- which would make those actions permanently unreachable.

        limit_per_plant is accepted for backwards compatibility and ignored."""
        records = self.history_ws.get_all_records()
        if not records:
            return {}

        df = pd.DataFrame(records)
        summary = {}

        for plant in self.df['Name'].unique():
            plant_history = df[df['Plant'] == plant].sort_values('Date', ascending=False)
            if plant_history.empty:
                continue
            latest = plant_history.drop_duplicates(subset='Action', keep='first')
            summary[plant] = latest[['Date', 'Action']].to_dict('records')

        return summary

    def log_action(self, plant_name, action, date=None, notes=""):
        """Log a care action to history."""
        if not date:
            date = clock.today()
        self.history_ws.append_row([date, plant_name, action, notes])

    def log_task_action(self, plant_name, action, date=None, notes=""):
        """Log a specific care action for an exact plant name (case-insensitive).
        Returns True if the plant was found and updated, False otherwise."""
        if not date:
            date = clock.today()

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
            date = clock.today()

        mask_pending = self.df['Status'].apply(lambda s: _is_pending(s, action))
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

    def mark_fertilizer_done(self, code, date=None):
        """Confirm one fertilizer product across every plant pending a feed.

        Returns the plant names marked -- not a count, unlike mark_action_done --
        so the recorder can collapse exactly those keyboard rows rather than
        every FERTILIZE row on the message."""
        if not date:
            date = clock.today()

        if 'Fertilizer' not in self.df.columns:
            return []

        product = product_of(code) or code
        marked = []

        mask_pending = self.df['Status'].apply(lambda s: _is_pending(s, 'FERTILIZE'))
        for idx, row in self.df[mask_pending].iterrows():
            if normalize(row.get('Fertilizer')) != code:
                continue

            plant_name = row['Name']
            self.df.at[idx, 'Last Fertilized'] = date
            self.log_action(plant_name, 'FERTILIZE', date=date,
                            notes=f'Confirmed via {product}')
            self._clear_pending(idx, 'FERTILIZE')
            marked.append(plant_name)

        if marked:
            self.save()
        return marked

    def _clear_pending(self, idx, action):
        """Remove one action from a row's composite PENDING_ status string.

        Order-independent: the remaining actions keep their original sequence so
        the cell stays stable across edits."""
        current = str(self.df.at[idx, 'Status'])
        remaining = pending_actions(current)
        if action not in remaining:
            return
        ordered = [a for a in current[len(PENDING_PREFIX):].split("_")
                   if a and a != action]
        self.df.at[idx, 'Status'] = _compose_status(ordered)

    def mark_all_done(self, date=None):
        """Confirm every plant's pending actions at once. Returns the number of plants updated."""
        if not date:
            date = clock.today()

        mask_pending = self.df['Status'].apply(lambda s: bool(pending_actions(s)))
        updated = 0
        for idx, row in self.df[mask_pending].iterrows():
            plant_name = row['Name']
            actions = pending_actions(row['Status'])

            if 'WATER' in actions:
                self.df.at[idx, 'Last Watered'] = date
            if 'FERTILIZE' in actions:
                self.df.at[idx, 'Last Fertilized'] = date
            for action in actions:
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

                if action in pending_actions(current):
                    print(f"⏭️ {action} already pending for {name}, skipping")
                    continue

                if current.startswith(PENDING_PREFIX):
                    new_status = f"{current}_{action}"
                else:
                    new_status = f"{PENDING_PREFIX}{action}"

                self.df.loc[mask, 'Status'] = new_status
        
        self.save()

    def save(self):
        """Writes the DataFrame back to Google Sheets."""
        self.worksheet.update([self.df.columns.values.tolist()] + self.df.values.tolist())
        print("💾 Database saved.")