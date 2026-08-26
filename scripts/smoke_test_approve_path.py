"""
scripts/smoke_test_approve_path.py

Test 3 in the Step 7 sequence: verify the approve-resume path end to end -
graph resumes from human_review's interrupt with {"action": "approve"},
routes to finalize (not Critic), and finalize's DB writes actually land.

PRECONDITION STUB: finalize_node writes an Itinerary row whose trip_id has
a ForeignKey to trips.trip_id. In the real system, the FastAPI layer (Step 8,
not built yet) creates the Trip row when the user submits the form - before
the graph ever runs. Since that layer doesn't exist yet, this script inserts
a minimal Trip row itself as a stand-in, so finalize_node's real code path
can be exercised today instead of left completely unverified until Step 8.

This insert is deliberately plain, no try/except - a fresh UUID-suffixed
trip_id should never collide with an existing row, so a failure here would
mean something genuinely unexpected happened and should surface, not be
swallowed. Same "fail loud, don't guess" instinct as Critic's invalid-target
handling and human_review's unrecognized-action handling.

Reuses the same interrupt-dispatch pattern as smoke_test_happy_path.py
(distinguishing Concierge's str payload from human_review's dict payload).
See that file's docstring for why thread_id must be freshly generated per
run rather than reused.

Run with:
    python -m scripts.smoke_test_approve_path
"""

import asyncio
import json
import uuid

from sqlalchemy import select
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from core.config import settings
from graph.build_graph import build_graph
from db.session import async_session_factory
from db.models import Trip, Itinerary


def make_dummy_trip_input() -> dict:
    """Fresh dict per call so trip_id is unique per run."""
    return {
        "trip_id": f"smoke-test-{uuid.uuid4().hex[:8]}",
        "destination": "Tokyo",
        "origin_city": "Mumbai",
        "start_date": "2027-01-25",
        "end_date": "2027-01-30",
        "budget": 150000.0,
        "currency": "INR",
        "num_travelers": 2,
        "interests": ["food", "history"],
        "transport_pref": "flights",
        "wants_rental_car": False,
        "pace": "packed",
        "messages": [],
        "approved": False,
        "status": "",
    }


MAX_ROUNDS = 5  # safety cap so a bug can't spin this forever


async def insert_stub_trip_row(trip_input: dict) -> None:
    """
    Stand-in for the Step 8 FastAPI 'create trip' endpoint, which doesn't
    exist yet. Plain insert, no defensive try/except - a fresh trip_id
    should never collide, so let a failure here surface loudly.
    """
    async with async_session_factory() as session:
        session.add(
            Trip(
                trip_id=trip_input["trip_id"],
                destination=trip_input["destination"],
                origin_city=trip_input["origin_city"],
                start_date=trip_input["start_date"],
                end_date=trip_input["end_date"],
                num_travelers=trip_input["num_travelers"],
                budget=trip_input["budget"],
                currency=trip_input["currency"],
                # status left at model default ("planning")
            )
        )
        await session.commit()
    print(f"Stub Trip row inserted for trip_id={trip_input['trip_id']!r}")


async def check_db_writes(trip_id: str) -> None:
    """
    Queries the app tables directly to confirm finalize_node's writes
    actually landed - not just trusting the graph's returned state.
    """
    async with async_session_factory() as session:
        itinerary_row = await session.scalar(
            select(Itinerary).where(Itinerary.trip_id == trip_id)
        )
        trip_row = await session.scalar(
            select(Trip).where(Trip.trip_id == trip_id)
        )

    print("\n--- DB write checks ---")

    if itinerary_row is not None:
        print(f"PASS: itineraries row exists for trip_id={trip_id!r} "
              f"(approved_at={itinerary_row.approved_at})")
    else:
        print(f"FAIL: no itineraries row found for trip_id={trip_id!r}")

    if trip_row is not None and trip_row.status == "finalized":
        print(f"PASS: trips row status == 'finalized' for trip_id={trip_id!r}")
    elif trip_row is not None:
        print(f"FAIL: trips row status == {trip_row.status!r}, expected 'finalized'")
    else:
        print(f"FAIL: no trips row found for trip_id={trip_id!r}")


async def main() -> None:
    conn_string = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()

        compiled_graph = build_graph(checkpointer)

        dummy_trip_input = make_dummy_trip_input()
        print(f"Using fresh trip_id: {dummy_trip_input['trip_id']}")

        # Precondition stub - see module docstring.
        await insert_stub_trip_row(dummy_trip_input)

        config = {
            "configurable": {
                "thread_id": dummy_trip_input["trip_id"],
                "checkpoint_ns": "",
            }
        }

        print("Invoking full graph with dummy trip input...")
        result = await compiled_graph.ainvoke(dummy_trip_input, config=config)

        for round_num in range(1, MAX_ROUNDS + 1):
            interrupts = result.get("__interrupt__")

            if not interrupts:
                print("\nNo interrupt present - graph ran to completion "
                      "without pausing. If you expected a pause at "
                      "human_review, something upstream is wrong "
                      "(or routing skipped it).")
                print("Final result keys:", list(result.keys()))
                return

            payload = interrupts[0].value
            print(f"\n--- Round {round_num}: interrupt payload ---")
            print(json.dumps(payload, indent=2, default=str) if isinstance(payload, dict) else payload)

            if isinstance(payload, str):
                # Concierge's clarification pause - plain string question.
                print("\n-> This is Concierge's clarification pause.")
                fake_answer = "Budget is in USD, dates are fixed as given."
                print(f"Resuming with plain-string answer: {fake_answer!r}")
                result = await compiled_graph.ainvoke(
                    Command(resume=fake_answer), config=config
                )
                continue

            if isinstance(payload, dict) and "itinerary" in payload:
                # human_review's review pause - resume with approve this time.
                print("\n-> This is human_review's pause. Resuming with approve.")
                result = await compiled_graph.ainvoke(
                    Command(resume={"action": "approve"}), config=config
                )
                break

            print("\nFAIL: interrupt payload didn't match either known "
                  "shape (str for Concierge, dict-with-itinerary for "
                  "human_review). Inspect payload above manually.")
            return
        else:
            print(f"\nFAIL: hit MAX_ROUNDS={MAX_ROUNDS} without reaching "
                  f"human_review. Likely stuck looping on Concierge "
                  f"clarification, or clarification_attempts fallback isn't "
                  f"terminating as expected.")
            return

        # --- Post-approve assertions on graph state ---
        print("\n--- Post-approve graph state checks ---")

        still_interrupted = bool(result.get("__interrupt__"))
        if still_interrupted:
            print("FAIL: graph is still paused on an interrupt after "
                  "approving - expected it to run to completion.")
        else:
            print("PASS: graph has no pending interrupt after approve.")

        approved_flag = result.get("approved")
        if approved_flag is True:
            print("PASS: state['approved'] is True.")
        else:
            print(f"FAIL: state['approved'] == {approved_flag!r}, expected True.")

        status_val = result.get("status")
        if status_val == "finalized":
            print("PASS: state['status'] == 'finalized'.")
        else:
            print(f"FAIL: state['status'] == {status_val!r}, expected 'finalized'.")

        # --- DB write checks ---
        await check_db_writes(dummy_trip_input["trip_id"])


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)