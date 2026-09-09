"""
graph/finalize.py
 
The finalize node. Sole job: on approval, persist the finished itinerary to
the application's durable tables (separate from the checkpointer, which is
LangGraph's internal pause/resume mechanism and not meant to be queried by
the API layer for things like trip history).
 
Design decision this implements (locked before writing):
  - Finalize is a real graph node, not logic punted to the FastAPI layer,
    so the graph stays testable standalone per the Step 7 build plan.
  - Writes: itineraries row (trip_id, itinerary JSON, approved_at), trips
    row status update, and TripState["status"] set to a terminal value the
    frontend's progress UI can read.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


from db.session import async_session_factory
from db.models import Trip, Itinerary
from core.logging import get_trip_logger

logger = logging.getLogger(__name__)

async def finalize_node(state: dict) -> dict:
    """
    Persists the approved itinerary and marks the trip finalized.
 
    Runs only on the approve path (human_review's conditional edge routes
    here exclusively when state["approved"] is True).
    """

    trip_id = state["trip_id"]
    itinerary = state["itinerary"]
    log = get_trip_logger(logger, trip_id)

    log.info("Finalize: persisting approved itinerary")

    try:
        async with async_session_factory() as session:
            session: AsyncSession
            session.add(
                Itinerary(
                    trip_id=trip_id,
                    itinerary=itinerary,
                    approved_at=datetime.now(timezone.utc),
                )
            )

            await session.execute(
                update(Trip)
                .where(Trip.trip_id == trip_id)
                .values(status="finalized")
            )

            await session.commit()

        log.info("Finalize: trip marked finalized")  # NEW

    except Exception as e:
        # A failed commit here means the user's approved itinerary never
        # actually got saved — this must never fail silently.
        log.error("Finalize: failed to persist itinerary — %s", e, exc_info=True)  # NEW
        raise

    return {"status": "finalized"}

