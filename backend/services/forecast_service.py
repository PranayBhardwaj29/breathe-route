"""
Forecast & Source Likelihood Service for Breathe Route.

1. Best Time to Leave: Fetches real 24-48h hourly PM2.5 forecast from Open-Meteo Air Quality.
   Finds the lowest exposure departure window and computes the exposure reduction percentage.
2. Source Likelihood: Empirical source apportionment based on time-of-day, wind vector,
   and atmospheric dispersion models for Delhi NCR.

Note: All outputs are labeled as model estimates.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from services.http_client import http_get

OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

def fetch_hourly_pm25_forecast(lat: float = 28.6139, lng: float = 77.2090, timeout: int = 6) -> Optional[List[Dict[str, Any]]]:
    """
    Fetches real-time hourly PM2.5 forecast for Delhi from Open-Meteo Copernicus CAMS model.
    Zero API key required.
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": "pm2_5",
        "timezone": "Asia/Kolkata",
        "forecast_days": 2
    }
    try:
        resp = http_get(OPEN_METEO_AIR_QUALITY_URL, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            hourly_raw = data.get("hourly", {})
            times = hourly_raw.get("time", [])
            pm25_vals = hourly_raw.get("pm2_5", [])

            forecast_list = []
            for t_str, val in zip(times, pm25_vals):
                if val is not None:
                    forecast_list.append({
                        "iso_time": t_str,
                        "pm25": round(float(val), 1)
                    })
            return forecast_list
    except Exception as exc:
        print(f"[forecast_service] Forecast fetch error: {exc}")
    return None

def analyze_best_departure_time(lat: float, lng: float, current_pm25: float) -> Dict[str, Any]:
    """
    Analyzes the upcoming 12-hour forecast to find the optimal departure time for cyclists.
    """
    forecast_data = fetch_hourly_pm25_forecast(lat, lng)

    if not forecast_data:
        return {
            "status": "unavailable",
            "message": "Hourly forecast data temporarily unavailable.",
            "hourly_timeline": []
        }

    # Filter to upcoming 12 hours from current local time
    # Open-Meteo ISO format: "2026-10-09T21:00"
    now_hour_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    
    # Find index of current hour
    current_idx = 0
    for i, item in enumerate(forecast_data):
        if item["iso_time"] >= now_hour_str:
            current_idx = i
            break

    upcoming_12h = forecast_data[current_idx : current_idx + 12]
    if not upcoming_12h:
        upcoming_12h = forecast_data[:12]

    # Find the cleanest hour in the upcoming window
    best_entry = min(upcoming_12h, key=lambda x: x["pm25"])
    worst_entry = max(upcoming_12h, key=lambda x: x["pm25"])

    # Calculate percentage reduction compared to current or worst
    baseline = current_pm25 if current_pm25 > 0 else (upcoming_12h[0]["pm25"] if upcoming_12h else 60.0)
    best_val = best_entry["pm25"]
    
    pct_reduction = 0
    if baseline > best_val:
        pct_reduction = round(((baseline - best_val) / baseline) * 100)

    # Format human-readable hour (e.g. "14:00" or "2:00 PM")
    best_hour_raw = best_entry["iso_time"].split("T")[-1] if "T" in best_entry["iso_time"] else best_entry["iso_time"]
    
    timeline_formatted = []
    for entry in upcoming_12h:
        time_part = entry["iso_time"].split("T")[-1]
        timeline_formatted.append({
            "time": time_part,
            "pm25": entry["pm25"]
        })

    is_now_best = (best_entry["iso_time"] == upcoming_12h[0]["iso_time"])

    recommendation_text = (
        "Current conditions are optimal! Best time to cycle is right now."
        if is_now_best else
        f"Postponing departure to {best_hour_raw} can reduce pollution exposure by up to {pct_reduction}%."
    )

    return {
        "status": "available",
        "recommended_departure_time": best_hour_raw,
        "recommended_pm25": best_val,
        "current_baseline_pm25": round(baseline, 1),
        "pct_reduction": pct_reduction,
        "is_now_best": is_now_best,
        "recommendation_text": recommendation_text,
        "hourly_timeline": timeline_formatted,
        "disclaimer": "Forecast estimate derived from Copernicus CAMS model. Actual atmospheric conditions may fluctuate."
    }

def estimate_source_likelihood(hour_ist: int, wind_speed_kmh: float, wind_dir_deg: float, pm25_val: float) -> Dict[str, Any]:
    """
    Estimates probable particulate source contribution for Delhi NCR based on:
    - Diurnal traffic cycle (peak traffic 8-11 AM, 5-9 PM)
    - Wind direction (NW/W = regional stubble/drift, SE/E = industrial/secondary aerosols)
    - Wind speed (low < 6 km/h = local stagnation, moderate > 10 km/h = dust & long-range transport)
    """
    # Baseline source weights for Delhi urban environment
    traffic_weight = 30.0
    dust_weight = 25.0
    regional_weight = 25.0
    waste_burning_weight = 20.0

    # 1. Traffic influence (Rush hours)
    if (8 <= hour_ist <= 11) or (17 <= hour_ist <= 21):
        traffic_weight += 20.0
        explanation_factor = "Peak vehicular commute with heavy idling and tailpipe exhaust."
    else:
        traffic_weight -= 5.0
        explanation_factor = "Off-peak traffic hours with moderate vehicular activity."

    # 2. Wind direction influence (North-West drift: 270 to 330 deg)
    if 270 <= wind_dir_deg <= 330:
        regional_weight += 15.0
        dust_weight += 5.0
        regional_note = "North-westerly winds transporting upwind regional smoke/biomass drift."
    else:
        regional_note = "Easterly/variable surface winds limiting trans-boundary agricultural transport."

    # 3. Wind speed influence
    if wind_speed_kmh < 6.0:
        # Stagnant air traps local burning and vehicular emissions
        traffic_weight += 10.0
        waste_burning_weight += 15.0
        dust_weight -= 10.0
        dispersion_note = "Calm winds create surface-level atmospheric stagnation."
    elif wind_speed_kmh > 12.0:
        # High winds kick up loose road dust
        dust_weight += 15.0
        traffic_weight -= 5.0
        dispersion_note = "Moderate winds cause mechanical road dust re-suspension."
    else:
        dispersion_note = "Moderate ventilation facilitating gradual pollutant dispersion."

    # Normalize weights to 100%
    total = traffic_weight + dust_weight + regional_weight + waste_burning_weight
    traffic_pct = round((traffic_weight / total) * 100)
    dust_pct = round((dust_weight / total) * 100)
    regional_pct = round((regional_weight / total) * 100)
    waste_pct = max(0, 100 - (traffic_pct + dust_pct + regional_pct))

    breakdown = [
        {"source": "Vehicular Exhaust & Idling", "percentage": traffic_pct, "color": "#dc2626"},
        {"source": "Road Dust & Re-suspension", "percentage": dust_pct, "color": "#d97706"},
        {"source": "Regional Drift & Biomass Smoke", "percentage": regional_pct, "color": "#7c3aed"},
        {"source": "Local Domestic/Waste Burning", "percentage": waste_pct, "color": "#4b5563"}
    ]

    # Primary source is highest percentage
    primary = max(breakdown, key=lambda x: x["percentage"])

    return {
        "primary_source": primary["source"],
        "confidence": "Medium",
        "breakdown": breakdown,
        "explanation": f"{explanation_factor} {regional_note} {dispersion_note}",
        "disclaimer": "Empirical estimate based on Delhi CPCB diurnal source apportionment profiles."
    }
