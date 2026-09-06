"""
scripts/debug_single_fare.py

ONE-OFF, SINGLE-CALL debug script. Fires exactly one raw fare request
and prints the unparsed JSON response. No normalization, no retry logic,
no throttling — just enough to see what RailRadar actually returns.

Run: uv run python -m scripts.debug_single_fare
"""

import json
import httpx

from core.config import settings

RAILRADAR_BASE = "https://api.railradar.in/v1"

# Same params as the train that succeeded (200 OK) in the last live test.
TRAIN_NUMBER = "19038"
SOURCE = "VAPI"
DESTINATION = "BVI"
JOURNEY_DATE = "2026-09-10"
CLASS_CODE = "3A"
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