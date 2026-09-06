# """
# search_trains — free-API stage (RailRadar API)

# Mechanical tool node: no LLM calls. Two-step flow:
#   1. GET /v1/trains/between/{from}/{to} — list of trains with schedule,
#      available classes, running days, distance, duration. NO fares.
#   2. GET /v1/trains/{number}/fare — itemized fare breakdown for a specific
#      train + class + quota. Called for top N trains to conserve quota.

# RailRadar free sandbox plan: 1,000 requests/month.
# Base URL: https://api.railradar.in/v1
# Auth: Bearer token in the Authorization header.

# Fails loud — no dummy fallback.
# """

# import httpx
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# from core.config import settings
# from tools._constants import resolve_station


# RAILRADAR_BASE = "https://api.railradar.in/v1"

# # Max trains to fetch fares for per direction.
# # Round-trip: 2 between-stations calls + up to 2*N fare calls.
# MAX_FARE_LOOKUPS = 4

# # Default class code preference — pick the first available from each train's list.
# CLASS_PREFERENCE = ["3A", "2A", "1A", "CC", "EC", "3E", "SL", "2S"]

# # Default quota code: GN = General
# DEFAULT_QUOTA = "GN"


# class TrainsAPIError(Exception):
#     """Raised when RailRadar returns an explicit error or no usable train data."""


# def _headers() -> dict:
#     return {"Authorization": f"Bearer {settings.railradar_api_key}"}


# @retry(
#     stop=stop_after_attempt(3),
#     wait=wait_exponential(multiplier=1, min=2, max=10),
#     retry=retry_if_exception_type(httpx.HTTPError),
#     reraise=True,
# )
# def _fetch_trains_between(from_code: str, to_code: str, date_str: str) -> list[dict]:
#     """
#     Step 1: Get all trains between two stations. No fares in this response —
#     only schedule, available classes, running days, distance, duration.
#     """
#     url = f"{RAILRADAR_BASE}/trains/between/{from_code}/{to_code}"
#     params = {"date": date_str} if date_str else {}

#     response = httpx.get(url, headers=_headers(), params=params, timeout=30)
#     response.raise_for_status()
#     data = response.json()

#     # RailRadar wraps responses in {"success": bool, "data": {...}}
#     if isinstance(data, dict) and not data.get("success", True):
#         error_msg = data.get("error", {}).get("message", "Unknown RailRadar error")
#         raise TrainsAPIError(f"RailRadar error: {error_msg}")

#     # Extract trains from the response envelope
#     payload = data.get("data", data) if isinstance(data, dict) else data
#     if isinstance(payload, list):
#         trains = payload
#     elif isinstance(payload, dict):
#         trains = payload.get("trains", [])
#         if not trains and "trainNumber" in payload:
#             trains = [payload]
#     else:
#         trains = []

#     if not trains:
#         raise TrainsAPIError(f"No trains found between {from_code} and {to_code}")

#     return trains


# @retry(
#     stop=stop_after_attempt(3),
#     wait=wait_exponential(multiplier=1, min=2, max=10),
#     retry=retry_if_exception_type(httpx.HTTPError),
#     reraise=True,
# )
# def _fetch_fare(
#     train_number: str,
#     from_code: str,
#     to_code: str,
#     date_str: str,
#     class_code: str,
#     quota: str = DEFAULT_QUOTA,
# ) -> dict:
#     """
#     Step 2: Get the itemized fare breakdown for a specific train + class + quota.

#     Endpoint: GET /v1/trains/{number}/fare
#     Query params: source, destination, journeyDate, classCode, quotaCode
#     Returns: {"totalFare": 2145, "breakdown": {"baseFare": 1750, ...}}
#     """
#     url = f"{RAILRADAR_BASE}/trains/{train_number}/fare"
#     params = {
#         "source": from_code,
#         "destination": to_code,
#         "journeyDate": date_str,
#         "classCode": class_code,
#         "quotaCode": quota,
#     }

#     response = httpx.get(url, headers=_headers(), params=params, timeout=30)
#     response.raise_for_status()
#     data = response.json()

#     if isinstance(data, dict) and not data.get("success", True):
#         error_msg = data.get("error", {}).get("message", "Unknown RailRadar error")
#         raise TrainsAPIError(f"RailRadar fare error for train {train_number}: {error_msg}")

#     fare_data = data.get("data", {})
#     if not fare_data:
#         raise TrainsAPIError(f"No fare data for train {train_number}")

#     return fare_data


# def _pick_class(available_classes: list[str]) -> str:
#     """
#     Pick the best travel class from a train's available classes.
#     Prefers AC classes (3A, 2A, 1A) over non-AC (SL, 2S).
#     """
#     for preferred in CLASS_PREFERENCE:
#         if preferred in available_classes:
#             return preferred
#     return available_classes[0] if available_classes else "3A"


# def _normalize_train(
#     raw: dict,
#     from_code: str,
#     to_code: str,
#     direction: str,
#     currency: str,
#     fare_data: dict | None = None,
# ) -> dict:
#     """
#     Convert a RailRadar train object + optional fare data into
#     Waypoint's flat dict shape.
#     """
#     # Parse station objects — may be {"code": "...", "name": "..."} or a plain string
#     station_from = raw.get("stationFrom", raw.get("station_from", {}))
#     station_to = raw.get("stationTo", raw.get("station_to", {}))
#     from_code_actual = station_from.get("code", from_code) if isinstance(station_from, dict) else from_code
#     to_code_actual = station_to.get("code", to_code) if isinstance(station_to, dict) else to_code

#     # Parse duration — RailRadar returns "HH:MM" string, convert to minutes
#     duration_raw = raw.get("duration", raw.get("duration_minutes", 0))
#     duration_minutes = 0
#     if isinstance(duration_raw, str) and ":" in duration_raw:
#         parts = duration_raw.split(":")
#         if len(parts) >= 2:
#             try:
#                 duration_minutes = int(parts[0]) * 60 + int(parts[1])
#             except ValueError:
#                 pass
#     elif isinstance(duration_raw, (int, float)):
#         duration_minutes = int(duration_raw)

#     # Extract available classes — field name varies between RailRadar endpoints
#     available_classes = raw.get("availableClasses", raw.get("available_classes", raw.get("classes", [])))
#     # Normalize: sometimes it's a list of strings, sometimes a list of dicts
#     if available_classes and isinstance(available_classes[0], dict):
#         available_classes = [c.get("class_code", c.get("code", "")) for c in available_classes]

#     # Determine class code and price
#     if fare_data:
#         class_code = fare_data.get("classCode", _pick_class(available_classes))
#         price = float(fare_data.get("totalFare", 0))
#         fare_breakdown = fare_data.get("breakdown", {})
#     else:
#         class_code = _pick_class(available_classes)
#         price = 0.0
#         fare_breakdown = {}

#     return {
#         "train_id": f"{raw.get('trainNumber', raw.get('train_number', ''))}-{direction[:3].upper()}",
#         "train_number": raw.get("trainNumber", raw.get("train_number", "")),
#         "train_name": raw.get("trainName", raw.get("train_name", "")),
#         "train_type": raw.get("trainType", raw.get("train_type", "")),
#         "departure_station": from_code_actual,
#         "arrival_station": to_code_actual,
#         "departure_time": raw.get("departureTime", raw.get("departure_time", "")),
#         "arrival_time": raw.get("arrivalTime", raw.get("arrival_time", "")),
#         "duration_minutes": duration_minutes,
#         "distance_km": raw.get("distance", raw.get("distance_km", 0)),
#         "class_code": class_code,
#         "price": price,
#         "currency": currency,
#         "direction": direction,
#         "pantry": raw.get("hasPantry", raw.get("pantry", False)),
#         "run_days": raw.get("runDays", raw.get("run_days", [])),
#         "available_classes": available_classes,
#         "fare_breakdown": fare_breakdown,
#     }


# def _search_direction(
#     from_code: str,
#     to_code: str,
#     date_str: str,
#     direction: str,
#     currency: str,
# ) -> list[dict]:
#     """
#     Search trains for one direction. Fetches the train list first,
#     then fetches fares for the top MAX_FARE_LOOKUPS trains.
#     """
#     # Step 1: Get all trains between stations
#     raw_trains = _fetch_trains_between(from_code, to_code, date_str)

#     # Step 2: Fetch fares for top N trains only (conserves API quota)
#     trains_to_price = raw_trains[:MAX_FARE_LOOKUPS]

#     normalized = []
#     for raw_train in raw_trains:
#         train_number = raw_train.get("trainNumber", raw_train.get("train_number", ""))
#         available_classes = raw_train.get("availableClasses", raw_train.get("available_classes", raw_train.get("classes", [])))
#         if available_classes and isinstance(available_classes[0], dict):
#             available_classes = [c.get("class_code", c.get("code", "")) for c in available_classes]
#         class_code = _pick_class(available_classes or ["3A"])

#         # Fetch fare only for the top N trains
#         fare_data = None
#         if raw_train in trains_to_price and train_number:
#             try:
#                 fare_data = _fetch_fare(
#                     train_number=train_number,
#                     from_code=from_code,
#                     to_code=to_code,
#                     date_str=date_str,
#                     class_code=class_code,
#                     quota=DEFAULT_QUOTA,
#                 )
#             except Exception:
#                 # Fare fetch failed for this train — continue without fare.
#                 # Train appears with price=0, fare_breakdown={}.
#                 fare_data = None

#         normalized.append(_normalize_train(
#             raw=raw_train,
#             from_code=from_code,
#             to_code=to_code,
#             direction=direction,
#             currency=currency,
#             fare_data=fare_data,
#         ))

#     return normalized


# def search_trains(state: dict) -> dict:
#     """
#     Tool node entry point. Fails loud on any problem — no dummy fallback.

#     Quota usage per search:
#         - Round-trip: 2 between-stations calls + up to 2*MAX_FARE_LOOKUPS fare calls
#           = 2 + 8 = 10 API calls (out of 1,000/month)
#         - One-way: 1 + 4 = 5 API calls
#     """
#     if "trains" not in state.get("search_plan", {}).get("transport_modes", []):
#         return {"trains": []}

#     if not settings.railradar_api_key:
#         return {"trains": [], "trains_note": "RAILRADAR_API_KEY not configured."}

#     origin = resolve_station(state.get("origin_city", ""))
#     destination = resolve_station(state.get("destination", ""))
#     start_date = state.get("start_date", "")
#     end_date = state.get("end_date", "")
#     currency = state.get("currency", "INR")

#     if not all([origin, destination, start_date]):
#         return {"trains": [], "trains_note": "Missing origin, destination, or start date."}

#     try:
#         # ── Outbound ──────────────────────────────────────────────────────
#         trains = _search_direction(
#             from_code=origin,
#             to_code=destination,
#             date_str=start_date,
#             direction="outbound",
#             currency=currency,
#         )

#         # ── Return (if round-trip) ────────────────────────────────────────
#         if end_date and end_date != start_date:
#             trains.extend(_search_direction(
#                 from_code=destination,
#                 to_code=origin,
#                 date_str=end_date,
#                 direction="return",
#                 currency=currency,
#             ))

#         return {"trains": trains}

#     except Exception as e:
#         return {"trains": [], "trains_note": f"Train search failed: {e}"}


"""
search_trains — free-API stage (RailRadar API)

Mechanical tool node: no LLM calls. Two-step flow:
  1. GET /v1/trains/between/{from}/{to}?byCity=true — trains + schedule.
  2. GET /v1/trains/{number}/fare — fare for top N trains.

Station resolution: static dict in _constants.py (zero API cost).
If a city isn't in the static dict, falls back to autocomplete API (1 call, cached).

Fare calls use each train's OWN from/to station codes (from the
between-stations response, confirmed present when byCity=true), not the
city-level resolved codes. With byCity=true, train A may arrive at BVI
while train B arrives at MMCT.

Rate limiting: RailRadar allows 10 requests/minute. A flat 6s delay is
applied before every call to this API (between-stations, fare, and
autocomplete alike) so calls average ~10/minute even in the worst case
of back-to-back requests. If a fare call still returns 429 (e.g. another
process hit the same window), fare lookups for the rest of that
direction's trains are abandoned immediately — no retry, no waterfall
through remaining trains. Already-priced trains keep their price;
unpriced ones stay unpriced with class_code="".

Fails loud — no dummy fallback.
"""

import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings
from tools._constants import resolve_station


RAILRADAR_BASE = "https://api.railradar.in/v1"

# Max trains to fetch fares for per direction.
MAX_FARE_LOOKUPS = 3

# Classes to try for fare, in order. 3A and SL cover the large majority of
# mail/express trains. Cut down from a 5-class waterfall to keep worst-case
# calls-per-train at 2 instead of 5 — a train with neither class is simply
# unpriced (fail-loud via class_code="" / price=0), not chased further.
CLASS_PREFERENCE = ["3A", "SL"]

DEFAULT_QUOTA = "GN"

# Flat delay before every RailRadar call (any endpoint). 10 req/min limit
# means calls need to average ~1 per 6s in the worst case of back-to-back
# requests to never trip 429.
THROTTLE_SECONDS = 6.0


class TrainsAPIError(Exception):
    """RailRadar returned an error or no usable data."""


class FareNotFoundError(Exception):
    """Fare endpoint returned 404 — train doesn't serve this station pair/class.
    Not transient, should not be retried."""


class RateLimitError(Exception):
    """Fare endpoint returned 429. Not retried — propagates up so the caller
    can stop pricing further trains in this direction rather than hammering
    a window that hasn't reset."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.railradar_api_key}"}


def _throttle() -> None:
    """Single choke point for RailRadar's 10 req/min limit. Called first
    thing in every function that hits the API, including retries."""
    time.sleep(THROTTLE_SECONDS)


# ── Station resolution with autocomplete fallback + cache ───────────────────

_autocomplete_cache: dict[str, str] = {}


def _strip_country(city_str: str) -> str:
    """
    RailRadar's station lookup (both the static dict and the autocomplete
    API) expects a bare city name — "Vapi", not "Vapi, India". Concierge
    deliberately normalizes to "City, Country" form for other consumers
    (geocoding, hotel/flight location params) where that's the correct
    format, so the split happens HERE, at the one boundary that needs it,
    rather than upstream in Concierge's output.

    Splits on the first comma only, trims whitespace. A bare name with no
    comma passes through unchanged.
    """
    return city_str.split(",")[0].strip()


def _resolve_station(query: str) -> str:
    """
    Resolve a city name to a station code.
    1. Strip any "Country" suffix ("Vapi, India" -> "Vapi") since RailRadar
       and our static dict both key on bare city names.
    2. Try static dict (zero API cost).
    3. If not found, call autocomplete API (1 call), cache the result.
    """
    query = _strip_country(query)

    # Static dict first — zero cost
    code = resolve_station(query)
    if code and code != query.strip():
        return code

    # Check autocomplete cache
    cache_key = query.strip().lower()
    if cache_key in _autocomplete_cache:
        return _autocomplete_cache[cache_key]

    # Fallback: autocomplete API
    try:
        _throttle()
        url = f"{RAILRADAR_BASE}/lookup/search/stations"
        response = httpx.get(url, headers=_headers(), params={"q": query, "limit": 1}, timeout=15)
        response.raise_for_status()
        data = response.json()

        stations = data.get("data", [])
        if stations:
            code = stations[0].get("code", "")
            _autocomplete_cache[cache_key] = code
            return code
    except Exception:
        pass

    return ""


# ── Step 1: Trains between stations ──────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_trains_between(from_code: str, to_code: str, date_str: str) -> list[dict]:
    """
    GET /v1/trains/between/{from}/{to}?byCity=true&date=YYYY-MM-DD

    Response envelope:
        {"success": true, "data": {"from": {...}, "to": {...}, "count": N, "trains": [...]}}

    Each train in the trains array (byCity=true confirmed to include
    per-train from/to code/name/city — verified against live response):
        {
            "train": {"number": "22946", "name": "...", "type": "...", "runDays": [...]},
            "from": {"code": "VAPI", "name": "Vapi", "city": "Vapi", "departure": "01:40", "day": 2, "sequence": 138},
            "to": {"code": "BVI", "name": "Borivali", "city": "Mumbai", "arrival": "03:12", "day": 3, "sequence": 341},
            "distance": 138.5,
            "duration": 127,
            "totalHaltsBetween": 1
        }
    """
    _throttle()

    url = f"{RAILRADAR_BASE}/trains/between/{from_code}/{to_code}"
    params = {"byCity": "true"}
    if date_str:
        params["date"] = date_str

    response = httpx.get(url, headers=_headers(), params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and not data.get("success", True):
        error_msg = data.get("error", {}).get("message", "Unknown error")
        raise TrainsAPIError(f"RailRadar error: {error_msg}")

    payload = data.get("data", {})
    if isinstance(payload, dict):
        return payload.get("trains", [])
    elif isinstance(payload, list):
        return payload
    return []


# ── Step 2: Fare lookup ──────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=5),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_fare_request(
    train_number: str,
    from_code: str,
    to_code: str,
    date_str: str,
    class_code: str,
    quota: str = DEFAULT_QUOTA,
) -> dict:
    """
    GET /v1/trains/{number}/fare?source=...&destination=...&journeyDate=...&classCode=...&quotaCode=...

    Verified real response shape (confirmed against two live trains/classes,
    NOT the shape shown in RailRadar's own docs example):
        {
            "success": true,
            "data": {
                "trainNumber": "...", "trainName": "...", "distance": ...,
                "breakdown": {
                    "baseFare": ..., "reservationCharge": ..., ...,
                    "totalFare": 520,   # ← lives HERE, not at data.totalFare
                    ...
                },
                "generatedAt": "..."
            }
        }

    Note: classCode is NOT echoed back anywhere in the response — the
    class actually used is only known because we requested it.

    404 → FareNotFoundError (not retried — station/class mismatch is permanent).
    429 → RateLimitError (not retried — quota window, retrying immediately
          just fails again).
    5xx/network → retried by tenacity (transient).
    """
    _throttle()

    url = f"{RAILRADAR_BASE}/trains/{train_number}/fare"
    params = {
        "source": from_code,
        "destination": to_code,
        "journeyDate": date_str,
        "classCode": class_code,
        "quotaCode": quota,
    }

    response = httpx.get(url, headers=_headers(), params=params, timeout=30)

    if response.status_code == 429:
        raise RateLimitError(f"Train {train_number}: rate limited (429) on fare lookup")

    if response.status_code == 404:
        raise FareNotFoundError(f"Train {train_number}: no fare for {from_code}→{to_code} class={class_code}")

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and not data.get("success", True):
        raise FareNotFoundError(f"Train {train_number}: fare API returned error")

    payload = data.get("data", {})
    breakdown = payload.get("breakdown", {})

    # Normalize here so nothing downstream needs to know about the nesting.
    # total_fare is pulled from breakdown; classCode isn't in the response
    # at all, so we stamp back the class we requested.
    return {
        "totalFare": breakdown.get("totalFare", 0),
        "breakdown": breakdown,
        "classCode": class_code,
    }


def _try_fetch_fare(
    train_number: str,
    from_code: str,
    to_code: str,
    date_str: str,
) -> tuple[dict | None, str]:
    """
    Try fetching fare, attempting CLASS_PREFERENCE in order. First success
    wins. 404 skips to next class. RateLimitError propagates immediately —
    the caller (_search_direction) stops pricing further trains entirely
    rather than continuing to hammer a rate-limited window.

    Success check uses `is not None` rather than truthiness — a
    legitimately free/zero fare (e.g. some promotional or short-hop fares)
    would otherwise be misread as "no fare found" and skip to the next
    class unnecessarily.

    Returns (fare_data, class_code) or (None, "") if no class in
    CLASS_PREFERENCE had a fare for this train.

    Raises: RateLimitError (propagated, not swallowed).
    """
    for class_code in CLASS_PREFERENCE:
        try:
            fare_data = _fetch_fare_request(
                train_number=train_number,
                from_code=from_code,
                to_code=to_code,
                date_str=date_str,
                class_code=class_code,
            )
            if fare_data and fare_data.get("totalFare") is not None:
                return fare_data, class_code
        except FareNotFoundError:
            continue
        except RateLimitError:
            raise
        except Exception:
            continue
    return None, ""


# ── Normalization ────────────────────────────────────────────────────────────

def _normalize_train(
    raw: dict,
    direction: str,
    currency: str,
    fare_data: dict | None = None,
    class_code: str = "",
) -> dict:
    """Convert a RailRadar train object into Waypoint's flat dict shape."""
    train_obj = raw.get("train", {})
    from_obj = raw.get("from", {})
    to_obj = raw.get("to", {})

    train_number = train_obj.get("number", "")
    train_name = train_obj.get("name", "")
    train_type = train_obj.get("type", "")
    run_days = train_obj.get("runDays", [])

    from_code = from_obj.get("code", "")
    from_name = from_obj.get("name", "")
    from_city = from_obj.get("city", "")
    departure_time = from_obj.get("departure", "")
    departure_day = from_obj.get("day", 1)

    to_code = to_obj.get("code", "")
    to_name = to_obj.get("name", "")
    to_city = to_obj.get("city", "")
    arrival_time = to_obj.get("arrival", "")
    arrival_day = to_obj.get("day", 1)

    duration_minutes = raw.get("duration", 0)
    if isinstance(duration_minutes, str) and ":" in duration_minutes:
        parts = duration_minutes.split(":")
        try:
            duration_minutes = int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            duration_minutes = 0

    price = float(fare_data.get("totalFare", 0)) if fare_data else 0.0
    fare_breakdown = fare_data.get("breakdown", {}) if fare_data else {}
    final_class = fare_data.get("classCode", class_code) if fare_data else class_code

    return {
        "train_id": f"{train_number}-{direction[:3].upper()}",
        "train_number": train_number,
        "train_name": train_name,
        "train_type": train_type,
        "departure_station": from_code,
        "departure_station_name": from_name,
        "departure_city": from_city,
        "departure_time": departure_time,
        "departure_day": departure_day,
        "arrival_station": to_code,
        "arrival_station_name": to_name,
        "arrival_city": to_city,
        "arrival_time": arrival_time,
        "arrival_day": arrival_day,
        "duration_minutes": duration_minutes,
        "distance_km": raw.get("distance", 0),
        "class_code": final_class,
        "price": price,
        "currency": currency,
        "direction": direction,
        "pantry": False,
        "run_days": run_days,
        "available_classes": [],
        "fare_breakdown": fare_breakdown,
    }


# ── Orchestration ────────────────────────────────────────────────────────────

def _search_direction(
    from_city: str,
    to_city: str,
    date_str: str,
    direction: str,
    currency: str,
) -> tuple[list[dict], bool]:
    """
    One direction: resolve stations → fetch trains → fetch fares for top N.

    Returns (normalized_trains, rate_limited) — rate_limited is True if a
    429 cut fare lookups short for this direction, so the caller can
    surface a note without treating it as a hard failure.
    """
    # Step 1: Resolve station codes (static dict, zero API cost)
    from_code = _resolve_station(from_city)
    to_code = _resolve_station(to_city)

    if not from_code or not to_code:
        raise TrainsAPIError(
            f"Could not resolve stations: '{from_city}'→'{from_code}', '{to_city}'→'{to_code}'"
        )

    # Step 2: Fetch trains (byCity=true expands to all metro stations)
    raw_trains = _fetch_trains_between(from_code, to_code, date_str)
    if not raw_trains:
        return [], False

    # Step 3: Fetch fares for top N trains
    trains_to_price = raw_trains[:MAX_FARE_LOOKUPS]

    normalized = []
    rate_limited = False

    for raw_train in raw_trains:
        train_obj = raw_train.get("train", {})
        train_number = train_obj.get("number", "")

        # Use each train's OWN station codes for the fare call.
        # With byCity=true, different trains arrive at different stations.
        train_from = raw_train.get("from", {}).get("code", from_code)
        train_to = raw_train.get("to", {}).get("code", to_code)

        fare_data = None
        class_code = ""

        if not rate_limited and raw_train in trains_to_price and train_number:
            try:
                fare_data, class_code = _try_fetch_fare(
                    train_number=train_number,
                    from_code=train_from,
                    to_code=train_to,
                    date_str=date_str,
                )
            except RateLimitError:
                # Stop pricing any further trains in this direction.
                # This train and all remaining ones stay unpriced.
                rate_limited = True

        normalized.append(_normalize_train(
            raw=raw_train,
            direction=direction,
            currency=currency,
            fare_data=fare_data,
            class_code=class_code,
        ))

    return normalized, rate_limited






def search_trains(state: dict) -> dict:
    """
    Tool node entry point. Fails loud — no dummy fallback.

    API cost (with THROTTLE_SECONDS=6, MAX_FARE_LOOKUPS=3, 2-class waterfall):
        One-way:    1 between-stations + up to (3 trains × 2 classes) = up to 7 calls
        Round-trip: up to 14 calls total, ~84s worst case due to throttling

    If a 429 is hit mid-direction, fare lookups for the rest of that
    direction stop immediately (see _search_direction) and a
    trains_note is set describing the partial result — this is a
    softer signal than a hard failure, but still surfaced per the
    fail-loud pattern rather than silently returning incomplete data
    with no note key.
    """
    if "trains" not in state.get("search_plan", {}).get("transport_modes", []):
        return {"trains": []}

    if not settings.railradar_api_key:
        return {"trains": [], "trains_note": "RAILRADAR_API_KEY not configured."}

    origin_city = state.get("origin_city", "")
    destination_city = state.get("destination", "")
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    currency = state.get("currency", "INR")

    if not all([origin_city, destination_city, start_date]):
        return {"trains": [], "trains_note": "Missing origin, destination, or start date."}

    try:
        trains, rate_limited_out = _search_direction(
            from_city=origin_city,
            to_city=destination_city,
            date_str=start_date,
            direction="outbound",
            currency=currency,
        )

        rate_limited_ret = False
        if end_date and end_date != start_date:
            return_trains, rate_limited_ret = _search_direction(
                from_city=destination_city,
                to_city=origin_city,
                date_str=end_date,
                direction="return",
                currency=currency,
            )
            trains.extend(return_trains)

        result = {"trains": trains}
        if rate_limited_out or rate_limited_ret:
            result["trains_note"] = (
                "Rate limited mid-search — some trains returned without fare pricing."
            )
        return result

    except Exception as e:
        return {"trains": [], "trains_note": f"Train search failed: {e}"}