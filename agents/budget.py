"""budget_node — sums cheapest transport + hotel + activities cost against
budget. All numeric fields deterministic; LLM only supplies suggestions."""

import logging

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.budget_prompt import BUDGET_SYSTEM_PROMPT, build_budget_user_message
from models.schemas import BudgetAnalysis
from graph.state import TripState


logger = logging.getLogger(__name__)

# ── Price field mapping per transport mode ───────────────────────────
# Each tool node normalizes its API response differently.  This map
# tells the budget node which key to read for the fare, so we never
# silently skip a mode because the field name didn't match.
#
#   flights  → "price"        (SerpApi / _normalize_flight)
#   trains   → "price"        (RailRadar / _normalize_train — totalFare
#                             is renamed to "price" during normalization)
#   buses    → "price"        (dummy data, same key as flights)
#   cars     → "price"        (dummy data, same key as flights)
#
# If a future tool uses a different key, add it here — nothing else
# in this file needs to change.
_TRANSPORT_PRICE_FIELDS = {
    "flights": "price",
    "trains":  "price",
    "buses":   "price",
    "cars":    "price",
}


def _cheapest_transport(state: dict) -> tuple[str | None, float]:
    """Cheapest single option across flights/trains/buses/cars.

    Each mode may use a different key for the fare (see
    _TRANSPORT_PRICE_FIELDS), so we look up the correct key per mode
    instead of hardcoding "price" for all of them.

    Returns (winning_mode, price) or (None, 0.0) if nothing searched
    or no option in any mode has a fare.
    """
    candidates = []

    for mode, price_key in _TRANSPORT_PRICE_FIELDS.items():
        for option in state.get(mode, []):
            price = option.get(price_key)
            # Skip None and 0 — a price of 0 means the fare lookup
            # failed (e.g. rate limited), not that the option is free.
            if price is not None and price > 0:
                candidates.append((mode, float(price)))

    if not candidates:
        return None, 0.0

    return min(candidates, key=lambda c: c[1])


def _cheapest_hotel(state: dict) -> float:
    """Cheapest hotel by total_price."""
    hotels = state.get("hotels", [])
    prices = [
        h["total_price"]
        for h in hotels
        if h.get("total_price") is not None and h["total_price"] > 0
    ]
    return min(prices) if prices else 0.0


def _activities_cost(state: dict) -> float:
    """Sum of activity prices. Returns 0.0 when no price data exists (v1)."""
    activities = state.get("activities", [])
    return sum(
        a["price"] for a in activities if a.get("price") is not None
    )


def budget_node(state: TripState) -> dict:
    """Computes budget_analysis (deterministic) plus LLM-generated
    suggestions when over budget."""
    budget = state["normalized_input"]["budget"]

    log = get_trip_logger(logger, state["trip_id"])

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
    # Every numeric field below is computed deterministically, not trusted
    # from the model.
    structured_llm = get_structured_llm(BudgetAnalysis)

    state_slice = {
        "budget": budget,
        "currency": state["normalized_input"]["currency"],
        "estimated_total": estimated_total,
        "cost_breakdown": cost_breakdown,
        "over_budget": over_budget,
        "overage_amount": overage_amount,
    }

    user_message = build_budget_user_message(state_slice)
    log.debug(
        "Budget pre-LLM: transport=%s@%.2f hotel=%.2f activities=%.2f total=%.2f budget=%.2f",
        transport_mode, transport_cost, hotel_cost, activities_cost,
        estimated_total, budget,
    )
    log.debug(
        "Budget input: system_prompt_len=%d user_msg_len=%d",
        len(BUDGET_SYSTEM_PROMPT), len(user_message),
    )

    response = structured_llm.invoke(
        [
            {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
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

    log.info("Budget analysis: %s", budget_analysis)
    return {"budget_analysis": budget_analysis, "status": "building_itinerary"}