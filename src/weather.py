import requests
from src.config import LATITUDE, LONGITUDE

def get_forecast():
    """Fetches past 3 days and today's forecast."""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}"
           f"&daily=temperature_2m_max,precipitation_sum&past_days=3&forecast_days=1&timezone=auto")
    try:
        response = requests.get(url).json()
        return response.get('daily')
    except Exception as e:
        print(f"⚠️ Weather API Error: {e}")
        return None