"""
Standalone test script for search_activities tool node.

Run from project root:
    uv run python -m scripts.test_search_activities
"""

from tools.search_activities import search_activities  
from core.config import settings


def _report(label: str, result: dict):
    has_note = "activities_note" in result
    status = "NOTE" if has_note else "OK"
    print(f"[{status}] {label}")
    if has_note:
        print(f"    note: {result['activities_note']}")
    else:
        print(f"    activities returned: {len(result.get('activities', []))}")
    print()


def test_missing_destination():
    """Guard clause — no destination provided, should short-circuit before any API call."""
    state = {
        "destination": "",
        "interests": ["food", "history"],
    }
    result = search_activities(state)
    _report("missing_destination", result)


def test_happy_path_with_key():
    """Live call using Tavily API key from settings, with interests + dates provided."""
    state = {
        "destination": "Goa",
        "interests": ["beaches", "nightlife"],
        "start_date": "2026-12-10",
        "end_date": "2026-12-14",
    }
    result = search_activities(state)
    _report("happy_path_with_key", result)


def test_happy_path_no_interests():
    """No interests provided — falls back to default 'things to do' query phrase."""
    state = {
        "destination": "Jaipur",
        "interests": [],
    }
    result = search_activities(state)
    _report("happy_path_no_interests", result)


def test_keyless_fallback():
    """Temporarily blank the Tavily key to force the keyless API path."""
    original_key = settings.tavily_api_key
    settings.tavily_api_key = ""
    try:
        state = {
            "destination": "Manali",
            "interests": ["trekking"],
        }
        result = search_activities(state)
        _report("keyless_fallback", result)
    finally:
        settings.tavily_api_key = original_key


if __name__ == "__main__":
    test_missing_destination()
    test_happy_path_with_key()
    test_happy_path_no_interests()
    test_keyless_fallback()