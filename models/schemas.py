"""
models/schemas.py

Pydantic V2 schemas for API boundaries and agent structured outputs.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Concierge ────────────────────────────────────────────────────────────────

class NormalizedInput(BaseModel):
    """
    Concierge's clean structured output. Written directly to state["normalized_input"].
    All fields are required — guarantees downstream agents never encounter null fields.
    """
    destination: str = Field(
        description="Canonicalized destination, e.g. 'Goa, India' or 'Jaipur, India'."
    )
    origin_city: str = Field(
        description="Canonicalized origin city, e.g. 'Mumbai, India' or 'New Delhi, India'."
    )
    start_date: str = Field(description="ISO date string: YYYY-MM-DD.")
    end_date: str = Field(description="ISO date string: YYYY-MM-DD.")
    num_travelers: int = Field(default=1, description="Total number of travelers.")
    budget: float = Field(description="Total budget in currency.")
    currency: str = Field(default="INR", description="ISO currency code.")
    interests: list[str] = Field(
        default_factory=list,
        description="List of traveler interests passed from form options."
    )
    transport_pref: Literal["flights", "trains", "any"] = Field(
        default="any",
        description="User transport preference."
    )
    pace: Literal["relaxed", "moderate", "packed"] = Field(
        default="moderate",
        description="Travel pace."
    )


# ── Planner ──────────────────────────────────────────────────────────────────

TransportMode = Literal["flights", "trains"]


class SearchPlan(BaseModel):
    transport_modes: list[TransportMode] = Field(
        description="Which transport modes to search. Narrowed from transport_pref (e.g. 'any' -> ['flights', 'trains'])."
    )
    transport_priority: list[TransportMode] = Field(
        description="Priority order among chosen transport modes."
    )
    budget_tier: Literal["tight", "balanced", "luxury"]
    reasoning: str


# ── Activity Extraction ──────────────────────────────────────────────────────

class Activity(BaseModel):
    name: str = Field(description="Name of place, attraction, or local activity.")
    category: str = Field(description="Category: sightseeing, food, outdoors, cultural, nightlife.")
    area: Optional[str] = Field(default=None, description="Locality or neighborhood (e.g. 'North Goa', 'Old City').")
    est_duration_hours: Optional[float] = Field(default=2.0)
    est_price_inr: Optional[int] = Field(default=0, description="Per-person estimate in INR if known, else 0.")
    source_url: Optional[str] = Field(default="")


class ActivityCatalog(BaseModel):
    activities: list[Activity] = Field(description="List of 10-18 distinct activities.")


# ── Budget Agent ─────────────────────────────────────────────────────────────

class BudgetAnalysis(BaseModel):
    estimated_total: float
    cost_breakdown: dict[str, float]
    budget: float
    over_budget: bool
    overage_amount: float
    suggestions: list[str]


# ── Itinerary Builder ────────────────────────────────────────────────────────

class Itinerary(BaseModel):
    trip_summary: dict = Field(description="{'destination', 'start_date', 'end_date', 'num_travelers'}")
    chosen_transport: list[dict] = Field(
        description="List of chosen outbound and return legs (flight or train)."
    )
    chosen_hotel: dict = Field(description="Selected hotel object with hotel_id, name, total_price, etc.")
    days: list[dict] = Field(
        description="List of days: [{'date': 'YYYY-MM-DD', 'events': [{'time': '09:00', 'type': 'activity'|'transport'|'hotel_checkin'|'hotel_checkout', 'title': '...', 'details': '...'}]}]"
    )
    total_cost: Optional[float] = Field(
        default=0.0,
        description="Estimated total cost. Safe fallback to 0.0 — Python recomputes exact math downstream.")


# ── Critic / Revision ────────────────────────────────────────────────────────

CriticTarget = Literal[
    "planner",
    "itinerary_builder",
    "search_flights",
    "search_trains",
    "search_hotels",
    "search_activities",
    "get_weather",
]


class CriticAnalysis(BaseModel):
    user_request: str
    interpretation: str
    target: list[CriticTarget] = Field(
        description="Nodes to re-run. Use 'planner' only when budget, dates, travelers or transport mode change."
    )
    updated_budget: float | None = Field(
        default=None,
        description="New total budget in INR, only if the user states a new total (e.g. 'budget to 50000' -> 50000.0)."
    )
    updated_transport_pref: Literal["flights", "trains", "any"] | None = Field(
        default=None,
        description="New transport preference, only if the user asks to change it."
    )
    updated_num_travelers: int | None = Field(
        default=None,
        description="New number of travelers, only if the user states a new number."
    )
    reasoning: str