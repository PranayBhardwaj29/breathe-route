"""
Route Planner Coordinator for Breathe Route.
Combines routing, live AQI stations, weather data, IDW exposure scoring,
best time to leave forecast analysis, and source likelihood estimation.
Produces the finalized JSON response strictly matching the API contract.
"""

from datetime import datetime
from typing import Dict, Any, List
from services.weather_service import fetch_weather
from services.aqi_service import get_delhi_aqi
from services.router_service import get_cycling_routes
from services.exposure import compute_route_exposure
from services.forecast_service import analyze_best_departure_time, estimate_source_likelihood

LIMITATIONS_NOTICE = (
    "Exposure score is an inverse-distance weighted (IDW) estimate from live monitoring stations "
    "sampled every ~200m. It is not an in-situ physical sensor measurement. Sparse station coverage "
    "and hyper-local vehicle exhaust at intersections are not fully captured."
)

def plan_routes(start: Dict[str, float], end: Dict[str, float], mode: str = "cycling") -> Dict[str, Any]:
    """
    Main route evaluation logic.
    start: {"lat": float, "lng": float}
    end: {"lat": float, "lng": float}
    """
    # 1. Fetch live or cached Delhi AQI
    aqi_data = get_delhi_aqi()
    stations = aqi_data.get("stations", [])
    data_status = aqi_data.get("data_status", "live")
    aqi_updated_at = aqi_data.get("updated_at", "")
    
    # 2. Fetch live weather (center point between start & end)
    mid_lat = (start["lat"] + end["lat"]) / 2.0
    mid_lng = (start["lng"] + end["lng"]) / 2.0
    weather_info = fetch_weather(lat=mid_lat, lng=mid_lng) or {}
    
    # 3. Fetch 2-3 cycling routes
    raw_routes = get_cycling_routes(start, end)
    
    if not raw_routes:
        return {
            "error": "No cycling routes found between the specified coordinates.",
            "routes": [],
            "recommended_id": None,
            "trade_off": "N/A",
            "weather": {
                "wind_speed": weather_info.get("wind_speed_kmh", 0),
                "wind_dir": weather_info.get("wind_dir_deg", 0)
            },
            "aqi_updated_at": aqi_updated_at,
            "data_status": data_status,
            "limitations": LIMITATIONS_NOTICE
        }
        
    # 4. Compute exposure score for each route
    scored_routes = [
        compute_route_exposure(r, stations)
        for r in raw_routes
    ]
    
    # 5. Determine recommended route (cleanest = lowest exposure score)
    cleanest_route = min(scored_routes, key=lambda r: r["exposure_score"])
    fastest_route = min(scored_routes, key=lambda r: r["duration_s"])
    
    recommended_id = cleanest_route["id"]
    
    # 6. Calculate trade-off compared to the fastest route
    if cleanest_route["id"] == fastest_route["id"]:
        trade_off = "Cleanest and fastest route!"
    else:
        extra_sec = cleanest_route["duration_s"] - fastest_route["duration_s"]
        extra_min = max(1, round(extra_sec / 60.0))
        
        exposure_diff = fastest_route["exposure_score"] - cleanest_route["exposure_score"]
        if fastest_route["exposure_score"] > 0:
            pct_saved = round((exposure_diff / fastest_route["exposure_score"]) * 100)
        else:
            pct_saved = 0
            
        trade_off = f"+{extra_min} min, {pct_saved}% less exposure"

    # 7. Stage 5: Best Time to Leave Forecast & Source Likelihood Analysis
    departure_forecast = analyze_best_departure_time(
        lat=mid_lat,
        lng=mid_lng,
        current_pm25=cleanest_route["exposure_score"]
    )

    current_hour_ist = datetime.now().hour
    source_likelihood = estimate_source_likelihood(
        hour_ist=current_hour_ist,
        wind_speed_kmh=weather_info.get("wind_speed_kmh", 7.0),
        wind_dir_deg=weather_info.get("wind_dir_deg", 90.0),
        pm25_val=cleanest_route["exposure_score"]
    )
        
    # Build clean response adhering strictly to the contract
    clean_routes_output = [
        {
            "id": r["id"],
            "distance_m": r["distance_m"],
            "duration_s": r["duration_s"],
            "avg_aqi": r["avg_aqi"],
            "exposure_score": r["exposure_score"],
            "geometry": r["geometry"]
        }
        for r in scored_routes
    ]
    
    return {
        "routes": clean_routes_output,
        "recommended_id": recommended_id,
        "trade_off": trade_off,
        "weather": {
            "wind_speed": weather_info.get("wind_speed_kmh", 0),
            "wind_dir": weather_info.get("wind_dir_deg", 0)
        },
        "aqi_updated_at": aqi_updated_at,
        "data_status": data_status,
        "departure_forecast": departure_forecast,
        "source_likelihood": source_likelihood,
        "limitations": LIMITATIONS_NOTICE
    }
