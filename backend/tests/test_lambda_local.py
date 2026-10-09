"""
Test script for verifying lambda_handler locally with synthetic Function URL events.
"""

import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import lambda_handler

def test_lambda():
    print("=" * 70)
    print("   TESTING AWS LAMBDA HANDLER LOCALLY")
    print("=" * 70)
    
    # 1. Test CORS OPTIONS
    print("\n[1/3] Testing OPTIONS Preflight Request...")
    options_event = {
        "requestContext": {
            "http": {
                "method": "OPTIONS"
            }
        }
    }
    resp_opt = lambda_handler(options_event, None)
    print(f"  Status: {resp_opt['statusCode']}")
    print(f"  CORS Origin Header: {resp_opt['headers'].get('Access-Control-Allow-Origin')}")
    assert resp_opt["statusCode"] == 200, "OPTIONS preflight should return 200"

    # 2. Test Invalid JSON
    print("\n[2/3] Testing Malformed Request Body...")
    bad_event = {
        "requestContext": {"http": {"method": "POST"}},
        "body": "invalid-json{"
    }
    resp_bad = lambda_handler(bad_event, None)
    print(f"  Status: {resp_bad['statusCode']}")
    assert resp_bad["statusCode"] == 400, "Bad JSON should return 400"

    # 3. Test Valid POST Request
    print("\n[3/3] Testing POST /routes (Connaught Place to India Gate)...")
    post_event = {
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({
            "start": {"lat": 28.6328, "lng": 77.2197},
            "end": {"lat": 28.6129, "lng": 77.2295},
            "mode": "cycling"
        })
    }
    resp_post = lambda_handler(post_event, None)
    print(f"  Status: {resp_post['statusCode']}")
    print(f"  CORS Origin Header: {resp_post['headers'].get('Access-Control-Allow-Origin')}")
    
    body = json.loads(resp_post["body"])
    print(f"  Recommended Route: {body.get('recommended_id')} ({body.get('trade_off')})")
    print(f"  Routes Count: {len(body.get('routes', []))}")
    assert resp_post["statusCode"] == 200, "POST should return 200"
    assert "routes" in body, "Response body must contain routes"
    
    print("\n" + "=" * 70)
    print("  [SUCCESS] Lambda handler passed all local verification checks!")
    print("=" * 70)

if __name__ == "__main__":
    test_lambda()
