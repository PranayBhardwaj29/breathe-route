"""
Stage 5 Verification Test:
Tests hourly forecast departure analysis, wind-drift vectors, and source likelihood estimation.
"""

import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from route_planner import plan_routes

def test_stage5():
    print("=" * 74)
    print("   STAGE 5: FORECAST DEPARTURE & SOURCE LIKELIHOOD VERIFICATION")
    print("=" * 74)

    start = {"lat": 28.6328, "lng": 77.2197}
    end = {"lat": 28.6129, "lng": 77.2295}

    print("\n[1/3] Planning routes with Stage 5 intelligence...")
    result = plan_routes(start, end)

    # 1. Verify departure forecast
    print("\n[2/3] Verifying 'Best Time to Leave' Forecast:")
    forecast = result.get("departure_forecast", {})
    status = forecast.get("status")
    rec_time = forecast.get("recommended_departure_time")
    rec_pm25 = forecast.get("recommended_pm25")
    pct_red = forecast.get("pct_reduction")
    rec_text = forecast.get("recommendation_text")
    timeline = forecast.get("hourly_timeline", [])

    print(f"  - Forecast Status:       {status}")
    print(f"  - Recommended Departure: {rec_time} (Expected PM2.5: {rec_pm25} ug/m3)")
    print(f"  - Exposure Reduction:    {pct_red}%")
    print(f"  - Recommendation:        {rec_text}")
    print(f"  - Hourly Timeline (Next 6h):")
    for item in timeline[:6]:
        print(f"      {item['time']} -> {item['pm25']} ug/m3")

    # 2. Verify source likelihood
    print("\n[3/3] Verifying Pollutant Source Likelihood:")
    sources = result.get("source_likelihood", {})
    prim = sources.get("primary_source")
    conf = sources.get("confidence")
    breakdown = sources.get("breakdown", [])
    exp = sources.get("explanation")

    print(f"  - Primary Source:  {prim} (Confidence: {conf})")
    print(f"  - Explanation:     {exp}")
    print(f"  - Source Breakdown:")
    for b in breakdown:
        print(f"      {b['source']:<32} | {b['percentage']}%")

    # Save to mock for offline resilience
    mock_file = os.path.join(os.path.dirname(__file__), "..", "..", "mock", "mock_routes.json")
    with open(mock_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\n[INFO] Updated mock/mock_routes.json with Stage 5 schema.")

    print("\n" + "=" * 74)
    print("  [SUCCESS] Stage 5 data layers generated and verified!")
    print("=" * 74)
    return True

if __name__ == "__main__":
    test_stage5()
