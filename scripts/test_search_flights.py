"""
scripts/test_search_flights.py

Standalone test script for search_flights (SerpApi Google Flights stage).
Three cases are zero-cost (no live API call). One case makes a real
live SerpApi call (one-way only, to keep quota usage to 1 request per run).

Round-trip and unresolvable-city cases are deliberately NOT automated
here — run those manually, one at a time, when you actually want to
spend the quota on them.
"""

from datetime import date, timedelta
from core.config import settings
from tools.search_flights import search_flights


def _base_state(transport_modes=None, origin_city="Mumbai", destination="Goa", days_out=5) -> dict:
    start = date.today() + timedelta(days=days_out)
    return {
        "origin_city": origin_city,
        "destination": destination,
        "start_date": start.isoformat(),
        "end_date": start.isoformat(),  # one-way: same as start_date, skips return leg
        "num_travelers": 1,
        "currency": "INR",
        "search_plan": {"transport_modes": transport_modes if transport_modes is not None else ["flights"]},
    }


def _report(case_name: str, result: dict):
    has_note = "flights_note" in result
    flight_count = len(result.get("flights", []))
    status = "NOTE PRESENT (degraded/failed)" if has_note else "NO NOTE (success)"
    print(f"[{case_name}] {status} — flights entries: {flight_count}")
    if has_note:
        print(f"    note: {result['flights_note']}")
    print()


def test_mode_not_selected():
    """Zero cost — flights not in transport_modes, should short-circuit."""
    state = _base_state(transport_modes=["trains"])
    result = search_flights(state)
    _report("mode_not_selected", result)


def test_missing_api_key():
    """Zero cost — temporarily blank the API key, restore after."""
    original_key = settings.serpapi_flights_key
    settings.serpapi_flights_key = ""
    try:
        state = _base_state()
        result = search_flights(state)
        _report("missing_api_key", result)
    finally:
        settings.serpapi_flights_key = original_key


def test_missing_origin_city():
    """Zero cost — empty origin_city should fail the 'missing fields' check before any request."""
    state = _base_state(origin_city="")
    result = search_flights(state)
    _report("missing_origin_city", result)


def test_happy_path_one_way():
    """LIVE — burns exactly 1 SerpApi request (one-way, no return leg)."""
    print("[happy_path_one_way] LIVE CALL — burning 1 SerpApi request...")
    state = _base_state()
    result = search_flights(state)
    _report("happy_path_one_way", result)


if __name__ == "__main__":
    test_mode_not_selected()
    test_missing_api_key()
    test_missing_origin_city()
    test_happy_path_one_way()