from datetime import date

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from langgraph.types import interrupt

from prompts.concierge_prompt import CONCIERGE_SYSTEM_PROMPT, build_concierge_user_message
from prompts.concierge_fallback_prompt import SYSTEM_PROMPT as FALLBACK_SYSTEM_PROMPT, build_concierge_fallback_user_message

from models.schemas import NormalizedInput, TripContext
from graph.state import TripState


MAX_TRIP_DAYS = 7
TRIP_LENGTH_MESSAGE = (
    "Waypoint currently plans trips up to 7 days. "
    "Could you narrow your dates and try again?"
)


def _collect_raw_form_input(state: TripState) -> dict:
    """Pull the original form fields straight from top-level state."""

    return {
        "destination": state["destination"],
        "origin_city": state["origin_city"],
        "start_date": state["start_date"],
        "end_date": state["end_date"],
        "budget": state["budget"],
        "currency": state["currency"],
        "num_travelers": state["num_travelers"],
        "interests": state["interests"],
        "transport_pref": state["transport_pref"],
        "wants_rental_car": state["wants_rental_car"],
        "pace": state["pace"],
    }


def concierge_node(state: TripState) -> dict:

    attempts = state.get("clarification_attempts", 0)
    raw_form_input = _collect_raw_form_input(state)

    # ---- Trip-length hard cap (deterministic, no LLM) ----
    start_date_str = raw_form_input["start_date"]
    end_date_str = raw_form_input["end_date"]

    while (date.fromisoformat(end_date_str) - date.fromisoformat(start_date_str)).days > MAX_TRIP_DAYS - 1:
        print(
            f"[Concierge] trip length "
            f"{(date.fromisoformat(end_date_str) - date.fromisoformat(start_date_str)).days} "
            f"days exceeds cap, interrupting"
        )

        corrected = interrupt(TRIP_LENGTH_MESSAGE)

        # Expect only the two ISO date strings back, not a full form resubmission
        start_date_str = corrected["start_date"]
        end_date_str = corrected["end_date"]

    raw_form_input["start_date"] = start_date_str
    raw_form_input["end_date"] = end_date_str

    # ---- Round 1 ----
    if attempts == 0:
        print("--- Concierge ---")
        print(len(CONCIERGE_SYSTEM_PROMPT))
        print(len(build_concierge_user_message(raw_form_input)))

        response: NormalizedInput = get_structured_llm(NormalizedInput).invoke(
                    [
                        {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
                        {"role": "user", "content": build_concierge_user_message(raw_form_input)}
                    ],
                    max_tokens=AGENT_MAX_TOKENS["concierge"]
                )

        print(f"[Concierge] needs_clarification: {response.needs_clarification}")

        if not response.needs_clarification:
            trip_context = TripContext(**response.model_dump())
            print(f"[Concierge] normalized_input: {trip_context.model_dump()}")
            return {
                "normalized_input": trip_context.model_dump(),
                "start_date": start_date_str,
                "end_date": end_date_str,
                "status": "planning",
            }

        print(f"[Concierge] clarification_question: {response.clarification_question}")

        answer = interrupt(response.clarification_question)

        # ---- Round 2 (resumed with answer) ----
        print("--- Concierge (round 2) ---")
        print(len(CONCIERGE_SYSTEM_PROMPT))
        print(len(build_concierge_user_message(raw_form_input)))

        response2: NormalizedInput = get_structured_llm(NormalizedInput).invoke(
                    [
                        {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_concierge_user_message(raw_form_input)
                            + f"\n\nClarification question: {response.clarification_question}"
                            + f"\nUser's answer: {answer}",
                        },
                    ],
                    max_tokens=AGENT_MAX_TOKENS["concierge"],
                )

        print(f"[Concierge round 2] needs_clarification: {response2.needs_clarification}")

        if not response2.needs_clarification:
            trip_context = TripContext(**response2.model_dump())
            print(f"[Concierge round 2] normalized_input: {trip_context.model_dump()}")
            return {
                "normalized_input": trip_context.model_dump(),
                "start_date": start_date_str,
                "end_date": end_date_str,
                "clarification_attempts": 1,
                "status": "planning"
            }

        # ---- Round 2 still ambiguous -> fallback, no second interrupt ----
        print("--- Concierge (fallback) ---")
        print(len(FALLBACK_SYSTEM_PROMPT))

        fallback_response: TripContext = get_structured_llm(TripContext).invoke(
                    [
                        {"role": "system", "content": FALLBACK_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_concierge_fallback_user_message(
                                raw_form_input,
                                clarification_qa={
                                    "question": response.clarification_question,
                                    "answer": answer,
                                },
                            ),
                        }
                    ],
                    max_tokens=AGENT_MAX_TOKENS["concierge"],
                )

        print(f"[Concierge fallback] normalized_input: {fallback_response.model_dump()}")

        return {
            "normalized_input": fallback_response.model_dump(),
            "start_date": start_date_str,
            "end_date": end_date_str,
            "clarification_attempts": 2,
            "status": "planning"
        }