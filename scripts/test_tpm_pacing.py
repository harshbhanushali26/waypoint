"""
scripts/test_tpm_pacing.py

Stress-tests Groq TPM risk with two scenarios, using real Groq calls and
real prompts/schemas -- no mocking. This does NOT go through the compiled
graph or node functions directly (several depend on interrupt(), which
needs a real graph context) -- it calls the same LLM invocations each node
would make, in the same sequence, with real AGENT_MAX_TOKENS values.

Scenario 1: one normal build run (Concierge -> Planner -> Budget ->
Itinerary Builder build mode), back to back, no delay.

Scenario 2: rapid Itinerary Builder REVISE-mode calls fired back to back,
simulating a user sending several quick edits in human_review. Critic is
NOT called here (prompts/critic_prompt.py wasn't available for this
script) -- edit_request strings are hand-written to stand in for what
Critic would normally produce. This still exercises the heaviest call
(5000 max_tokens) repeatedly, which is the real risk driver.

Watches for Groq 429s directly rather than just computing a token sum --
that's the real signal, not a manual estimate.

Run via: uv run python -m scripts.test_tpm_pacing
"""

import time

from core.llm import AGENT_MAX_TOKENS, get_structured_llm

from prompts.concierge_prompt import CONCIERGE_SYSTEM_PROMPT, build_concierge_user_message
from prompts.planner_prompt import PLANNER_SYSTEM_PROMPT, build_planner_user_message
from prompts.budget_prompt import BUDGET_SYSTEM_PROMPT, build_budget_user_message
from prompts.itinerary_builder_prompt import ITINERARY_BUILDER_SYSTEM_PROMPT, build_itinerary_builder_user_message
from prompts.itinerary_reviser_prompt import ITINERARY_REVISER_SYSTEM_PROMPT, build_itinerary_reviser_user_message

from models.schemas import NormalizedInput, SearchPlan, BudgetAnalysis, Itinerary

from agents.itinerary_builder import (
    _compute_trip_dates,
    _filter_weather_to_trip_dates,
    _filter_priced_trains,
    _trim,
    _TRAIN_FIELDS,
    _HOTEL_FIELDS,
    _ACTIVITY_FIELDS,
)


START_TIME = time.monotonic()


def _elapsed() -> str:
    return f"{time.monotonic() - START_TIME:.2f}s"


def _invoke_and_report(agent_name: str, structured_llm, messages, max_tokens):
    """Real Groq call. Reports elapsed time, token usage, or a 429 if hit."""
    try:
        response = structured_llm.invoke(messages, max_tokens=max_tokens)
        usage = response["raw"].usage_metadata
        print(f"[{_elapsed()}] {agent_name} OK -- usage: {usage}")
        if response["parsed"] is None:
            print(f"[{agent_name}] WARNING: parsing failed -- {response['raw'].content}")
        return response
    except Exception as e:
        msg = str(e)
        is_rate_limit = "429" in msg or "rate_limit" in msg.lower()
        tag = "RATE LIMIT HIT" if is_rate_limit else "ERROR"
        print(f"[{_elapsed()}] {agent_name} {tag}: {type(e).__name__}: {msg}")
        return None


# --- Sample trip: Vapi -> Ahmedabad, 6 days, trains, moderate pace ---

RAW_FORM_INPUT = {
    "destination": "Ahmedabad",
    "origin_city": "Vapi",
    "start_date": "2026-10-01",
    "end_date": "2026-10-06",
    "budget": 15000.0,
    "currency": "INR",
    "num_travelers": 1,
    "interests": ["heritage", "food"],
    "transport_pref": "trains",
    "wants_rental_car": False,
    "pace": "moderate",
}

DUMMY_TRAINS = [
    {"train_id": "t1", "train_number": "19023", "train_name": "Firozpur Janata Express",
     "departure_station": "Vapi", "arrival_station": "Ahmedabad", "departure_time": "06:10",
     "arrival_time": "12:40", "price": 320.0, "direction": "outbound", "class_code": "SL"},
    {"train_id": "t2", "train_number": "12933", "train_name": "Karmali Mumbai CSMT Express",
     "departure_station": "Ahmedabad", "arrival_station": "Vapi", "departure_time": "17:20",
     "arrival_time": "23:50", "price": 340.0, "direction": "return", "class_code": "SL"},
]

DUMMY_HOTELS = [
    {"hotel_id": "h1", "name": "Hotel Cama", "rating": 4.1, "total_price": 6500.0,
     "check_in_time": "12:00", "check_out_time": "11:00", "latitude": 23.03, "longitude": 72.58},
]

DUMMY_ACTIVITIES = [
    {"title": "Sabarmati Ashram", "snippet": "Gandhi's former residence and museum.", "url": "https://example.com/1"},
    {"title": "Adalaj Stepwell", "snippet": "Intricately carved 15th-century stepwell.", "url": "https://example.com/2"},
    {"title": "Manek Chowk street food", "snippet": "Famous night food market.", "url": "https://example.com/3"},
]

DUMMY_WEATHER_RAW = [
    {"date": "2026-10-01", "condition": "Clear sky", "temp_max_c": 34.0, "temp_min_c": 24.0, "temp_avg_c": 29.0},
    {"date": "2026-10-02", "condition": "Partly cloudy", "temp_max_c": 33.5, "temp_min_c": 23.5, "temp_avg_c": 28.5},
    {"date": "2026-10-03", "condition": "Clear sky", "temp_max_c": 35.0, "temp_min_c": 24.5, "temp_avg_c": 29.7},
    {"date": "2026-10-04", "condition": "Overcast", "temp_max_c": 32.0, "temp_min_c": 23.0, "temp_avg_c": 27.5},
    {"date": "2026-10-05", "condition": "Clear sky", "temp_max_c": 34.5, "temp_min_c": 24.0, "temp_avg_c": 29.2},
    {"date": "2026-10-06", "condition": "Partly cloudy", "temp_max_c": 33.0, "temp_min_c": 23.5, "temp_avg_c": 28.2},
]


def scenario_1_normal_run():
    print("\n=== SCENARIO 1: normal build run (Concierge -> Planner -> Budget -> Itinerary Builder) ===")

    # --- Concierge ---
    concierge_llm = get_structured_llm(NormalizedInput, include_raw=True)
    concierge_response = _invoke_and_report(
        "Concierge",
        concierge_llm,
        [
            {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
            {"role": "user", "content": build_concierge_user_message(RAW_FORM_INPUT)},
        ],
        AGENT_MAX_TOKENS["concierge"],
    )
    if concierge_response is None or concierge_response["parsed"] is None:
        print("Aborting scenario 1 -- Concierge did not return usable output.")
        return None

    normalized = concierge_response["parsed"].model_dump()
    if normalized.get("needs_clarification"):
        print(f"Concierge asked for clarification: {normalized.get('clarification_question')}")
        print("Aborting scenario 1 -- can't proceed without a resolved trip (this script has no interrupt/resume loop).")
        return None

    # Fill in TripContext-shaped normalized_input (Concierge only returns non-null
    # trip fields when needs_clarification is False, per NormalizedInput's contract)
    normalized_input = {k: v for k, v in normalized.items()
                         if k not in ("needs_clarification", "clarification_question")}

    # --- Planner ---
    planner_llm = get_structured_llm(SearchPlan, include_raw=True)
    planner_response = _invoke_and_report(
        "Planner",
        planner_llm,
        [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": build_planner_user_message(normalized_input)},
        ],
        AGENT_MAX_TOKENS["planner"],
    )
    if planner_response is None or planner_response["parsed"] is None:
        print("Aborting scenario 1 -- Planner did not return usable output.")
        return None
    search_plan = planner_response["parsed"].model_dump()

    # --- Budget ---
    transport_cost = min(t["price"] for t in DUMMY_TRAINS)
    hotel_cost = min(h["total_price"] for h in DUMMY_HOTELS)
    activities_cost = 0.0  # no price field on trimmed activities, matches real budget_node behavior
    estimated_total = transport_cost + hotel_cost + activities_cost
    over_budget = estimated_total > RAW_FORM_INPUT["budget"]

    budget_state_slice = {
        "budget": RAW_FORM_INPUT["budget"],
        "currency": RAW_FORM_INPUT["currency"],
        "estimated_total": estimated_total,
        "cost_breakdown": {"trains": transport_cost, "hotels": hotel_cost, "activities": activities_cost},
        "over_budget": over_budget,
        "overage_amount": max(estimated_total - RAW_FORM_INPUT["budget"], 0.0),
    }

    budget_llm = get_structured_llm(BudgetAnalysis, include_raw=True)
    budget_response = _invoke_and_report(
        "Budget",
        budget_llm,
        [
            {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
            {"role": "user", "content": build_budget_user_message(budget_state_slice)},
        ],
        AGENT_MAX_TOKENS["budget"],
    )
    if budget_response is None:
        print("Aborting scenario 1 -- Budget did not return usable output.")
        return None

    suggestions = budget_response["parsed"].suggestions if (budget_response["parsed"] and over_budget) else []
    budget_analysis = {
        "estimated_total": estimated_total,
        "cost_breakdown": budget_state_slice["cost_breakdown"],
        "budget": RAW_FORM_INPUT["budget"],
        "over_budget": over_budget,
        "overage_amount": budget_state_slice["overage_amount"],
        "suggestions": suggestions,
    }

    # --- Itinerary Builder (build mode) ---
    trip_dates = _compute_trip_dates(normalized_input["start_date"], normalized_input["end_date"])
    trains = _filter_priced_trains(_trim(DUMMY_TRAINS, _TRAIN_FIELDS))
    hotels = _trim(DUMMY_HOTELS, _HOTEL_FIELDS)
    activities = _trim(DUMMY_ACTIVITIES, _ACTIVITY_FIELDS)
    weather = _filter_weather_to_trip_dates(DUMMY_WEATHER_RAW, normalized_input["start_date"], normalized_input["end_date"])

    itinerary_state_slice = {
        "search_plan": search_plan,
        "flights": [],
        "trains": trains,
        "buses": [],
        "cars": [],
        "hotels": hotels,
        "activities": activities,
        "weather": weather,
        "budget_analysis": budget_analysis,
        "trip_summary": {
            "destination": normalized_input["destination"],
            "start_date": normalized_input["start_date"],
            "end_date": normalized_input["end_date"],
            "num_travelers": normalized_input["num_travelers"],
        },
        "trip_dates": trip_dates,
        "pace": normalized_input["pace"],
        "wants_rental_car": normalized_input["wants_rental_car"],
    }

    itinerary_llm = get_structured_llm(Itinerary, include_raw=True)
    itinerary_response = _invoke_and_report(
        "Itinerary Builder (build)",
        itinerary_llm,
        [
            {"role": "system", "content": ITINERARY_BUILDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_itinerary_builder_user_message(itinerary_state_slice)},
        ],
        AGENT_MAX_TOKENS["itinerary_builder"],
    )
    if itinerary_response is None or itinerary_response["parsed"] is None:
        print("Scenario 1 finished, but Itinerary Builder did not return usable output.")
        return None

    print(f"[{_elapsed()}] Scenario 1 complete.")
    return itinerary_response["parsed"].model_dump(), trip_dates


def scenario_2_rapid_revise_burst(previous_itinerary: dict, trip_dates: list[str], num_edits: int = 4):
    print(f"\n=== SCENARIO 2: {num_edits} rapid Itinerary Builder REVISE-mode calls (Critic skipped -- see script header) ===")

    edit_requests = [
        "Make day 2 cheaper -- swap to a lower-cost activity if possible.",
        "Reduce walking on day 3.",
        "Move the food market visit to evening.",
        "Add a short buffer before the return train on the last day.",
    ]

    itinerary_llm = get_structured_llm(Itinerary, include_raw=True)
    current_itinerary = previous_itinerary

    for i in range(num_edits):
        edit_request = edit_requests[i % len(edit_requests)]
        revise_slice = {
            "previous_itinerary": current_itinerary,
            "edit_request": edit_request,
            "trip_dates": trip_dates,
        }

        response = _invoke_and_report(
            f"Revise #{i+1} ('{edit_request[:30]}...')",
            itinerary_llm,
            [
                {"role": "system", "content": ITINERARY_REVISER_SYSTEM_PROMPT},
                {"role": "user", "content": build_itinerary_reviser_user_message(revise_slice)},
            ],
            AGENT_MAX_TOKENS["itinerary_builder"],
        )

        if response is None or response["parsed"] is None:
            print(f"Stopping burst early at revise #{i+1} -- no usable output.")
            break

        current_itinerary = response["parsed"].model_dump()

    print(f"[{_elapsed()}] Scenario 2 complete.")


if __name__ == "__main__":
    result = scenario_1_normal_run()
    if result is not None:
        itinerary, trip_dates = result
        scenario_2_rapid_revise_burst(itinerary, trip_dates, num_edits=4)
    else:
        print("\nSkipping scenario 2 -- scenario 1 did not produce a usable itinerary to revise.")