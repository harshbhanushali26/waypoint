"""
scripts/smoke_test_checkpointer.py

Isolated smoke test for the AsyncPostgresSaver + Windows event loop, run
BEFORE trusting any output from the real graph.

Deliberately does NOT use your real agent nodes (Concierge etc.) - those
call Groq and depend on graph logic that hasn't been proven yet. This test
isolates exactly one thing: does an async checkpoint write actually succeed
against Postgres under SelectorEventLoop, on this machine, right now.

If this fails, the problem is infra (event loop / connection string / Postgres
reachability) - not your graph logic. Don't move on to real graph testing
until this passes cleanly.

Run with:
    python -m scripts.smoke_test_checkpointer
"""

import asyncio
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.config import settings


class DummyState(TypedDict):
    trip_id: str
    touched: bool


def dummy_node(state: DummyState) -> dict:
    # No LLM calls, no external I/O - just proves a node can run and its
    # write can be checkpointed.
    return {"touched": True}


async def main() -> None:
    # AsyncPostgresSaver wants a plain postgresql:// string, not the
    # +psycopg dialect suffix SQLAlchemy's engine needs (Step 2 decision).
    conn_string = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

    test_thread_id = "smoke-test-trip"

    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()  # no-op if checkpoint tables already exist

        graph = StateGraph(DummyState)
        graph.add_node("dummy", dummy_node)
        graph.set_entry_point("dummy")
        graph.add_edge("dummy", END)
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": test_thread_id, "checkpoint_ns": ""}}

        print("Invoking dummy graph...")
        result = await compiled.ainvoke({"trip_id": test_thread_id, "touched": False}, config=config)
        print("Invoke completed. Result:", result)

        print("Reading back checkpoint via get_tuple...")
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if checkpoint_tuple is None:
            print("FAIL: no checkpoint found for thread_id =", test_thread_id)
        else:
            print("PASS: checkpoint persisted and read back successfully.")
            print("Checkpoint state snapshot:", checkpoint_tuple.checkpoint.get("channel_values"))


if __name__ == "__main__":
    # The actual point of this test: confirm this loop_factory avoids the
    # ProactorEventLoop incompatibility with psycopg's async driver on
    # Windows (documented in Step 2). set_event_loop_policy is deprecated
    # as of Python 3.12 - loop_factory is the current approach.
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)