"""
Router Service for Breathe Route.
Fetches 2-3 alternative cycling routes between two coordinates.

Supports:
1. OpenRouteService (/v2/directions/cycling-regular/geojson) if ORS_API_KEY is present in .env
2. OSRM Bike Router (public, no key required) with automatic waypoint offsetting
   to guarantee 2-3 distinct cycling routes for comparison.
"""

import os
import math
from typing import List, Dict, Any, Tuple
from services.http_client import http_get, http_post

def fetch_ors_routes(start: Dict[str, float], end: Dict[str, float], api_key: str, timeout: int = 8) -> List[Dict[str, Any]]:
    """Fetches cycling routes with alternatives from OpenRouteService."""
    url = "https://api.openrouteservice.org/v2/directions/cycling-regular/geojson"
    headers = {
        "Authorization": api_key,
        "Accept": "application/json, application/geo+json"
    }
    payload = {
        "coordinates": [
            [start["lng"], start["lat"]],
            [end["lng"], end["lat"]]
        ],
        "alternative_routes": {
            "target_count": 3,
            "weight_factor": 1.4,
            "share_factor": 0.6
        }
    }
    
    try:
        resp = http_post(url, json_data=payload, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("features", [])
            routes = []
            for i, feat in enumerate(features):
                props = feat.get("properties", {}).get("summary", {})
                coords = feat.get("geometry", {}).get("coordinates", [])
                lat_lng_coords = [[pt[1], pt[0]] for pt in coords]
                routes.append({
                    "id": f"r{i+1}",
                    "distance_m": round(props.get("distance", 0)),
                    "duration_s": round(props.get("duration", 0)),
                    "geometry": lat_lng_coords,
                    "provider": "OpenRouteService"
                })
            if len(routes) >= 2:
                return routes
    except Exception as exc:
        print(f"[router_service] ORS fetch error: {exc}")
    return []

def _query_osrm_single(coords_list: List[Tuple[float, float]], timeout: int = 6) -> Dict[str, Any]:
    """Helper to query OSRM for a specific sequence of (lat, lng) waypoints."""
    coord_str = ";".join(f"{pt[1]},{pt[0]}" for pt in coords_list)
    url = f"https://router.project-osrm.org/route/v1/biking/{coord_str}?overview=full&geometries=geojson"
    try:
        resp = http_get(url, timeout=timeout)
        if resp.status_code == 200:
            routes = resp.json().get("routes", [])
            if routes:
                return routes[0]
    except Exception as e:
        print(f"[router_service] OSRM waypoint query error: {e}")
    return {}

def fetch_osrm_routes_with_alternatives(start: Dict[str, float], end: Dict[str, float], timeout: int = 8) -> List[Dict[str, Any]]:
    """
    Fetches cycling routes from OSRM. If OSRM only returns 1 route,
    computes perpendicular via-points (~600m offset) to discover
    parallel street alternatives through Delhi.
    """
    start_pt = (start["lat"], start["lng"])
    end_pt = (end["lat"], end["lng"])
    
    # 1. Direct query with alternatives=true
    direct_url = f"https://router.project-osrm.org/route/v1/biking/{start_pt[1]},{start_pt[0]};{end_pt[1]},{end_pt[0]}?alternatives=true&overview=full&geometries=geojson"
    routes = []
    
    try:
        resp = http_get(direct_url, timeout=timeout)
        if resp.status_code == 200:
            raw_routes = resp.json().get("routes", [])
            for i, r in enumerate(raw_routes):
                coords = [[pt[1], pt[0]] for pt in r.get("geometry", {}).get("coordinates", [])]
                routes.append({
                    "id": f"r{i+1}",
                    "distance_m": round(r.get("distance", 0)),
                    "duration_s": round(r.get("duration", 0)),
                    "geometry": coords,
                    "provider": "OSRM Biking"
                })
    except Exception as e:
        print(f"[router_service] Direct OSRM error: {e}")

    # 2. If fewer than 2 routes, generate via-points perpendicular to the direct vector
    if len(routes) < 2:
        mid_lat = (start_pt[0] + end_pt[0]) / 2.0
        mid_lng = (start_pt[1] + end_pt[1]) / 2.0
        d_lat = end_pt[0] - start_pt[0]
        d_lng = end_pt[1] - start_pt[1]
        length = math.sqrt(d_lat**2 + d_lng**2)
        
        if length > 0:
            scale = 0.0055
            perp1 = (mid_lat - (d_lng / length) * scale, mid_lng + (d_lat / length) * scale)
            perp2 = (mid_lat + (d_lng / length) * scale, mid_lng - (d_lat / length) * scale)
            
            for offset_pt in [perp1, perp2]:
                via_route = _query_osrm_single([start_pt, offset_pt, end_pt], timeout=timeout)
                if via_route:
                    coords = [[pt[1], pt[0]] for pt in via_route.get("geometry", {}).get("coordinates", [])]
                    dist = round(via_route.get("distance", 0))
                    if not any(abs(r["distance_m"] - dist) < 50 for r in routes):
                        routes.append({
                            "id": f"r{len(routes)+1}",
                            "distance_m": dist,
                            "duration_s": round(via_route.get("duration", 0)),
                            "geometry": coords,
                            "provider": "OSRM Biking (Avenue Alternative)"
                        })
                if len(routes) >= 3:
                    break

    for idx, r in enumerate(routes):
        r["id"] = f"r{idx+1}"
        
    return routes

def get_cycling_routes(start: Dict[str, float], end: Dict[str, float]) -> List[Dict[str, Any]]:
    """Main routing function."""
    ors_key = os.getenv("ORS_API_KEY", "").strip()
    if ors_key:
        routes = fetch_ors_routes(start, end, ors_key)
        if len(routes) >= 2:
            return routes
            
    return fetch_osrm_routes_with_alternatives(start, end)
