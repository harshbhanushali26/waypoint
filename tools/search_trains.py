"""
tools/search_trains.py

Free-API train search using RailRadar API.
Station resolution uses centralized _constants.resolve_station with autocomplete fallback.
"""

import logging
import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings
from tools._constants import resolve_station, strip_country
from core.logging import get_trip_logger

logger = logging.getLogger(__name__)
RAILRADAR_BASE = "https://api.railradar.in/v1"

MAX_FARE_LOOKUPS = 3
CLASS_PREFERENCE = ["3A", "SL", "CC"]
DEFAULT_QUOTA = "GN"
THROTTLE_SECONDS = 6.0


class TrainsAPIError(Exception):
    """RailRadar returned an error or no usable data."""


class FareNotFoundError(Exception):
    """Train does not serve this station pair or class."""


class RateLimitError(Exception):
    """RailRadar rate limit (429) encountered."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.railradar_api_key}"}


def _throttle() -> None:
    time.sleep(THROTTLE_SECONDS)


# ── Station Resolution with Autocomplete Fallback + Cache ──────────────────────

_autocomplete_cache: dict[str, str] = {}


def _resolve_station_with_fallback(city_query: str) -> str:
    """Resolves station code via static dict, falling back to RailRadar autocomplete API."""
    # 1. Try centralized static dict (which already strips country suffixes)
    code = resolve_station(city_query)
    clean_name = strip_country(city_query)
    if code and code != clean_name.strip():
        return code

    # 2. Check in-memory cache
    cache_key = clean_name.strip().lower()
    if cache_key in _autocomplete_cache:
        return _autocomplete_cache[cache_key]

    # 3. Autocomplete API lookup fallback
    try:
        _throttle()
        url = f"{RAILRADAR_BASE}/lookup/search/stations"
        response = httpx.get(
            url,
            headers=_headers(),
            params={"q": clean_name, "limit": 1},
            timeout=15,
        )
        response.raise_for_status()
        stations = response.json().get("data", [])
        if stations:
            station_code = stations[0].get("code", "")
            _autocomplete_cache[cache_key] = station_code
            return station_code
    except Exception:
        pass

    return ""


# ── Step 1: Trains Between Stations ────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_trains_between(from_code: str, to_code: str, date_str: str) -> list[dict]:
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
    return payload.get("trains", []) if isinstance(payload, dict) else (payload or [])


# ── Step 2: Fare Lookup ────────────────────────────────────────────────────────

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
        raise RateLimitError(f"Train {train_number}: 429 rate limited on fare lookup")
    if response.status_code == 404:
        raise FareNotFoundError(f"Train {train_number}: class {class_code} not available")

    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and not data.get("success", True):
        raise FareNotFoundError(f"Train {train_number}: fare API returned error")

    breakdown = data.get("data", {}).get("breakdown", {})
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


# ── Normalization ──────────────────────────────────────────────────────────────

def _normalize_train(
    raw: dict,
    direction: str,
    currency: str,
    fare_data: dict | None = None,
    class_code: str = "",
    num_travelers: int = 1,
) -> dict:
    train_obj = raw.get("train", {})
    from_obj = raw.get("from", {})
    to_obj = raw.get("to", {})

    train_number = train_obj.get("number", "")
    from_code = from_obj.get("code", "")
    to_code = to_obj.get("code", "")

    duration_raw = raw.get("duration", 0)
    if isinstance(duration_raw, str) and ":" in duration_raw:
        try:
            parts = duration_raw.split(":")
            duration_minutes = int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            duration_minutes = 0
    else:
        try:
            duration_minutes = int(duration_raw)
        except (ValueError, TypeError):
            duration_minutes = 0

    base_single_fare = float(fare_data.get("totalFare", 0)) if fare_data else 0.0
    total_group_price = round(base_single_fare * max(num_travelers, 1), 2)

    return {
        "train_id": f"{train_number}-{direction[:3].upper()}",
        "train_number": train_number,
        "train_name": train_obj.get("name", "Express"),
        "train_type": train_obj.get("type", "EXP"),
        "departure_station": from_code,
        "departure_station_name": from_obj.get("name", from_code),
        "departure_city": from_obj.get("city", ""),
        "departure_time": from_obj.get("departure", ""),
        "departure_day": from_obj.get("day", 1),
        "arrival_station": to_code,
        "arrival_station_name": to_obj.get("name", to_code),
        "arrival_city": to_obj.get("city", ""),
        "arrival_time": to_obj.get("arrival", ""),
        "arrival_day": to_obj.get("day", 1),
        "duration_minutes": duration_minutes,
        "distance_km": raw.get("distance", 0),
        "class_code": fare_data.get("classCode", class_code) if fare_data else (class_code or "SL"),
        "base_fare": base_single_fare,
        "price": total_group_price,
        "currency": currency,
        "direction": direction,
        "pantry": False,
        "run_days": train_obj.get("runDays", []),
        "available_classes": [],
        "fare_breakdown": fare_data.get("breakdown", {}) if fare_data else {},
    }


def _search_direction(
    from_city: str,
    to_city: str,
    date_str: str,
    direction: str,
    currency: str,
    num_travelers: int,
) -> tuple[list[dict], bool]:
    from_code = _resolve_station_with_fallback(from_city)
    to_code = _resolve_station_with_fallback(to_city)

    if not from_code or not to_code:
        raise TrainsAPIError(
            f"Could not resolve stations: '{from_city}'→'{from_code}', '{to_city}'→'{to_code}'"
        )

    raw_trains = _fetch_trains_between(from_code, to_code, date_str)
    if not raw_trains:
        return [], False

    trains_to_price = raw_trains[:MAX_FARE_LOOKUPS]
    normalized = []
    rate_limited = False

    for raw_train in raw_trains:
        train_obj = raw_train.get("train", {})
        train_number = train_obj.get("number", "")

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
                rate_limited = True

        normalized.append(_normalize_train(
            raw=raw_train,
            direction=direction,
            currency=currency,
            fare_data=fare_data,
            class_code=class_code,
            num_travelers=num_travelers,
        ))

    return normalized, rate_limited


def search_trains(state: dict) -> dict:
    """Tool node entry point for StateGraph."""
    log = get_trip_logger(logger, state.get("trip_id", "-"))

    if "trains" not in state.get("search_plan", {}).get("transport_modes", []):
        log.debug("search_trains: skipped — not in transport_modes")
        return {"trains": []}

    if not settings.railradar_api_key:
        log.warning("search_trains: RAILRADAR_API_KEY not configured")
        return {"trains": [], "trains_note": "RAILRADAR_API_KEY not configured."}

    normalized = state.get("normalized_input") or {}
    origin_city = normalized.get("origin_city") or state.get("origin_city", "")
    destination_city = normalized.get("destination") or state.get("destination", "")
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    currency = state.get("currency", "INR")
    num_travelers = state.get("num_travelers", 1)

    if not all([origin_city, destination_city, start_date]):
        log.warning("search_trains: missing origin, destination, or start date")
        return {"trains": [], "trains_note": "Missing origin, destination, or start date."}

    try:
        log.debug("search_trains: outbound %s -> %s on %s", origin_city, destination_city, start_date)
        trains, rate_limited_out = _search_direction(
            from_city=origin_city,
            to_city=destination_city,
            date_str=start_date,
            direction="outbound",
            currency=currency,
            num_travelers=num_travelers,
        )

        rate_limited_ret = False
        if end_date and end_date != start_date:
            log.debug("search_trains: return %s -> %s on %s", destination_city, origin_city, end_date)
            return_trains, rate_limited_ret = _search_direction(
                from_city=destination_city,
                to_city=origin_city,
                date_str=end_date,
                direction="return",
                currency=currency,
                num_travelers=num_travelers,
            )
            trains.extend(return_trains)

        log.info("search_trains: found %d trains total", len(trains))

        result = {"trains": trains}
        if rate_limited_out or rate_limited_ret:
            log.warning("search_trains: rate limited mid-search, partial fare data")
            result["trains_note"] = (
                "Rate limited mid-search — some trains returned without fare pricing."
            )
        return result

    except Exception as e:
        log.warning("search_trains: search failed — %s", e, exc_info=True)
        return {"trains": [], "trains_note": f"Train search failed: {e}"}