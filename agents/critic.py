"""
agents/critic.py

Routes human review edit requests to specific tool nodes or itinerary_builder.
Runs on openai/gpt-oss-120b.
"""

import logging
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

    # If replanning, clear critic_analysis so builder executes in full BUILD mode
    update_dict = {"critic_analysis": None if "planner" in targets else critic_analysis}
    return Command(update=update_dict, goto=targets)