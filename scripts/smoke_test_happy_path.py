"""
scripts/smoke_test_happy_path.py

Test 2 in the Step 7 sequence: run a dummy trip through the REAL graph.

There are TWO distinct interrupt() call sites in this graph, both riding on
the same generic LangGraph interrupt/resume mechanism, but with different
resume contracts:

  - Concierge's clarification pause: interrupt(question_string) -> resume
    with a plain string answer: Command(resume="some text")
  - human_review's review pause: interrupt({"itinerary":..., "budget_analysis":...})
    -> resume with a structured dict:
    Command(resume={"action": "approve"}) or
    Command(resume={"action": "edit", "message": "..."})

This script distinguishes them by inspecting the interrupt payload's shape
(str vs dict) and resumes accordingly, looping until it reaches
human_review's pause (or hits a safety limit).

NOTE ON thread_id: a fresh UUID suffix is generated on every run. Reusing a
fixed thread_id (as an earlier version of this script did) lets
AsyncPostgresSaver resume from a stale checkpoint instead of running the
graph from scratch - Concierge's node body (and its debug prints) can be
silently skipped because normalized_input already exists in the old
checkpoint, and other fields can carry over from a totally different prior
run. If you need to deliberately resume a specific prior run for debugging,
hardcode that run's printed trip_id back in instead of using the generated
one.

Run with:
    python -m scripts.smoke_test_happy_path
"""

import asyncio
import json
import uuid

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from core.config import settings
from graph.build_graph import build_graph


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


async def main() -> None:
    conn_string = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()

        compiled_graph = build_graph(checkpointer)

        dummy_trip_input = make_dummy_trip_input()
        print(f"Using fresh trip_id: {dummy_trip_input['trip_id']}")

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
                # human_review's review pause - the one we actually want to test.
                print("\n-> This is human_review's pause. Running checks.")
                has_itinerary = bool(payload.get("itinerary"))
                has_budget = bool(payload.get("budget_analysis"))
                print(f"itinerary present: {has_itinerary}")
                print(f"budget_analysis present: {has_budget}")

                if not has_itinerary:
                    print("FAIL: itinerary missing or empty in interrupt payload.")
                if not has_budget:
                    print("FAIL: budget_analysis missing or empty in interrupt payload.")
                if has_itinerary and has_budget:
                    print("\nPASS: graph correctly reached human_review with a full payload.")

                checkpoint_tuple = await checkpointer.aget_tuple(config)
                current_state = checkpoint_tuple.checkpoint.get("channel_values", {})
                print(f"approved (should be False/unset): {current_state.get('approved')}")
                return

            print("\nFAIL: interrupt payload didn't match either known "
                  "shape (str for Concierge, dict-with-itinerary for "
                  "human_review). Inspect payload above manually.")
            return

        print(f"\nFAIL: hit MAX_ROUNDS={MAX_ROUNDS} without reaching "
              f"human_review. Likely stuck looping on Concierge "
              f"clarification, or clarification_attempts fallback isn't "
              f"terminating as expected.")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)