"""
graph/build_graph.py

StateGraph wiring for Waypoint:
Concierge -> Planner -> [5 Parallel Tool Nodes] -> Budget -> Itinerary Builder -> Human Review -> Finalize / Critic
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
from tools.search_hotels import search_hotels
from tools.search_activities import search_activities
from tools.get_weather import get_weather

from graph.human_review import human_review_node
from graph.finalize import finalize_node

logger = logging.getLogger(__name__)

# Active tool nodes for V1 (cars and buses pruned from graph execution)
ACTIVE_TOOL_NODES = [
    ("search_flights", search_flights),
    ("search_trains", search_trains),
    ("search_hotels", search_hotels),
    ("search_activities", search_activities),
    ("get_weather", get_weather),
]


def route_after_human_review(state: TripState) -> str:
    if state.get("approved"):
        return "finalize"
    return "critic"


def build_graph(checkpointer: AsyncPostgresSaver):
    graph = StateGraph(TripState)

    graph.add_node("concierge", concierge_node)
    graph.add_node("planner", planner_node)

    for name, fn in ACTIVE_TOOL_NODES:
        graph.add_node(name, fn)

    graph.add_node("budget", budget_node)
    graph.add_node("itinerary_builder", itinerary_builder_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("critic", critic_node)
    graph.add_node("finalize", finalize_node)

    # Entry point & fan-out
    graph.set_entry_point("concierge")
    graph.add_edge("concierge", "planner")

    for name, _ in ACTIVE_TOOL_NODES:
        graph.add_edge("planner", name)
        graph.add_edge(name, "budget")

    graph.add_edge("budget", "itinerary_builder")
    graph.add_edge("itinerary_builder", "human_review")

    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {"finalize": "finalize", "critic": "critic"},
    )

    graph.add_edge("finalize", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("Waypoint StateGraph compiled successfully with %d nodes", len(graph.nodes))
    return compiled




async def get_compiled_graph(conn_string: str):
    """
    Convenience factory for standalone scripts and test harnesses:
    Opens AsyncPostgresSaver against the provided connection string,
    runs table setup, and returns a compiled graph ready to invoke.

    Windows note: psycopg's async driver is incompatible with the default
    ProactorEventLoop. Run standalone scripts with:
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    """
    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()
        return build_graph(checkpointer)