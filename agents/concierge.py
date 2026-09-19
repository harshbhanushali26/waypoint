"""
agents/concierge.py

Normalizes user form inputs into clean NormalizedInput data in a single fast pass.
Runs on openai/gpt-oss-20b for high speed and separate TPM bucket usage.
"""

import logging
from datetime import date

from core.llm import AGENT_MAX_TOKENS, get_structured_llm
from core.logging import get_trip_logger
from prompts.concierge_prompt import CONCIERGE_SYSTEM_PROMPT, build_concierge_user_message
from models.schemas import NormalizedInput
from graph.state import TripState

logger = logging.getLogger(__name__)

MAX_TRIP_DAYS = 7


def concierge_node(state: TripState) -> dict:
    """
    Normalizes raw form input in a single, fast LLM pass without interrupt rounds.
    Enforces the 7-day cap deterministically before the LLM call.
    """
    trip_id = state.get("trip_id", "-")
    log = get_trip_logger(logger, trip_id)
    log.info("Concierge: starting input normalization")

    start_date_str = state["start_date"]
    end_date_str = state["end_date"]

    # Deterministic trip-length cap safeguard (max 7 days)
    try:
        d_start = date.fromisoformat(start_date_str)
        d_end = date.fromisoformat(end_date_str)
        days = (d_end - d_start).days + 1

        if days > MAX_TRIP_DAYS:
            log.warning("Concierge: trip length %d days exceeds 7-day cap. Capping to 7 days.", days)
            d_end = date.fromordinal(d_start.toordinal() + MAX_TRIP_DAYS - 1)
            end_date_str = d_end.isoformat()
    except Exception as e:
        log.warning("Concierge: date parsing issue (%s), proceeding with original dates", e)

    raw_form_input = {
        "destination": state["destination"],
        "origin_city": state["origin_city"],
        "start_date": start_date_str,
        "end_date": end_date_str,
        "budget": state["budget"],
        "currency": state.get("currency", "INR"),
        "num_travelers": state.get("num_travelers", 1),
        "interests": state.get("interests", []),
        "transport_pref": state.get("transport_pref", "any"),
        "pace": state.get("pace", "moderate"),
    }

    user_message = build_concierge_user_message(raw_form_input)

    structured_llm = get_structured_llm(
        NormalizedInput,
        model_tier="fast",
        include_raw=True,
        max_tokens=AGENT_MAX_TOKENS["concierge"],
    )

    log.debug(
        "Concierge input: system_prompt_len=%d user_msg_len=%d",
        len(CONCIERGE_SYSTEM_PROMPT), len(user_message),
    )

    response = structured_llm.invoke([
        {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ])

    log.debug("Concierge token usage: %s", response["raw"].usage_metadata)

    if response["parsed"] is None:
        log.error(
            "Concierge parsing failed. raw_content=%r usage=%s",
            response["raw"].content, response["raw"].usage_metadata,
        )
        raise RuntimeError("Concierge parsing failed - see logged raw content above")

    normalized_data = response["parsed"].model_dump()
    log.info("Concierge normalized destination to '%s'", normalized_data["destination"])

    return {
        "normalized_input": normalized_data,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "status": "planning",
    }