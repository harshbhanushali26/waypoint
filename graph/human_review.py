"""
graph/human_review.py
 
The human_review node. Sole job: pause the graph via interrupt() and handle
the structured resume payload once the user responds.
 
Design decisions this implements (locked before writing):
  - Resume payload shape: {"action": "approve"} or
    {"action": "edit", "message": "..."} - decided by which UI control the
    user used (button vs text box), never inferred from message content.
  - This node is the SOLE writer to state["messages"] anywhere in the graph
    (confirmed against all 5 agent node functions). That's what makes
    Critic's `state["messages"][-1].content` read safe.
  - Stateless per-pass: no round counter, no "is this the first review"
    flag. Every pass just reads current state and pauses again.
  - approved is written explicitly, only here, only on the approve path -
    never set implicitly as a side effect of anything else.
"""

import logging

from langgraph.types import interrupt
from langchain_core.messages import HumanMessage

from core.logging import get_trip_logger

logger = logging.getLogger(__name__)

def human_review_node(state: dict) -> dict:
    """
    Pauses the graph for user review of the current itinerary.
 
    On resume, `response` is whatever was passed as `Command(resume=...)`
    at invocation time - expected shape:
        {"action": "approve"}
        {"action": "edit", "message": "<user's edit request>"}
    """

    trip_id = state.get("trip_id", "-")
    log = get_trip_logger(logger, trip_id)

    log.info("human_review: pausing for user review")

    # Pause the graph and shows up what did it get upto now 
    response = interrupt(
        {
            "itinerary": state.get("itinerary"),
            "budget_analysis": state.get("budget_analysis")
        }
    )

    # Gets value after the resume
    action = response.get("action")
    log.info("human_review: resumed with action=%s", action)

    if action == "approve":
        return {"approved": True}

    if action == "edit":
        message_text = response.get("message", "")
        log.debug("human_review: edit message=%r", message_text)
        return {
            "messages": [HumanMessage(content=message_text)],
        }
    
    # Defensive: an unrecognized action shape is a bug in whatever called
    # resume, not a case to silently swallow. Fail loudly rather than let
    # the graph proceed with an ambiguous state, same "raise, don't guess"
    # instinct applied to Critic's invalid-target handling in Step 6.

    log.error("human_review: unrecognized resume action=%r", action)
    raise ValueError(
        f"human_review received an unrecognized resume action: {action!r}. "
        f"Expected 'approve' or 'edit'."
    )