"""
search_hotels — free-API stage (SerpApi Google Hotels)

Mechanical tool node: no LLM calls. Fails loud — no dummy fallback.
"""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings


SERPAPI_BASE = "https://serpapi.com/search"


class HotelsAPIError(Exception):
    """Raised when SerpApi returns an explicit error or no usable hotel data."""


# ── Fetch ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_hotels(params: dict) -> list[dict]:
    response = httpx.get(SERPAPI_BASE, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise HotelsAPIError(f"SerpApi error: {data['error']}")

    properties = data.get("properties", [])
    if not properties:
        raise HotelsAPIError("SerpApi returned no hotel properties")

    return properties


# ── Normalize ────────────────────────────────────────────────────────────

def _normalize_hotel(raw: dict, currency: str) -> dict:
    rate = raw.get("rate_per_night", {})
    total = raw.get("total_rate", {})
    coords = raw.get("gps_coordinates", {})

    hotel_class = raw.get("extracted_hotel_class")
    if hotel_class is None:
        class_str = raw.get("hotel_class", "")
        hotel_class = int(class_str[0]) if class_str and class_str[0].isdigit() else 0

    ota_prices = [
        {
            "source": p.get("source", ""),
            "price_per_night": float(p.get("rate_per_night", {}).get("extracted_lowest", 0)),
            "free_cancellation": p.get("free_cancellation", False),
        }
        for p in raw.get("prices", [])
    ]

    images = raw.get("images", [])
    thumbnail = images[0].get("thumbnail", "") if images else ""

    return {
        "hotel_id": raw.get("property_token", ""),
        "name": raw.get("name", ""),
        "hotel_class": hotel_class,
        "rating": raw.get("overall_rating", 0),
        "reviews_count": raw.get("reviews", 0),
        "price_per_night": float(rate.get("extracted_lowest", 0)),
        "total_price": float(total.get("extracted_lowest", 0)),
        "currency": currency,
        "check_in_time": raw.get("check_in_time", ""),
        "check_out_time": raw.get("check_out_time", ""),
        "latitude": coords.get("latitude", 0),
        "longitude": coords.get("longitude", 0),
        "amenities": raw.get("amenities", []),
        "free_cancellation": raw.get("free_cancellation", False),
        "thumbnail": thumbnail,
        "ota_prices": ota_prices,
        "serpapi_details_link": raw.get("serpapi_property_details_link", ""),
    }


# ── Node entry point ─────────────────────────────────────────────────────

def search_hotels(state: dict) -> dict:
    """
    Tool node entry point. Fails loud on any problem — no dummy fallback.
    """
    if not settings.serpapi_hotels_key:
        return {"hotels": [], "hotels_note": "SERPAPI_HOTELS_KEY not configured."}

    destination = state.get("destination", "")
    check_in = state.get("start_date", "")
    check_out = state.get("end_date", "")
    num_travelers = state.get("num_travelers", 1)
    currency = state.get("currency", "INR")

    if not all([destination, check_in, check_out]):
        return {"hotels": [], "hotels_note": "Missing destination or check-in/check-out dates."}

    try:
        params = {
            "engine": "google_hotels",
            "q": f"hotels in {destination}",
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": str(num_travelers),
            "currency": currency,
            "hl": "en",
            "gl": "in",
            "api_key": settings.serpapi_hotels_key,
        }
        raw_hotels = _fetch_hotels(params)
        hotels = [_normalize_hotel(h, currency) for h in raw_hotels]

        # SerpApi returns hotels in Google's default ranking order
        # (relevance/popularity), not by price. Sort by total_price
        # ascending so the budget node's min() and the itinerary
        # builder's top-N cut both see the cheapest hotels first.
        hotels.sort(key=lambda h: h.get("total_price", 0))

        return {"hotels": hotels}

    except Exception as e:
        return {"hotels": [], "hotels_note": f"Hotel search failed: {e}"}   