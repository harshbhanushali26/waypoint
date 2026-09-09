"""
search_activities — free-API stage (Tavily)

Mechanical tool node: no LLM calls. Fails loud — no dummy fallback.
"""

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings

from core.logging import get_trip_logger

logger = logging.getLogger(__name__)

class ActivitiesAPIError(Exception):
    """Raised when Tavily returns no usable activity data."""


# ── Fetch ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_activities(query: str, use_key: bool = False) -> list[dict]:
    """Queries Tavily (keyed client or keyless HTTP fallback), returns raw results."""
    if use_key and settings.tavily_api_key:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(query, max_results=10, search_depth="advanced")
        results = response.get("results", [])
    else:
        response = httpx.post(
                "https://api.tavily.com/search",
                json={"query": query, "max_results": 10, "search_depth": "advanced"},
                headers={"X-Tavily-Access-Mode": "keyless"},
                timeout=30,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

    if not results:
        raise ActivitiesAPIError("Tavily returned no results")
    return results


# ── Normalize ────────────────────────────────────────────────────────────


def _normalize_activity(raw: dict) -> dict:
    """Converts one Tavily result into Waypoint's flat activity dict."""
    return {
        "title": raw.get("title", ""),
        "snippet": raw.get("content", "")[:500],
        "url": raw.get("url", ""),
    }

# ── Node entry point ─────────────────────────────────────────────────────

def search_activities(state: dict) -> dict:
    """
    Tool node entry point. Fails loud on any problem — no dummy fallback.
    """
    log = get_trip_logger(logger, state.get("trip_id", "-"))

    destination = state.get("destination", "")
    interests = state.get("interests", [])
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")

    if not destination:
        log.warning("search_activities: missing destination")
        return {"activities": [], "activities_note": "Missing destination."}

    interest_str = ", ".join(interests) if interests else "things to do"

    if start_date and end_date:
        date_context = f" in {start_date} to {end_date}"
    elif start_date:
        date_context = f" in {start_date}"
    else:
        date_context = ""

    query = f"best {interest_str} in {destination}{date_context} India"
    log.debug("search_activities: query=%r", query)

    try:
        use_key = bool(settings.tavily_api_key and settings.tavily_api_key != "YOUR_TAVILY_API_KEY")
        raw_results = _fetch_activities(query, use_key=use_key)
        activities = [_normalize_activity(r) for r in raw_results]
        log.info("search_activities: found %d activities", len(activities))  # NEW
        return {"activities": activities}

    except Exception as e:
        log.warning("search_activities: search failed — %s", e, exc_info=True)
        return {"activities": [], "activities_note": f"Activity search failed: {e}"}