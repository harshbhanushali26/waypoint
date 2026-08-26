from typing import Literal, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Concierge Agent
# ─────────────────────────────────────────────────────────────

class NormalizedInput(BaseModel):
    """
    Concierge Agent's structured LLM output. Single schema, always returned
    in this shape — no union, to avoid relying on Groq structured-output
    discriminated unions.

    needs_clarification / clarification_question carry the "ask the user
    something" case. When needs_clarification is True, the node function
    calls interrupt(clarification_question) and DISCARDS every other field
    on this object — none of it gets written to state.

    Only when needs_clarification is False are the real trip fields written
    to state.normalized_input. That state field stays exactly as clean as
    originally designed; this extra bookkeeping lives only in this one
    throwaway LLM response, never propagates further.
    """

    needs_clarification: bool = Field(
        description="True if the trip request can't be safely normalized — "
        "e.g. budget is clearly unrealistic for the destination/duration/"
        "traveler count, or the destination can't be resolved at all. "
        "False otherwise."
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="Required if needs_clarification is True: a single, "
        "specific question the user can answer in one short reply. Leave "
        "null/empty if needs_clarification is False."
    )

    destination: Optional[str] = Field(
        default=None,
        description="Canonicalized destination, e.g. 'goa' -> 'Goa, India'. "
        "Null if needs_clarification is True."
    )
    origin_city: Optional[str] = Field(
        default=None,
        description="Canonicalized origin city, same treatment as destination."
    )
    start_date: Optional[str] = Field(default=None, description="ISO date.")
    end_date: Optional[str] = Field(default=None, description="ISO date.")
    num_travelers: Optional[int] = None
    budget: Optional[float] = None
    currency: Optional[str] = Field(
        default=None, description="ISO currency code, e.g. 'INR', 'USD'."
    )
    interests: Optional[list[str]] = Field(
        default=None,
        description="Passed through as-is from the form's fixed multi-select "
        "options — do not invent or reinterpret these.",
    )
    transport_pref: Optional[Literal["flights", "trains", "buses", "cars", "any"]] = None
    wants_rental_car: Optional[bool] = None
    pace: Optional[Literal["relaxed", "moderate", "packed"]] = None



class TripContext(BaseModel):
    """
    The clean, fully-validated version of trip input. This — not
    NormalizedInput — is what actually gets written to
    state.normalized_input. Every field is required: no other agent should
    ever have to handle a missing/null value here.

    Constructed manually inside the Concierge node function, only after
    confirming needs_clarification was False on the LLM's NormalizedInput
    response. Never handed to the LLM directly — Pydantic validation on
    construction is the safety net that catches a missing field immediately,
    right here, instead of surfacing as a confusing crash in a downstream
    agent.
    """

    destination: str = Field(
        description="Canonicalized destination, e.g. 'goa' -> 'Goa, India'."
    )
    origin_city: str = Field(
        description="Canonicalized origin city, same treatment as destination."
    )
    start_date: str = Field(description="ISO date, e.g. '2026-09-10'.")
    end_date: str = Field(description="ISO date, e.g. '2026-09-14'.")
    num_travelers: int
    budget: float
    currency: str = Field(description="ISO currency code, e.g. 'INR', 'USD'.")
    interests: list[str] = Field(
        description="Passed through as-is from the form's fixed multi-select "
        "options — do not invent or reinterpret these."
    )
    transport_pref: Literal["flights", "trains", "buses", "cars", "any"]
    wants_rental_car: bool
    pace: Literal["relaxed", "moderate", "packed"]



# ─────────────────────────────────────────────────────────────
# Planner Agent
# ─────────────────────────────────────────────────────────────

TransportMode = Literal["flights", "trains", "buses", "cars"]


class SearchPlan(BaseModel):
    """
    Planner Agent's output. Narrows transport_pref + budget_tier into a
    concrete search strategy before the tool nodes fan out. Written to
    state.search_plan.
    """

    transport_modes: list[TransportMode] = Field(
        description="Which transport tool nodes should actually search. "
        "Narrowed from transport_pref — e.g. 'any' might resolve to "
        "['flights', 'trains']."
    )
    transport_priority: list[TransportMode] = Field(
        description="Same modes as transport_modes, reordered by preference. "
        "Every entry here MUST also appear in transport_modes — do not "
        "include a mode that wasn't selected for search. Used only as a "
        "hint for Itinerary Builder, not for controlling which tool nodes run."
    )
    budget_tier: Literal["tight", "balanced", "luxury"] = Field(
        description="Trip-wide budget tier. Drives both transport_modes "
        "narrowing and hotel tier filtering downstream."
    )
    reasoning: str = Field(
        description="Short explanation of the choices above, for debugging "
        "only — not read by any downstream node."
    )


# ─────────────────────────────────────────────────────────────
# Budget Agent
# ─────────────────────────────────────────────────────────────

class BudgetAnalysis(BaseModel):
    """
    Budget Agent's output. A conservative floor check against the cheapest
    option per category — not the final chosen cost (that's Itinerary
    Builder's job). Written to state.budget_analysis.
    """

    estimated_total: float = Field(
        description="Sum of the CHEAPEST option per category. A feasibility "
        "floor, not a final price."
    )
    cost_breakdown: dict[str, float] = Field(
        description="Per-category subtotal, e.g. "
        "{'flights': 12000, 'hotels': 8000, 'activities': 2000}."
    )
    budget: float = Field(description="Pass-through from normalized_input.budget.")
    over_budget: bool
    overage_amount: float = Field(
        description="0 if not over budget."
    )
    suggestions: list[str] = Field(
        description="General, category-level cut suggestions only, e.g. "
        "'hotel tier could be lowered'. Do NOT name a specific alternative "
        "or swap — that's Itinerary Builder's job."
    )


# ─────────────────────────────────────────────────────────────
# Itinerary Builder Agent
# ─────────────────────────────────────────────────────────────

class Itinerary(BaseModel):
    """
    Itinerary Builder Agent's output. The final, self-contained artifact —
    carries FULL chosen objects (not IDs referencing back into state), since
    this gets shown on the review/final screens and saved to the
    itineraries DB table. Written to state.itinerary.

    NOTE: trip_summary, chosen_hotel, and days are left as plain dict/list[dict]
    for now rather than fully nested models — flag for revisit if loose
    structured-output shape becomes a reliability problem in practice.
    """

    trip_summary: dict = Field(
        description="{'destination', 'start_date', 'end_date', 'num_travelers'}."
    )
    chosen_transport: list[dict] = Field(
        description="List, not a single object — handles round trips and "
        "mixed-mode legs (e.g. fly out, train back) without needing a "
        "schema change. Each entry: {'leg': 'outbound'|'return', "
        "'mode': 'flight'|'train'|'bus', ...full fields from the "
        "matching tool node object}. A rental car is NEVER represented "
        "here — see chosen_car."
    )
    chosen_car: dict | None = Field(
        default=None,
        description="Full rental car object if wants_rental_car was true, "
        "else null. Represents local mobility availability for the trip "
        "duration, not a point-to-point transport leg — never appears in "
        "chosen_transport and never appears as a scheduled event in days."
    )
    chosen_hotel: dict = Field(
        description="Full hotel object as returned by search_hotels."
    )
    days: list[dict] = Field(
        description="Each entry: {'date': ISO str, 'events': [...]}. date is "
        "explicit per entry, never inferred from list position — a Critic "
        "re-run can reorder/replace a single day. Each event: {'type': "
        "'transport'|'hotel_checkin'|'hotel_checkout'|'activity', 'time', "
        "'title', 'details'}. No cost field on individual events."
    )
    total_cost: float = Field(
        description="Actual cost of what was chosen — distinct from Budget "
        "Agent's earlier estimated_total."
    )


# ─────────────────────────────────────────────────────────────
# Critic / Revision Agent
# ─────────────────────────────────────────────────────────────

class CriticAnalysis(BaseModel):
    """
    Critic Agent's output. Logging-only — does NOT itself drive routing.
    The node function separately returns Command(update={"critic_analysis":
    this.model_dump()}, goto=target) using the `target` field below to
    decide where to route.
    """

    user_request: str = Field(description="Raw feedback message from the user.")
    interpretation: str = Field(description="Critic's read on what the user wants.")
    target: list[str] = Field(
        description="Node(s) to re-run. A list because one request can need "
        "multiple tool nodes at once (e.g. 'change destination slightly' "
        "needing both search_hotels and search_activities). Valid values: "
        "'planner' (full replan), 'itinerary_builder' (pure rearrangement, "
        "no new data), or any tool node name (new data needed, flows "
        "forward through Budget Agent to Itinerary Builder)."
    )
    reasoning: str = Field(description="Why this target was chosen.")