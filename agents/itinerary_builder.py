import json
import logging

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from prompts.itinerary_builder_prompt import ITINERARY_BUILDER_SYSTEM_PROMPT, build_itinerary_builder_user_message
from prompts.itinerary_reviser_prompt import ITINERARY_REVISER_SYSTEM_PROMPT, build_itinerary_reviser_user_message
from models.schemas import Itinerary
from graph.state import TripState
from datetime import date, timedelta

logger = logging.getLogger(__name__)


# --- field allowlists, one per tool-node object type ---
# Rule: keep a field only if a real screen (current or already in the
# design doc, e.g. the Final Itinerary route map) could plausibly show it.
# Internal/derivable fields (duration_minutes, distance_km, per-trip-fixed
# currency) are dropped - they cost tokens and are never surfaced.

_FLIGHT_FIELDS = [
    "flight_id", "direction", "airline", "flight_number",
    "departure_airport", "arrival_airport", "departure_time",
    "arrival_time", "price", "stops",
]

_TRAIN_FIELDS = [
    "train_id", "train_number", "train_name", "departure_station",
    "arrival_station", "departure_time", "arrival_time", "price",
    "direction", "class_code",
]

_BUS_FIELDS = [
    "bus_id", "operator", "departure_station", "arrival_station",
    "departure_time", "arrival_time", "price", "direction",
]

_CAR_FIELDS = [
    "car_id", "provider", "car_type", "pickup_location",
    "dropoff_location", "pickup_time", "dropoff_time", "total_price",
]

_HOTEL_FIELDS = [
    "hotel_id", "name", "rating", "total_price",
    "check_in_time", "check_out_time", "latitude", "longitude",
]


def _trim(objects: list[dict], allowed_fields: list[str]) -> list[dict]:
    """Keep only the allowlisted fields on each object in the list."""
    return [
        {k: obj[k] for k in allowed_fields if k in obj}
        for obj in objects
    ]


def _filter_weather_to_trip_dates(weather: list[dict], start_date: str, end_date: str) -> list[dict]:
    """
    Weather is never count-capped - every calendar day of the trip needs
    its own forecast entry for the prompt's weather-aware sequencing rule
    to work. If the dummy/API data returns more days than the trip spans,
    filter by actual date range, not by a top-N cut.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return [
        w for w in weather
        if "date" in w and start <= date.fromisoformat(w["date"]) <= end
    ]


def _compute_trip_dates(start_date: str, end_date: str) -> list[str]:
    """
    Explicit list of every calendar day in the trip, inclusive of both
    endpoints. Computed here rather than left for the model to derive
    from start_date/end_date - day-count is arithmetic, not judgment,
    and leaving it to inference was producing off-by-one over-generation.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days = (end - start).days + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def itinerary_builder_node(state: TripState) -> dict:
    normalized_input = state["normalized_input"]
    

    trip_dates = _compute_trip_dates(
        normalized_input["start_date"],
        normalized_input["end_date"],
    )

    # --- REVISE MODE: Critic routed back here with an edit request ---
    if state.get("critic_analysis"):
        critic_analysis = state["critic_analysis"]

        revise_slice = {
            "previous_itinerary": state["itinerary"],
            "edit_request": critic_analysis["interpretation"],
            "trip_dates": trip_dates,
        }

        structured_llm = get_structured_llm(Itinerary, include_raw=True)

        print("--- Itinerary (revise mode) ---")
        print(len(ITINERARY_REVISER_SYSTEM_PROMPT))
        print(len(build_itinerary_reviser_user_message(revise_slice)))
        print("No of days", len(trip_dates))

        response = structured_llm.invoke(
            [
                {"role": "system", "content": ITINERARY_REVISER_SYSTEM_PROMPT},
                {"role": "user", "content": build_itinerary_reviser_user_message(revise_slice)},
            ],
            max_tokens=AGENT_MAX_TOKENS["itinerary_builder"],
        )

        print("--- Token usage (revise mode) ---")
        print(response["raw"].usage_metadata)

        if response["parsed"] is None:
            print("--- Parsing failed, raw content ---")
            print(response["raw"].content)
            raise RuntimeError("Itinerary revision parsing failed - see raw content and token usage above")

        itinerary = response["parsed"].model_dump()
        print(f"[Itinerary revise] itinerary: {itinerary}")

        return {"itinerary": itinerary, "status": "awaiting_review"}

    # --- BUILD MODE: first pass, compose from raw search results ---

    search_plan = state["search_plan"]

    transport_modes = set(search_plan.get("transport_modes", []))

    flights = state.get("flights", []) if "flights" in transport_modes else []
    trains = state.get("trains", []) if "trains" in transport_modes else []
    buses = state.get("buses", []) if "buses" in transport_modes else []
    cars = state.get("cars", [])
    hotels = state.get("hotels", [])
    activities = state.get("activities", [])
    weather = state.get("weather", [])

    # Field-trim every object down to what a real screen could show.
    flights = _trim(flights, _FLIGHT_FIELDS)
    trains = _trim(trains, _TRAIN_FIELDS)
    buses = _trim(buses, _BUS_FIELDS)
    cars = _trim(cars, _CAR_FIELDS)
    hotels = _trim(hotels, _HOTEL_FIELDS)

    hotels = hotels[:3]
    activities = activities[:8]

    weather = _filter_weather_to_trip_dates(
        weather,
        normalized_input["start_date"],
        normalized_input["end_date"],
    )

    state_slice = {
        "search_plan": search_plan,
        "flights": flights,
        "trains": trains,
        "buses": buses,
        "cars": cars,
        "hotels": hotels,
        "activities": activities,
        "weather": weather,
        "budget_analysis": state["budget_analysis"],
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

    # structured_llm = get_structured_llm(Itinerary)
    # structured_llm = get_structured_llm(Itinerary, include_raw=True)
    structured_llm = get_structured_llm(Itinerary, include_raw=True)

    print("--- Itinerary (build mode) ---")
    print(len(ITINERARY_BUILDER_SYSTEM_PROMPT))
    print(len(build_itinerary_builder_user_message(state_slice)))

    print("No of days", len(trip_dates))

    response = structured_llm.invoke(
        [
            {"role": "system", "content": ITINERARY_BUILDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_itinerary_builder_user_message(state_slice)},
        ],
        max_tokens=AGENT_MAX_TOKENS["itinerary_builder"],
    )

    # itinerary = response.model_dump()
    # print(f"[Itinerary] itinerary: {itinerary}")

    print("--- Token usage (build mode) ---")
    print(response["raw"].usage_metadata)

    if response["parsed"] is None:
        print("--- Parsing failed, raw content ---")
        print(response["raw"].content)
        raise RuntimeError("Itinerary build parsing failed - see raw content and token usage above")

    itinerary = response["parsed"].model_dump()
    print(f"[Itinerary] itinerary: {itinerary}")

    if not normalized_input["wants_rental_car"] and itinerary.get("chosen_car") is not None:
        logger.warning(
            "itinerary_builder_node: chosen_car was set despite "
            "wants_rental_car=False. chosen_car=%s",
            itinerary["chosen_car"],
        )

    return {"itinerary": itinerary, "status": "awaiting_review"}