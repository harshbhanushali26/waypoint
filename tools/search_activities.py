"""
tools/search_activities.py

Free-API stage (Tavily search) + LLM extraction pass using model_tier="fast".
"""

import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings
from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from models.schemas import ActivityCatalog
from prompts.activity_extraction_prompt import (
    ACTIVITY_EXTRACTION_SYSTEM_PROMPT,
    build_activity_extraction_user_message,
)

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

_MAX_INTEREST_QUERIES = 3
_RESULTS_PER_QUERY = 4
_MAX_SOURCES_FOR_EXTRACTION = 7
_SNIPPET_CAP = 400


class ActivitiesAPIError(Exception):
    """Raised when Tavily returns no usable activity data."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_search_results(query: str) -> list[dict]:
    headers = {"Content-Type": "application/json"}
    if settings.tavily_api_key and settings.tavily_api_key != "YOUR_TAVILY_API_KEY":
        headers["Authorization"] = f"Bearer {settings.tavily_api_key}"
    else:
        headers["X-Tavily-Access-Mode"] = "keyless"

    response = httpx.post(
        TAVILY_SEARCH_URL,
        json={
            "query": query,
            "max_results": _RESULTS_PER_QUERY,
            "search_depth": "basic",
        },
        headers=headers,
        timeout=25,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def _build_queries(destination: str, interests: list[str]) -> list[str]:
    if interests:
        return [
            f"best {interest} in {destination} India"
            for interest in interests[:_MAX_INTEREST_QUERIES]
        ]
    return [
        f"top attractions and things to do in {destination} India",
        f"famous food culture and sights in {destination} India",
    ]


def _fetch_all(queries: list[str], log) -> list[dict]:
    merged: list[dict] = []
    seen_urls: set[str] = set()
    failures: list[str] = []

    for query in queries:
        try:
            results = _fetch_search_results(query)
            for raw in results:
                url = raw.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    merged.append(raw)
        except Exception as e:
            log.warning("search_activities: query '%s' failed — %s", query, e)
            failures.append(f"{query}: {e}")
            continue

    if not merged:
        detail = "; ".join(failures) if failures else "Tavily returned no results"
        raise ActivitiesAPIError(detail)

    if failures:
        log.info(
            "search_activities: %d/%d queries succeeded, %d merged sources",
            len(queries) - len(failures), len(queries), len(merged),
        )
    return merged


def _extract_activities(
    sources: list[dict], destination: str, interests: list[str], log
) -> list[dict]:
    capped_sources = sources[:_MAX_SOURCES_FOR_EXTRACTION]

    # Uses the fast 20B model tier
    structured_llm = get_structured_llm(
        ActivityCatalog,
        model_tier="fast",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS.get("activity_extraction", 2000),
        reasoning_effort="low",
    )
    user_message = build_activity_extraction_user_message(
        capped_sources, destination, interests
    )

    response = structured_llm.invoke(
        [
            {"role": "system", "content": ACTIVITY_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    if isinstance(response, dict) and "raw" in response:
        log.debug("search_activities token usage: %s", getattr(response["raw"], "usage_metadata", None))

    if response.get("parsed") is None:
        raw_msg = getattr(response.get("raw"), "content", "")
        log.error("search_activities: structured parsing failed. Raw response: %r", raw_msg)
        raise RuntimeError("Activity extraction output parsing failed")

    return [a.model_dump() for a in response["parsed"].activities]


def _normalize_page(raw: dict) -> dict:
    return {
        "name": raw.get("title", "Local Attraction"),
        "category": "sightseeing",
        "area": None,
        "est_duration_hours": 2.0,
        "est_price_inr": 0,
        "source_url": raw.get("url", ""),
        "snippet": (raw.get("content") or "")[:_SNIPPET_CAP],
    }


def search_activities(state: dict) -> dict:
    log = get_trip_logger(logger, state.get("trip_id", "-"))

    normalized_input = state.get("normalized_input") or {}
    destination = normalized_input.get("destination") or state.get("destination", "")
    interests = normalized_input.get("interests") or state.get("interests") or []

    if not destination:
        log.warning("search_activities: missing destination")
        return {"activities": [], "activities_note": "Missing destination."}

    queries = _build_queries(destination, interests)
    try:
        sources = _fetch_all(queries, log)
    except Exception as e:
        log.warning("search_activities: fetch failed — %s", e, exc_info=True)
        return {"activities": [], "activities_note": f"Activity search failed: {e}"}

    try:
        activities = _extract_activities(sources, destination, interests, log)
        if not activities:
            raise ActivitiesAPIError("Extraction returned 0 activities")
        log.info("search_activities: extracted %d activities from %d pages", len(activities), len(sources))
        return {"activities": activities}
    except Exception as e:
        log.warning("search_activities: extraction failed — degrading to raw pages — %s", e, exc_info=True)
        return {
            "activities": [_normalize_page(r) for r in sources[:8]],
            "activities_note": f"Activity extraction degraded to source pages: {e}",
        }