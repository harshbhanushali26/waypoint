"""
test_concierge_step0.py — Standalone verification for Step 0
"""

from agents.concierge import concierge_node
from models.schemas import NormalizedInput


def test_standard_trip():
    state = {
        "trip_id": "test-standard",
        "destination": "goa",
        "origin_city": "bombay",
        "start_date": "2026-11-10",
        "end_date": "2026-11-14",
        "budget": 25000.0,
        "num_travelers": 2,
        "interests": ["beaches", "food"],
        "transport_pref": "flights",
        "pace": "relaxed",
    }
    result = concierge_node(state)
    norm = result["normalized_input"]

    # 1. Check dictionary contract
    assert isinstance(norm, dict), "normalized_input must be a dict"

    # 2. Check canonicalization
    assert norm["destination"] == "Goa, India", f"Expected 'Goa, India', got {norm['destination']}"
    assert norm["origin_city"] == "Mumbai, India", f"Expected 'Mumbai, India', got {norm['origin_city']}"

    # 3. Check schema validity with Pydantic
    validated = NormalizedInput(**norm)
    assert validated.num_travelers == 2
    assert validated.budget == 25000.0
    print("✅ Standard Trip: PASSED")


def test_duration_capping():
    state = {
        "trip_id": "test-capping",
        "destination": "Jaipur",
        "origin_city": "Delhi",
        "start_date": "2026-12-01",
        "end_date": "2026-12-20",  # 20 days requested
        "budget": 50000.0,
    }
    result = concierge_node(state)
    norm = result["normalized_input"]

    # Check 7-day cap: Dec 01 to Dec 07 = 7 days
    assert norm["end_date"] == "2026-12-07", f"Expected '2026-12-07', got {norm['end_date']}"
    print("✅ 7-Day Duration Capping: PASSED")


def test_defaults_and_sanitization():
    state = {
        "trip_id": "test-defaults",
        "destination": "Varanasi",
        "origin_city": "Kolkata",
        "start_date": "2026-10-01",
        "end_date": "2026-10-03",
        "budget": -500,          # Invalid negative budget
        "num_travelers": 0,      # Invalid 0 travelers
        "transport_pref": "rocket", # Invalid mode
        "pace": "hyper",         # Invalid pace
    }
    result = concierge_node(state)
    norm = result["normalized_input"]

    assert norm["budget"] == 0.0, "Negative budget should clamp to 0.0"
    assert norm["num_travelers"] == 1, "0 travelers should default to 1"
    assert norm["transport_pref"] == "any", "Invalid transport_pref should fallback to 'any'"
    assert norm["pace"] == "moderate", "Invalid pace should fallback to 'moderate'"
    print("✅ Defaults & Sanitization: PASSED")


if __name__ == "__main__":
    print("\nRunning Step 0 Concierge Verification...")
    test_standard_trip()
    test_duration_capping()
    test_defaults_and_sanitization()
    print("\n🎉 ALL STEP 0 CHECKS PASSED!\n")