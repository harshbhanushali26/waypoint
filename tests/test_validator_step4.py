"""
test_validator_step4.py — Standalone verification for Step 4
"""

from graph.validator import validator_node


def test_validator_guardrails():
    # Corrupted itinerary with:
    # 1. Out-of-order events (18:00 before 09:00)
    # 2. Activity title with prepended verb ("Visit Fort Aguada" instead of "Fort Aguada")
    # 3. Deliberately wrong total_cost (999999.0)
    corrupted_state = {
        "trip_id": "test-val-1",
        "normalized_input": {"num_travelers": 2},
        "activities": [
            {"name": "Fort Aguada", "est_price_inr": 300.0},
            {"name": "Anjuna Flea Market", "est_price_inr": 0.0}
        ],
        "itinerary": {
            "chosen_transport": [{"price": 4000.0}, {"price": 4000.0}],  # total 8000
            "chosen_hotel": {"total_price": 6000.0},                      # total 6000
            "days": [
                {
                    "date": "2026-11-10",
                    "events": [
                        {"time": "18:00", "type": "activity", "title": "Sunset dinner"},
                        {"time": "09:00", "type": "activity", "title": "Visit Fort Aguada"}, # 300 * 2 = 600
                        {"time": "14:00", "type": "hotel_checkin", "title": "Check in"}
                    ]
                }
            ],
            "total_cost": 999999.0  # Bogus number
        }
    }

    result = validator_node(corrupted_state)
    itinerary = result["itinerary"]

    # 1. Verify chronological sorting: 09:00 -> 14:00 -> 18:00
    times = [ev["time"] for ev in itinerary["days"][0]["events"]]
    assert times == ["09:00", "14:00", "18:00"], f"Expected sorted times, got {times}"
    print("✅ Event Chronological Sorting: PASSED")

    # 2. Verify exact total_cost recalculation:
    # Transport (8000) + Hotel (6000) + Fort Aguada (300 * 2 = 600) = 14600.0
    expected_total = 8000.0 + 6000.0 + 600.0
    assert itinerary["total_cost"] == expected_total, (
        f"Expected total_cost {expected_total}, got {itinerary['total_cost']}"
    )
    print("✅ Fuzzy Activity Price Matching & Exact Cost Math: PASSED")


def test_graph_compilation_with_validator():
    from graph.build_graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    compiled = build_graph(MemorySaver())
    assert "validator" in compiled.nodes, "Validator node must be registered in graph"
    print("✅ StateGraph Wiring with Validator Node: PASSED")


if __name__ == "__main__":
    print("\nRunning Step 4 Verification...")
    test_validator_guardrails()
    test_graph_compilation_with_validator()
    print("\n🎉 ALL STEP 4 CHECKS PASSED!\n")