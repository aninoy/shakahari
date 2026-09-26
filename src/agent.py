import json
from datetime import datetime

from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY, MODEL_ID
from src.plant_api import get_care_guidelines
from src.actions import CARE_ACTIONS
from src.fertilizers import normalize, product_of
from src.intervals import effective_interval
from src.weather import derive_climate
from src import clock

SYSTEM_PROMPT = """You are an expert botanist and plant care advisor. You have deep knowledge of:
- Tropical houseplants, succulents, cacti, herbs, and common garden plants
- Light requirements (direct sun, bright indirect, low light, shade)
- Watering needs based on season, temperature, humidity, and plant type
- Fertilization schedules (growing season vs dormancy)
- Common problems (overwatering, leggy growth, pests, root rot)
- Environmental adjustments (humidity, temperature, placement)

Each plant arrives with due_in_days already computed from local weather,
season, irrigation method and its own care guidelines. Those numbers are
authoritative -- an action is only worth recommending once its days_since has
reached its due_in_days. Your judgement is for deciding which of the genuinely
due actions actually matter today, not for overriding the schedule.

BE CONSERVATIVE. An action absent from due_in_days does not apply to that plant
at all and must never be recommended."""

# Actions whose last occurrence is tracked in CareHistory rather than in a
# dedicated sheet column.
HISTORY_ACTIONS = ['MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']


def days_since(date_str):
    """Days since a YYYY-MM-DD string, or None if absent or unparseable.

    Delegates to the garden clock so "how many days ago" uses the same day
    boundary the digest and the Recorder do."""
    return clock.days_since(date_str)


def _is_due(interval, days):
    return days is None or days >= interval["days"]


def _has_other_work_due(intervals, days_by_action):
    return any(action != "CHECK" and _is_due(interval, days_by_action.get(action))
               for action, interval in intervals.items())


def build_plant_context(row, care_history, climate):
    """One plant's context: history, care guidelines, and the intervals the
    engine computed for it.

    Module-level rather than a method so the dry-run harness exercises exactly
    this path instead of a parallel reimplementation that could drift.
    """
    plant_name = row.get('Name', 'Unknown')

    days_by_action = {
        "WATER": days_since(row.get('Last Watered', '')),
        "FERTILIZE": days_since(row.get('Last Fertilized', '')),
    }
    if care_history and plant_name in care_history:
        for action in HISTORY_ACTIONS:
            for record in care_history[plant_name]:
                if record.get('Action') == action:
                    days = days_since(record.get('Date', ''))
                    if days is not None:
                        days_by_action[action] = days
                    break

    care = get_care_guidelines(plant_name)

    plant = {
        "name": plant_name,
        "environment": row.get('Environment', ''),
        "watering": row.get('Watering'),
        "fertilizer": normalize(row.get('Fertilizer')),
        "notes": row.get('Notes', ''),
    }

    intervals = {}
    for action in CARE_ACTIONS:
        result = effective_interval(
            action, plant, care, climate, days_since=days_by_action.get(action))
        if result is not None:
            intervals[action] = result

    # CHECK is the fallback action, not an additional one: if you are already
    # at the plant to water or feed it, you are looking at it. It earns a line
    # only for plants nothing else brings you to.
    if _has_other_work_due(intervals, days_by_action):
        intervals.pop("CHECK", None)

    plant["_care"] = care
    plant["_intervals"] = intervals
    plant["_days_since"] = days_by_action
    return plant


def prompt_view(plant):
    """What Gemini sees: no private keys, and only actions that apply."""
    view = {
        "name": plant["name"],
        "environment": plant["environment"],
        "days_since_action": plant["_days_since"],
        "due_in_days": {a: r["days"] for a, r in plant["_intervals"].items()},
    }
    if plant["fertilizer"]:
        view["fertilizer"] = product_of(plant["fertilizer"])
    if plant["watering"]:
        view["watered_by"] = plant["watering"]
    if plant["notes"]:
        view["notes"] = plant["notes"]
    return view


def due_tasks(plant):
    """Every action currently past its interval, in digest-task shape.

    Used by the dry-run harness to show what the engine considers due before
    Gemini prunes it."""
    tasks = []
    for action, interval in plant["_intervals"].items():
        days = plant["_days_since"].get(action)
        if not _is_due(interval, days):
            continue
        tasks.append({
            "name": plant["name"],
            "action": action,
            "priority": "HIGH" if days is None else "MEDIUM",
            "days_since": days,
            "threshold": interval["days"],
            "base": interval["base"],
            "adjustments": interval["adjustments"],
            "fertilizer": plant["fertilizer"],
        })
    return tasks


class PlantAgent:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def get_tasks(self, weather, inventory_df, care_history=None):
        """Returns (tasks, summary). Each task carries the days-since, the
        computed threshold, the base it came from and the labelled adjustments
        that moved it, so the digest can render them without re-deriving."""
        print("🌱 Building plant context with care guidelines...")

        climate = derive_climate(weather)
        inventory = [build_plant_context(row, care_history, climate)
                     for _, row in inventory_df.iterrows()]
        by_name = {p["name"]: p for p in inventory}

        prompt = f"""Analyze this plant inventory and recommend care actions.

## Local conditions
{json.dumps({k: v for k, v in climate.items() if v is not None}, indent=2)}

## Plant Inventory
`days_since_action` is how many days ago each action was last performed
(null = never). `due_in_days` is how many days should pass before that action
is worth doing again -- already adjusted for weather, season and how the plant
is watered.

{json.dumps([prompt_view(p) for p in inventory], indent=2)}

## Instructions
1. Recommend an action only when its days_since_action has reached or passed
   its due_in_days, or is null (never done).
2. Never recommend an action that is absent from that plant's due_in_days --
   it does not apply to that plant.
3. Among the genuinely due actions, use judgement about what matters today.
   Skip anything marginal.
4. Assign priority by urgency: how far past due, and how much the plant suffers
   if it waits.

## Output Format
Return valid JSON:
{{
  "tasks": [
    {{
      "name": "PlantName",
      "action": "ACTION_TYPE",
      "priority": "HIGH|MEDIUM|LOW",
      "reason": "Brief explanation"
    }}
  ],
  "summary": "One-line overall assessment"
}}

If no actions are needed, return {{"tasks": [], "summary": "All plants look healthy!"}}.
"""

        try:
            response = self.client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    system_instruction=SYSTEM_PROMPT
                )
            )
            result = json.loads(response.text)
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return [], ""

        return self._filter(result.get('tasks', []), by_name), result.get('summary', '')

    def _filter(self, tasks, by_name):
        """Enforce the same intervals the prompt showed the model."""
        kept = []
        for task in tasks:
            action = (task.get('action') or '').upper()
            plant = by_name.get(task.get('name'))

            if plant is None:
                print(f"   ⏭️ Dropped {action} for unknown plant {task.get('name')!r}")
                continue

            interval = plant["_intervals"].get(action)
            if interval is None:
                print(f"   ⏭️ Dropped {action} for {plant['name']} (does not apply)")
                continue

            days = plant["_days_since"].get(action)
            if not _is_due(interval, days):
                print(f"   ⏭️ Filtered {action} for {plant['name']} "
                      f"({days}d, due at {interval['days']}d)")
                continue

            task['days_since'] = days
            task['threshold'] = interval["days"]
            task['base'] = interval["base"]
            task['adjustments'] = interval["adjustments"]
            task['fertilizer'] = plant["fertilizer"]
            kept.append(task)

        return kept
