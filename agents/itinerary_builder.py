"""itinerary_builder_node — composes the day-by-day itinerary. Runs in BUILD
mode (first pass) or REVISE mode (Critic routed back with an edit request)."""

import logging
from datetime import date, timedelta

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.itinerary_builder_prompt import ITINERARY_BUILDER_SYSTEM_PROMPT, build_itinerary_builder_user_message
from prompts.itinerary_reviser_prompt import ITINERARY_REVISER_SYSTEM_PROMPT, build_itinerary_reviser_user_message
from models.schemas import Itinerary
from graph.state import TripState

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

_ACTIVITY_FIELDS = ["title", "snippet", "url"]


def _collect_data_gaps(state: TripState, transport_modes: set[str]) -> list[str]:
    """
    Surface only expected-but-missing data - a mode was actually
    selected and its fetch failed (empty result + a *_note in state).
    Never fires for unselected modes or legitimate empty results
    with no accompanying note.
    """
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


def _filter_priced_trains(trains: list[dict]) -> list[dict]:
    """
    Only MAX_FARE_LOOKUPS trains per direction ever get a real fare (see
    search_trains.py) - the rest sit at price=0, class_code="" and are not
    meaningfully choosable. Filtering here means the itinerary prompt only
    ever sees trains it could actually select and cost out, and naturally
    bounds the list size without an arbitrary top-N cut.
    """
    return [t for t in trains if t.get("price", 0) > 0]


def itinerary_builder_node(state: TripState) -> dict:
    """Builds or revises the itinerary depending on whether
    critic_analysis is present in state."""
    normalized_input = state["normalized_input"]

    log = get_trip_logger(logger, state["trip_id"])
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
        revise_user_message = build_itinerary_reviser_user_message(revise_slice)

        log.debug(
            "Itinerary reviser input: system_prompt_len=%d user_msg_len=%d days=%d",
            len(ITINERARY_REVISER_SYSTEM_PROMPT), len(revise_user_message), len(trip_dates),
        )

        response = structured_llm.invoke(
            [
                {"role": "system", "content": ITINERARY_REVISER_SYSTEM_PROMPT},
                {"role": "user", "content": revise_user_message},
            ],
            max_tokens=AGENT_MAX_TOKENS["itinerary_builder"],
        )

        log.debug("Itinerary reviser token usage: %s", response["raw"].usage_metadata)

        if response["parsed"] is None:
            log.error(
                "Itinerary revision parsing failed. raw_content=%r usage=%s",
                response["raw"].content, response["raw"].usage_metadata,
            )
            raise RuntimeError("Itinerary revision parsing failed - see logged raw content above")

        itinerary = response["parsed"].model_dump()
        itinerary["data_gaps"] = state["itinerary"].get("data_gaps", [])
        log.info("Itinerary revised: %s", itinerary)

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
    activities = _trim(activities, _ACTIVITY_FIELDS)

    hotels = hotels[:3]
    activities = activities[:8]
    trains = _filter_priced_trains(trains)

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

    structured_llm = get_structured_llm(Itinerary, include_raw=True)
    build_user_message = build_itinerary_builder_user_message(state_slice)

    log.debug("Itinerary builder state_slice: %s", state_slice)
    log.debug(
        "Itinerary builder input: system_prompt_len=%d user_msg_len=%d days=%d",
        len(ITINERARY_BUILDER_SYSTEM_PROMPT), len(build_user_message), len(trip_dates),
    )

    response = structured_llm.invoke(
        [
            {"role": "system", "content": ITINERARY_BUILDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message},
        ],
        max_tokens=AGENT_MAX_TOKENS["itinerary_builder"],
    )

    log.debug("Itinerary builder token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Itinerary build parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Itinerary build parsing failed - see logged raw content above")

    itinerary = response["parsed"].model_dump()
    log.info("Itinerary built: %s", itinerary)

    itinerary["data_gaps"] = _collect_data_gaps(state, transport_modes)

    if not normalized_input["wants_rental_car"] and itinerary.get("chosen_car") is not None:
        log.warning(
            "itinerary_builder_node: chosen_car was set despite "
            "wants_rental_car=False. chosen_car=%s",
            itinerary["chosen_car"],
        )

    return {"itinerary": itinerary, "status": "awaiting_review"}