import json
import logging

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from prompts.budget_prompt import BUDGET_SYSTEM_PROMPT, build_budget_user_message
from models.schemas import BudgetAnalysis
from graph.state import TripState


logger = logging.getLogger(__name__)



def _cheapest_transport(state: dict) -> tuple[str | None, float]:
    """Cheapest single option across flights/trains/buses/cars.
    Returns (winning_mode, price) or (None, 0.0) if nothing searched."""

    candidates = []
    for mode in ("flights", "trains", "buses", "cars"):
        for option in state.get(mode, []):
            price = option.get("price")
            if price is not None:
                candidates.append((mode, price))

    if not candidates:
        return None, 0.0

    return min(candidates, key=lambda c: c[1])      # c[1] -> price element 


def _cheapest_hotel(state: dict) -> float:
    hotels = state.get("hotels", [])
    prices = [h["total_price"] for h in hotels if h.get("total_price") is not None]
    return min(prices) if prices else 0.0


def _activities_cost(state: dict) -> dict:
    activities = state.get("activities", [])
    # No price data at v1 -> 0, per locked scope. Do not estimate.
    return sum(a["price"] for a in activities if a.get("price") is not None)



def budget_node(state: TripState) -> dict:
    budget = state["normalized_input"]["budget"]

    transport_mode, transport_cost = _cheapest_transport(state)
    hotel_cost = _cheapest_hotel(state)
    activities_cost = _activities_cost(state)

    cost_breakdown = {"hotels": hotel_cost, "activities": activities_cost}
    if transport_mode is not None:
        cost_breakdown[transport_mode] = transport_cost

    estimated_total = transport_cost + hotel_cost + activities_cost
    over_budget = estimated_total > budget
    overage_amount = max(estimated_total - budget, 0.0)

    # LLM call: schema requires all fields, but only `suggestions` is kept.
    # Every numeric field below is computed, not trusted from the model.
    # structured_llm = llm.with_structured_output(BudgetAnalysis)
    structured_llm = get_structured_llm(BudgetAnalysis)

    state_slice = {
        "budget": budget,
        "currency": state["normalized_input"]["currency"],
        "estimated_total": estimated_total,
        "cost_breakdown": cost_breakdown,
        "over_budget": over_budget,
        "overage_amount": overage_amount,
    }

    print("--- Budget ---")
    print(len(BUDGET_SYSTEM_PROMPT))
    print(len(build_budget_user_message(state_slice)))

    response = structured_llm.invoke(
        [
            {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
            {"role": "user", "content": build_budget_user_message(state_slice)},
        ],
        max_tokens=AGENT_MAX_TOKENS["budget"],
    )



    suggestions = response.suggestions if over_budget else []

    budget_analysis = {
        "estimated_total": estimated_total,
        "cost_breakdown": cost_breakdown,
        "budget": budget,
        "over_budget": over_budget,
        "overage_amount": overage_amount,
        "suggestions": suggestions,
    }

    print(f"[Budget] budget_analysis: {budget_analysis}")
    return {"budget_analysis": budget_analysis, "status": "building_itinerary"}