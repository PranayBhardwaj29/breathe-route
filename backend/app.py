"""
AWS Lambda Handler for Breathe Route & Canopy Tree Recommender.
Supports AWS Lambda Function URLs (Payload Format 2.0) and API Gateway.
Full CORS support for browser fetch/axios calls.

Endpoints handled:
- POST /routes          : Clean-air cycling navigation & IDW PM2.5 exposure planning
- GET/POST /api/overview: Delhi study sites and planting patches catalog
- POST /api/recommend   : Site environmental baseline, species ranking, patch plan & 20-year projection curves
- GET /api/health       : System status, sites, and tree species counts
"""

import json
import base64
import os
import sys
from pathlib import Path
from typing import Dict, Any

# Ensure backend directory is in python search path
CURRENT_DIR = Path(__file__).parent.resolve()
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
SERVICES_DIR = CURRENT_DIR / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from route_planner import plan_routes

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Amz-Date, Authorization, X-Api-Key, X-Amz-Security-Token"
}

# Lazy-loaded Tree Recommendation Engine singleton
_tree_engine = None
_tree_palette = [
    "#1f7a4d", "#2b7fb8", "#e08a00", "#8e5bd0", "#d64545", "#13a0a0", "#b08900", "#d4568f",
    "#4f5bd5", "#6f9c1f", "#e0612a", "#0e8fb0", "#7a6ad8", "#7b756c"
]
_tree_colors = None
_tree_sp = None
_tree_names = None

def get_tree_engine():
    global _tree_engine, _tree_colors, _tree_sp, _tree_names
    if _tree_engine is None:
        from tree_recommender import RecommendationEngine, DataError
        data_path = CURRENT_DIR / "data"
        if not data_path.exists():
            # Fallback check
            data_path = Path("backend/data")
        _tree_engine = RecommendationEngine(data_path)
        _tree_colors = {sid: _tree_palette[i % len(_tree_palette)] for i, sid in enumerate(_tree_engine.species["species_id"])}
        _tree_sp = _tree_engine.species.set_index("species_id")
        _tree_names = _tree_sp["common_name"].to_dict()
    return _tree_engine


def handle_routes(payload: Dict[str, Any]) -> Dict[str, Any]:
    start = payload.get("start")
    end = payload.get("end")
    mode = payload.get("mode", "cycling")

    # If coordinates are missing or zeroed, provide central Delhi defaults
    if not start or not isinstance(start, dict) or "lat" not in start or "lng" not in start:
        start = {"lat": 28.6328, "lng": 77.2197}  # Connaught Place
    if not end or not isinstance(end, dict) or "lat" not in end or "lng" not in end:
        end = {"lat": 28.6129, "lng": 77.2295}    # India Gate

    try:
        start_lat = float(start["lat"])
        start_lng = float(start["lng"])
        end_lat = float(end["lat"])
        end_lng = float(end["lng"])
    except (ValueError, TypeError):
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "Coordinates (lat, lng) must be valid numbers."})
        }

    try:
        result = plan_routes(
            start={"lat": start_lat, "lng": start_lng},
            end={"lat": end_lat, "lng": end_lng},
            mode=mode
        )
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(result)
        }
    except Exception as exc:
        print(f"[app] Unhandled error during route planning: {exc}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "error": "Internal server error while calculating routes.",
                "details": str(exc)
            })
        }


def handle_overview() -> Dict[str, Any]:
    try:
        engine = get_tree_engine()
        from tree_recommender import _clean
        p = engine.patches.dropna(subset=["lat", "lon"])
        data = _clean({
            "sites": engine.locations[["location_id", "name", "lat", "lon"]].to_dict("records"),
            "patches": p[["patch_id", "lat", "lon", "area_m2", "site_type"]].to_dict("records")
        })
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(data)
        }
    except Exception as e:
        print(f"[app] Error in /api/overview: {e}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Failed to load tree study sites: {str(e)}"})
        }


def handle_recommend(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        engine = get_tree_engine()
        from tree_recommender import OutOfCoverageError, _clean
        from projections import build_projection

        query = payload.get("query")
        lat = payload.get("lat") or payload.get("latitude")
        lon = payload.get("lon") or payload.get("lng") or payload.get("longitude")
        top_k = int(payload.get("top_k", 6))
        top_k = max(3, min(top_k, 10))

        if lat is not None:
            lat = float(lat)
        if lon is not None:
            lon = float(lon)

        rec = engine.recommend(query=query, lat=lat, lon=lon, top_k=top_k)
        res = rec.to_dict()
        ranked = engine.score_species(res["matched_location"]["location_id"]).set_index("species_id")
        ids = [s["species_id"] for s in res["species_ranking"]]
        table = []
        for s in res["species_ranking"]:
            r = _tree_sp.loc[s["species_id"]]
            sv = float(r["survival_yr10"])
            table.append({
                "species_id": s["species_id"],
                "common_name": s["common_name"],
                "scientific_name": s["scientific_name"],
                "score": s["score"],
                "color": _tree_colors.get(s["species_id"], "#1f7a4d"),
                "pm25_g": s["pm25_removal_g_yr_mature_local"],
                "cooling_c": float(r["air_cooling_c_scenario"]),
                "crown_m2": float(r["crown_area_m2_mature"]),
                "water_l": float(r["irrigation_L_per_yr_yr4plus"]),
                "survival10": sv * 100 if sv <= 1 else sv,
                "cost7": float(r["total_cost_7yr_inr"]),
                "why": s["why"]
            })
        counts = res["plan_summary"]["by_species"]
        proj = build_projection(_tree_sp, ranked, ids, counts, _tree_names, _tree_colors)

        output = _clean({
            "result": res,
            "geojson": rec.to_geojson(),
            "table": table,
            "colors": _tree_colors,
            "projection": proj
        })
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(output)
        }
    except Exception as e:
        # Check if OutOfCoverageError
        err_type = type(e).__name__
        if err_type == "OutOfCoverageError":
            return {
                "statusCode": 422,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": str(e), "detail": str(e)})
            }
        elif isinstance(e, ValueError):
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": str(e), "detail": str(e)})
            }
        print(f"[app] Error in /api/recommend: {e}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Recommendation failed: {str(e)}", "detail": str(e)})
        }


def handle_health() -> Dict[str, Any]:
    try:
        engine = get_tree_engine()
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "status": "ok",
                "service": "Breathe Route & Canopy Tree Recommender",
                "sites": len(engine.locations),
                "species": len(engine.species)
            })
        }
    except Exception as e:
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "status": "degraded",
                "service": "Breathe Route",
                "tree_engine_error": str(e)
            })
        }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda entry point.
    Handles OPTIONS preflight, POST /routes, and Canopy /api/* endpoints.
    """
    # 1. Determine HTTP Method
    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method") or
        event.get("httpMethod") or
        "POST"
    ).upper()

    # 2. Handle CORS preflight
    if http_method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({"status": "ok"})
        }

    # 3. Determine Route Path
    raw_path = (
        event.get("rawPath") or
        event.get("path") or
        event.get("requestContext", {}).get("http", {}).get("path") or
        "/routes"
    ).lower()

    # 4. Parse Request Body
    raw_body = event.get("body")
    if event.get("isBase64Encoded") and raw_body:
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except Exception as e:
            print(f"[app] Base64 decode failed: {e}")

    payload = {}
    if isinstance(raw_body, str) and raw_body.strip():
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": f"Invalid JSON payload: {str(exc)}"})
            }
    elif isinstance(raw_body, dict):
        payload = raw_body

    # Check query parameters for GET requests (or payload fallback)
    query_params = event.get("queryStringParameters") or {}
    if isinstance(query_params, dict):
        for k, v in query_params.items():
            if k not in payload:
                payload[k] = v

    # 5. Route dispatch
    if "recommend" in raw_path:
        return handle_recommend(payload)
    elif "overview" in raw_path:
        return handle_overview()
    elif "health" in raw_path:
        return handle_health()
    else:
        # Default route handler: /routes
        return handle_routes(payload)
