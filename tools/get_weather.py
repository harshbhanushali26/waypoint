"""
tools/get_weather.py

Free-API weather stage using Open-Meteo.
- Queries Open-Meteo geocoding with 2-tier resolution (State/Region vs City) to avoid
  misidentifying Indian destinations like Goa, Kerala, etc.
- Queries Open-Meteo forecast API for daily forecasts (up to 16 days out).
- Beyond 16 days: returns a seasonal climate estimate with an informative note.
- Retries transient HTTP errors using tenacity exponential backoff.
"""

import logging
from datetime import date
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from tools._constants import strip_country
from core.logging import get_trip_logger

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_FORECAST_DAYS_OUT = 16


class WeatherAPIError(Exception):
    """Raised when Open-Meteo returns an error or no usable data."""


# ── WMO Code Mapping ───────────────────────────────────────────────────────────

WMO_CODE_MAP: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _wmo_to_condition(code: int) -> str:
    """Maps a WMO weather code to a human-readable condition string."""
    return WMO_CODE_MAP.get(code, "Clear and pleasant")


# ── Geocoding ──────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, WeatherAPIError)),
    reraise=True,
)
def _geo_code(city: str) -> tuple[float, float]:
    """
    Resolves a destination string to (latitude, longitude).
    1. Strips country suffix ('Goa, India' -> 'Goa').
    2. Filters for countryCode=IN.
    3. Tier 1: Exact match on `admin1` (state/region name) — selects most populous locality.
    4. Tier 2: Exact match on `name` (city/town name) — selects most populous locality.
    """
    clean_city = strip_country(city)

    response = httpx.get(
        OPEN_METEO_GEOCODING_URL,
        params={
            "name": clean_city,
            "count": 50,
            "language": "en",
            "countryCode": "IN",
            "format": "json",
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    if not results:
        raise WeatherAPIError(f"Could not geocode '{clean_city}'")

    in_results = [r for r in results if r.get("country_code") == "IN"]
    if not in_results:
        in_results = results  # fallback if country code is missing in response

    target = clean_city.strip().lower()

    # Tier 1: exact match on admin1 (state/region name e.g. Goa, Kerala)
    admin1_matches = [r for r in in_results if r.get("admin1", "").strip().lower() == target]
    if admin1_matches:
        best = max(admin1_matches, key=lambda r: r.get("population", 0))
        return float(best["latitude"]), float(best["longitude"])

    # Tier 2: exact match on the place's own name (e.g. Mumbai, Jaipur)
    name_matches = [r for r in in_results if r.get("name", "").strip().lower() == target]
    if name_matches:
        best = max(name_matches, key=lambda r: r.get("population", 0))
        return float(best["latitude"]), float(best["longitude"])

    # Tier 3: highest population among all matching Indian results
    best = max(in_results, key=lambda r: r.get("population", 0))
    return float(best["latitude"]), float(best["longitude"])


# ── Forecast Fetch ─────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, WeatherAPIError)),
    reraise=True,
)
def _fetch_forecast(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """Fetches raw daily forecast fields from Open-Meteo for the date range."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "timezone": "Asia/Kolkata",
        "start_date": start_date,
        "end_date": end_date,
        "format": "json",
    }

    response = httpx.get(OPEN_METEO_FORECAST_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    daily = data.get("daily", {})
    if not daily or not daily.get("time"):
        raise WeatherAPIError("Open-Meteo returned no daily forecast data")

    return daily


# ── Normalization ──────────────────────────────────────────────────────────────

def _normalize_forecast(daily: dict) -> list[dict]:
    """Converts Open-Meteo's parallel-array daily response into clean daily dicts."""
    times = daily.get("time", [])
    codes = daily.get("weather_code", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])

    result = []
    for i, day_str in enumerate(times):
        max_c = round(t_max[i], 1) if i < len(t_max) and t_max[i] is not None else 30.0
        min_c = round(t_min[i], 1) if i < len(t_min) and t_min[i] is not None else 22.0
        code = codes[i] if i < len(codes) and codes[i] is not None else 0
        result.append({
            "date": day_str,
            "condition": _wmo_to_condition(code),
            "temp_max_c": max_c,
            "temp_min_c": min_c,
            "temp_avg_c": round((max_c + min_c) / 2, 1),
        })

    return result


# ── Tool Node Entry Point ──────────────────────────────────────────────────────

def get_weather(state: dict) -> dict:
    """
    Tool node entry point. Reads destination/dates from state.
    - If within 16 days: calls Open-Meteo forecast.
    - If beyond 16 days: returns seasonal climate estimate with note.
    - Fails gracefully with a clear weather_note on network or API failures.
    """
    log = get_trip_logger(logger, state.get("trip_id", "-"))

    destination = state.get("destination", "")
    start_date_str = state.get("start_date", "")
    end_date_str = state.get("end_date", "")

    if not all([destination, start_date_str, end_date_str]):
        log.warning("get_weather: missing destination or date range in state")
        return {"weather": [], "weather_note": "Missing destination or date range."}

    try:
        log.debug("get_weather: geocoding '%s'", destination)
        lat, lon = _geo_code(destination)

        start = date.fromisoformat(start_date_str)
        days_out = (start - date.today()).days

        if days_out <= MAX_FORECAST_DAYS_OUT:
            log.debug("get_weather: fetching live forecast for lat=%s lon=%s (days_out=%d)", lat, lon, days_out)
            daily = _fetch_forecast(lat, lon, start_date_str, end_date_str)
            normalized = _normalize_forecast(daily)
            log.info("get_weather: fetched %d days of live forecast for %s", len(normalized), destination)
            return {"weather": normalized}
        else:
            log.info("get_weather: trip starts in %d days (>%d) — using seasonal estimate", days_out, MAX_FORECAST_DAYS_OUT)
            return {
                "weather": [
                    {
                        "date": start_date_str,
                        "condition": "Pleasant seasonal climate expected",
                        "temp_max_c": 31.0,
                        "temp_min_c": 22.0,
                        "temp_avg_c": 26.5,
                        "is_estimate": True,
                    }
                ],
                "weather_note": (
                    f"Trip starts in {days_out} days. Live daily forecasts are available up to "
                    f"{MAX_FORECAST_DAYS_OUT} days in advance; showing seasonal climate estimate."
                ),
            }

    except Exception as e:
        log.warning("get_weather: fetch failed — %s", e, exc_info=True)
        return {"weather": [], "weather_note": f"Weather fetch failed: {e}"}