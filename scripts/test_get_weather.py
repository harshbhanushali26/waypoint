"""
scripts/test_get_weather.py

Standalone test script for the get_weather tool node (Open-Meteo stage).
Each function builds its own minimal state dict — only the keys
get_weather actually reads (destination, start_date, end_date) — and
checks for presence of "weather_note", not truthiness, per the
fail-loud convention (no note key = success).

Run with real network calls, so happy-path / bad-destination cases
will hit the live Open-Meteo API.
"""

from datetime import date, timedelta
from tools.get_weather import get_weather, MAX_FORECAST_DAYS_OUT


def _base_state(days_from_today: int = 2, trip_length: int = 3, destination: str = "Goa") -> dict:
    start = date.today() + timedelta(days=days_from_today)
    end = start + timedelta(days=trip_length)
    return {
        "destination": destination,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def _report(case_name: str, result: dict):
    has_note = "weather_note" in result
    weather_len = len(result.get("weather", []))
    status = "NOTE PRESENT (degraded/failed)" if has_note else "NO NOTE (success)"
    print(f"[{case_name}] {status} — weather entries: {weather_len}")
    if has_note:
        print(f"    note: {result['weather_note']}")
    print()


def test_happy_path():
    state = _base_state(days_from_today=2, trip_length=3, destination="Goa")
    result = get_weather(state)
    _report("happy_path", result)


def test_bad_destination():
    state = _base_state(days_from_today=2, trip_length=3, destination="Xyzzqqnotarealplace123")
    result = get_weather(state)
    _report("bad_destination", result)


def test_beyond_forecast_horizon():
    state = _base_state(days_from_today=MAX_FORECAST_DAYS_OUT + 5, trip_length=3, destination="Goa")
    result = get_weather(state)
    _report("beyond_forecast_horizon", result)


def test_missing_start_date():
    state = _base_state()
    del state["start_date"]
    result = get_weather(state)
    _report("missing_start_date", result)


def test_missing_destination():
    state = _base_state()
    state["destination"] = ""
    result = get_weather(state)
    _report("missing_destination", result)


def test_malformed_start_date():
    """
    Known gap: date.fromisoformat() runs outside the try/except in
    get_weather, so a present-but-malformed start_date will raise
    ValueError instead of failing loud. Expect a traceback here, not
    a clean weather_note.
    """
    state = _base_state()
    state["start_date"] = "not-a-date"
    try:
        result = get_weather(state)
        _report("malformed_start_date", result)
    except Exception as e:
        print(f"[malformed_start_date] CRASHED instead of failing loud: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    test_happy_path()
    test_bad_destination()
    test_beyond_forecast_horizon()
    test_missing_start_date()
    test_missing_destination()
    test_malformed_start_date()