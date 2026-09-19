"""
api/routers/trips.py
"""

from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from sqlalchemy import select
from db.session import async_session_factory
from db.models import Trip
from langgraph.types import Command
from pydantic import BaseModel
from typing import Literal

router = APIRouter()

class TripCreateRequest(BaseModel):
    destination: str
    origin_city: str
    start_date: str
    end_date: str
    budget: float
    currency: str = "INR"
    num_travelers: int = 1
    interests: list[str] = []
    transport_pref: str = "any"
    pace: str = "moderate"

class TripCreateResponse(BaseModel):
    trip_id: str

class TripStatusResponse(BaseModel):
    trip_id: str
    status: str

class ReviewRequest(BaseModel):
    action: Literal["approve", "edit"]
    message: str | None = None


def _config(trip_id: str) -> dict:
    return {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}


async def _run_graph(graph, trip_id: str, state: dict):
    await graph.ainvoke(state, config=_config(trip_id))


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

    background_tasks.add_task(_run_graph, request.app.state.graph, trip_id, initial_state)
    return TripCreateResponse(trip_id=trip_id)


@router.get("/{trip_id}/status", response_model=TripStatusResponse)
async def get_trip_status(trip_id: str, request: Request):
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(trip_id))

    # FIX: If graph checkpoint is not yet committed, check SQL DB before returning 404
    if not snapshot.values:
        async with async_session_factory() as session:
            result = await session.execute(select(Trip).where(Trip.trip_id == trip_id))
            trip = result.scalar_one_or_none()
            if trip:
                return TripStatusResponse(trip_id=trip_id, status=trip.status)
        raise HTTPException(status_code=404, detail="Trip not found")

    return TripStatusResponse(trip_id=trip_id, status=snapshot.values.get("status", "planning"))


@router.get("/{trip_id}/itinerary")
async def get_itinerary(trip_id: str, request: Request):
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(trip_id))
    if not snapshot.values or not snapshot.values.get("itinerary"):
        raise HTTPException(status_code=404, detail="Itinerary not ready")

    itinerary = snapshot.values.get("itinerary")
    # Hotel thumbnail fallback image
    if itinerary.get("chosen_hotel") and not itinerary["chosen_hotel"].get("thumbnail"):
        itinerary["chosen_hotel"]["thumbnail"] = "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&auto=format&fit=crop&q=60"

    return {
        "trip_id": trip_id,
        "status": snapshot.values.get("status"),
        "itinerary": itinerary,
        "budget_analysis": snapshot.values.get("budget_analysis"),
    }


@router.post("/{trip_id}/review")
async def submit_review(trip_id: str, payload: ReviewRequest, background_tasks: BackgroundTasks, request: Request):
    graph = request.app.state.graph
    resume_payload = {"action": "approve"} if payload.action == "approve" else {"action": "edit", "message": payload.message}

    async def _resume():
        await graph.ainvoke(Command(resume=resume_payload), config=_config(trip_id))

    background_tasks.add_task(_resume)
    return {"trip_id": trip_id, "accepted": True}