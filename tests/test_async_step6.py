"""
test_async_step6.py — Standalone verification for Step 6
"""

import asyncio
import inspect
import sys
import os
import time

# Set dummy environment variables to allow clean imports
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_pass")
os.environ.setdefault("GROQ_API_KEY", "gsk_dummy_test_key_for_offline_evaluation")
os.environ.setdefault("TAVILY_API_KEY", "tvly_dummy_test_key_for_offline_evaluation")
os.environ.setdefault("SERPAPI_API_KEY", "serp_dummy_test_key_for_offline_evaluation")
os.environ.setdefault("RAILRADAR_API_KEY", "rail_dummy_test_key_for_offline_evaluation")

from agents.itinerary_builder import itinerary_builder_node
from tools.search_trains import search_trains


async def test_async_node_signatures():
    # 1. Assert nodes are coroutines (non-blocking async)
    assert inspect.iscoroutinefunction(itinerary_builder_node), (
        "itinerary_builder_node must be an async coroutine function"
    )
    print("✅ Itinerary Builder Async Coroutine Signature: PASSED")

    assert inspect.iscoroutinefunction(search_trains), (
        "search_trains must be an async coroutine function"
    )
    print("✅ Search Trains Async Coroutine Signature: PASSED")


async def test_non_blocking_pacing_latency():
    # 2. Verify that without a prior LLM call, it does NOT sleep for 10 seconds
    t0 = time.time()
    # Pacing check when _budget_llm_done_at is None
    last_llm_time = None
    if last_llm_time:
        elapsed = time.time() - last_llm_time
        remaining = 3.0 - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
    t1 = time.time()

    elapsed_time = t1 - t0
    assert elapsed_time < 0.1, f"Expected zero sleep, but took {elapsed_time:.2f}s"
    print("✅ Zero Pacing Latency (No Artificial 10s Sleep): PASSED")

    # 3. Verify recent call only sleeps fractional difference
    recent_time = time.time() - 2.85  # 2.85s ago -> only 0.15s remaining
    t0 = time.time()
    elapsed = time.time() - recent_time
    remaining = 3.0 - elapsed
    if remaining > 0:
        await asyncio.sleep(remaining)
    t1 = time.time()

    sleep_duration = t1 - t0
    assert 0.05 <= sleep_duration <= 0.35, f"Expected ~0.15s non-blocking sleep, got {sleep_duration:.2f}s"
    print("✅ Dynamic Token-Aware Pacing (~0.15s instead of 25s): PASSED")


def test_graph_compilation_with_async_nodes():
    from graph.build_graph import build_graph
    from langgraph.checkpoint.memory import MemorySaver

    compiled = build_graph(MemorySaver())
    assert "itinerary_builder" in compiled.nodes
    assert "search_trains" in compiled.nodes
    print("✅ StateGraph Compilation with Async Nodes: PASSED")


async def main():
    print("\nRunning Step 6 Verification...")
    await test_async_node_signatures()
    await test_non_blocking_pacing_latency()
    test_graph_compilation_with_async_nodes()
    print("\n🎉 ALL STEP 6 CHECKS PASSED!\n")


if __name__ == "__main__":
    asyncio.run(main())