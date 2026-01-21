import json
from google import genai
from google.genai import types
from src.config import GEMINI_API_KEY, MODEL_ID

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

SYSTEM_PROMPT = """You are an expert botanist and plant care advisor. You have deep knowledge of:
- Tropical houseplants, succulents, cacti, herbs, and common garden plants
- Light requirements (direct sun, bright indirect, low light, shade)
- Watering needs based on season, temperature, humidity, and plant type
- Fertilization schedules (growing season vs dormancy)
- Common problems (overwatering, leggy growth, pests, root rot)
- Environmental adjustments (humidity, temperature, placement)

Your goal is to analyze a plant inventory along with weather, environmental context, and recent care history, then recommend specific care actions. Be practical and prioritize by urgency. Avoid recommending actions that were recently performed."""


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
        
        # Build inventory with all available context
        inventory = []
        for _, row in inventory_df.iterrows():
            plant_name = row.get('Name', 'Unknown')
            plant = {
                "name": plant_name,
                "environment": row.get('Environment', ''),
                "last_watered": row.get('Last Watered', ''),
                "last_fertilized": row.get('Last Fertilized', ''),
                "notes": row.get('Notes', ''),
            }
            # Include additional environmental fields if present
            if 'Light' in row:
                plant['light'] = row['Light']
            if 'Humidity' in row:
                plant['humidity'] = row['Humidity']
            
            # Include recent care history for this plant
            if care_history and plant_name in care_history:
                plant['recent_care'] = care_history[plant_name]
            
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

        prompt = f"""Analyze this plant inventory and recommend care actions.

## Weather Context
{weather_context}

## Plant Inventory (with recent care history)
{json.dumps(inventory, indent=2)}

## Available Actions
{', '.join(CARE_ACTIONS)}

## Instructions
1. Analyze each plant considering:
   - Days since last watered/fertilized
   - Recent care history (avoid repeating recent actions)
   - Current weather (skip watering if rainy)
   - Environment (indoor vs outdoor)
   - Light exposure (is the plant getting appropriate light?)
   - Season (growing season vs dormancy affects fertilizing)
   
2. Only recommend actions that are actually needed TODAY.
3. Do NOT recommend actions that were recently performed (check recent_care).
4. Assign priority: HIGH (urgent), MEDIUM (within 1-2 days), LOW (when convenient)
5. Provide a concise but helpful reason for each recommendation.

## Output Format
Return valid JSON:
{{
  "tasks": [
    {{
      "name": "PlantName",
      "action": "ACTION_TYPE",
      "priority": "HIGH|MEDIUM|LOW", 
      "reason": "Brief explanation of why this action is needed"
    }}
  ],
  "summary": "One-line overall assessment of garden health"
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
            return result.get('tasks', []), result.get('summary', '')
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return [], ""