import json
from datetime import datetime
from google import genai
from google.genai import types
from src.config import GEMINI_API_KEY, MODEL_ID
from src.plant_api import get_care_guidelines

# Predefined action types for consistency
CARE_ACTIONS = [
    "WATER",      # Water the plant
    "FERTILIZE",  # Apply fertilizer
    "MIST",       # Mist leaves for humidity
    "ROTATE",     # Rotate for even growth
    "MOVE",       # Relocate (light/temp issues)
    "PRUNE",      # Remove dead/leggy growth
    "REPOT",      # Needs larger container
    "CHECK",      # General inspection needed
]

# Minimum days before recommending each action again (safety nets)
MIN_ACTION_INTERVALS = {
    "WATER": 3,       # Never recommend if watered < 3 days ago
    "FERTILIZE": 14,  # Every 2+ weeks during growing season
    "MIST": 2,        # Can mist every few days
    "ROTATE": 7,      # Weekly rotation is enough
    "MOVE": 14,       # Don't suggest moving plants frequently
    "PRUNE": 30,      # Monthly at most
    "REPOT": 180,     # Every 6 months minimum
    "CHECK": 3,       # General check every few days is fine
}

SYSTEM_PROMPT = """You are an expert botanist and plant care advisor. You have deep knowledge of:
- Tropical houseplants, succulents, cacti, herbs, and common garden plants
- Light requirements (direct sun, bright indirect, low light, shade)
- Watering needs based on season, temperature, humidity, and plant type
- Fertilization schedules (growing season vs dormancy)
- Common problems (overwatering, leggy growth, pests, root rot)
- Environmental adjustments (humidity, temperature, placement)

Your goal is to analyze a plant inventory with calculated days_since_action for ALL action types. BE CONSERVATIVE - only recommend actions when sufficient time has passed since the last occurrence. The days_since_action field shows exactly how many days ago each action was performed (null means never)."""


def days_since(date_str: str) -> int | None:
    """Calculate days since a date string (YYYY-MM-DD format)."""
    if not date_str or date_str == 'N/A':
        return None
    try:
        past = datetime.strptime(str(date_str), '%Y-%m-%d')
        return (datetime.now() - past).days
    except ValueError:
        return None


class PlantAgent:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def get_tasks(self, weather, inventory_df, care_history=None):
        """Returns a list of care tasks with priorities and detailed reasoning.
        
        Args:
            weather: Weather data dict from Open-Meteo
            inventory_df: DataFrame of plant inventory
            care_history: Optional dict of {plant_name: [{Date, Action}, ...]}
        """
        
        print("🌱 Building plant context with care guidelines...")
        
        # Build inventory with all available context
        inventory = []
        for _, row in inventory_df.iterrows():
            plant_name = row.get('Name', 'Unknown')
            
            # Calculate days since last care actions from sheet columns
            days_water = days_since(row.get('Last Watered', ''))
            days_fert = days_since(row.get('Last Fertilized', ''))
            
            # Calculate days since ALL action types from CareHistory
            days_since_action = {
                "WATER": days_water,
                "FERTILIZE": days_fert,
            }
            
            # Check CareHistory for other actions
            if care_history and plant_name in care_history:
                plant_history = care_history[plant_name]
                for action in ['MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
                    # Find most recent occurrence of this action
                    for record in plant_history:
                        if record.get('Action') == action:
                            days = days_since(record.get('Date', ''))
                            if days is not None:
                                days_since_action[action] = days
                                break
            
            # Get plant-specific care guidelines from API
            care = get_care_guidelines(plant_name)
            
            plant = {
                "name": plant_name,
                "environment": row.get('Environment', ''),
                "days_since_action": days_since_action,
                "watering_guidelines": {
                    "min_days": care["min_watering_days"],
                    "max_days": care["max_watering_days"],
                    "frequency": care["watering"],
                },
                "notes": row.get('Notes', ''),
            }
            
            # Include additional environmental fields if present
            if 'Light' in row:
                plant['light'] = row['Light']
            if 'Humidity' in row:
                plant['humidity'] = row['Humidity']
            
            inventory.append(plant)

        # Build weather context
        weather_context = "Unknown"
        if weather:
            temps = weather.get('temperature_2m_max', [])
            precip = weather.get('precipitation_sum', [])
            weather_context = f"""
            - Recent temperatures (past 3 days + today): {temps}
            - Recent precipitation (mm): {precip}
            - Today's max temp: {temps[-1] if temps else 'N/A'}°C
            - Today's rain: {precip[-1] if precip else 0}mm
            """

        # Format minimum intervals for prompt
        intervals_str = ", ".join([f"{k}: {v}d" for k, v in MIN_ACTION_INTERVALS.items()])

        prompt = f"""Analyze this plant inventory and recommend care actions.

## Weather Context
{weather_context}

## Plant Inventory
Each plant has days_since_action showing days since each action type was performed (null = never done).
{json.dumps(inventory, indent=2)}

## Available Actions & Minimum Intervals
{intervals_str}

## CRITICAL Instructions
1. Check days_since_action for EACH action type before recommending:
   - WATER: Only if days_since >= max_days in watering_guidelines
   - FERTILIZE: Only during growing season AND if days_since >= 14
   - MIST: Only if days_since >= 2
   - ROTATE: Only if days_since >= 7
   - CHECK: Only if days_since >= 3
   - PRUNE/REPOT: Only if clearly needed AND sufficient time has passed

2. Consider weather (skip watering outdoor plants if it rained)

3. For null values: action has never been done, may be needed

4. Assign priority based on urgency

5. Skip plants that were recently cared for.

## Output Format
Return valid JSON:
{{
  "tasks": [
    {{
      "name": "PlantName",
      "action": "ACTION_TYPE",
      "priority": "HIGH|MEDIUM|LOW", 
      "reason": "Brief explanation including days since last action"
    }}
  ],
  "summary": "One-line overall assessment"
}}

If no actions needed, return {{"tasks": [], "summary": "All plants look healthy!"}}.
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
            tasks = result.get('tasks', [])
            
            # Post-process: Filter out actions that are too soon based on MIN_ACTION_INTERVALS
            filtered_tasks = []
            for task in tasks:
                action = task.get('action', '').upper()
                plant_name = task.get('name')
                
                # Check minimum interval for this action
                min_interval = MIN_ACTION_INTERVALS.get(action, 0)
                plant_data = next((p for p in inventory if p['name'] == plant_name), None)
                
                if plant_data and min_interval > 0:
                    days = plant_data.get('days_since_action', {}).get(action)
                    if days is not None and days < min_interval:
                        print(f"   ⏭️ Filtered {action} for {plant_name} (only {days} days, min={min_interval})")
                        continue
                
                filtered_tasks.append(task)
            
            return filtered_tasks, result.get('summary', '')
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return [], ""