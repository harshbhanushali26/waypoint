"""
agents/budget.py

Deterministic budget floor calculation with gpt-oss-20b suggestions.
Computes cheapest transport, hotel, and pace-scaled activities.
Stamps _budget_llm_done_at so the Itinerary Builder can pace Groq TPM quota.
"""

import time
import logging
from datetime import date

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from graph.transport_utils import split_by_direction
from prompts.budget_prompt import BUDGET_SYSTEM_PROMPT, build_budget_user_message
from models.schemas import BudgetAnalysis
from graph.state import TripState

logger = logging.getLogger(__name__)


def _cheapest_leg(options: list[dict], price_key: str = "price") -> float | None:
    prices = [float(o[price_key]) for o in options if o.get(price_key) is not None and o[price_key] > 0]
    return min(prices) if prices else None


def _cheapest_transport(state: dict) -> tuple[str | None, float]:
    candidates = []
    is_round_trip = state["normalized_input"]["start_date"] != state["normalized_input"]["end_date"]

    for mode in ["flights", "trains"]:
        options = state.get(mode, [])
        if not options:
            continue
        grouped = split_by_direction(options)
        outbound = _cheapest_leg(grouped["outbound"])
        if outbound is None:
            continue

        if not is_round_trip:
            candidates.append((mode, outbound))
        else:
            ret = _cheapest_leg(grouped["return"])
            if ret is not None:
                candidates.append((mode, outbound + ret))

    if not candidates:
        return None, 0.0
    return min(candidates, key=lambda c: c[1])


def budget_node(state: TripState) -> dict:
    log = get_trip_logger(logger, state["trip_id"])
    normalized_input = state["normalized_input"]
    budget = normalized_input["budget"]
    num_travelers = normalized_input.get("num_travelers", 1)

    transport_mode, transport_cost = _cheapest_transport(state)

    hotels = state.get("hotels", [])
    hotel_prices = [h["total_price"] for h in hotels if h.get("total_price", 0) > 0]
    hotel_cost = min(hotel_prices) if hotel_prices else 0.0

    activities = state.get("activities", [])
    act_prices = sorted([
        float(a["est_price_inr"])
        for a in activities
        if a.get("est_price_inr") is not None and float(a.get("est_price_inr", 0)) > 0
    ])
    activities_cost = sum(act_prices[:6]) * num_travelers if act_prices else 0.0

    cost_breakdown = {"hotels": hotel_cost, "activities": activities_cost}
    if transport_mode:
        cost_breakdown[transport_mode] = transport_cost

    estimated_total = transport_cost + hotel_cost + activities_cost
    over_budget = estimated_total > budget
    overage = max(estimated_total - budget, 0.0)

    state_slice = {
        "budget": budget,
        "currency": normalized_input["currency"],
        "estimated_total": estimated_total,
        "cost_breakdown": cost_breakdown,
        "over_budget": over_budget,
        "overage_amount": overage,
    }

    user_message = build_budget_user_message(state_slice)
    structured_llm = get_structured_llm(
        BudgetAnalysis,
        model_tier="fast",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["budget"],
    )

    log.debug(
        "Budget input: system_prompt_len=%d user_msg_len=%d",
        len(BUDGET_SYSTEM_PROMPT), len(user_message),
    )

    response = structured_llm.invoke([
        {"role": "system", "content": BUDGET_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ])

    log.debug("Budget token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Budget parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Budget parsing failed - see logged raw content above")

    budget_analysis = {
        "estimated_total": estimated_total,
        "cost_breakdown": cost_breakdown,
        "budget": budget,
        "over_budget": over_budget,
        "overage_amount": overage,
        "suggestions": response["parsed"].suggestions if over_budget else [],
    }

    log.info("Budget: estimated_total=%.2f, budget=%.2f", estimated_total, budget)
    return {
        "budget_analysis": budget_analysis,
        "status": "building_itinerary",
        "_budget_llm_done_at": time.time(),
    }