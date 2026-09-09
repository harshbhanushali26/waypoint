"""
search_flights — free-API stage (SerpApi Google Flights)

Mechanical tool node: no LLM calls. Fails loud — on any failure returns
{"flights": [], "flights_note": "..."} rather than silently substituting
dummy data, so degraded state is always visible in TripState.
"""

import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings
from tools._constants import resolve_airport
from core.logging import get_trip_logger


logger = logging.getLogger(__name__)
SERPAPI_BASE = "https://serpapi.com/search"


class FlightsAPIError(Exception):
    """Raised when SerpApi returns an explicit error or no usable flight data."""


# ── Fetch ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),  # only retry transient network failures
    reraise=True,
)
def _fetch_flights(params: dict) -> list[dict]:
    """Calls SerpApi Google Flights, returns combined best+other flights."""
    response = httpx.get(SERPAPI_BASE, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise FlightsAPIError(f"SerpApi error: {data['error']}")

    all_flights = data.get("best_flights", []) + data.get("other_flights", [])
    if not all_flights:
        raise FlightsAPIError("SerpApi returned no flight data")

    return all_flights


# ── Normalize ────────────────────────────────────────────────────────────

def _normalize_flight(raw: dict, direction: str, currency: str) -> dict:
    """Converts one SerpApi flight object into Waypoint's flat flight dict."""
    flight_segments = raw.get("flights", [])
    first_segment = flight_segments[0] if flight_segments else {}
    last_segment = flight_segments[-1] if flight_segments else {}

    dep = first_segment.get("departure_airport", {})
    arr = last_segment.get("arrival_airport", {})

    flight_number = ", ".join(
        seg.get("flight_number", "") for seg in flight_segments if seg.get("flight_number")
    ) or "N/A"

    airline = first_segment.get("airline", "Unknown")

    return {
        "flight_id": f"{airline[:2].upper()}-{flight_number[:6]}" if flight_number != "N/A" else "N/A",
        "direction": direction,
        "airline": airline,
        "flight_number": flight_number,
        "departure_airport": dep.get("id", ""),
        "departure_airport_name": dep.get("name", ""),
        "departure_time": dep.get("time", ""),
        "arrival_airport": arr.get("id", ""),
        "arrival_airport_name": arr.get("name", ""),
        "arrival_time": arr.get("time", ""),
        "duration_minutes": raw.get("total_duration") or raw.get("duration", 0),
        "stops": len(flight_segments) - 1 if flight_segments else 0,
        "price": float(raw.get("price", 0)),
        "currency": currency,
        "airplane": first_segment.get("airplane", ""),
        "carbon_emissions_grams": raw.get("carbon_emissions", {}).get("this_flight", 0),
        "booking_token": raw.get("booking_token", ""),
    }


# ── Node entry point ─────────────────────────────────────────────────────

def search_flights(state: dict) -> dict:
    """
    Tool node entry point. Fails loud on any problem — no dummy fallback.
    """
    log = get_trip_logger(logger, state.get("trip_id", "-"))

    if "flights" not in state.get("search_plan", {}).get("transport_modes", []):
        log.debug("search_flights: skipped — not in transport_modes")
        return {"flights": []}

    if not settings.serpapi_flights_key:
        log.warning("search_flights: SERPAPI_FLIGHTS_KEY not configured")
        return {"flights": [], "flights_note": "SERPAPI_FLIGHTS_KEY not configured."}

    origin = resolve_airport(state.get("origin_city", ""))
    destination = resolve_airport(state.get("destination", ""))
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    num_travelers = state.get("num_travelers", 1)
    currency = state.get("currency", "INR")

    if not all([origin, destination, start_date]):
        log.warning("search_flights: missing origin, destination, or start date")
        return {"flights": [], "flights_note": "Missing origin, destination, or start date."}

    try:
        outbound_params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": start_date,
            "currency": currency,
            "hl": "en",
            "gl": "in",
            "adults": str(num_travelers),
            "type": "2",
            "api_key": settings.serpapi_flights_key,
        }
        log.debug("search_flights: fetching outbound %s -> %s on %s", origin, destination, start_date)
        raw_outbound = _fetch_flights(outbound_params)
        flights = [_normalize_flight(f, "outbound", currency) for f in raw_outbound]

        if end_date and end_date != start_date:
            return_params = {**outbound_params, "departure_id": destination, "arrival_id": origin, "outbound_date": end_date}
            log.debug("search_flights: fetching return %s -> %s on %s", destination, origin, end_date)
            raw_return = _fetch_flights(return_params)
            flights.extend([_normalize_flight(f, "return", currency) for f in raw_return])

        log.info("search_flights: found %d flights total", len(flights))
        return {"flights": flights}

    except Exception as e:
        log.warning("search_flights: search failed — %s", e, exc_info=True)
        return {"flights": [], "flights_note": f"Flight search failed: {e}"}