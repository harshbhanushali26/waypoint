"""
agents/itinerary_builder.py

Composes the day-by-day itinerary. Runs in:
    - BUILD mode: First pass, composes from tool search results.
    - REVISE mode: Re-entered via Critic; receives the previous itinerary plus
        fresh tool candidates to perform targeted swaps.
"""

import time
import logging
from datetime import date, timedelta

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.itinerary_builder_prompt import ITINERARY_BUILDER_SYSTEM_PROMPT, build_itinerary_builder_user_message
from prompts.itinerary_reviser_prompt import ITINERARY_REVISER_SYSTEM_PROMPT, build_itinerary_reviser_user_message
from models.schemas import Itinerary
from graph.state import TripState
from graph.transport_utils import top_n_per_direction

logger = logging.getLogger(__name__)

# Field allowlists (pruned to optimize prompt token usage)
_FLIGHT_FIELDS = [
    "flight_id", "direction", "airline", "flight_number",
    "departure_airport", "departure_airport_name",
    "arrival_airport", "arrival_airport_name",
    "departure_time", "arrival_time", "price", "stops",
]

_TRAIN_FIELDS = [
    "train_id", "train_number", "train_name",
    "departure_station", "departure_station_name", "departure_city",
    "arrival_station", "arrival_station_name", "arrival_city",
    "departure_time", "arrival_time", "price", "direction", "class_code",
]

_HOTEL_FIELDS = [
    "hotel_id", "name", "rating", "total_price",
    "check_in_time", "check_out_time", "latitude", "longitude",
]

_ACTIVITY_FIELDS = [
    "name", "category", "area",
    "est_duration_hours", "est_price_inr",
]

_TRANSPORT_TOP_N_PER_DIRECTION = 2
_ACTIVITIES_PER_DAY_BY_PACE = {"relaxed": 2, "moderate": 3, "packed": 4}


# ── Data Gap Collector ───────────────────────────────────────────────────────

def _collect_data_gaps(state: TripState, transport_modes: set[str]) -> list[str]:
    gaps = []

    def _check(note_key: str, result_key: str, expected: bool):
        if not expected:
            return
        if state.get(result_key):
            return
        note = state.get(note_key)
        if note:
            gaps.append(note)

    _check("flights_note", "flights", "flights" in transport_modes)
    _check("trains_note", "trains", "trains" in transport_modes)
    _check("hotels_note", "hotels", True)
    _check("activities_note", "activities", True)
    _check("weather_note", "weather", True)

    return gaps


# ── Allowlist Trimmer ────────────────────────────────────────────────────────

def _trim(objects: list[dict], allowed_fields: list[str]) -> list[dict]:
    return [
        {k: obj[k] for k in allowed_fields if k in obj}
        for obj in objects
        if isinstance(obj, dict)
    ]


# ── Date & Weather Helpers ───────────────────────────────────────────────────

def _compute_trip_dates(start_date: str, end_date: str) -> list[str]:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        days = (end - start).days + 1
        return [(start + timedelta(days=i)).isoformat() for i in range(max(days, 1))]
    except Exception:
        return [start_date]


def _filter_weather_to_trip_dates(weather: list[dict], start_date: str, end_date: str) -> list[dict]:
    if not weather:
        return []
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        return [
            w for w in weather
            if "date" in w and start <= date.fromisoformat(w["date"]) <= end
        ]
    except Exception:
        return weather[:7]


# ── Cost Computation ─────────────────────────────────────────────────────────

def _scheduled_activities_cost(
    itinerary: dict, activities: list[dict], num_travelers: int, log
) -> tuple[float, list[str]]:
    price_by_name = {
        a["name"]: float(a["est_price_inr"])
        for a in activities
        if a.get("name") and a.get("est_price_inr") is not None
    }

    total = 0.0
    scheduled_names = []

    for day in itinerary.get("days", []):
        for ev in day.get("events", []):
            if ev.get("type") == "activity":
                title = ev.get("title", "")
                if title in price_by_name:
                    total += price_by_name[title] * num_travelers
                    scheduled_names.append(title)

    return total, scheduled_names


def _compute_total_cost(
    itinerary: dict, activities: list[dict], num_travelers: int, log
) -> float:
    total = 0.0

    # Transport legs
    for t in itinerary.get("chosen_transport", []):
        if t.get("price"):
            total += float(t["price"])

    # Hotel
    hotel = itinerary.get("chosen_hotel")
    if hotel and hotel.get("total_price"):
        total += float(hotel["total_price"])

    # Car
    car = itinerary.get("chosen_car")
    if car and car.get("total_price"):
        total += float(car["total_price"])

    # Activities
    act_total, _ = _scheduled_activities_cost(itinerary, activities, num_travelers, log)
    total += act_total

    return round(total, 2)


# ── Node Entry Point ─────────────────────────────────────────────────────────

def itinerary_builder_node(state: TripState) -> dict:
    """
    Composes or revises the itinerary using openai/gpt-oss-120b.
    """
    normalized_input = state["normalized_input"]
    log = get_trip_logger(logger, state["trip_id"])
    num_travelers = normalized_input.get("num_travelers", 1)

    trip_dates = _compute_trip_dates(
        normalized_input["start_date"],
        normalized_input["end_date"],
    )

    # Groq TPM window safety pacing
    last_llm_time = state.get("_budget_llm_done_at")
    if last_llm_time:
        elapsed = time.time() - last_llm_time
        remaining = 25.0 - elapsed
        if remaining > 0:
            log.info("Pacing Groq TPM window: waiting %.1fs before building itinerary...", remaining)
            time.sleep(remaining)
    else:
        time.sleep(10)

    structured_llm = get_structured_llm(
        Itinerary,
        model_tier="reasoning",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["itinerary_builder"],
    )

    # ─────────────────────────────────────────────────────────────────────────
    # REVISE MODE: User requested targeted edits in Human Review
    # ─────────────────────────────────────────────────────────────────────────
    if state.get("critic_analysis"):
        critic_analysis = state["critic_analysis"]
        log.info("Itinerary Builder: executing REVISE mode for: %r", critic_analysis.get("interpretation"))

        candidate_hotels = _trim(state.get("hotels", [])[:4], _HOTEL_FIELDS)
        candidate_flights = _trim(top_n_per_direction(state.get("flights", []), "price", 2), _FLIGHT_FIELDS)
        candidate_trains = _trim(top_n_per_direction(state.get("trains", []), "price", 2), _TRAIN_FIELDS)
        candidate_activities = _trim(state.get("activities", [])[:14], _ACTIVITY_FIELDS)

        prev_itinerary = state.get("itinerary", {})
        revise_slice = {
            "previous_itinerary": prev_itinerary,
            "edit_request": critic_analysis["interpretation"],
            "trip_dates": trip_dates,
            "candidate_hotels": candidate_hotels,
            "candidate_flights": candidate_flights,
            "candidate_trains": candidate_trains,
            "candidate_activities": candidate_activities,
        }

        revise_user_message = build_itinerary_reviser_user_message(revise_slice)
        response = structured_llm.invoke([
            {"role": "system", "content": ITINERARY_REVISER_SYSTEM_PROMPT},
            {"role": "user", "content": revise_user_message},
        ])

        log.debug("Itinerary reviser token usage: %s", response["raw"].usage_metadata)

        if response["parsed"] is None:
            log.error(
                "Itinerary revision parsing failed. raw_content=%r usage=%s",
                response["raw"].content, response["raw"].usage_metadata,
            )
            raise RuntimeError("Itinerary revision parsing failed - see logged raw content above")

        itinerary = response["parsed"].model_dump()
        itinerary["data_gaps"] = prev_itinerary.get("data_gaps", [])
        itinerary["total_cost"] = _compute_total_cost(itinerary, state.get("activities", []), num_travelers, log)

        log.info("Itinerary revised successfully. New total_cost: %.2f", itinerary["total_cost"])
        return {"itinerary": itinerary, "status": "awaiting_review"}

    # ─────────────────────────────────────────────────────────────────────────
    # BUILD MODE: Initial full itinerary generation
    # ─────────────────────────────────────────────────────────────────────────
    log.info("Itinerary Builder: executing BUILD mode")

    search_plan = state.get("search_plan", {})
    transport_modes = set(search_plan.get("transport_modes", []))

    flights = state.get("flights", []) if "flights" in transport_modes else []
    trains = state.get("trains", []) if "trains" in transport_modes else []
    hotels = state.get("hotels", [])
    activities = state.get("activities", [])
    weather = state.get("weather", [])

    flights = top_n_per_direction(flights, "price", _TRANSPORT_TOP_N_PER_DIRECTION)
    trains = top_n_per_direction(trains, "price", _TRANSPORT_TOP_N_PER_DIRECTION)

    flights = _trim(flights, _FLIGHT_FIELDS)
    trains = _trim(trains, _TRAIN_FIELDS)
    hotels = _trim([h for h in hotels if h.get("total_price", 0) > 0][:3], _HOTEL_FIELDS)

    per_day = _ACTIVITIES_PER_DAY_BY_PACE.get(normalized_input.get("pace", "moderate"), 3)
    target_act_count = max(len(trip_dates) * per_day, 8)
    activities = _trim(activities[:target_act_count], _ACTIVITY_FIELDS)

    weather = _filter_weather_to_trip_dates(
        weather,
        normalized_input["start_date"],
        normalized_input["end_date"],
    )

    build_slice = {
        "trip_summary": {
            "destination": normalized_input["destination"],
            "start_date": normalized_input["start_date"],
            "end_date": normalized_input["end_date"],
            "num_travelers": num_travelers,
        },
        "trip_dates": trip_dates,
        "pace": normalized_input["pace"],
        "search_plan": search_plan,
        "flights": flights,
        "trains": trains,
        "hotels": hotels,
        "activities": activities,
        "weather": weather,
        "budget_analysis": state.get("budget_analysis", {}),
    }

    build_user_message = build_itinerary_builder_user_message(build_slice)
    response = structured_llm.invoke([
        {"role": "system", "content": ITINERARY_BUILDER_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message},
    ])

    log.debug("Itinerary builder token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Itinerary build parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Itinerary build parsing failed - see logged raw content above")

    itinerary = response["parsed"].model_dump()
    itinerary["total_cost"] = _compute_total_cost(itinerary, activities, num_travelers, log)
    itinerary["data_gaps"] = _collect_data_gaps(state, transport_modes)

    log.info("Itinerary built successfully. Total cost: %.2f", itinerary["total_cost"])
    return {"itinerary": itinerary, "status": "awaiting_review"}