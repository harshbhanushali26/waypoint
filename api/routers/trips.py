"""
api/routers/trips.py
"""

import logging
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select

from core.logging import get_trip_logger
from db.models import Trip
from db.session import async_session_factory

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_TRIP_DAYS = 7
REVIEW_NODE = "human_review"   # must match the node name in graph/build_graph.py

# In-process bookkeeping. Fine for one uvicorn worker; with several workers
# these would need to live in the database instead.
_running: set[str] = set()   # trips with a graph run in flight
_failed: set[str] = set()    # trips whose last run raised


# ── Models ───────────────────────────────────────────────────────────────────

class TripCreateRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=100)
    origin_city: str = Field(min_length=1, max_length=100)
    start_date: str
    end_date: str
    budget: float = Field(gt=0)
    currency: str = "INR"
    num_travelers: int = Field(default=1, ge=1, le=20)
    interests: list[str] = Field(default_factory=list, max_length=12)
    transport_pref: Literal["any", "flights", "trains"] = "any"
    pace: Literal["relaxed", "moderate", "packed"] = "moderate"

    @field_validator("destination", "origin_city")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field can't be blank.")
        return v

    @field_validator("interests")
    @classmethod
    def _clean_interests(cls, v: list[str]) -> list[str]:
        return [i.strip()[:40] for i in v if i and i.strip()]

    @model_validator(mode="after")
    def _check_dates(self):
        try:
            start = date.fromisoformat(self.start_date)
            end = date.fromisoformat(self.end_date)
        except ValueError:
            raise ValueError("Dates must be in YYYY-MM-DD format.")
        if start < date.today():
            raise ValueError("Start date can't be in the past.")
        if end <= start:
            raise ValueError("End date must be after the start date.")
        if (end - start).days + 1 > MAX_TRIP_DAYS:
            raise ValueError(f"Trips can be at most {MAX_TRIP_DAYS} days.")
        return self


class TripCreateResponse(BaseModel):
    trip_id: str


class TripStatusResponse(BaseModel):
    trip_id: str
    status: str


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit"]
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _edit_needs_message(self):
        if self.action == "edit":
            self.message = (self.message or "").strip()
            if not self.message:
                raise ValueError("An edit request needs a message.")
        return self


# ── Helpers ──────────────────────────────────────────────────────────────────

def _config(trip_id: str) -> dict:
    return {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}


def _claim(trip_id: str) -> None:
    """Mark a trip as running. Rejects a second run on the same thread."""
    if trip_id in _running:
        raise HTTPException(status_code=409, detail="This trip is already being processed.")
    _running.add(trip_id)
    _failed.discard(trip_id)


async def _run_graph(graph, trip_id: str, graph_input) -> None:
    """
    Single entry point for every background run (start, review, resume).
    The error is logged server-side only: provider exceptions can contain
    request URLs with API keys, so nothing from them goes to the client.
    """
    log = get_trip_logger(logger, trip_id)
    try:
        await graph.ainvoke(graph_input, config=_config(trip_id))
    except Exception:
        log.exception("Graph run failed")
        _failed.add(trip_id)
    finally:
        _running.discard(trip_id)


def _paused_for_review(snapshot) -> bool:
    return (
        snapshot.values.get("status") == "awaiting_review"
        and REVIEW_NODE in (snapshot.next or ())
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("", response_model=TripCreateResponse)
async def create_trip(payload: TripCreateRequest, background_tasks: BackgroundTasks, request: Request):
    trip_id = str(uuid4())

    async with async_session_factory() as session:
        trip = Trip(
            trip_id=trip_id,
            destination=payload.destination,
            origin_city=payload.origin_city,
            start_date=payload.start_date,
            end_date=payload.end_date,
            num_travelers=payload.num_travelers,
            budget=payload.budget,
            currency=payload.currency,
            status="created",
        )
        session.add(trip)
        await session.commit()

    initial_state = {
        "trip_id": trip_id,
        "destination": payload.destination,
        "origin_city": payload.origin_city,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "budget": payload.budget,
        "currency": payload.currency,
        "num_travelers": payload.num_travelers,
        "interests": payload.interests,
        "transport_pref": payload.transport_pref,
        "pace": payload.pace,
        "status": "created",
        "messages": [],
        "approved": False,
        "clarification_attempts": 0,
    }

    _claim(trip_id)
    background_tasks.add_task(_run_graph, request.app.state.graph, trip_id, initial_state)
    return TripCreateResponse(trip_id=trip_id)


@router.get("/{trip_id}/status", response_model=TripStatusResponse)
async def get_trip_status(trip_id: str, request: Request):
    if trip_id in _failed:
        return TripStatusResponse(trip_id=trip_id, status="failed")

    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(trip_id))

    # Checkpoint not committed yet: fall back to the SQL row before giving up.
    if not snapshot.values:
        async with async_session_factory() as session:
            result = await session.execute(select(Trip).where(Trip.trip_id == trip_id))
            trip = result.scalar_one_or_none()
            if trip:
                return TripStatusResponse(trip_id=trip_id, status=trip.status)
        raise HTTPException(status_code=404, detail="Trip not found")

    status = snapshot.values.get("status", "planning")

    # The saved status still reads "awaiting_review" for a moment after an
    # edit or approval is accepted. Report the live state instead, so the
    # frontend can't mistake the stale value for "done".
    if trip_id in _running and status == "awaiting_review":
        status = "revising"

    return TripStatusResponse(trip_id=trip_id, status=status)


@router.get("/{trip_id}/itinerary")
async def get_itinerary(trip_id: str, request: Request):
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(trip_id))
    if not snapshot.values or not snapshot.values.get("itinerary"):
        raise HTTPException(status_code=404, detail="Itinerary not ready")

    return {
        "trip_id": trip_id,
        "status": snapshot.values.get("status"),
        "itinerary": snapshot.values.get("itinerary"),
        "budget_analysis": snapshot.values.get("budget_analysis"),
    }


@router.post("/{trip_id}/review")
async def submit_review(trip_id: str, payload: ReviewRequest, background_tasks: BackgroundTasks, request: Request):
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(trip_id))

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not _paused_for_review(snapshot):
        raise HTTPException(status_code=409, detail="This trip isn't waiting for review.")

    resume_payload = (
        {"action": "approve"} if payload.action == "approve"
        else {"action": "edit", "message": payload.message}
    )

    _claim(trip_id)
    background_tasks.add_task(_run_graph, graph, trip_id, Command(resume=resume_payload))
    return {"trip_id": trip_id, "accepted": True}


@router.post("/{trip_id}/resume")
async def resume_trip(trip_id: str, background_tasks: BackgroundTasks, request: Request):
    """
    Continues a failed or interrupted run from its last checkpoint.
    Refuses when the trip is already running, finished, or paused for review.
    """
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(trip_id))

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="No checkpoint found for this trip.")

    status = snapshot.values.get("status")
    next_nodes = list(snapshot.next or ())

    if trip_id in _running:
        return {"trip_id": trip_id, "resumed": False, "current_status": status,
                "message": "This trip is already being processed."}

    if not next_nodes or _paused_for_review(snapshot):
        return {"trip_id": trip_id, "resumed": False, "current_status": status,
                "message": f"Nothing to resume. The trip is {status}."}

    _claim(trip_id)
    background_tasks.add_task(_run_graph, graph, trip_id, None)   # None = continue from checkpoint
    return {"trip_id": trip_id, "resumed": True, "resuming_from_node": next_nodes,
            "message": f"Resuming from {next_nodes}."}