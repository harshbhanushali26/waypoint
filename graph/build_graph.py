"""
graph/build_graph.py
 
Waypoint's StateGraph wiring. Structure per waypoint-architecture.md Section 4:
 
    Concierge -> Planner -> [7 parallel tool nodes] -> Budget -> Itinerary Builder
        -> human_review (interrupt)
            -- approved --> Finalize -> END
            -- edit requested --> Critic --(Command(goto=...))--> target node(s)
 
Design decisions locked before writing this file (see project memory):
  1. human_review resume payload is structured: {"action": "approve"} or
     {"action": "edit", "message": "..."} - never inferred from message text.
  2. human_review is a dedicated node. It is the SOLE writer to state["messages"].
     On the edit path it wraps the user's text in a HumanMessage so Critic's
     `state["messages"][-1].content` read is safe by construction.
  3. human_review is stateless per-pass - no round counter. It always sits
     immediately after Itinerary Builder, on every pass, by ordinary edge
     traversal (Critic's re-run paths all flow forward through Itinerary
     Builder again before reaching human_review).
  4. Finalize is a real graph node (not punted to the FastAPI layer) so the
     graph stays testable standalone, per the Step 7 build plan.
  5. Checkpointer is AsyncPostgresSaver, compiled in, async invocation
     throughout. Every invoke/resume call MUST pass
     config={"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}.
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


from graph.state import TripState


from agents.concierge import concierge_node
from agents.planner import planner_node
from agents.budget import budget_node
from agents.itinerary_builder import itinerary_builder_node
from agents.critic import critic_node


from tools.search_flights import search_flights
from tools.search_trains import search_trains
from tools.search_buses import search_buses
from tools.search_cars import search_cars
from tools.search_hotels import search_hotels
from tools.search_activities import search_activities
from tools.get_weather import get_weather


from graph.human_review import human_review_node
from graph.finalize import finalize_node

logger = logging.getLogger(__name__)

TOOL_NODE_NAMES = [
    "search_flights",
    "search_trains",
    "search_buses",
    "search_cars",
    "search_hotels",
    "search_activities",
    "get_weather",
]


def route_after_human_review(state: TripState) -> str:
    """
    Conditional edge out of human_review.
 
    approved is written ONLY by human_review's own approve-path handler
    (design decision #2/#3) - nothing else in the graph touches it, so
    this read is safe.
    """

    if state.get("approved"):
        return "finalize"
    return "critic"


def build_graph(checkpointer: AsyncPostgresSaver):
    graph = StateGraph(TripState)

    graph.add_node("concierge", concierge_node)
    graph.add_node("planner", planner_node)

    for name, fn in zip(
        TOOL_NODE_NAMES,
        [
            search_flights,
            search_trains,
            search_buses,
            search_cars,
            search_hotels,
            search_activities,
            get_weather,
        ],
    ):

        graph.add_node(name, fn)


    graph.add_node("budget", budget_node)
    graph.add_node("itinerary_builder", itinerary_builder_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("critic", critic_node)
    graph.add_node("finalize", finalize_node)


    # --- entry point ---
    graph.set_entry_point("concierge")

    # --- sequential edges ---
    graph.add_edge("concierge", "planner")

    for name in TOOL_NODE_NAMES:
        graph.add_edge("planner", name)
        graph.add_edge(name, "budget")

    graph.add_edge("budget", "itinerary_builder")
    graph.add_edge("itinerary_builder", "human_review")

    # --- conditional edge out of human_review ---
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "finalize": "finalize",
            "critic": "critic",
        },
    )

    # --- Critic is NOT given a static outgoing edge. ---
    # Its node function returns Command(update=..., goto=target), so the
    # node's return value IS the edge - LangGraph routes dynamically to
    # whatever target(s) the Critic decided on (a tool node, itinerary_builder
    # directly, or planner for a full replan). Declaring a static edge here
    # would be wrong and is intentionally omitted.

    graph.add_edge("finalize", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("Waypoint graph compiled: %d nodes", len(graph.nodes))
    return compiled


async def get_compiled_graph(conn_string: str):
    """
    Convenience factory: opens the AsyncPostgresSaver against the given
    Postgres connection string and returns a compiled graph ready to invoke.
 
    Windows note: psycopg's async driver is incompatible with the default
    ProactorEventLoop. Run your entrypoint with:
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    (set_event_loop_policy is deprecated as of Python 3.12).
    """

    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()
        return build_graph(checkpointer)


# --- example invocation shape (for reference only, not run on import) ---
#
# config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}
#
# initial invoke:
#   result = await compiled_graph.ainvoke(initial_state, config=config)
#
# resume after interrupt (approve):
#   result = await compiled_graph.ainvoke(
#       Command(resume={"action": "approve"}), config=config
#   )
#
# resume after interrupt (edit):
#   result = await compiled_graph.ainvoke(
#       Command(resume={"action": "edit", "message": user_text}), config=config
#   )