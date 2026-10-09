"""
Weather Service using Open-Meteo API (No API key required).
Provides live wind speed, wind direction, and temperature for coordinates in Delhi.
"""
from typing import Dict, Any, Optional
from services.http_client import http_get

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

def fetch_weather(lat: float = 28.6139, lng: float = 77.2090, timeout: int = 6) -> Optional[Dict[str, Any]]:
    """
    Fetches live weather (wind speed, wind direction, temperature) from Open-Meteo.
    Default coordinates: Central Delhi (Connaught Place: 28.6139 N, 77.2090 E).
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
        "timezone": "Asia/Kolkata"
    }
    
    try:
        resp = http_get(OPEN_METEO_URL, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            current = data.get("current", {})
            return {
                "source": "Open-Meteo",
                "timestamp": current.get("time"),
                "temperature_c": current.get("temperature_2m"),
                "humidity_percent": current.get("relative_humidity_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_dir_deg": current.get("wind_direction_10m"),
                "status": "live"
            }
        else:
            print(f"[weather_service] Open-Meteo returned status {resp.status_code}")
    except Exception as exc:
        print(f"[weather_service] Warning: Failed to fetch weather from Open-Meteo: {exc}")
    return None
