"""
Perenual Plant API integration for plant-specific care guidelines.
https://perenual.com/docs/api

Includes file-based caching to avoid rate limits.
"""
import json
import requests
import time
from pathlib import Path
from google import genai
from google.genai import types
from src.config import PERENUAL_API_KEY, GEMINI_API_KEY, MODEL_ID

BASE_URL = "https://perenual.com/api/v2"
CACHE_FILE = Path(__file__).parent.parent / "data" / "plant_cache.json"

# Default watering guidelines if both API and AI fail
DEFAULT_CARE = {
    "watering": "Average",
    "watering_period": "weekly",
    "min_watering_days": 5,
    "max_watering_days": 10,
    "sunlight": ["Indirect"],
}

# In-memory cache (loaded from file on startup)
_cache = {}
_cache_loaded = False

# Circuit breaker flag to skip API calls after a 429 error in the current session
_circuit_broken = False

# Initialize Gemini Client for fallback lookups
_ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def _load_cache():
    """Load cache from disk (once per session)."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True
    
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r') as f:
                _cache = json.load(f)
            if _cache:
                print(f"📂 Loaded {len(_cache)} plants from cache")
        except Exception as e:
            print(f"⚠️ Cache load error: {e}")
            _cache = {}


def _save_cache():
    """Save cache to disk."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(_cache, f, indent=2)
    except Exception as e:
        print(f"⚠️ Cache save error: {e}")


def _get_gemini_care(plant_name: str) -> dict | None:
    """Use Gemini to fetch plant care data when API is restricted."""
    if not _ai_client:
        return None
        
    prompt = f"""Provide scientific plant care guidelines for '{plant_name}'.
    Return ONLY valid JSON in this exact format:
    {{
      "watering": "Frequent|Average|Minimum",
      "watering_period": "brief description like 7-10 days",
      "min_watering_days": integer,
      "max_watering_days": integer,
      "sunlight": ["List", "of", "light", "needs"],
      "common_name": "Standard Common Name"
    }}
    Rules: 
    - Frequent: 2-4 days
    - Average: 5-10 days
    - Minimum: 14-21 days
    - Sunlight should be a list like ["Full sun", "Part shade"]
    """
    
    try:
        response = _ai_client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
        )
        # Manually extract JSON from response text as grounding doesn't support mime_type='application/json'
        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        return json.loads(text)
    except Exception as e:
        print(f"⚠️ Gemini fallback error for '{plant_name}': {e}")
        return None


def search_plant(name: str) -> dict | None:
    """Search for a plant by name and return first match."""
    global _circuit_broken
    if not PERENUAL_API_KEY or _circuit_broken:
        return None
    
    # Sequential delay to avoid burst limits
    time.sleep(1.5)
    
    try:
        url = f"{BASE_URL}/species-list"
        params = {"key": PERENUAL_API_KEY, "q": name}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 429:
            # Differentiate between real rate limit and plan block
            if "Please Upgrade" in response.text:
                print(f"   ⚠️ Perenual search for '{name}' is Tier-Locked.")
                return None
            else:
                print("🛑 Perenual API Rate Limit hit. Circuit breaker active.")
                _circuit_broken = True
                return None
            
        response.raise_for_status()
        data = response.json()
        
        if data.get("data"):
            return data["data"][0]
        return None
    except Exception as e:
        print(f"⚠️ Perenual search error: {e}")
        return None


def get_plant_details(plant_id: int) -> dict | None:
    """Get detailed care info for a specific plant ID."""
    global _circuit_broken
    if not PERENUAL_API_KEY or _circuit_broken:
        return None
    
    # Sequential delay to avoid burst limits
    time.sleep(1.5)
    
    try:
        url = f"{BASE_URL}/species/details/{plant_id}"
        params = {"key": PERENUAL_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 429:
            # Differentiate between real rate limit and plan block
            if "Please Upgrade" in response.text:
                print(f"   ⚠️ Perenual details for ID {plant_id} are Tier-Locked.")
                return None
            else:
                print("🛑 Perenual API Rate Limit hit. Circuit breaker active.")
                _circuit_broken = True
                return None
            
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️ Perenual details error: {e}")
        return None


def get_care_guidelines(plant_name: str) -> dict:
    """
    Get care guidelines for a plant by name.
    Uses Perenual API with Gemini fallback and file-based cache.
    """
    # Load cache from disk on first call
    _load_cache()
    
    cache_key = plant_name.lower().strip()
    
    # Check cache first
    if cache_key in _cache:
        cached = _cache[cache_key]
        source = cached.get("_source", "cache")
        print(f"   📖 {plant_name}: water every {cached['min_watering_days']}-{cached['max_watering_days']} days ({source})")
        return cached
    
    # Not in cache - try Perenual API first
    result = search_plant(cache_key) if not _circuit_broken else None
    details = None
    
    if result:
        plant_id = result.get("id")
        details = get_plant_details(plant_id) if plant_id else None
    
    if details:
        # Success from Perenual
        watering = details.get("watering", "Average")
        watering_period = details.get("watering_general_benchmark", {})
        
        watering_map = {
            "Frequent": {"min": 2, "max": 4},
            "Average": {"min": 5, "max": 10},
            "Minimum": {"min": 14, "max": 21},
            "None": {"min": 30, "max": 60},
        }
        days = watering_map.get(watering, {"min": 5, "max": 10})
        
        care = {
            "watering": watering,
            "watering_period": watering_period.get("value", "weekly") if isinstance(watering_period, dict) else "weekly",
            "min_watering_days": days["min"],
            "max_watering_days": days["max"],
            "sunlight": details.get("sunlight", ["Indirect"]),
            "common_name": details.get("common_name", plant_name),
            "_source": "Perenual API"
        }
    else:
        # Fallback to Gemini AI
        print(f"   ✨ Researching '{plant_name}' using Gemini AI (Grounded)...")
        care = _get_gemini_care(plant_name)
        if care:
            care["_source"] = "Gemini AI (Grounded)"
        else:
            # Absolute fallback
            care = DEFAULT_CARE.copy()
            care["_source"] = "Default"
    
    # Cache and save
    _cache[cache_key] = care
    _save_cache()
    
    print(f"   📖 {plant_name}: water every {care['min_watering_days']}-{care['max_watering_days']} days ({care['_source']}) [saved to cache]")
    return care



