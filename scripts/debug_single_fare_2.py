"""
scripts/debug_single_fare_2.py

ONE-OFF, SINGLE-CALL verification script. Fires exactly one raw fare
request for a DIFFERENT train + DIFFERENT class than the first debug
check, to confirm breakdown.totalFare is consistently where the fare
lives rather than a fluke of one specific train/class combo.

Run: uv run python -m scripts.debug_single_fare_2
"""

import json
import httpx

from core.config import settings

RAILRADAR_BASE = "https://api.railradar.in/v1"

# Different train, different class than the first verification call.
TRAIN_NUMBER = "20942"
SOURCE = "VAPI"
DESTINATION = "BDTS"
JOURNEY_DATE = "2026-09-10"
CLASS_CODE = "SL"
QUOTA = "GN"


def main():
    url = f"{RAILRADAR_BASE}/trains/{TRAIN_NUMBER}/fare"
    params = {
        "source": SOURCE,
        "destination": DESTINATION,
        "journeyDate": JOURNEY_DATE,
        "classCode": CLASS_CODE,
        "quotaCode": QUOTA,
    }
    headers = {"Authorization": f"Bearer {settings.railradar_api_key}"}

    print(f"GET {url}")
    print(f"params: {params}\n")

    response = httpx.get(url, headers=headers, params=params, timeout=30)

    print(f"status_code: {response.status_code}\n")
    print("raw response body:")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"(could not parse as JSON: {e})")
        print(response.text)


if __name__ == "__main__":
    main()