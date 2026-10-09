"""
Exposure Calculation Service for Breathe Route.

Calculates length-weighted exposure scores along cycling routes using 
Inverse-Distance Weighting (IDW) from nearby live monitoring stations.
Samples the route approximately every 200 meters.
"""

import math
from typing import List, Dict, Any, Tuple

EARTH_RADIUS_M = 6371000.0

def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculates great-circle distance between two points in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c

def interpolate_point(lat1: float, lng1: float, lat2: float, lng2: float, fraction: float) -> Tuple[float, float]:
    """Linearly interpolates between two lat/lng coordinates."""
    return (
        lat1 + (lat2 - lat1) * fraction,
        lng1 + (lng2 - lng1) * fraction
    )

def sample_route_polyline(geometry: List[List[float]], step_m: float = 200.0) -> List[Tuple[float, float]]:
    """
    Samples points along the route polyline at approximately step_m (default 200m) intervals.
    geometry: [[lat, lng], [lat, lng], ...]
    """
    if not geometry:
        return []
    if len(geometry) == 1:
        return [(geometry[0][0], geometry[0][1])]
        
    sampled_points = [(geometry[0][0], geometry[0][1])]
    accumulated_dist = 0.0
    
    for i in range(len(geometry) - 1):
        p1 = geometry[i]
        p2 = geometry[i + 1]
        seg_dist = haversine_distance_m(p1[0], p1[1], p2[0], p2[1])
        
        if seg_dist == 0.0:
            continue
            
        remaining_in_seg = seg_dist
        current_p = p1
        
        while accumulated_dist + remaining_in_seg >= step_m:
            needed = step_m - accumulated_dist
            fraction = needed / remaining_in_seg
            interp_lat, interp_lng = interpolate_point(current_p[0], current_p[1], p2[0], p2[1], fraction)
            sampled_points.append((interp_lat, interp_lng))
            current_p = [interp_lat, interp_lng]
            remaining_in_seg -= needed
            accumulated_dist = 0.0
            
        accumulated_dist += remaining_in_seg
        
    # Ensure end point is included
    end_pt = (geometry[-1][0], geometry[-1][1])
    if sampled_points[-1] != end_pt:
        sampled_points.append(end_pt)
        
    return sampled_points

def estimate_point_pm25(lat: float, lng: float, stations: List[Dict[str, Any]], power: float = 2.0, epsilon_km: float = 0.05) -> float:
    """
    Estimates PM2.5 / AQI at a given location using Inverse-Distance Weighting (IDW).
    epsilon_km avoids singularity if point is right next to a monitoring station.
    """
    if not stations:
        return 0.0
        
    total_weight = 0.0
    weighted_sum = 0.0
    
    for station in stations:
        st_lat = station["lat"]
        st_lng = station["lng"]
        st_val = station.get("pm25", 0.0)
        
        # Distance in kilometers
        dist_km = haversine_distance_m(lat, lng, st_lat, st_lng) / 1000.0
        
        # Weight = 1 / (d^p + epsilon)
        weight = 1.0 / (math.pow(dist_km, power) + epsilon_km)
        weighted_sum += weight * st_val
        total_weight += weight
        
    if total_weight == 0.0:
        return 0.0
    return weighted_sum / total_weight

def compute_route_exposure(route: Dict[str, Any], stations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes length-weighted avg_aqi and exposure_score along the route.
    Samples every ~200m.
    """
    geometry = route.get("geometry", [])
    sampled_points = sample_route_polyline(geometry, step_m=200.0)
    
    if not sampled_points:
        return {
            **route,
            "avg_aqi": 0.0,
            "exposure_score": 0.0,
            "sample_count": 0
        }
        
    point_readings = [
        estimate_point_pm25(pt[0], pt[1], stations)
        for pt in sampled_points
    ]
    
    avg_pm25 = sum(point_readings) / len(point_readings)
    
    # Exposure score: length-weighted average PM2.5 (equidistant 200m samples)
    exposure_score = round(avg_pm25, 1)
    
    return {
        "id": route["id"],
        "distance_m": route["distance_m"],
        "duration_s": route["duration_s"],
        "avg_aqi": round(avg_pm25, 1),
        "exposure_score": exposure_score,
        "sample_count": len(sampled_points),
        "geometry": route["geometry"]
    }
