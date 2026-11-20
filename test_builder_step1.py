"""
test_builder_step1.py — Standalone verification for Step 1
"""

from models.schemas import Itinerary


def test_schema_total_cost_resilience():
    # Simulate an LLM payload where Groq cut off before writing total_cost
    truncated_payload = {
        "trip_summary": {
            "destination": "Goa, India",
            "start_date": "2026-11-10",
            "end_date": "2026-11-12",
            "num_travelers": 2
        },
        "chosen_transport": [
            {"leg": "outbound", "mode": "flight", "price": 4500.0}
        ],
        "chosen_hotel": {
            "name": "Baga Retreat",
            "total_price": 6000.0
        },
        "days": [
            {
                "date": "2026-11-10",
                "events": [{"time": "10:00", "type": "activity", "title": "Beach walk", "details": ""}]
            }
        ]
        # Notice: total_cost is completely omitted!
    }

    parsed = Itinerary(**truncated_payload)
    assert parsed.total_cost == 0.0, "total_cost should default to 0.0 without crashing"
    assert parsed.chosen_hotel["name"] == "Baga Retreat"
    print("✅ Schema Resilience (Omitted total_cost): PASSED")


def test_candidate_caps():
    from agents.itinerary_builder import _MAX_ACTIVITIES_FOR_BUILDER, _MAX_HOTELS_FOR_BUILDER, _TRANSPORT_TOP_N_PER_DIRECTION

    assert _TRANSPORT_TOP_N_PER_DIRECTION == 1, "Transport should be capped at 1 per direction"
    assert _MAX_HOTELS_FOR_BUILDER == 2, "Hotels should be capped at 2"
    assert _MAX_ACTIVITIES_FOR_BUILDER <= 8, "Activities should be capped at 8 max"
    print("✅ Candidate Token Pruning Caps: PASSED")


if __name__ == "__main__":
    print("\nRunning Step 1 Verification...")
    test_schema_total_cost_resilience()
    test_candidate_caps()
    print("\n🎉 ALL STEP 1 CHECKS PASSED!\n")