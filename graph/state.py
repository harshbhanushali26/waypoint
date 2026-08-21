"""
TripState — shared state schema flowing through the LangGraph graph.
TypedDict convention (LangGraph standard) — Pydantic reserved for API boundary
schemas in models/schemas.py. Routing decisions live in graph control flow
(Command(goto=...)), not in state.
"""

from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages


class TripState(TypedDict):
    # ── Input (from form) ───────────────────────────────────────────────────
    trip_id: str
    destination: str
    origin_city: str
    start_date: str
    end_date: str
    budget: float
    currency: str
    num_travelers: int
    interests: list[str]
    transport_pref: str        # "flights", "trains", "buses", "cars", "any"
    wants_rental_car: bool     # Independent add-on for local mobility; effectively redundant if transport_pref is "cars"
    pace: str                  # "relaxed", "moderate", "packed"

    # ── Populated by agents/tools ───────────────────────────────────────────
    normalized_input: dict              # Concierge Agent output
    search_plan: dict                   # Planner Agent output
    flights: list[dict]                 # search_flights results
    trains: list[dict]                  # search_trains results
    buses: list[dict]                   # search_buses output
    cars: list[dict]                    # search_cars output
    hotels: list[dict]                  # search_hotels results
    activities: list[dict]              # search_activities results
    weather: list[dict]                 # get_weather results
    budget_analysis: dict               # Budget Agent output
    itinerary: dict                     # Itinerary Builder output
    critic_analysis: dict               # Critic Agent output

    # ── Review loop ─────────────────────────────────────────────────────────
    approved: bool                      # Drives the human_review conditional branch
    messages: Annotated[list, add_messages]  # Single source of truth for review-loop chat

    # ── Execution status (for frontend progress UI) ─────────────────────────
    status: str                         # current node name, drives frontend progress UI