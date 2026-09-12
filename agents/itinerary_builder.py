"""itinerary_builder_node — composes the day-by-day itinerary. Runs in BUILD
mode (first pass) or REVISE mode (Critic routed back with an edit request)."""

import logging
import time
from datetime import date, timedelta

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.itinerary_builder_prompt import ITINERARY_BUILDER_SYSTEM_PROMPT, build_itinerary_builder_user_message
from prompts.itinerary_reviser_prompt import ITINERARY_REVISER_SYSTEM_PROMPT, build_itinerary_reviser_user_message
from models.schemas import Itinerary
from graph.state import TripState
from graph.transport_utils import top_n_per_direction

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

_ACTIVITY_FIELDS = [
    "name", "category", "area",
    "est_duration_hours", "est_price_inr", "snippet",
]

_ACTIVITY_CAP_BY_PACE = {"relaxed": 5, "moderate": 7, "packed": 9}


_TRANSPORT_TOP_N_PER_DIRECTION = 2


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


def _activity_lookup(activities: list[dict]) -> tuple[set[str], dict[str, float]]:
    """
    Returns (all_names, price_by_name) from the trimmed activity catalog,
    both keyed by casefolded name. all_names exists so unpriced activities
    (free / unknown cost) still count as real catalog entries — matching
    one is NOT a fabrication signal. price_by_name holds only the priced
    subset, used for costing.
    """
    all_names: set[str] = set()
    price_by_name: dict[str, float] = {}
    for a in activities:
        name = (a.get("name") or "").strip().casefold()
        if not name:
            continue
        all_names.add(name)
        price = a.get("est_price_inr")
        if price is not None and price > 0:
            price_by_name[name] = float(price)
    return all_names, price_by_name


def _match_activity(title: str, all_names: set[str]) -> str | None:
    """
    Exact name match first, then substring in either direction as a
    fallback ('fort aguada visit' vs catalog 'fort aguada'). Returns the
    matched CATALOG name (deduping happens on this, not on the event
    title, so two title variants of the same activity count once), or
    None when nothing matches.
    """
    if title in all_names:
        return title
    for name in all_names:
        if name in title or title in name:
            return name
    return None


def _scheduled_activities_cost(
    itinerary: dict, activities: list[dict], log
) -> tuple[float, list[str]]:
    """
    Sums est_price_inr for each DISTINCT activity scheduled in the itinerary's
    day events — deduped on the matched CATALOG name, so the same activity
    under two title variants still counts exactly once.

    An event that matches no catalog entry is logged as a warning — that
    is a fabrication signal worth surfacing — and contributes 0 rather
    than crashing the build. A matched activity with no price also
    contributes 0 (free or unknown), and is NOT a warning.

    Returns (cost, unmatched_titles).
    """
    all_names, price_by_name = _activity_lookup(activities)

    total = 0.0
    counted: set[str] = set()
    unmatched: list[str] = []

    for day in itinerary.get("days", []):
        for event in day.get("events", []):
            if event.get("type") != "activity":
                continue
            title = (event.get("title") or "").strip().casefold()
            if not title:
                continue

            matched_name = _match_activity(title, all_names)
            if matched_name is None:
                unmatched.append(event.get("title", ""))
                continue
            if matched_name in counted:
                continue
            counted.add(matched_name)
            total += price_by_name.get(matched_name, 0.0)

    if unmatched:
        log.warning(
            "_scheduled_activities_cost: %d scheduled activities matched nothing "
            "in the catalog (possible fabrication): %s",
            len(unmatched), unmatched,
        )
    return total, unmatched


def _compute_total_cost(itinerary: dict, activities: list[dict], log) -> float:
    """
    Computes the real cost of what was actually chosen, replacing the
    LLM-authored total_cost field entirely (see locked design: the LLM
    was echoing budget_analysis.estimated_total instead of summing its
    own selections).

    Reads chosen_transport (list, key "price"), chosen_car (dict or
    None, key "total_price"), chosen_hotel (dict, key "total_price"),
    and the activity events scheduled in days (matched back to the
    activity catalog by name, summed once per distinct activity, key
    "est_price_inr"). Activities with no price — free or unknown —
    contribute 0, same as before extraction existed.

    A missing/zero price on an entry that IS present is logged as a
    warning and treated as 0 in the sum, rather than raised - this is
    LLM-reproduced data that already passed schema validation, not a
    tool-node contract violation, so a suspicious value shouldn't crash
    itinerary building.
    """
    total = 0.0

    for leg in itinerary.get("chosen_transport", []):
        price = leg.get("price")
        if not price or price <= 0:
            log.warning(
                "_compute_total_cost: chosen_transport leg has missing/zero price: %s",
                leg,
            )
            price = 0
        total += price

    chosen_car = itinerary.get("chosen_car")
    if chosen_car is not None:
        price = chosen_car.get("total_price")
        if not price or price <= 0:
            log.warning(
                "_compute_total_cost: chosen_car has missing/zero total_price: %s",
                chosen_car,
            )
            price = 0
        total += price

    chosen_hotel = itinerary.get("chosen_hotel", {})
    price = chosen_hotel.get("total_price")
    if not price or price <= 0:
        log.warning(
            "_compute_total_cost: chosen_hotel has missing/zero total_price: %s",
            chosen_hotel,
        )
        price = 0
    total += price

    # Activities: summed from the distinct activity events scheduled in
    # days, matched back to the catalog by name (see
    # _scheduled_activities_cost). Free/unknown-price activities
    # contribute 0 — same as before extraction existed.
    activities_total, _unmatched = _scheduled_activities_cost(
        itinerary, activities, log
    )
    total += activities_total

    return total


def itinerary_builder_node(state: TripState) -> dict:
    """Builds or revises the itinerary depending on whether
    critic_analysis is present in state."""
    normalized_input = state["normalized_input"]

    log = get_trip_logger(logger, state["trip_id"])

    # ── Groq token-window wait ─────────────────────────────────────
    # Budget's LLM call just finished (BUILD mode) and its tokens sit
    # in Groq's 60s sliding TPM window alongside Concierge's and
    # Planner's. This call needs ~8k tokens on its own — more than
    # what's left (~2.4k). Waiting until all prior tokens have expired
    # guarantees a fresh 8,000-token window.
    #
    # REVISE mode: runs minutes later (after human review + critic),
    # so elapsed >> 62 and the wait is a no-op — same code serves both.
    _budget_done = state.get("_budget_llm_done_at")
    if _budget_done:
        _elapsed = time.time() - _budget_done
        if _elapsed < 62:
            _wait = 62 - _elapsed + 2   # +2s clock-skew buffer
            log.info(
                "Itinerary builder: %.0fs since Budget LLM call — "
                "waiting %.0fs for Groq token window reset",
                _elapsed, _wait,
            )
            time.sleep(_wait)
        else:
            log.info(
                "Itinerary builder: %.0fs since Budget LLM call — "
                "token window already clear, proceeding",
                _elapsed,
            )

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

        structured_llm = get_structured_llm(Itinerary, include_raw=True, max_tokens=AGENT_MAX_TOKENS["itinerary_builder"])
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
        activities_for_cost = _trim(state.get("activities", []), _ACTIVITY_FIELDS)
        itinerary["total_cost"] = _compute_total_cost(itinerary, activities_for_cost, log)
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

    # Cut to the cheapest N per direction BEFORE field-trimming, while
    # "price" is still guaranteed present - trimming keeps "price" per
    # _FLIGHT_FIELDS/_TRAIN_FIELDS anyway, but ranking should happen on
    # full objects, not an assumption about what survives the allowlist.
    flights = top_n_per_direction(flights, "price", _TRANSPORT_TOP_N_PER_DIRECTION)
    trains = top_n_per_direction(trains, "price", _TRANSPORT_TOP_N_PER_DIRECTION)

    # Field-trim every object down to what a real screen could show.
    flights = _trim(flights, _FLIGHT_FIELDS)
    trains = _trim(trains, _TRAIN_FIELDS)
    buses = _trim(buses, _BUS_FIELDS)
    cars = _trim(cars, _CAR_FIELDS)
    hotels = _trim(hotels, _HOTEL_FIELDS)
    activities = _trim(activities, _ACTIVITY_FIELDS)

    hotels = [h for h in hotels if h.get("total_price", 0) > 0]
    hotels = hotels[:3]
    activities = activities[:8]
    # trains = _filter_priced_trains(trains)
    activities = activities[: _ACTIVITY_CAP_BY_PACE.get(normalized_input["pace"], 10)]

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

    structured_llm = get_structured_llm(Itinerary, include_raw=True, max_tokens=AGENT_MAX_TOKENS["itinerary_builder"])
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
    )

    log.debug("Itinerary builder token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Itinerary build parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Itinerary build parsing failed - see logged raw content above")

    itinerary = response["parsed"].model_dump()
    itinerary["total_cost"] = _compute_total_cost(itinerary, activities, log)
    log.info("Itinerary built: %s", itinerary)

    itinerary["data_gaps"] = _collect_data_gaps(state, transport_modes)

    if not normalized_input["wants_rental_car"] and itinerary.get("chosen_car") is not None:
        log.warning(
            "itinerary_builder_node: chosen_car was set despite "
            "wants_rental_car=False. chosen_car=%s",
            itinerary["chosen_car"],
        )

    return {"itinerary": itinerary, "status": "awaiting_review"}