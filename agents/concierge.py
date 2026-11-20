"""
agents/concierge.py

Deterministic input normalization in pure Python (Zero LLM / Zero Token Cost).
Validates against the NormalizedInput Pydantic schema, canonicalizes Indian
city names, and enforces the 7-day trip cap without making external API calls.
"""

import logging
from datetime import date, timedelta
from graph.state import TripState
from models.schemas import NormalizedInput
from core.logging import get_trip_logger

logger = logging.getLogger(__name__)

MAX_TRIP_DAYS = 7

CITY_ALIASES: dict[str, str] = {
    "bombay": "Mumbai, India",
    "mumbai": "Mumbai, India",
    "delhi": "New Delhi, India",
    "new delhi": "New Delhi, India",
    "calcutta": "Kolkata, India",
    "kolkata": "Kolkata, India",
    "madras": "Chennai, India",
    "chennai": "Chennai, India",
    "bangalore": "Bengaluru, India",
    "bengaluru": "Bengaluru, India",
    "trivandrum": "Thiruvananthapuram, India",
    "thiruvananthapuram": "Thiruvananthapuram, India",
    "cochin": "Kochi, India",
    "kochi": "Kochi, India",
    "poona": "Pune, India",
    "pune": "Pune, India",
    "banaras": "Varanasi, India",
    "kashi": "Varanasi, India",
    "varanasi": "Varanasi, India",
    "goa": "Goa, India",
    "panaji": "Goa, India",
    "ahmedabad": "Ahmedabad, India",
    "jaipur": "Jaipur, India",
    "bhuj": "Bhuj, India",
    "surat": "Surat, India",
    "vapi": "Vapi, India",
    "udaipur": "Udaipur, India",
}


def _canonicalize_city(raw_name: str) -> str:
    """Cleans up raw city inputs, resolves aliases, and standardizes to 'City, India'."""
    if not raw_name:
        return "Unknown, India"

    cleaned = raw_name.strip()
    lookup_key = cleaned.lower().split(",")[0].strip()

    if lookup_key in CITY_ALIASES:
        return CITY_ALIASES[lookup_key]

    if "," in cleaned:
        parts = [p.strip().title() for p in cleaned.split(",")]
        return ", ".join(parts)

    return f"{cleaned.title()}, India"


def concierge_node(state: TripState) -> dict:
    """
    Deterministic normalization node.
    Constructs and validates state['normalized_input'] against NormalizedInput
    in pure Python with zero LLM tokens.
    """
    trip_id = state.get("trip_id", "-")
    log = get_trip_logger(logger, trip_id)
    log.info("Concierge (Deterministic): normalizing and validating input data")

    start_date_str = state.get("start_date", "")
    end_date_str = state.get("end_date", "")

    # 1. Deterministic trip-length cap (max 7 days)
    try:
        d_start = date.fromisoformat(start_date_str)
        d_end = date.fromisoformat(end_date_str)
        days = (d_end - d_start).days + 1

        if days < 1:
            log.warning("Concierge: end_date is before start_date; clamping to same-day trip.")
            d_end = d_start
            end_date_str = d_start.isoformat()
        elif days > MAX_TRIP_DAYS:
            log.info("Concierge: clamping trip from %d days to max %d days.", days, MAX_TRIP_DAYS)
            d_end = d_start + timedelta(days=MAX_TRIP_DAYS - 1)
            end_date_str = d_end.isoformat()
    except Exception as e:
        log.warning("Concierge: date parsing issue (%s), proceeding with original dates", e)

    # 2. Canonicalize locations
    canonical_destination = _canonicalize_city(state.get("destination", ""))
    canonical_origin = _canonicalize_city(state.get("origin_city", ""))

    # 3. Sanitize options
    raw_pref = state.get("transport_pref", "any")
    transport_pref = raw_pref if raw_pref in ("flights", "trains", "any") else "any"

    raw_pace = state.get("pace", "moderate")
    pace = raw_pace if raw_pace in ("relaxed", "moderate", "packed") else "moderate"

    # 4. Instantiate NormalizedInput (Pydantic validates fields, types, and defaults)
    validated_model = NormalizedInput(
        destination=canonical_destination,
        origin_city=canonical_origin,
        start_date=start_date_str,
        end_date=end_date_str,
        num_travelers=max(int(state.get("num_travelers", 1)), 1),
        budget=max(float(state.get("budget", 0.0)), 0.0),
        currency=state.get("currency", "INR"),
        interests=list(state.get("interests", [])),
        transport_pref=transport_pref,
        pace=pace,
    )

    # 5. model_dump() produces the clean dict matching TripState["normalized_input"]
    normalized_data = validated_model.model_dump()
    log.info("Concierge validated: '%s' -> '%s'", canonical_origin, canonical_destination)

    return {
        "normalized_input": normalized_data,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "status": "planning",
    }