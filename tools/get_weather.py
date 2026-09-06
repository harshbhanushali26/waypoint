"""
get_weather — free-API stage (Open-Meteo)

Mechanical tool node: no LLM calls. Queries Open-Meteo's free forecast
API for daily weather data covering the trip's date range, then
normalizes results into the flat dict shape that TripState.weather and
the Itinerary Builder expect.

Fails loud: if the forecast window is too far out, or the API/geocoding
fails, returns an empty list plus a `weather_note` explaining why —
never silently substitutes dummy data. This keeps "real data" and
"degraded" visibly distinguishable in state.
"""

import httpx
from datetime import date
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_FORECAST_DAYS_OUT = 7


class WeatherAPIError(Exception):
    """Raised when Open-Meteo returns no usable weather data."""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, WeatherAPIError)),
    reraise=True
)
def _geo_code(city: str) -> tuple[float, float]:
    response = httpx.get(
        OPEN_METEO_GEOCODING_URL,
        params={"name": f"{city}, India", "count": 1, "language": "en", "format": "json"},
        timeout=15
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    if not results:
        raise WeatherAPIError(f"Could not geocode '{city}'")

    first = results[0]
    return float(first["latitude"]), float(first["longitude"])


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, WeatherAPIError)),
    reraise=True,
)
def _fetch_forecast(lat: float, lon: float, start_date: str, end_date: str) -> dict:
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


WMO_CODE_MAP: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _wmo_to_condition(code: int) -> str:
    return WMO_CODE_MAP.get(code, f"Unknown (code {code})")


def _normalize_forecast(daily: dict) -> list[dict]:
    times = daily.get("time", [])
    codes = daily.get("weather_code", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])

    result = []
    for i, day_str in enumerate(times):
        result.append({
            "date": day_str,
            "condition": _wmo_to_condition(codes[i] if i < len(codes) else 0),
            "temp_max_c": round(t_max[i], 1) if i < len(t_max) else 0,
            "temp_min_c": round(t_min[i], 1) if i < len(t_min) else 0,
            "temp_avg_c": round((t_max[i] + t_min[i]) / 2, 1) if i < len(t_max) and i < len(t_min) else 0,
        })

    return result


def get_weather(state: dict) -> dict:
    """
    Tool node entry point. Reads destination/dates from state.
    Fails loud on any problem — returns {"weather": [], "weather_note": "..."}
    rather than silently substituting dummy data.
    """

    destination = state.get("destination", "")
    start_date_str = state.get("start_date", "")
    end_date_str = state.get("end_date", "")

    if not all([destination, start_date_str, end_date_str]):
        return {"weather": [], "weather_note": "Missing destination or date range."}

    try:
        start = date.fromisoformat(start_date_str)
        days_out = (start - date.today()).days
        
        if days_out > MAX_FORECAST_DAYS_OUT:
            return {
                "weather": [],
                "weather_note": (
                    f"Trip starts {days_out} days from today. Forecast is only "
                    f"fetched within {MAX_FORECAST_DAYS_OUT} days out for now, "
                    f"so no weather data is available yet for this trip."
                ),
            }
        
        lat, lon = _geo_code(destination)
        daily = _fetch_forecast(lat, lon, start_date_str, end_date_str)
        return {"weather": _normalize_forecast(daily)}
    except Exception as e:
        return {"weather": [], "weather_note": f"Weather fetch failed: {e}"}

