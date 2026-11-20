"""
graph/validator.py

Deterministic post-builder guardrail node.
Enforces chronological event ordering, resilient activity cost matching,
and exact total_cost calculation before presenting the itinerary to human review.
Zero API calls — pure Python.
"""

import logging
from graph.state import TripState
from core.logging import get_trip_logger

logger = logging.getLogger(__name__)


def _clean_str(s: str) -> str:
    """Lowercase and strip noise for fuzzy title matching."""
    if not s:
        return ""
    # Strip common leading action verbs
    cleaned = s.lower().strip()
    for verb in ("visit ", "explore ", "enjoy ", "tour ", "see ", "relax at "):
        if cleaned.startswith(verb):
            cleaned = cleaned[len(verb):].strip()
    return cleaned


def _match_activity_price(title: str, activities: list[dict]) -> float:
    """Matches scheduled event title against catalog activities to find estimated price."""
    clean_title = _clean_str(title)
    if not clean_title:
        return 0.0

    for act in activities:
        act_name = _clean_str(act.get("name", ""))
        if not act_name:
            continue
        # Direct match or substring containment
        if act_name == clean_title or act_name in clean_title or clean_title in act_name:
            price = act.get("est_price_inr")
            if price is not None and float(price) > 0:
                return float(price)
    return 0.0


def validator_node(state: TripState) -> dict:
    """
    Guardrail node between itinerary_builder and human_review.
    Cleans, sorts, and recalculates exact costs in Python.
    """
    trip_id = state.get("trip_id", "-")
    log = get_trip_logger(logger, trip_id)
    log.info("Validator: verifying chronology and recalculating exact costs")

    itinerary = state.get("itinerary")
    if not itinerary or not isinstance(itinerary, dict):
        log.warning("Validator: no valid itinerary in state; skipping.")
        return {}

    num_travelers = max(int(state.get("normalized_input", {}).get("num_travelers", 1)), 1)
    catalog_activities = state.get("activities", [])

    # 1. Deterministic Chronological Sorting for every day
    days = itinerary.get("days", [])
    for day in days:
        events = day.get("events", [])
        # Sort events by time string ("HH:MM")
        events.sort(key=lambda ev: ev.get("time", "00:00"))
        day["events"] = events

    # 2. Compute exact transport cost
    transport_cost = 0.0
    for leg in itinerary.get("chosen_transport", []):
        if leg and leg.get("price"):
            try:
                transport_cost += float(leg["price"])
            except (ValueError, TypeError):
                pass

    # 3. Compute exact hotel cost
    hotel = itinerary.get("chosen_hotel", {})
    hotel_cost = 0.0
    if hotel and hotel.get("total_price"):
        try:
            hotel_cost += float(hotel["total_price"])
        except (ValueError, TypeError):
            pass

    # 4. Compute scheduled activities cost using fuzzy matching
    activities_cost = 0.0
    for day in days:
        for ev in day.get("events", []):
            if ev.get("type") == "activity":
                unit_price = _match_activity_price(ev.get("title", ""), catalog_activities)
                activities_cost += unit_price * num_travelers

    # 5. Exact total arithmetic
    exact_total = round(transport_cost + hotel_cost + activities_cost, 2)
    itinerary["total_cost"] = exact_total

    log.info(
        "Validator completed: %d days sorted. Verified total_cost: %.2f (transport=%.2f, hotel=%.2f, activities=%.2f)",
        len(days), exact_total, transport_cost, hotel_cost, activities_cost
    )

    return {"itinerary": itinerary}