import json
from google import genai
from google.genai import types
from src.config import GEMINI_API_KEY, MODEL_ID

class PlantAgent:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def get_tasks(self, weather, inventory_df):
        """Returns a list of tasks (Water AND/OR Fertilize)."""
        
        inventory = []
        for _, row in inventory_df.iterrows():
            inventory.append({
                "name": row['Name'],
                "type": row['Type'],
                "last_water": row['Last Watered'],
                "last_fert": row['Last Fertilized'],
                "notes": row['Notes']
            })

        prompt = f"""
        ROLE: Expert Botanist Agent.
        
        CONTEXT:
        Weather: Max {weather['temperature_2m_max']}, Rain {weather['precipitation_sum']}
        INVENTORY: {json.dumps(inventory)}
        
        INSTRUCTIONS:
        Analyze each plant. Determine if it needs:
        1. WATER (Based on weather/last_water)
        2. FERTILIZE (Based on season/last_fert. Usually every 2-4 weeks in growing season, never in winter).
        
        OUTPUT JSON:
        {{ 
          "tasks": [ 
            {{ "name": "PlantName", "action": "WATER", "reason": "..." }},
            {{ "name": "PlantName", "action": "FERTILIZE", "reason": "..." }},
            {{ "name": "PlantName", "action": "BOTH", "reason": "..." }}
          ] 
        }}
        """

        try:
            response = self.client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type='application/json')
            )
            return json.loads(response.text).get('tasks', [])
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return []