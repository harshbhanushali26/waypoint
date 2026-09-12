"""
Activity Extraction — prompts/activity_extraction_prompt.py

Used by the ONE documented LLM exception inside a tool node: the extraction
pass in search_activities. Tavily returns web PAGES ("Top 10 things to do in
Goa"), not activities; this prompt converts those pages into discrete,
schedulable Activity objects.

TOKEN BUDGET: snippets are capped at 400 chars (down from 800) — enough to
see every named activity in a listicle, without burning input tokens on
boilerplate.
"""

ACTIVITY_EXTRACTION_SYSTEM_PROMPT = """You are the Activity Extraction step inside Waypoint's search_activities tool node.

You receive web-search results about things to do at one destination. Each
result is a PAGE — often a listicle naming many distinct places and
experiences. Convert those pages into DISCRETE activity objects that a trip
planner can schedule one at a time.

Rules:
1. ONE OBJECT PER ACTUAL ACTIVITY — never one per source page. "Fort
   Aguada" and "Parasailing at Baga Beach" extracted from a "Top 10" page
   ARE activities; the page itself is NOT.
2. NEVER INVENT — every activity must be directly supported by the title
   or snippet of at least one source page.
3. KEEP source_url — provenance for the traveler.
4. PRICE ONLY FROM SOURCES — est_price_inr only when a snippet mentions a
   number (lower bound of any range). Never guess. Null otherwise.
5. DURATION ONLY WHEN OBVIOUS — est_duration_hours only when the snippet
   or the exact activity makes it trivially clear. Null otherwise.
6. AREA WHEN NAMED — neighborhood/locality when the sources name it.
7. CATEGORY — best-fit from the interest list, else a generic label:
   "sightseeing", "food", "outdoors", "nightlife", "shopping".
8. DROP NON-ACTIVITIES — skip booking portals, transport guides, hotels.
9. DEDUPLICATE near-identical activities, keeping the richer one. Aim for
   10-25 distinct activities total.
10. NO EXTRAS — no commentary or fields beyond the structured format.

You must always respond in the required structured format.
"""


def build_activity_extraction_user_message(
   sources: list[dict], destination: str, interests: list[str]
) -> str:
   """
   sources: merged, deduped Tavily results — each {'title', 'content', 'url'}.
   Snippets capped at 400 chars: enough for the model to see every named
   activity in a listicle, without burning input tokens on boilerplate.
   """
   import json

   payload = [
      {
            "title": s.get("title", ""),
            "snippet": (s.get("content") or "")[:400],
            "url": s.get("url", ""),
      }
      for s in sources
   ]
   interest_line = ", ".join(interests) if interests else "none stated"
   payload = json.dumps(payload, separators=(",", ":"))
   
   return f"""Destination: {destination}
Traveler interests: {interest_line}

Search results (each is a web page — extract the discrete activities inside them):

{json.dumps(payload, indent=2)}

Extract every distinct, specific activity these pages support."""
