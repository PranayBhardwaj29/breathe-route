"""
Stage 2 Test Script: Core Routing & Exposure Logic Verification.
Tests 3 fixed Delhi cycling route pairs, computes IDW exposure scores,
and validates response JSON against the API contract.
"""

import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from route_planner import plan_routes

TEST_CASES = [
    {
        "name": "Pair 1: Connaught Place -> India Gate (Central Delhi, ~3 km)",
        "start": {"lat": 28.6328, "lng": 77.2197},
        "end": {"lat": 28.6129, "lng": 77.2295}
    },
    {
        "name": "Pair 2: Hauz Khas -> Saket (South Delhi, ~4.5 km)",
        "start": {"lat": 28.5494, "lng": 77.2001},
        "end": {"lat": 28.5244, "lng": 77.2185}
    },
    {
        "name": "Pair 3: Delhi University -> Red Fort (North to Central Delhi, ~6 km)",
        "start": {"lat": 28.6904, "lng": 77.2088},
        "end": {"lat": 28.6562, "lng": 77.2410}
    }
]

def run_stage2_verification():
    print("=" * 76)
    print("   STAGE 2: ROUTE PLANNING & EXPOSURE SCORING TEST")
    print("=" * 76)

    all_passed = True

    for i, test in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/3] Testing {test['name']}")
        result = plan_routes(test["start"], test["end"], mode="cycling")
        
        # Contract Verification
        required_keys = ["routes", "recommended_id", "weather", "aqi_updated_at", "data_status"]
        missing_keys = [k for k in required_keys if k not in result]
        if missing_keys:
            print(f"  [ERROR] Response missing contract keys: {missing_keys}")
            all_passed = False
            continue

        routes = result.get("routes", [])
        rec_id = result.get("recommended_id")
        trade_off = result.get("trade_off", "N/A")
        weather = result.get("weather", {})
        
        print(f"  Received {len(routes)} routes | Recommended Route: {rec_id} ({trade_off})")
        print(f"  Weather: Wind {weather.get('wind_speed')} km/h at {weather.get('wind_dir')} deg")
        print(f"  Data Status: {result.get('data_status')} (Updated: {result.get('aqi_updated_at')})")
        print("  " + "-" * 72)
        print(f"  {'Route ID':<10} | {'Distance (m)':<14} | {'Duration':<12} | {'Exposure Score (PM2.5)'}")
        print("  " + "-" * 72)
        
        for r in routes:
            mins = round(r['duration_s'] / 60.0, 1)
            is_rec = " [RECOMMENDED]" if r['id'] == rec_id else ""
            print(f"  {r['id']:<10} | {r['distance_m']:<14} | {mins:<5} min     | {r['exposure_score']}{is_rec}")
            
            # Verify geometry format: [[lat, lng], ...]
            geom = r.get("geometry", [])
            if not geom or not isinstance(geom[0], list) or len(geom[0]) != 2:
                print(f"    [WARN] Geometry format invalid for route {r['id']}")
                all_passed = False
                
        print("  " + "-" * 72)

    # Save a mock response file for mock/mock_routes.json matching Pair 1
    sample_response = plan_routes(TEST_CASES[0]["start"], TEST_CASES[0]["end"])
    mock_file = os.path.join(os.path.dirname(__file__), "..", "..", "mock", "mock_routes.json")
    with open(mock_file, "w", encoding="utf-8") as f:
        json.dump(sample_response, f, indent=2)
    print(f"\n[INFO] Saved sample response to mock/mock_routes.json")

    print("\n" + "=" * 76)
    if all_passed:
        print("  [SUCCESS] All 3 Delhi route pairs passed and match API contract!")
    else:
        print("  [WARNING] Some contract checks had warnings.")
    print("=" * 76)
    return all_passed

if __name__ == "__main__":
    success = run_stage2_verification()
    sys.exit(0 if success else 1)
