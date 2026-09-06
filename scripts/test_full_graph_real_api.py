"""
Full graph integration test — real API stage, Vapi -> Ahmedabad.

Runs the entire graph against real APIs (RailRadar trains, SerpApi hotels,
Tavily activities, Open-Meteo weather) end to end: form input -> planning ->
simulated approval -> finalize. Confirms data_gaps and enrichment behave
correctly against real data, not dummy JSON.

transport_pref forced to "trains" — Vapi has no commercial airport, so this
keeps the test isolated to the transport mode that actually applies here.

Run from project root:
    uv run python -m scripts.test_full_graph_real_api
"""

"""
Full graph integration test — real API stage, Vapi -> Ahmedabad.
"""

import time
import asyncio
from uuid import uuid4
from datetime import date, timedelta

from langgraph.types import Command

from graph.build_graph import build_graph
from db.checkpointer import get_checkpointer
from db.session import async_session_factory
from db.models import Trip  # adjust import if needed


def make_trip_input() -> dict:
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=3)
    return {
        "trip_id": f"test-real-api-{uuid4().hex[:8]}",
        "destination": "Ahmedabad",
        "origin_city": "Vapi",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "budget": 15000.0,
        "currency": "INR",
        "num_travelers": 2,
        "interests": ["food", "history"],
        "transport_pref": "trains",
        "wants_rental_car": False,
        "pace": "moderate",
    }


async def main():
    total_start = time.monotonic()

    async with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        trip_input = make_trip_input()
        thread_id = trip_input["trip_id"]
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

        # Stub Trip row first — itineraries.trip_id FK requires this
        async with async_session_factory() as session:
            session.add(Trip(
                trip_id=thread_id,
                destination=trip_input["destination"],
                origin_city=trip_input["origin_city"],
                start_date=trip_input["start_date"],
                end_date=trip_input["end_date"],
                num_travelers=trip_input["num_travelers"],
                budget=trip_input["budget"],
                currency=trip_input["currency"],
                status="planning",
            ))
            await session.commit()

        print(f"=== Starting run: {thread_id} ===")
        print(f"Route: {trip_input['origin_city']} -> {trip_input['destination']}")
        print(f"Dates: {trip_input['start_date']} to {trip_input['end_date']}\n")

        # --- Phase 1: build -> human_review ---
        phase1_start = time.monotonic()
        result = await graph.ainvoke(trip_input, config=config)
        phase1_elapsed = time.monotonic() - phase1_start

        print("--- Reached human_review ---")
        print(f"status: {result.get('status')}")
        print(f"data_gaps: {result.get('itinerary', {}).get('data_gaps')}")
        print(f"budget_analysis: {result.get('budget_analysis')}\n")

        for key in ["flights", "trains", "hotels", "activities", "weather"]:
            val = result.get(key)
            note_key = f"{key}_note"
            note = result.get(note_key)
            print(f"{key}: {len(val) if val else 0} items" + (f" | note: {note}" if note else ""))

        print(f"\n[TIMER] Phase 1 (build -> human_review): {phase1_elapsed:.1f}s")

        # --- Phase 2: approve -> finalize ---
        phase2_start = time.monotonic()
        final_result = await graph.ainvoke(
            Command(resume={"action": "approve"}),
            config=config,
        )
        phase2_elapsed = time.monotonic() - phase2_start

        print(f"\nfinal status: {final_result.get('status')}")
        print(f"approved: {final_result.get('approved')}")

        itinerary = final_result.get("itinerary", {})
        print(f"\nitinerary days: {len(itinerary.get('days', []))}")
        print(f"total_cost: {itinerary.get('total_cost')}")
        print(f"chosen_transport legs: {len(itinerary.get('chosen_transport', []))}")
        print(f"chosen_hotel id: {itinerary.get('chosen_hotel', {}).get('hotel_id')}")
        print(f"data_gaps (final): {itinerary.get('data_gaps')}")

        print(f"\n[TIMER] Phase 2 (approve -> finalize): {phase2_elapsed:.1f}s")

        async with async_session_factory() as session:
            row = await session.get(Trip, thread_id)
            print(f"\nDB trip row present: {row is not None}")

    total_elapsed = time.monotonic() - total_start
    print(f"\n=== Total run time: {total_elapsed:.1f}s ===")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)