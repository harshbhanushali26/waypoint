"""critic_node — interprets a human_review edit request and routes to the
node(s) that need to re-run via Command(goto=...)."""

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
    "search_buses",
    "search_cars",
    "search_hotels",
    "search_activities",
    "get_weather",
}


class InvalidCriticTargetError(Exception):
    """Raised when the Critic Agent returns a target outside VALID_TARGETS.
    Deliberately not auto-corrected or retried yet — see Step 7 testing
    notes before deciding whether this needs a retry loop or fuzzy-match
    fallback. Better to see real failures first than guess at a fix."""


def critic_node(state: TripState) -> Command:
    """Interprets the latest human_review message, returns a Command
    routing to the node(s) that need to re-run."""
    # Latest user turn during human_review
    user_request = state["messages"][-1].content

    log = get_trip_logger(logger, state["trip_id"])

    user_message = build_critic_user_message(user_request)
    structured_llm = get_structured_llm(CriticAnalysis, include_raw=True, max_tokens=AGENT_MAX_TOKENS["critic"])

    log.debug(
        "Critic input: system_prompt_len=%d user_msg_len=%d",
        len(CRITIC_SYSTEM_PROMPT), len(user_message),
    )

    response = structured_llm.invoke(
        [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    log.debug("Critic token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Critic parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Critic parsing failed - see logged raw content above")

    critic_analysis = response["parsed"].model_dump()
    log.info("Critic analysis: %s", critic_analysis)
    target = critic_analysis["target"]

    invalid = [t for t in target if t not in VALID_TARGETS]
    if invalid:
        log.error(
            "critic_node: invalid target(s) from LLM. invalid=%s "
            "full_target=%s user_request=%r interpretation=%r reasoning=%r",
            invalid, target, user_request,
            critic_analysis.get("interpretation"),
            critic_analysis.get("reasoning"),
        )
        raise InvalidCriticTargetError(
            f"Critic returned invalid target(s) {invalid} "
            f"(full target: {target}) for user_request: {user_request!r}"
        )

    return Command(
        update={"critic_analysis": critic_analysis},
        goto=target,
    )