# scripts/retry_from_checkpoint.py
import asyncio
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from core.config import settings
from graph.build_graph import build_graph

TRIP_ID = "cf9d96d0-8e01-449e-8b2b-d403fdb9707e"

async def main():
    conn_string = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = {"configurable": {"thread_id": TRIP_ID, "checkpoint_ns": ""}}

        # No new input, no Command() - just continue from the last
        # checkpoint. LangGraph picks up at whatever node was next
        # (itinerary_builder, per the last saved state).
        result = await graph.ainvoke(None, config=config)
        print("Interrupt present:", bool(result.get("__interrupt__")))
        print("Status:", result.get("status"))

if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)