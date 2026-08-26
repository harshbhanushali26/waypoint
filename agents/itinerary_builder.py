import json
import logging

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from prompts.itinerary_builder_prompt import ITINERARY_BUILDER_SYSTEM_PROMPT, build_itinerary_builder_user_message
from models.schemas import Itinerary
from graph.state import TripState

logger = logging.getLogger(__name__)

def itinerary_builder_node(state: TripState) -> dict:
    normalized_input = state["normalized_input"]

    state_slice = {
        "search_plan": state["search_plan"],
        "flights": state.get("flights", []),
        "trains": state.get("trains", []),
        "buses": state.get("buses", []),
        "cars": state.get("cars", []),
        "hotels": state.get("hotels", []),
        "activities": state.get("activities", []),
        "weather": state.get("weather", []),
        "budget_analysis": state["budget_analysis"],
        "trip_summary": {
            "destination": normalized_input["destination"],
            "start_date": normalized_input["start_date"],
            "end_date": normalized_input["end_date"],
            "num_travelers": normalized_input["num_travelers"],
        },
        "pace": normalized_input["pace"],
        "wants_rental_car": normalized_input["wants_rental_car"],
    }

    # structured_llm = llm.with_structured_output(Itinerary)
    structured_llm = get_structured_llm(Itinerary)

    print("--- Itinerary ---")
    print(len(ITINERARY_BUILDER_SYSTEM_PROMPT))
    print(len(build_itinerary_builder_user_message(state_slice)))

    response = structured_llm.invoke(
        [
            {"role": "system", "content": ITINERARY_BUILDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_itinerary_builder_user_message(state_slice)},
        ],
        max_tokens=AGENT_MAX_TOKENS["itinerary_builder"],
    )

    itinerary = response.model_dump()
    print(f"[Itinerary] itinerary: {itinerary}")

    # Contract check, not a fix: wants_rental_car=False must mean
    # chosen_car is null. If the LLM invents a car anyway, that's a real
    # prompt-adherence failure worth knowing about, not silently discarding.
    if not normalized_input["wants_rental_car"] and itinerary.get("chosen_car") is not None:
        logger.warning(
            "itinerary_builder_node: chosen_car was set despite "
            "wants_rental_car=False. chosen_car=%s",
            itinerary["chosen_car"],
        )

    return {"itinerary": itinerary}