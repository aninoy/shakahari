import json
import threading
from contextlib import contextmanager
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.config import SHEET_CREDENTIALS, SHEET_NAME, SHEET_ID, WORKSHEET_NAME
from src.fertilizers import normalize, product_of
from src import clock

HISTORY_WORKSHEET = "CareHistory"
HISTORY_HEADERS = ["Date", "Plant", "Action", "Notes"]

PENDING_PREFIX = "PENDING_"

# Serialises the read-modify-write window within one container.
#
# Targeted cell writes keep taps on different plants from colliding, but two
# taps on the SAME plant still contend for its Status cell: each reads the same
# snapshot, clears a different action, and the last write wins. The Recorder is
# pinned to a single instance so this lock covers every concurrent request;
# that instance accepts several at once (a concurrency of 1 makes Cloud Run
# reject bursts with 429) and they queue here instead.
_write_lock = threading.RLock()


@contextmanager
def exclusive():
    """Hold the write lock for a whole read-modify-write cycle."""
    with _write_lock:
        yield


# How many trailing CareHistory rows to consult when deduping an append.
# Duplicates only arise from Telegram retrying a delivery within minutes, so a
# bounded tail is enough and stays cheap however large the log grows.
HISTORY_DEDUPE_TAIL = 100


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


def _history_key(plant, action, date):
    return (str(plant).strip().lower(), str(action).strip().upper(), str(date).strip())


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
        
        self.spreadsheet = self._open_spreadsheet(client)
        
        # Main Plants worksheet
        try:
            self.worksheet = self.spreadsheet.worksheet(WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            raise Exception(f"Worksheet '{WORKSHEET_NAME}' not found in '{SHEET_NAME}'")
        
        self.df = pd.DataFrame(self.worksheet.get_all_records())
        self._reset_write_state()
        
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

    @staticmethod
    def _open_spreadsheet(client):
        """Prefer the id (a direct fetch) over the name (a Drive search)."""
        if SHEET_ID:
            try:
                return client.open_by_key(SHEET_ID)
            except Exception as e:
                print(f"⚠️ SHEET_ID lookup failed ({e}); falling back to name search")
        try:
            return client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            raise Exception(
                f"Spreadsheet '{SHEET_NAME}' not found. Did you share it with the service account?")

    def _reset_write_state(self):
        """Dirty-cell tracking and the lazily-read history tail."""
        self._dirty = set()
        self._history_keys = None

    def _set(self, idx, column, value):
        """Change one cell and remember to write just that cell.

        Every mutation goes through here so save() can write only what actually
        changed. Rewriting the whole sheet meant two overlapping taps clobbered
        each other, and because CareHistory appends land immediately while
        Plants is written at save(), the loser left history saying the action
        happened and Plants still saying it was pending."""
        self.df.at[idx, column] = value
        self._dirty.add((idx, column))

    def _a1(self, idx, column):
        """Sheet address of a DataFrame cell. Row 1 is the header, so the
        first data row is 2; columns follow the sheet's own order."""
        col = self.df.columns.get_loc(column) + 1
        return gspread.utils.rowcol_to_a1(idx + 2, col)

    def _history_tail_keys(self):
        """(plant, action, date) for the tail of CareHistory, read once."""
        if self._history_keys is not None:
            return self._history_keys

        keys = set()
        try:
            used = len(self.history_ws.col_values(1))
            if used > 1:
                start = max(2, used - HISTORY_DEDUPE_TAIL + 1)
                for row in self.history_ws.get(f"A{start}:C{used}"):
                    if len(row) >= 3:
                        keys.add(_history_key(row[1], row[2], row[0]))
        except Exception as e:
            # A failed dedupe check must not block logging the action.
            print(f"⚠️ Could not read history tail for dedupe: {e}")

        self._history_keys = keys
        return keys

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
        """Log a care action to history, unless that exact action is already
        recorded for that plant on that day.

        Telegram retries any delivery that times out, and the handler is not
        idempotent -- without this a retry writes the action twice."""
        if not date:
            date = clock.today()

        key = _history_key(plant_name, action, date)
        if key in self._history_tail_keys():
            print(f"⏭️ {action} for {plant_name} already logged on {date}")
            return False

        self.history_ws.append_row([date, plant_name, action, notes])
        self._history_keys.add(key)
        return True

    def _product_note(self, idx):
        """'Confirmed via <product>' for the plant's assigned fertilizer.

        Which bottle went on the plant is the point of a feeding log, so a
        per-plant tap records it the same way the per-product bulk button does.
        Blank when the plant has no product assigned -- never guess one."""
        if 'Fertilizer' not in self.df.columns:
            return ""
        product = product_of(normalize(self.df.at[idx, 'Fertilizer']))
        return f'Confirmed via {product}' if product else ""

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
            self._set(idx, 'Last Watered', date)
        elif action == 'FERTILIZE':
            self._set(idx, 'Last Fertilized', date)
            if not notes:
                notes = self._product_note(idx)

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
                self._set(idx, 'Last Watered', date)
            elif action == 'FERTILIZE':
                self._set(idx, 'Last Fertilized', date)

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
            self._set(idx, 'Last Fertilized', date)
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
        self._set(idx, 'Status', _compose_status(ordered))

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
                self._set(idx, 'Last Watered', date)
            if 'FERTILIZE' in actions:
                self._set(idx, 'Last Fertilized', date)
            for action in actions:
                self.log_action(plant_name, action, date=date, notes='Confirmed via Mark all done')

            self._set(idx, 'Status', 'OK')
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

                self._set(self.df[mask].index[0], 'Status', new_status)
        
        self.save()

    def save(self):
        """Write only the cells that changed since this request started.

        A full-sheet rewrite from a request-start snapshot is a lost update
        waiting to happen: two taps on different plants would overwrite one
        another even though their changes never overlapped."""
        if not self._dirty:
            return

        updates = [{"range": self._a1(idx, column),
                    "values": [[self.df.at[idx, column]]]}
                   for idx, column in sorted(self._dirty, key=lambda c: (c[0], str(c[1])))]
        self.worksheet.batch_update(updates)
        self._dirty.clear()
        print(f"💾 Saved {len(updates)} cell(s).")