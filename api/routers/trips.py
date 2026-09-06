from datetime import date
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from pydantic import BaseModel
from typing import Literal

from db.session import async_session_factory
from db.models import Trip

from langgraph.types import Command


router = APIRouter()

class TripCreateRequest(BaseModel):
    destination: str
    origin_city: str
    start_date: date
    end_date: date
    budget: float
    currency: str
    num_travelers: int
    interests: list[str]
    transport_pref: str
    wants_rental_car: bool
    pace: str


class TripCreateResponse(BaseModel):
    trip_id: str


class TripStatusResponse(BaseModel):
    trip_id: str
    status: str


class TripItineraryResponse(BaseModel):
    trip_id: str
    status: str
    itinerary: dict | None
    budget_analysis: dict | None


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit"]
    message: str | None = None

    def model_post_init(self, __context) -> None:
        if self.action == "edit" and not self.message:
            raise ValueError('message is required when action is "edit"')


class ReviewResponse(BaseModel):
    trip_id: str
    accepted: bool


def _index_by_id(objects: list[dict], id_field: str) -> dict[str, dict]:
    """Build a lookup dict keyed by id_field, skipping objects that don't have it."""
    return {obj[id_field]: obj for obj in objects if id_field in obj}


_TRANSPORT_ID_FIELDS = {
    "flight": "flight_id",
    "train": "train_id",
    "bus": "bus_id",
}


def _enrich_itinerary(itinerary: dict, state: dict) -> dict:
    """
    Fills the LLM-trimmed chosen_hotel / chosen_transport / chosen_car
    objects back in with their full untrimmed fields (images, amenities,
    OTA prices, airline logos, etc.) by matching on the id field each
    object already carries. Pure mechanical lookup — no judgment, nothing
    the LLM needs to see. If a match isn't found (e.g. state pruned or the
    id is missing), the original trimmed object is left as-is rather than
    failing the whole response.
    """
    enriched = dict(itinerary)  # shallow copy, don't mutate the checkpoint's dict

    # ── Hotel ──────────────────────────────────────────────────────────
    hotel_lookup = _index_by_id(state.get("hotels", []), "hotel_id")
    chosen_hotel = enriched.get("chosen_hotel")
    if chosen_hotel and chosen_hotel.get("hotel_id") in hotel_lookup:
        enriched["chosen_hotel"] = {
            **hotel_lookup[chosen_hotel["hotel_id"]],
            **chosen_hotel,  # itinerary's own fields take priority if they overlap
        }

    # ── Transport (list of legs, each tagged with a mode) ────────────────
    flight_lookup = _index_by_id(state.get("flights", []), "flight_id")
    train_lookup = _index_by_id(state.get("trains", []), "train_id")
    bus_lookup = _index_by_id(state.get("buses", []), "bus_id")
    mode_lookups = {"flight": flight_lookup, "train": train_lookup, "bus": bus_lookup}

    enriched_transport = []
    for leg in enriched.get("chosen_transport", []):
        mode = leg.get("mode")
        id_field = _TRANSPORT_ID_FIELDS.get(mode)
        lookup = mode_lookups.get(mode, {})
        if id_field and leg.get(id_field) in lookup:
            enriched_transport.append({**lookup[leg[id_field]], **leg})
        else:
            enriched_transport.append(leg)
    enriched["chosen_transport"] = enriched_transport

    # ── Rental car ─────────────────────────────────────────────────────
    car_lookup = _index_by_id(state.get("cars", []), "car_id")
    chosen_car = enriched.get("chosen_car")
    if chosen_car and chosen_car.get("car_id") in car_lookup:
        enriched["chosen_car"] = {**car_lookup[chosen_car["car_id"]], **chosen_car}

    return enriched


async def _run_graph(graph, trip_id: str, initial_state: dict):
    config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}
    await graph.ainvoke(initial_state, config=config)


@router.post("", response_model=TripCreateResponse)
async def create_trip(
    payload: TripCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):

    trip_id = str(uuid4())

    async with async_session_factory() as session:
        trip = Trip(
        trip_id=trip_id,
        destination=payload.destination,
        origin_city=payload.origin_city,
        start_date=payload.start_date.isoformat(),
        end_date=payload.end_date.isoformat(),
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
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "budget": payload.budget,
        "currency": payload.currency,
        "num_travelers": payload.num_travelers,
        "interests": payload.interests,
        "transport_pref": payload.transport_pref,
        "wants_rental_car": payload.wants_rental_car,
        "pace": payload.pace,
        "status": "created",
        "messages": [],
    }

    graph = request.app.state.graph
    background_tasks.add_task(_run_graph, graph, trip_id, initial_state)

    return TripCreateResponse(trip_id=trip_id)


@router.get("/{trip_id}/status", response_model=TripStatusResponse)
async def get_trip_status(trip_id: str, request: Request):
    

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}

    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        # No checkpoint exists for this thread_id at all — either a bad
        # trip_id was passed, or the background graph invocation hasn't
        # written its first checkpoint yet (very early race, unlikely
        # given Concierge alone takes real LLM-call time).
        raise HTTPException(status_code=404, detail="Trip not found")

    return TripStatusResponse(
        trip_id=trip_id,
        status=snapshot.values.get("status", "unknown"),
    )


@router.get("/{trip_id}/itinerary", response_model=TripItineraryResponse)
async def get_trip_itinerary(trip_id: str, request: Request):

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}

    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Trip not found")

    itinerary = snapshot.values.get("itinerary")

    if itinerary is None:
        raise HTTPException(
            status_code=409,
            detail=f"Itinerary not yet available (status: {snapshot.values.get('status')})",
        )

    itinerary = _enrich_itinerary(itinerary, snapshot.values)

    return TripItineraryResponse(
        trip_id=trip_id,
        status=snapshot.values.get("status", "unknown"),
        itinerary=itinerary,
        budget_analysis=snapshot.values.get("budget_analysis"),
    )


async def _resume_graph(graph, trip_id: str, resume_payload: dict):
    config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}
    await graph.ainvoke(Command(resume=resume_payload), config=config)


@router.post("/{trip_id}/review", response_model=ReviewResponse)
async def submit_review(
    trip_id: str,
    payload: ReviewRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": ""}}

    # Confirm the trip actually exists and is genuinely paused before
    # accepting a resume - resuming a trip_id with no pending interrupt
    # either does nothing useful or raises deep inside LangGraph with a
    # much less clear error than catching it here.
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not snapshot.next:
        raise HTTPException(
            status_code=409,
            detail="Trip has no pending review - nothing to resume",
        )

    if payload.action == "approve":
        resume_payload = {"action": "approve"}
    else:
        resume_payload = {"action": "edit", "message": payload.message}

    background_tasks.add_task(_resume_graph, graph, trip_id, resume_payload)

    return ReviewResponse(trip_id=trip_id, accepted=True)