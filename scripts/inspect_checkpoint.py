"""
scripts/inspect_checkpoint.py

Read-only inspector for a given thread_id's checkpointed state in Postgres.
Does NOT run the graph and does NOT call any LLM - it only reads whatever
AsyncPostgresSaver already persisted for that thread_id.

Useful for:
  - Confirming whether a thread_id already has state before a run (explains
    why a node's body - and its prints - might get skipped on resume).
  - Inspecting exactly what's sitting in a paused (interrupted) run without
    re-invoking the graph.
  - Checking channel_values field-by-field instead of relying on whatever
    got printed to console during the original run.

Run with:
    python -m scripts.inspect_checkpoint <thread_id>

Example:
    python -m scripts.inspect_checkpoint smoke-test-2c810826

If no thread_id is given, lists the most recent thread_ids found in the
checkpoints table instead, so you can pick one.
"""

import asyncio
import json
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.config import settings


def _default(o):
    # Fallback for anything json.dumps can't handle natively (dates, etc.)
    return str(o)


async def list_recent_thread_ids(checkpointer: AsyncPostgresSaver, limit: int = 15) -> None:
    """
    No direct 'list all threads' API on the checkpointer, so this queries
    the underlying table directly via the checkpointer's own connection pool.
    """
    async with checkpointer.conn.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT thread_id, MAX(checkpoint_id) as latest
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY latest DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    if not rows:
        print("No checkpoints found in the database yet.")
        return

    print(f"Most recent {len(rows)} thread_id(s):\n")
    for thread_id, _latest in rows:
        print(f"  {thread_id}")
    print("\nRe-run with one of these:")
    print("    python -m scripts.inspect_checkpoint <thread_id>")


async def inspect_thread(checkpointer: AsyncPostgresSaver, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    checkpoint_tuple = await checkpointer.aget_tuple(config)

    if checkpoint_tuple is None:
        print(f"No checkpoint found for thread_id = {thread_id!r}")
        print("Either it was never run, or the thread_id is misspelled.")
        return

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})

    print(f"--- Checkpoint state for thread_id = {thread_id!r} ---\n")

    # Print each top-level state field on its own line, truncating anything
    # very long (e.g. a full itinerary dict) so this stays scannable.
    for key, value in channel_values.items():
        value_str = json.dumps(value, default=_default)
        if len(value_str) > 300:
            value_str = value_str[:300] + f"... [truncated, {len(value_str)} chars total]"
        print(f"{key}: {value_str}")

    print("\n--- Pending interrupts (if any) ---")
    pending = checkpoint_tuple.pending_writes
    if pending:
        print(f"{len(pending)} pending write(s) present - run is likely paused mid-interrupt.")
    else:
        print("None recorded on this checkpoint tuple.")

    print("\nTip: to see the FULL untruncated value of one field, e.g. 'itinerary':")
    print(f"    python -m scripts.inspect_checkpoint {thread_id} itinerary")


async def inspect_single_field(checkpointer: AsyncPostgresSaver, thread_id: str, field: str) -> None:
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint_tuple = await checkpointer.aget_tuple(config)

    if checkpoint_tuple is None:
        print(f"No checkpoint found for thread_id = {thread_id!r}")
        return

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})

    if field not in channel_values:
        print(f"Field '{field}' not present in state. Available fields:")
        for key in channel_values:
            print(f"  {key}")
        return

    print(f"--- Full value of '{field}' for thread_id = {thread_id!r} ---\n")
    print(json.dumps(channel_values[field], indent=2, default=_default))


async def main() -> None:
    conn_string = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()

        args = sys.argv[1:]

        if not args:
            await list_recent_thread_ids(checkpointer)
            return

        thread_id = args[0]

        if len(args) >= 2:
            field = args[1]
            await inspect_single_field(checkpointer, thread_id, field)
        else:
            await inspect_thread(checkpointer, thread_id)


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)