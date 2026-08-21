import asyncio
import selectors
import sys

from db.checkpointer import get_checkpointer


async def main():
    async with get_checkpointer() as checkpointer:
        # One-time setup: creates the checkpointer's own tables if they
        # don't already exist. Safe to call every run — no-ops if present.
        await checkpointer.setup()
        print("Checkpointer tables ready.")

        config = {
            "configurable": {
                "thread_id": "test-thread-1",
                "checkpoint_ns": "",
            }
        }

        dummy_checkpoint = {
            "v": 1,
            "ts": "2026-01-01T00:00:00+00:00",
            "id": "test-checkpoint-1",
            "channel_values": {"test_key": "hello from waypoint"},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }

        await checkpointer.aput(config, dummy_checkpoint, {}, {})
        print("Wrote dummy checkpoint.")

        result = await checkpointer.aget(config)
        print("Read back:", result)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(main())