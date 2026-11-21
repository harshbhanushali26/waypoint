"""
test_clean_step3.py — Standalone verification for Step 3
"""

from models.schemas import SearchPlan, NormalizedInput
from prompts.planner_prompt import PLANNER_SYSTEM_PROMPT


def test_planner_prompt_alignment():
    # 1. Assert prompt no longer asks for buses/cars in transport_modes
    assert '["flights", "trains", "buses", "cars"]' not in PLANNER_SYSTEM_PROMPT, (
        "Planner prompt still mentions buses/cars in transport_modes subset"
    )

    # 2. Verify SearchPlan schema validates a tight-budget train plan
    sample_tight_plan = {
        "transport_modes": ["trains"],
        "transport_priority": ["trains"],
        "budget_tier": "tight",
        "reasoning": "Tight budget prioritizes rail travel."
    }
    validated = SearchPlan(**sample_tight_plan)
    assert validated.transport_modes == ["trains"]
    assert validated.budget_tier == "tight"
    print("✅ Planner Prompt & SearchPlan Schema Alignment: PASSED")


def test_normalized_input_clean_init():
    # Verify NormalizedInput accepts clean arguments without needs_clarification
    norm = NormalizedInput(
        destination="Jaipur, India",
        origin_city="New Delhi, India",
        start_date="2026-12-01",
        end_date="2026-12-05",
        budget=20000.0,
        currency="INR",
        num_travelers=2,
    )
    assert norm.destination == "Jaipur, India"
    assert norm.num_travelers == 2
    print("✅ NormalizedInput Schema Clean Initialization: PASSED")


if __name__ == "__main__":
    print("\nRunning Step 3 Verification...")
    test_planner_prompt_alignment()
    test_normalized_input_clean_init()
    print("\n🎉 ALL STEP 3 CHECKS PASSED!\n")