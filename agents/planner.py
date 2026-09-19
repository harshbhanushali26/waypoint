"""
agents/planner.py

Generates search plan for transport modes (flights, trains) and budget tier.
Runs on openai/gpt-oss-20b for high speed.
"""

import logging
from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.planner_prompt import PLANNER_SYSTEM_PROMPT, build_planner_user_message
from models.schemas import SearchPlan
from graph.state import TripState

logger = logging.getLogger(__name__)


def planner_node(state: TripState) -> dict:
    log = get_trip_logger(logger, state["trip_id"])
    normalized_input = state["normalized_input"]
    user_message = build_planner_user_message(normalized_input)

    structured_llm = get_structured_llm(
        SearchPlan,
        model_tier="fast",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["planner"],
    )

    log.debug(
        "Planner input: system_prompt_len=%d user_msg_len=%d",
        len(PLANNER_SYSTEM_PROMPT), len(user_message),
    )

    response = structured_llm.invoke([
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ])

    log.debug("Planner token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Planner parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Planner parsing failed - see logged raw content above")

    search_plan = response["parsed"].model_dump()

    # Ensure transport_priority only contains valid selected modes
    valid_modes = set(search_plan["transport_modes"])
    search_plan["transport_priority"] = [m for m in search_plan["transport_priority"] if m in valid_modes]

    log.info("Planner: selected modes=%s, tier=%s", search_plan["transport_modes"], search_plan["budget_tier"])
    return {"search_plan": search_plan, "status": "searching_and_analyzing_budget"}