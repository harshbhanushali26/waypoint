"""
test_guard_step2.py — Standalone verification for Step 2
"""

from tools._constants import resolve_airport, resolve_station, is_valid_iata
from tools.search_flights import search_flights


def test_airport_and_station_lookups():
    # 1. Newly added cities
    assert resolve_airport("Surat, India") == "STV", "Surat should resolve to STV"
    assert resolve_airport("Bhuj, Gujarat") == "BHJ", "Bhuj should resolve to BHJ"
    assert resolve_airport("Udaipur") == "UDR", "Udaipur should resolve to UDR"

    assert resolve_station("Surat") == "ST", "Surat station should resolve to ST"
    assert resolve_station("Bhuj") == "BHJ", "Bhuj station should resolve to BHJ"
    assert resolve_station("Vapi, Gujarat, India") == "VAPI", "Vapi station should resolve to VAPI"

    # 2. IATA validator
    assert is_valid_iata("BOM") is True
    assert is_valid_iata("DEL") is True
    assert is_valid_iata("Surat") is False  # Word, not 3-letter code
    assert is_valid_iata("VAPI") is False   # 4 letters
    assert is_valid_iata("") is False
    print("✅ Airport & Station Code Resolutions: PASSED")


def test_search_flights_guard():
    # Test with a destination that has no commercial airport (e.g. Vapi or Manali)
    state = {
        "trip_id": "test-flight-guard",
        "search_plan": {"transport_modes": ["flights"]},
        "normalized_input": {
            "origin_city": "Mumbai, India",
            "destination": "Vapi, India"  # Vapi has no IATA airport code
        },
        "start_date": "2026-12-01",
        "end_date": "2026-12-05",
    }

    result = search_flights(state)
    assert result["flights"] == [], "Flights list must be empty"
    assert "flights_note" in result, "Must provide an informative flights_note"
    assert "no IATA code" in result["flights_note"], "Must explain missing IATA code"
    print("✅ Non-IATA Destination Flight Guard: PASSED (Zero SerpApi 400 calls!)")


if __name__ == "__main__":
    print("\nRunning Step 2 Verification...")
    test_airport_and_station_lookups()
    test_search_flights_guard()
    print("\n🎉 ALL STEP 2 CHECKS PASSED!\n")