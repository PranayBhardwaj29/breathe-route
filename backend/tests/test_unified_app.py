"""
Unified test suite for Breathe Route & Canopy Tree Recommender backend.
Verifies all Lambda Function URL and API Gateway routes:
1. OPTIONS preflight
2. POST /routes (Cycling clean air routing)
3. GET  /api/health
4. GET  /api/overview (Sites and patches catalogue)
5. POST /api/recommend (Study site tree recommendation & 20-year projection)
"""

import json
import sys
import os

# Ensure backend directory in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import lambda_handler

def run_tests():
    print("=" * 70)
    print("   TESTING UNIFIED BREATHE ROUTE & CANOPY TREE RECOMMENDER")
    print("=" * 70)

    # 1. OPTIONS Preflight
    print("\n[1/5] Testing OPTIONS Preflight...")
    evt = {"rawPath": "/routes", "httpMethod": "OPTIONS"}
    res = lambda_handler(evt, None)
    assert res["statusCode"] == 200, f"Expected 200, got {res['statusCode']}"
    assert res["headers"]["Access-Control-Allow-Origin"] == "*", "Missing CORS origin"
    print("  -> Preflight OK (200, CORS: *)")

    # 2. GET /api/health
    print("\n[2/5] Testing GET /api/health...")
    evt = {"rawPath": "/api/health", "httpMethod": "GET"}
    res = lambda_handler(evt, None)
    assert res["statusCode"] == 200, f"Expected 200, got {res['statusCode']}"
    data = json.loads(res["body"])
    assert data["status"] == "ok"
    assert data["sites"] >= 3, f"Expected >= 3 sites, got {data['sites']}"
    assert data["species"] >= 10, f"Expected >= 10 species, got {data['species']}"
    print(f"  -> Health OK ({data['service']}, Sites: {data['sites']}, Species: {data['species']})")

    # 3. GET /api/overview
    print("\n[3/5] Testing GET /api/overview...")
    evt = {"rawPath": "/api/overview", "httpMethod": "GET"}
    res = lambda_handler(evt, None)
    assert res["statusCode"] == 200, f"Expected 200, got {res['statusCode']}"
    overview = json.loads(res["body"])
    assert "sites" in overview and "patches" in overview
    assert len(overview["sites"]) >= 3
    assert len(overview["patches"]) > 100
    print(f"  -> Overview OK ({len(overview['sites'])} study sites, {len(overview['patches'])} planting patches)")

    # 4. POST /api/recommend
    print("\n[4/5] Testing POST /api/recommend ('Anand Lok')...")
    evt = {
        "rawPath": "/api/recommend",
        "httpMethod": "POST",
        "body": json.dumps({"query": "Anand Lok", "top_k": 5})
    }
    res = lambda_handler(evt, None)
    assert res["statusCode"] == 200, f"Expected 200, got {res['statusCode']}, body: {res['body'][:200]}"
    rec = json.loads(res["body"])
    assert "result" in rec and "projection" in rec and "table" in rec
    site_name = rec["result"]["matched_location"]["name"]
    trees_planned = rec["result"]["plan_summary"]["trees"]
    top_species = rec["result"]["species_ranking"][0]["common_name"]
    years = len(rec["projection"]["years"])
    print(f"  -> Recommend OK (Matched: {site_name}, Trees: {trees_planned}, Top Species: {top_species}, Projection Years: {years})")

    # 5. POST /routes
    print("\n[5/5] Testing POST /routes (Connaught Place -> India Gate)...")
    evt = {
        "rawPath": "/routes",
        "httpMethod": "POST",
        "body": json.dumps({
            "start": {"lat": 28.6328, "lng": 77.2197},
            "end": {"lat": 28.6129, "lng": 77.2295},
            "mode": "cycling"
        })
    }
    res = lambda_handler(evt, None)
    assert res["statusCode"] == 200, f"Expected 200, got {res['statusCode']}"
    nav = json.loads(res["body"])
    assert "routes" in nav and len(nav["routes"]) > 0
    assert "departure_forecast" in nav
    assert "source_likelihood" in nav
    print(f"  -> Navigation OK ({len(nav['routes'])} routes evaluated, Recommended: {nav.get('recommended_id')})")

    print("\n" + "=" * 70)
    print("  [SUCCESS] All 5 unified API routes passed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
