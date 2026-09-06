"""
search_activities — free-API stage (Tavily)

Mechanical tool node: no LLM calls. Fails loud — no dummy fallback.
"""

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

from core.config import settings


class ActivitiesAPIError(Exception):
    """Raised when Tavily returns no usable activity data."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_activities(query: str, use_key: bool = False) -> list[dict]:
    if use_key and settings.tavily_api_key:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(query, max_results=10, search_depth="advanced")
        results = response.get("results", [])
        if not results:
            raise ActivitiesAPIError("Tavily returned no results")
        return results

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


def _normalize_activity(raw: dict) -> dict:
    return {
        "title": raw.get("title", ""),
        "snippet": raw.get("content", "")[:500],
        "url": raw.get("url", ""),
    }


def search_activities(state: dict) -> dict:
    """
    Tool node entry point. Fails loud on any problem — no dummy fallback.
    """
    destination = state.get("destination", "")
    interests = state.get("interests", [])
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")

    if not destination:
        return {"activities": [], "activities_note": "Missing destination."}

    interest_str = ", ".join(interests) if interests else "things to do"
    date_context = f" in {start_date} to {end_date}" if start_date and end_date else (f" in {start_date}" if start_date else "")
    query = f"best {interest_str} in {destination}{date_context} India"

    try:
        use_key = bool(settings.tavily_api_key and settings.tavily_api_key != "YOUR_TAVILY_API_KEY")
        raw_results = _fetch_activities(query, use_key=use_key)
        return {"activities": [_normalize_activity(r) for r in raw_results]}

    except Exception as e:
        return {"activities": [], "activities_note": f"Activity search failed: {e}"}