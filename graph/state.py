"""
graph/state.py

TripState schema definition for LangGraph.
"""

from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


class TripState(TypedDict):
    # Form Inputs
    trip_id: str
    destination: str
    origin_city: str
    start_date: str
    end_date: str
    budget: float
    currency: str
    num_travelers: int
    interests: list[str]
    transport_pref: str  # "flights", "trains", "any"
    pace: str            # "relaxed", "moderate", "packed"

    # Agent & Tool outputs
    normalized_input: dict
    search_plan: dict
    flights: list[dict]
    trains: list[dict]
    hotels: list[dict]
    activities: list[dict]
    weather: list[dict]
    budget_analysis: dict
    itinerary: dict
    critic_analysis: Optional[dict]

    # Review & Lifecycle
    approved: bool
    messages: Annotated[list, add_messages]
    status: str
    clarification_attempts: int