"""budget_node — sums cheapest transport + hotel + activities cost against
budget. All numeric fields deterministic; LLM only supplies suggestions."""

import logging

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from graph.transport_utils import split_by_direction
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


def _is_round_trip(normalized_input: dict) -> bool:
    """A trip needs a return leg only when end_date differs from
    start_date - matches the exact check search_flights/search_trains
    already use to decide whether to fetch a return at all."""
    start = normalized_input.get("start_date")
    end = normalized_input.get("end_date")
    return bool(end) and end != start


def _cheapest_leg_price(options: list[dict], price_key: str) -> float | None:
    """Cheapest single fare in a list of same-direction options for one
    mode. None if nothing in the list has a usable (non-zero) price -
    a price of 0 means the fare lookup failed, not that it's free."""
    prices = [
        float(o[price_key])
        for o in options
        if o.get(price_key) is not None and o[price_key] > 0
    ]
    return min(prices) if prices else None


def _cheapest_transport(state: dict) -> tuple[str | None, float, list[str]]:
    """Cheapest same-mode transport cost across flights/trains/buses/cars.

    Same-mode only: the floor is cheapest-outbound-flight +
    cheapest-return-flight, or cheapest-outbound-train + cheapest-return-
    train, etc. - never outbound-flight + return-train. Mixed-mode
    floors are deliberately out of scope for now (adds complexity for
    a rare case).

    Returns (winning_mode, total_price, gap_notes). gap_notes is
    non-empty when a round trip is needed but at least one mode had a
    priced outbound with no priced return - that mode is excluded from
    the candidate pool entirely rather than silently costed as
    outbound-only, so the reported floor never quietly drops a leg.
    """
    round_trip = _is_round_trip(state["normalized_input"])
    candidates = []
    gap_notes = []

    for mode, price_key in _TRANSPORT_PRICE_FIELDS.items():
        options = state.get(mode, [])
        if not options:
            continue

        by_direction = split_by_direction(options)
        outbound_price = _cheapest_leg_price(by_direction["outbound"], price_key)

        if outbound_price is None:
            continue  # no usable outbound fare for this mode at all

        if not round_trip:
            candidates.append((mode, outbound_price))
            continue

        return_price = _cheapest_leg_price(by_direction["return"], price_key)
        if return_price is None:
            gap_notes.append(
                f"{mode}: outbound fare found but no priced return leg "
                f"- excluded from the transport cost floor."
            )
            continue

        candidates.append((mode, outbound_price + return_price))

    if not candidates:
        return None, 0.0, gap_notes

    winning_mode, total = min(candidates, key=lambda c: c[1])
    return winning_mode, total, gap_notes


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

    transport_mode, transport_cost, transport_gaps = _cheapest_transport(state)
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
    if transport_gaps:
        log.warning("Budget transport gaps: %s", transport_gaps)
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
        "transport_gaps": transport_gaps,
    }

    log.info("Budget analysis: %s", budget_analysis)
    return {"budget_analysis": budget_analysis, "status": "building_itinerary"}