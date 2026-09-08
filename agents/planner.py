import logging

from prompts.planner_prompt import PLANNER_SYSTEM_PROMPT, build_planner_user_message
from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from models.schemas import SearchPlan
from graph.state import TripState

logger = logging.getLogger(__name__)


def planner_node(state: TripState) -> dict:
    normalized_input = state["normalized_input"]
    user_message = build_planner_user_message(normalized_input)

    structured_llm = get_structured_llm(SearchPlan)

    logger.debug(
        "Planner input: system_prompt_len=%d user_msg_len=%d",
        len(PLANNER_SYSTEM_PROMPT), len(user_message),
    )

    response = structured_llm.invoke(
        [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=AGENT_MAX_TOKENS["planner"],
    )

    search_plan = response.model_dump()
    logger.info("Planner search_plan: %s", search_plan)

    # Cross-field constraint the schema can't express: strict:true guarantees
    # each field's shape individually, not that transport_priority is a
    # subset of transport_modes. Repair rather than trust or silently drop.
    valid_modes = set(search_plan["transport_modes"])
    priority = search_plan["transport_priority"]
    filtered_priority = [m for m in priority if m in valid_modes]

    if filtered_priority != priority:
        logger.warning(
            "planner_node: transport_priority contained modes outside "
            "transport_modes. raw=%s valid=%s -> repaired=%s",
            priority, sorted(valid_modes), filtered_priority,
        )
        search_plan["transport_priority"] = filtered_priority

    return {"search_plan": search_plan, "status": "searching_and_analyzing_budget"}