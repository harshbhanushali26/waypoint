"""concierge_node — normalizes raw form input into NormalizedInput, enforcing
the 7-day trip cap deterministically before any LLM call, asking at most one
clarifying question via interrupt(), then falling back to best-effort
normalization if still ambiguous."""

import logging
from datetime import date

from langgraph.types import interrupt

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.concierge_prompt import CONCIERGE_SYSTEM_PROMPT, build_concierge_user_message
from prompts.concierge_fallback_prompt import SYSTEM_PROMPT as FALLBACK_SYSTEM_PROMPT, build_concierge_fallback_user_message
from models.schemas import NormalizedInput, TripContext
from graph.state import TripState

logger = logging.getLogger(__name__)


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
    """Normalizes trip input, asking one clarifying question via interrupt()
    if needed, else falling back to best-effort normalization."""

    attempts = state.get("clarification_attempts", 0)
    raw_form_input = _collect_raw_form_input(state)

    log = get_trip_logger(logger, state["trip_id"])

    # ---- Trip-length hard cap (deterministic, no LLM) ----
    start_date_str = raw_form_input["start_date"]
    end_date_str = raw_form_input["end_date"]

    while (date.fromisoformat(end_date_str) - date.fromisoformat(start_date_str)).days > MAX_TRIP_DAYS - 1:
        trip_days = (date.fromisoformat(end_date_str) - date.fromisoformat(start_date_str)).days
        log.info("Concierge: trip length %d days exceeds cap, interrupting", trip_days)

        corrected = interrupt(TRIP_LENGTH_MESSAGE)

        # Expect only the two ISO date strings back, not a full form resubmission
        start_date_str = corrected["start_date"]
        end_date_str = corrected["end_date"]

    raw_form_input["start_date"] = start_date_str
    raw_form_input["end_date"] = end_date_str

    user_message = build_concierge_user_message(raw_form_input)

    # ---- Round 1 ----
    if attempts == 0:
        log.debug(
            "Concierge round 1 input: system_prompt_len=%d user_msg_len=%d",
            len(CONCIERGE_SYSTEM_PROMPT), len(user_message),
        )

        response: NormalizedInput = get_structured_llm(NormalizedInput).invoke(
            [
                {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=AGENT_MAX_TOKENS["concierge"],
        )

        log.debug("Concierge round 1 needs_clarification: %s", response.needs_clarification)

        if not response.needs_clarification:
            trip_context = TripContext(**response.model_dump())
            log.info("Concierge normalized_input: %s", trip_context.model_dump())
            return {
                "normalized_input": trip_context.model_dump(),
                "start_date": start_date_str,
                "end_date": end_date_str,
                "status": "planning",
            }

        log.info("Concierge clarification_question: %s", response.clarification_question)

        answer = interrupt(response.clarification_question)

        # ---- Round 2 (resumed with answer) ----
        round2_user_message = (
            user_message
            + f"\n\nClarification question: {response.clarification_question}"
            + f"\nUser's answer: {answer}"
        )

        log.debug(
            "Concierge round 2 input: system_prompt_len=%d user_msg_len=%d",
            len(CONCIERGE_SYSTEM_PROMPT), len(round2_user_message),
        )

        response2: NormalizedInput = get_structured_llm(NormalizedInput).invoke(
            [
                {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
                {"role": "user", "content": round2_user_message},
            ],
            max_tokens=AGENT_MAX_TOKENS["concierge"],
        )

        log.debug("Concierge round 2 needs_clarification: %s", response2.needs_clarification)

        if not response2.needs_clarification:
            trip_context = TripContext(**response2.model_dump())
            log.info("Concierge round 2 normalized_input: %s", trip_context.model_dump())
            return {
                "normalized_input": trip_context.model_dump(),
                "start_date": start_date_str,
                "end_date": end_date_str,
                "clarification_attempts": 1,
                "status": "planning",
            }

        # ---- Round 2 still ambiguous -> fallback, no second interrupt ----
        log.debug("Concierge fallback input: system_prompt_len=%d", len(FALLBACK_SYSTEM_PROMPT))

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
                },
            ],
            max_tokens=AGENT_MAX_TOKENS["concierge"],
        )

        log.info("Concierge fallback normalized_input: %s", fallback_response.model_dump())

        return {
            "normalized_input": fallback_response.model_dump(),
            "start_date": start_date_str,
            "end_date": end_date_str,
            "clarification_attempts": 2,
            "status": "planning",
        }