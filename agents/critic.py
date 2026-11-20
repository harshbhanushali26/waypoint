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


def _extract_budget(text: str) -> float | None:
    text_clean = text.lower().replace(",", "")
    m = re.search(r"budget\s*(?:to|is|of|=)?\s*(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|lakh)?", text_clean)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == "k":
            val *= 1000
        elif unit == "lakh":
            val *= 100000
        return val
    m2 = re.search(r"(?:to|increase to|reduce to)\s+(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|lakh)?", text_clean)
    if m2:
        val = float(m2.group(1))
        unit = m2.group(2)
        if unit == "k":
            val *= 1000
        elif unit == "lakh":
            val *= 100000
        return val
    return None


def _extract_transport_pref(text: str) -> str | None:
    t = text.lower()
    if "train" in t or "rail" in t:
        return "trains"
    if "flight" in t or "air" in t or "fly" in t:
        return "flights"
    if "bus" in t:
        return "buses"
    return None


def _extract_num_travelers(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"(\d+)\s*(?:travelers?|people|persons?|passengers?)", t)
    if m:
        return int(m.group(1))
    return None


def critic_node(state: TripState) -> Command:
    log = get_trip_logger(logger, state["trip_id"])
    user_request = state["messages"][-1].content
    user_msg = build_critic_user_message(user_request)

    structured_llm = get_structured_llm(
        CriticAnalysis,
        model_tier="reasoning",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["critic"],
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
    raw_targets = critic_analysis.get("target", ["itinerary_builder"])
    targets = [t for t in raw_targets if t in VALID_TARGETS] or ["itinerary_builder"]

    log.info("Critic routed to: %s for request: %r", targets, user_request)

    # ── State Update Logic for Human Review Feedback ──────────────────────────
    normalized_input = dict(state.get("normalized_input", {}))
    param_updated = False

    new_budget = critic_analysis.get("updated_budget") or _extract_budget(user_request)
    if new_budget and new_budget > 0:
        log.info("Critic: updating budget from %.2f to %.2f", normalized_input.get("budget", 0), new_budget)
        normalized_input["budget"] = float(new_budget)
        param_updated = True

    new_transport = critic_analysis.get("updated_transport_pref") or _extract_transport_pref(user_request)
    if new_transport:
        log.info("Critic: updating transport_pref from %s to %s", normalized_input.get("transport_pref"), new_transport)
        normalized_input["transport_pref"] = new_transport
        param_updated = True

    new_travelers = critic_analysis.get("updated_num_travelers") or _extract_num_travelers(user_request)
    if new_travelers and new_travelers > 0:
        log.info("Critic: updating num_travelers from %d to %d", normalized_input.get("num_travelers", 1), new_travelers)
        normalized_input["num_travelers"] = int(new_travelers)
        param_updated = True

    # If core parameters changed, ensure planner re-evaluates
    if param_updated and "planner" not in targets:
        targets.insert(0, "planner")

    update_dict = {
        "critic_analysis": None if "planner" in targets else critic_analysis,
        "normalized_input": normalized_input,
    }
    return Command(update=update_dict, goto=targets)