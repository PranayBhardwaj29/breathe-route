"""
AWS Lambda Handler for Breathe Route.
Supports AWS Lambda Function URLs (Payload Format 2.0) and API Gateway.
Full CORS support for browser fetch/axios calls.
"""

import json
import base64
from typing import Dict, Any

from route_planner import plan_routes

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Amz-Date, Authorization, X-Api-Key, X-Amz-Security-Token"
}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda entry point.
    Handles OPTIONS preflight and POST /routes requests.
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

    # 3. Parse Request Body
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

    # 4. Extract parameters with defaults for Delhi
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

    # 5. Execute route planning & exposure computation
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
