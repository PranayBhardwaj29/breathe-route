"""
AQI Service for Breathe Route.
Fetches real, live air quality monitoring data for Delhi.

Priority Order:
1. OpenAQ v3 API (if OPENAQ_API_KEY is configured in .env)
2. WAQI API (if WAQI_API_TOKEN is configured in .env)
3. Open-Meteo Live Air Quality (No key needed, live CAMS/Copernicus PM2.5 model grid across Delhi)
4. Local cached snapshot (mock/mock_aqi_delhi.json) if completely offline
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from services.http_client import http_get

CACHE_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "mock", "mock_aqi_delhi.json")

DELHI_MONITORING_POINTS = [
    {"name": "Central Delhi (Connaught Place / Mandir Marg)", "lat": 28.6328, "lng": 77.2197},
    {"name": "South Delhi (R K Puram / Siri Fort)", "lat": 28.5660, "lng": 77.1767},
    {"name": "North Delhi (Civil Lines / Delhi University)", "lat": 28.6940, "lng": 77.2100},
    {"name": "East Delhi (Anand Vihar / Patparganj)", "lat": 28.6469, "lng": 77.3160},
    {"name": "West Delhi (Punjabi Bagh / Janakpuri)", "lat": 28.6700, "lng": 77.1260},
    {"name": "South-West (IGI Airport / Dwarka)", "lat": 28.5562, "lng": 77.0999},
    {"name": "North-West (Rohini / Pitampura)", "lat": 28.7100, "lng": 77.1180},
    {"name": "South-East (Okhla / Nehru Nagar)", "lat": 28.5300, "lng": 77.2700}
]

def load_local_env():
    """Lightweight .env loader without external dependencies."""
    env_file = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() not in os.environ:
                            os.environ[k.strip()] = v.strip()
        except Exception:
            pass

load_local_env()

def _save_cache(stations: List[Dict[str, Any]], source: str):
    """Saves live readings to mock/mock_aqi_delhi.json for offline fallback."""
    try:
        cache_data = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "stations": stations
        }
        os.makedirs(os.path.dirname(os.path.abspath(CACHE_FILE_PATH)), exist_ok=True)
        with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"[aqi_service] Cache save error: {e}")

def _load_cache() -> Dict[str, Any]:
    """Loads cached snapshot if live APIs are unavailable."""
    if os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "stations": data.get("stations", []),
                    "updated_at": data.get("cached_at", ""),
                    "data_status": f"cached, {data.get('cached_at', 'unknown')}",
                    "source": f"Cached ({data.get('source', 'local')})"
                }
        except Exception as e:
            print(f"[aqi_service] Cache load error: {e}")
    return {"stations": [], "updated_at": "", "data_status": "unavailable", "source": "None"}

def fetch_openaq_stations(api_key: str, timeout: int = 6) -> Optional[List[Dict[str, Any]]]:
    """Fetches live Delhi stations from OpenAQ v3 API."""
    url = "https://api.openaq.org/v3/locations"
    headers = {"X-API-Key": api_key}
    params = {
        "bbox": "76.8,28.4,77.5,28.9",
        "limit": "40"
    }
    try:
        resp = http_get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            stations = []
            for loc in results:
                coords = loc.get("coordinates", {})
                lat = coords.get("latitude")
                lng = coords.get("longitude")
                name = loc.get("name", "OpenAQ Station")
                
                sensors = loc.get("sensors", [])
                pm25_sensor = next((s for s in sensors if s.get("parameter", {}).get("name") == "pm25"), None)
                pm25_val = None
                updated_at = loc.get("datetimeLast", {}).get("utc") or datetime.now(timezone.utc).isoformat()
                
                if pm25_sensor:
                    summary = pm25_sensor.get("summary", {})
                    pm25_val = summary.get("last", {}).get("value")
                
                if lat and lng and pm25_val is not None:
                    stations.append({
                        "name": name,
                        "lat": float(lat),
                        "lng": float(lng),
                        "pm25": float(pm25_val),
                        "updated_at": updated_at,
                        "source": "OpenAQ v3"
                    })
            if stations:
                return stations
    except Exception as exc:
        print(f"[aqi_service] OpenAQ v3 fetch error: {exc}")
    return None

def fetch_waqi_stations(token: str, timeout: int = 6) -> Optional[List[Dict[str, Any]]]:
    """Fetches live Delhi stations from WAQI bounding box API."""
    url = f"https://api.waqi.info/map/bounds/?latlng=28.3,76.8,28.9,77.4&token={token}"
    try:
        resp = http_get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                items = data.get("data", [])
                stations = []
                for item in items:
                    aqi_str = item.get("aqi")
                    if aqi_str and aqi_str != "-":
                        try:
                            aqi_val = float(aqi_str)
                            stations.append({
                                "name": item.get("station", {}).get("name", "WAQI Station"),
                                "lat": float(item.get("lat")),
                                "lng": float(item.get("lon")),
                                "pm25": aqi_val,
                                "updated_at": item.get("station", {}).get("time", datetime.now(timezone.utc).isoformat()),
                                "source": "WAQI"
                            })
                        except ValueError:
                            continue
                if stations:
                    return stations
    except Exception as exc:
        print(f"[aqi_service] WAQI fetch error: {exc}")
    return None

def fetch_open_meteo_aqi(timeout: int = 6) -> Optional[List[Dict[str, Any]]]:
    """
    Fetches live real-time PM2.5 across Delhi monitoring points from Open-Meteo Air Quality API.
    Zero API key required; verified real-time Copernicus European Earth Observation data.
    """
    lats = ",".join(str(p["lat"]) for p in DELHI_MONITORING_POINTS)
    lngs = ",".join(str(p["lng"]) for p in DELHI_MONITORING_POINTS)
    url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lats}&longitude={lngs}&current=pm2_5,pm10&timezone=Asia/Kolkata"
    
    try:
        resp = http_get(url, timeout=timeout)
        if resp.status_code == 200:
            res_list = resp.json()
            if isinstance(res_list, dict):
                res_list = [res_list]
            
            stations = []
            for i, item in enumerate(res_list):
                current = item.get("current", {})
                pm25 = current.get("pm2_5")
                time_str = current.get("time", datetime.now(timezone.utc).isoformat())
                station_name = DELHI_MONITORING_POINTS[i]["name"] if i < len(DELHI_MONITORING_POINTS) else f"Delhi Grid {i}"
                if pm25 is not None:
                    stations.append({
                        "name": station_name,
                        "lat": float(item.get("latitude")),
                        "lng": float(item.get("longitude")),
                        "pm25": round(float(pm25), 1),
                        "updated_at": time_str,
                        "source": "Open-Meteo Air Quality (Live Copernicus)"
                    })
            if stations:
                return stations
    except Exception as exc:
        print(f"[aqi_service] Open-Meteo AQI fetch error: {exc}")
    return None

def get_delhi_aqi() -> Dict[str, Any]:
    """Main entrypoint: retrieves real, verified Delhi AQI stations."""
    openaq_key = os.getenv("OPENAQ_API_KEY", "").strip()
    waqi_token = os.getenv("WAQI_API_TOKEN", "").strip()
    
    if openaq_key:
        stations = fetch_openaq_stations(openaq_key)
        if stations:
            _save_cache(stations, "OpenAQ v3")
            return {
                "stations": stations,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "data_status": "live",
                "source": "OpenAQ v3"
            }
            
    if waqi_token:
        stations = fetch_waqi_stations(waqi_token)
        if stations:
            _save_cache(stations, "WAQI")
            return {
                "stations": stations,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "data_status": "live",
                "source": "WAQI"
            }

    stations = fetch_open_meteo_aqi()
    if stations:
        _save_cache(stations, "Open-Meteo Copernicus")
        return {
            "stations": stations,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "data_status": "live",
            "source": "Open-Meteo Air Quality (Live)"
        }

    return _load_cache()
