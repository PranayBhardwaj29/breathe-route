import os
import requests
import json

def load_env(env_path=".env"):
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

load_env()
key = os.getenv("OPENAQ_API_KEY", "")
print("OPENAQ_API_KEY present:", bool(key))

headers = {}
if key:
    headers["X-API-Key"] = key

# Test OpenAQ v3
url = "https://api.openaq.org/v3/locations?coordinates=28.6139,77.2090&radius=25000&limit=10"
try:
    r = requests.get(url, headers=headers, timeout=10)
    print("OpenAQ v3 status:", r.status_code)
    print("OpenAQ response preview:", r.text[:300])
except Exception as e:
    print("OpenAQ error:", e)

# Test Open-Meteo weather
w_url = "https://api.open-meteo.com/v1/forecast?latitude=28.6139&longitude=77.2090&current=temperature_2m,wind_speed_10m,wind_direction_10m&timezone=Asia/Kolkata"
try:
    rw = requests.get(w_url, timeout=10)
    print("Open-Meteo weather status:", rw.status_code)
    print("Open-Meteo weather data:", json.dumps(rw.json().get("current", {}), indent=2))
except Exception as e:
    print("Open-Meteo error:", e)
