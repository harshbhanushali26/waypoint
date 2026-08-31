import json
import logging

from langgraph.types import Command

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
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
    # Latest user turn during human_review

    user_request = state["messages"][-1].content

    # structured_llm = llm.with_structured_output(CriticAnalysis)
    structured_llm = get_structured_llm(CriticAnalysis)

    print("--- Critic ---")
    print(len(CRITIC_SYSTEM_PROMPT))
    print(len(build_critic_user_message(user_request)))

    response = structured_llm.invoke(
        [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": build_critic_user_message(user_request)},
        ],
        max_tokens=AGENT_MAX_TOKENS["critic"],
    )

    critic_analysis = response.model_dump()
    print(f"[Critic] : {critic_analysis}")
    target = critic_analysis["target"]

    invalid = [t for t in target if t not in VALID_TARGETS]
    if invalid:
        logger.error(
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