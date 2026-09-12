"""
search_activities — free-API stage (Tavily) + LLM extraction pass

Two stages:

  1. MECHANICAL FETCH: one Tavily query per interest (capped at 3), merge,
     dedupe by URL. One httpx code path for keyed/keyless.
  2. EXTRACTION (the one documented LLM exception in a tool node):
     expands Tavily pages into discrete Activity objects via one
     structured-output Groq call.

TOKEN BUDGET (learned from production logs):
  Original settings burned 7,571 tokens (4,499 input + 3,072 output with
  2,602 reasoning tokens) — nearly the entire 8,000 TPM budget, which 429'd
  the Budget call immediately after.

  Three fixes applied:
    a. _RESULTS_PER_QUERY 8 → 5, _SNIPPET_CAP 800 → 400, cap sources at 10.
       Input drops from ~4,500 to ~2,000 tokens.
    b. reasoning_effort="low" on the extraction call. The model was spending
       2,602 of 3,072 output tokens on reasoning chains — "low" keeps it
       to a few hundred while preserving extraction quality.
    c. max_tokens 3,000 → 2,000 (in core/llm.py AGENT_MAX_TOKENS).

  Expected total: ~2,000 input + ~1,000 output = ~3,000 tokens.
  Leaves ~5,000 TPM for Budget's call — no 429.

Failure semantics: fails loud on fetch (no dummy data), degrades to raw
pages if extraction fails (activities_note in state). Reads from
normalized_input (Concierge's canonical output) with raw fields as fallback.
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
_RESULTS_PER_QUERY = 4          # was 8 — reduced to cut extraction input tokens
_MAX_SOURCES_FOR_EXTRACTION = 7  # cap before the LLM call
_SNIPPET_CAP = 400             # was 800 — 400 chars is enough to see named activities


class ActivitiesAPIError(Exception):
    """Raised when Tavily returns no usable activity data."""


# ── Stage 1: mechanical fetch ────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _fetch_search_results(query: str) -> list[dict]:
    """One Tavily search call. Keyed or keyless — one httpx code path."""
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
            "search_depth": "advanced",
        },
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def _build_queries(destination: str, interests: list[str]) -> list[str]:
    """One query per interest, capped at _MAX_INTEREST_QUERIES."""
    if interests:
        return [
            f"best {interest} in {destination} India"
            for interest in interests[:_MAX_INTEREST_QUERIES]
        ]
    return [f"best things to do in {destination} India"]


def _fetch_all(queries: list[str], log) -> list[dict]:
    """Run all queries, merge, dedupe by URL. Tolerates single-query failures."""
    merged: list[dict] = []
    seen_urls: set[str] = set()
    failures: list[str] = []

    for query in queries:
        try:
            results = _fetch_search_results(query)
        except Exception as e:
            log.warning("search_activities: query failed — %r — %s", query, e)
            failures.append(f"{query}: {e}")
            continue

        for raw in results:
            url = raw.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(raw)

    if not merged:
        detail = "; ".join(failures) if failures else "Tavily returned no results"
        raise ActivitiesAPIError(detail)

    if failures:
        log.info(
            "search_activities: %d/%d queries succeeded, %d merged results",
            len(queries) - len(failures), len(queries), len(merged),
        )
    return merged


# ── Stage 2: extraction pass ────────────────────────────────────────────

def _extract_activities(
    sources: list[dict], destination: str, interests: list[str], log
) -> list[dict]:
    """
    Expands merged source pages into discrete Activity objects via one
    structured-output LLM call. reasoning_effort="low" is critical — without
    it, gpt-oss-120b spends ~2,600 tokens on reasoning chains, which alone
    consume a third of the 8,000 TPM budget.

    Sources are capped at _MAX_SOURCES_FOR_EXTRACTION before the call to
    bound input size. Snippets are capped at _SNIPPET_CAP chars each.
    """
    # Cap the number of source pages sent to the LLM — 10 is enough to
    # extract 10-25 activities, and bounds input tokens.
    if len(sources) > _MAX_SOURCES_FOR_EXTRACTION:
        log.info(
            "search_activities: capping %d sources to %d for extraction",
            len(sources), _MAX_SOURCES_FOR_EXTRACTION,
        )
        sources = sources[:_MAX_SOURCES_FOR_EXTRACTION]

    structured_llm = get_structured_llm(
        ActivityCatalog,
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["activity_extraction"],
        reasoning_effort="low",
    )
    user_message = build_activity_extraction_user_message(
        sources, destination, interests
    )

    log.debug(
        "Activity extraction input: system_prompt_len=%d user_msg_len=%d sources=%d",
        len(ACTIVITY_EXTRACTION_SYSTEM_PROMPT), len(user_message), len(sources),
    )

    response = structured_llm.invoke(
        [
            {"role": "system", "content": ACTIVITY_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    log.debug("Activity extraction token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Activity extraction parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError(
            "Activity extraction parsing failed - see logged raw content above"
        )

    return [a.model_dump() for a in response["parsed"].activities]


# ── Degraded-mode normalizer ─────────────────────────────────────────────

def _normalize_page(raw: dict) -> dict:
    """Fallback when extraction fails: page-level activity in new field names."""
    return {
        "name": raw.get("title", ""),
        "category": "sightseeing",
        "area": None,
        "est_duration_hours": None,
        "est_price_inr": None,
        "source_url": raw.get("url", ""),
        "snippet": (raw.get("content") or "")[:500],
    }


# ── Node entry point ─────────────────────────────────────────────────────

def search_activities(state: dict) -> dict:
    """Tool node entry point. Fails loud on fetch, degrades on extraction."""
    log = get_trip_logger(logger, state.get("trip_id", "-"))

    normalized_input = state.get("normalized_input") or {}
    destination = normalized_input.get("destination") or state.get("destination", "")
    interests = normalized_input.get("interests") or state.get("interests") or []

    if not destination:
        log.warning("search_activities: missing destination")
        return {"activities": [], "activities_note": "Missing destination."}

    queries = _build_queries(destination, interests)
    log.debug("search_activities: queries=%r", queries)

    try:
        sources = _fetch_all(queries, log)
    except Exception as e:
        log.warning("search_activities: search failed — %s", e, exc_info=True)
        return {"activities": [], "activities_note": f"Activity search failed: {e}"}

    try:
        activities = _extract_activities(sources, destination, interests, log)
        if not activities:
            raise ActivitiesAPIError("extraction returned no activities")
        log.info(
            "search_activities: extracted %d discrete activities from %d source pages",
            len(activities), len(sources),
        )
        return {"activities": activities}

    except Exception as e:
        log.warning(
            "search_activities: extraction failed — degrading to raw pages — %s",
            e, exc_info=True,
        )
        return {
            "activities": [_normalize_page(r) for r in sources],
            "activities_note": (
                "Activity extraction failed, itinerary built from raw "
                f"source pages: {e}"
            ),
        }
