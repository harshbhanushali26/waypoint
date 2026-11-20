"""
agents/critic.py

Routes human review edit requests to specific tool nodes or itinerary_builder.
Runs on openai/gpt-oss-120b.
"""

import logging
import re
from langgraph.types import Command
from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.critic_prompt import CRITIC_SYSTEM_PROMPT, build_critic_user_message
from models.schemas import CriticAnalysis
from graph.state import TripState

logger = logging.getLogger(__name__)

VALID_TARGETS = {
    "planner",
    "itinerary_builder",
    "search_flights",
    "search_trains",
    "search_hotels",
    "search_activities",
    "get_weather",
}
SEARCH_TARGETS = VALID_TARGETS - {"planner", "itinerary_builder"}
VALID_TRANSPORT = {"flights", "trains", "any"}

MIN_BUDGET = 1_000
MAX_BUDGET = 10_000_000
MAX_TRAVELERS = 20
MAX_MESSAGE_CHARS = 500

_NEGATION = re.compile(r"\b(no|not|avoid|without|skip|dont|don't|never|instead of)\b")
_SWITCH = re.compile(r"\b(switch|change|use|prefer|take|travel|go|only|instead)\b")


# ── Regex fallbacks ──────────────────────────────────────────────────────────
# Only used when the LLM returned nothing for that field, and only on explicit
# phrasing. A wrong guess here silently changes the whole trip.

def _clean_request(content) -> str:
    text = str(content or "")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return text.strip()[:MAX_MESSAGE_CHARS]


def _extract_budget(text: str) -> float | None:
    t = text.lower().replace(",", "")
    m = re.search(r"\bbudget\b[^\d]{0,20}(\d+(?:\.\d+)?)\s*(k|lakhs?)?\b", t)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "k":
        val *= 1_000
    elif unit and unit.startswith("lakh"):
        val *= 100_000
    return val


def _extract_transport_pref(text: str) -> str | None:
    t = text.lower()
    if not _SWITCH.search(t) or _NEGATION.search(t):
        return None
    wants_train = bool(re.search(r"\b(trains?|rail|railway)\b", t))
    wants_flight = bool(re.search(r"\b(flights?|fly|flying)\b", t))
    if wants_train == wants_flight:      # neither, or both: let the LLM decide
        return None
    return "trains" if wants_train else "flights"


def _extract_num_travelers(text: str) -> int | None:
    m = re.search(r"\b(\d{1,2})\s*(?:travell?ers?|people|persons?|passengers?|adults?)\b", text.lower())
    return int(m.group(1)) if m else None


# ── Node ─────────────────────────────────────────────────────────────────────

def critic_node(state: TripState) -> Command:
    log = get_trip_logger(logger, state["trip_id"])

    messages = state.get("messages") or []
    if not messages:
        raise RuntimeError("Critic invoked with no user message in state")
    user_request = _clean_request(messages[-1].content)
    if not user_request:
        raise RuntimeError("Critic received an empty edit request")

    user_msg = build_critic_user_message(user_request)

    structured_llm = get_structured_llm(
        CriticAnalysis,
        model_tier="reasoning",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["critic"],
        reasoning_effort="low",
    )

    log.debug(
        "Critic input: system_prompt_len=%d user_msg_len=%d",
        len(CRITIC_SYSTEM_PROMPT), len(user_msg),
    )

    response = structured_llm.invoke([
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    log.debug("Critic token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Critic parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Critic parsing failed - see logged raw content above")

    critic_analysis = response["parsed"].model_dump()

    raw_targets = critic_analysis.get("target") or []
    targets = [t for t in dict.fromkeys(raw_targets) if t in VALID_TARGETS]
    if not targets:
        log.warning("Critic returned no valid target (%r); defaulting to itinerary_builder", raw_targets)
        targets = ["itinerary_builder"]

    # ── Trip parameter updates (validated, and only when they actually change) ──
    ni = dict(state.get("normalized_input", {}))
    changed: list[str] = []

    budget = critic_analysis.get("updated_budget")
    if budget is None:
        budget = _extract_budget(user_request)
    if budget is not None:
        if MIN_BUDGET <= budget <= MAX_BUDGET:
            if float(budget) != float(ni.get("budget") or 0):
                log.info("Critic: budget %s -> %.2f", ni.get("budget"), budget)
                ni["budget"] = float(budget)
                changed.append("budget")
        else:
            log.warning("Critic: ignoring out-of-range budget %r", budget)

    pref = critic_analysis.get("updated_transport_pref")
    if pref is None:
        pref = _extract_transport_pref(user_request)
    if pref in VALID_TRANSPORT and pref != ni.get("transport_pref"):
        log.info("Critic: transport_pref %s -> %s", ni.get("transport_pref"), pref)
        ni["transport_pref"] = pref
        changed.append("transport_pref")

    travelers = critic_analysis.get("updated_num_travelers")
    if travelers is None:
        travelers = _extract_num_travelers(user_request)
    if travelers is not None:
        if 1 <= int(travelers) <= MAX_TRAVELERS:
            if int(travelers) != int(ni.get("num_travelers") or 1):
                log.info("Critic: num_travelers %s -> %d", ni.get("num_travelers"), int(travelers))
                ni["num_travelers"] = int(travelers)
                changed.append("num_travelers")
        else:
            log.warning("Critic: ignoring out-of-range traveler count %r", travelers)

    # ── Routing ──────────────────────────────────────────────────────────────
    # The Planner fans out to every tool node, so when it runs it runs alone.
    # A search node leads on to Budget -> Builder, so the Builder must not run in parallel with it.
    if changed or "planner" in targets:
        targets = ["planner"]
    elif any(t in SEARCH_TARGETS for t in targets):
        targets = [t for t in targets if t != "itinerary_builder"]

    log.info("Critic routed to %s (changed=%s) for request: %r", targets, changed, user_request)

    return Command(
        update={
            "critic_analysis": None if "planner" in targets else critic_analysis,
            "normalized_input": ni,
        },
        goto=targets,
    )