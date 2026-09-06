"""
scripts/test_search_hotels.py

Standalone test script for search_hotels (SerpApi Google Hotels stage).
Two cases are zero-cost (no live API call). One case makes a real live
SerpApi call against the hotels account (separate quota from flights).
"""

from datetime import date, timedelta
from core.config import settings
from tools.search_hotels import search_hotels


def _base_state(destination="Goa", days_out=5, stay_length=3) -> dict:
    check_in = date.today() + timedelta(days=days_out)
    check_out = check_in + timedelta(days=stay_length)
    return {
        "destination": destination,
        "start_date": check_in.isoformat(),
        "end_date": check_out.isoformat(),
        "num_travelers": 1,
        "currency": "INR",
    }


def _report(case_name: str, result: dict):
    has_note = "hotels_note" in result
    hotel_count = len(result.get("hotels", []))
    status = "NOTE PRESENT (degraded/failed)" if has_note else "NO NOTE (success)"
    print(f"[{case_name}] {status} — hotels entries: {hotel_count}")
    if has_note:
        print(f"    note: {result['hotels_note']}")
    print()


def test_missing_api_key():
    """Zero cost — temporarily blank the hotels key, restore after."""
    original_key = settings.serpapi_hotels_key
    settings.serpapi_hotels_key = ""
    try:
        state = _base_state()
        result = search_hotels(state)
        _report("missing_api_key", result)
    finally:
        settings.serpapi_hotels_key = original_key


def test_missing_destination():
    """Zero cost — empty destination should fail the 'missing fields' check before any request."""
    state = _base_state(destination="")
    result = search_hotels(state)
    _report("missing_destination", result)


def test_happy_path():
    """LIVE — burns 1 SerpApi request against the hotels account."""
    print("[happy_path] LIVE CALL — burning 1 SerpApi request (hotels account)...")
    state = _base_state()
    result = search_hotels(state)
    _report("happy_path", result)


if __name__ == "__main__":
    test_missing_api_key()
    test_missing_destination()
    test_happy_path()