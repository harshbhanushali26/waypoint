"""
prompts/activity_extraction_prompt.py

Prompt for the structured activity extraction pass in search_activities.
Extracts discrete, schedulable Activity objects from web page search results.
"""

import json

ACTIVITY_EXTRACTION_SYSTEM_PROMPT = """You are the Activity Extraction step inside Waypoint's search_activities tool node.

You receive web-search results about things to do at one destination. Each result is a PAGE (often a listicle). Convert those pages into DISCRETE activity objects that a trip planner can schedule.

Rules:
1. ONE OBJECT PER ACTUAL ACTIVITY — "Fort Aguada" and "Parasailing at Baga Beach" from a "Top 10" page ARE activities; the page itself is NOT.
2. NEVER INVENT — every activity must be directly supported by the title or snippet of at least one source page.
3. KEEP source_url — provenance for the traveler.
4. PRICE ONLY FROM SOURCES — est_price_inr only when a snippet mentions a number (use the lower bound). Never guess. Default to 0.
5. DURATION ONLY WHEN OBVIOUS — est_duration_hours only when obvious (default 2.0).
6. AREA WHEN NAMED — neighborhood/locality when sources name it, else null.
7. CATEGORY — best-fit: "sightseeing", "food", "outdoors", "cultural", "nightlife", "shopping".
8. DROP NON-ACTIVITIES — skip booking portals, transport guides, hotels.
9. DEDUPLICATE near-identical activities, keeping the richer one. Aim for 10-18 distinct activities total.
10. NO MARKDOWN, NO COMMENTARY — start your output immediately with the JSON object.

--

EXAMPLE OUTPUT FORMAT:
{
  "activities": [
    {
      "name": "Prag Mahal",
      "category": "sightseeing",
      "area": "Bhuj",
      "est_duration_hours": 2.0,
      "est_price_inr": 100,
      "source_url": "https://example.com/bhuj"
    }
  ]
}

Always respond in the required structured format matching the ActivityCatalog schema.
"""


def build_activity_extraction_user_message(
    sources: list[dict], destination: str, interests: list[str]
) -> str:
    """
    sources: merged, deduped Tavily results — each {'title', 'content', 'url'}.
    Snippets capped at 400 chars to bound input tokens.
    """
    payload = [
        {
            "title": s.get("title", ""),
            "snippet": (s.get("content") or "")[:400],
            "url": s.get("url", ""),
        }
        for s in sources
    ]
    interest_line = ", ".join(interests) if interests else "sightseeing, local culture"

    # Single, clean json.dumps (no double stringification)
    sources_json = json.dumps(payload, separators=(",", ":"))

    return f"""Destination: {destination}
Traveler interests: {interest_line}

Search results (each is a web page — extract the discrete activities inside them):

{sources_json}

Extract every distinct, specific activity these pages support into the activities list."""