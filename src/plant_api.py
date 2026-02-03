"""
Perenual Plant API integration for plant-specific care guidelines.
https://perenual.com/docs/api

Includes file-based caching to avoid rate limits.
"""
import json
import os
import requests
from pathlib import Path
from src.config import PERENUAL_API_KEY

BASE_URL = "https://perenual.com/api/v2"
CACHE_FILE = Path(__file__).parent.parent / "data" / "plant_cache.json"

# Default watering guidelines if API unavailable or plant not found
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


def search_plant(name: str) -> dict | None:
    """Search for a plant by name and return first match."""
    if not PERENUAL_API_KEY:
        return None
    
    try:
        url = f"{BASE_URL}/species-list"
        params = {"key": PERENUAL_API_KEY, "q": name}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("data"):
            return data["data"][0]  # Return first match
        return None
    except Exception as e:
        print(f"⚠️ Perenual search error: {e}")
        return None


def get_plant_details(plant_id: int) -> dict | None:
    """Get detailed care info for a specific plant ID."""
    if not PERENUAL_API_KEY:
        return None
    
    try:
        url = f"{BASE_URL}/species/details/{plant_id}"
        params = {"key": PERENUAL_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️ Perenual details error: {e}")
        return None


def get_care_guidelines(plant_name: str) -> dict:
    """
    Get care guidelines for a plant by name.
    Uses file-based cache to avoid repeated API calls.
    """
    # Load cache from disk on first call
    _load_cache()
    
    cache_key = plant_name.lower().strip()
    
    # Check cache first
    if cache_key in _cache:
        cached = _cache[cache_key]
        print(f"   📖 {plant_name}: water every {cached['min_watering_days']}-{cached['max_watering_days']} days (cached)")
        return cached
    
    # Not in cache - try API
    result = search_plant(cache_key)
    if not result:
        print(f"   📖 No API data for '{plant_name}', using defaults")
        return DEFAULT_CARE
    
    # Get detailed info
    plant_id = result.get("id")
    details = get_plant_details(plant_id) if plant_id else None
    
    if not details:
        return DEFAULT_CARE
    
    # Parse watering info
    watering = details.get("watering", "Average")
    watering_period = details.get("watering_general_benchmark", {})
    
    # Convert watering level to day ranges
    watering_map = {
        "Frequent": {"min": 2, "max": 4},
        "Average": {"min": 5, "max": 10},
        "Minimum": {"min": 14, "max": 21},
        "None": {"min": 30, "max": 60},
    }
    
    days = watering_map.get(watering, {"min": 5, "max": 10})
    
    care = {
        "watering": watering,
        "watering_period": watering_period.get("value", "weekly"),
        "min_watering_days": days["min"],
        "max_watering_days": days["max"],
        "sunlight": details.get("sunlight", ["Indirect"]),
        "common_name": details.get("common_name", plant_name),
    }
    
    # Cache the result
    _cache[cache_key] = care
    _save_cache()
    
    print(f"   📖 {plant_name}: water every {days['min']}-{days['max']} days ({watering}) [saved to cache]")
    return care
