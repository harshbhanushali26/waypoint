"""
scripts/smoke_test_edit_path.py

Test 4 in the Step 7 sequence: verify the edit-resume path reaches Critic
correctly and Critic returns a valid Command(goto=...) - WITHOUT letting the
graph actually execute past Critic.

WHY astream() INSTEAD OF ainvoke():
ainvoke(Command(resume=...)) runs the graph forward until the *next*
interrupt or full completion. If Critic routes to "planner", ainvoke would
happily keep executing planner -> tools -> budget -> itinerary_builder ->
the next human_review pause, all inside that one call. That's the re-run
loop-closure behavior we deliberately deferred (open questions: does
planner behave differently on a re-run, do multi-target Command(goto=[...])
routes fan out correctly, does a re-run always land back at a fresh
human_review pause, etc. - see Step 7 notes).

astream(..., stream_mode="updates") yields each node's output one at a time
as it completes. This script watches for the "critic" key specifically,
asserts on it, then breaks out of the loop immediately - which stops
consuming the stream, so nothing past Critic gets a chance to run in this
test. This is the isolation the deferred-decisions call for.

Reuses the same interrupt-dispatch pattern as smoke_test_happy_path.py for
reaching the first human_review pause. See that file's docstring for why
thread_id must be freshly generated per run rather than reused.

Run with:
    python -m scripts.smoke_test_edit_path
"""

import asyncio
import json
import uuid

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from core.config import settings
from graph.build_graph import build_graph
from agents.critic import VALID_TARGETS


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


# Chosen per the CriticAnalysis schema's own docstring, which explicitly
# calls out "make it cheaper" -> full replan via "planner". Least ambiguous
# message to start with, since it's the one case the schema itself documents.
EDIT_MESSAGE = "Can you make this trip cheaper overall?"

MAX_ROUNDS = 5  # safety cap for reaching the first human_review pause


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

        # --- reach the first human_review pause (same dispatch as happy path) ---
        for round_num in range(1, MAX_ROUNDS + 1):
            interrupts = result.get("__interrupt__")

            if not interrupts:
                print("\nFAIL: graph ran to completion without pausing - "
                      "expected to reach human_review before this point.")
                return

            payload = interrupts[0].value

            if isinstance(payload, str):
                print(f"\n--- Round {round_num}: Concierge clarification pause ---")
                fake_answer = "Budget is in USD, dates are fixed as given."
                print(f"Resuming with plain-string answer: {fake_answer!r}")
                result = await compiled_graph.ainvoke(
                    Command(resume=fake_answer), config=config
                )
                continue

            if isinstance(payload, dict) and "itinerary" in payload:
                print(f"\n--- Round {round_num}: human_review pause reached ---")
                break

            print("\nFAIL: interrupt payload didn't match either known "
                  "shape. Inspect payload above manually.")
            print(payload)
            return
        else:
            print(f"\nFAIL: hit MAX_ROUNDS={MAX_ROUNDS} without reaching "
                  f"human_review.")
            return

        # --- resume with an edit action, but only stream up to Critic ---
        print(f"\nResuming with edit action: {EDIT_MESSAGE!r}")
        print("Streaming node-by-node - will stop immediately after Critic "
              "fires, before any re-run/loop-back behavior executes.\n")

        critic_update = None

        async for update in compiled_graph.astream(
            Command(resume={"action": "edit", "message": EDIT_MESSAGE}),
            config=config,
            stream_mode="updates",
        ):
            node_name = list(update.keys())[0]
            print(f"Node completed: {node_name}")

            if node_name == "critic":
                critic_update = update["critic"]
                print("\n-> Critic fired. Stopping stream consumption here - "
                      "not letting the graph continue to its routed target(s).")
                break

        if critic_update is None:
            print("\nFAIL: stream ended without Critic ever firing. "
                  "Check human_review's edit-path handling and the "
                  "conditional edge routing.")
            return

        # --- assertions on Critic's output ---
        print("\n--- Critic output checks ---")

        critic_analysis = critic_update.get("critic_analysis")
        if not critic_analysis:
            print("FAIL: critic_analysis missing from Critic's state update.")
            return

        print(json.dumps(critic_analysis, indent=2, default=str))

        target = critic_analysis.get("target")
        if not target or not isinstance(target, list):
            print(f"FAIL: target is missing or not a list: {target!r}")
            return
        print(f"PASS: target is a non-empty list: {target}")

        invalid = [t for t in target if t not in VALID_TARGETS]
        if invalid:
            print(f"FAIL: target contains invalid node name(s): {invalid}")
        else:
            print(f"PASS: all target(s) are valid node names: {target}")

        interpretation = critic_analysis.get("interpretation", "")
        reasoning = critic_analysis.get("reasoning", "")
        print(f"\nInterpretation: {interpretation}")
        print(f"Reasoning: {reasoning}")
        print("\n(Eyeball check: does the interpretation/reasoning make "
              "sense for the message "
              f"{EDIT_MESSAGE!r}? This isn't hard-asserted since Critic's "
              "routing is LLM-driven, not deterministic.)")

        print("\nNOTE: test stopped intentionally after Critic. Re-run/"
              "loop-back behavior (does the routed node behave differently "
              "on a revision pass, does a re-run land back at a fresh "
              "human_review pause, do multi-target Command(goto=[...]) "
              "routes fan out correctly) is deliberately untested pending "
              "open design decisions - see Step 7 notes.")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)