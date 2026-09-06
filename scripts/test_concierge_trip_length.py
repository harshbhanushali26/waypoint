"""
scripts/test_concierge_trip_length.py

Tests the trip-length hard-cap guard clause in concierge_node, with zero
LLM/API cost. Run via: uv run python -m scripts.test_concierge_trip_length
"""

from datetime import date, timedelta
from unittest.mock import patch

from langgraph.errors import GraphInterrupt

from agents.concierge import concierge_node, MAX_TRIP_DAYS, TRIP_LENGTH_MESSAGE


class _LLMNotCalled(Exception):
    """Sentinel raised if the LLM path is reached — proves zero-cost test."""


def _base_state(start: date, end: date) -> dict:
    return {
        "trip_id": "test-trip",
        "destination": "Goa",
        "origin_city": "Mumbai",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "budget": 20000.0,
        "currency": "INR",
        "num_travelers": 2,
        "interests": ["beaches"],
        "transport_pref": "trains",
        "wants_rental_car": False,
        "pace": "moderate",
        "clarification_attempts": 0,
    }


def _report(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}{': ' + detail if detail else ''}")


def test_boundary_arithmetic():
    """Pure day-count check, no node call at all — cheapest possible test."""
    print("\n--- test_boundary_arithmetic ---")

    start = date(2026, 10, 1)

    exactly_7 = start + timedelta(days=MAX_TRIP_DAYS - 1)  # day 0..6 inclusive = 7 days
    span_days = (exactly_7 - start).days
    _report("7-day span should NOT exceed cap", span_days == MAX_TRIP_DAYS - 1, f"span={span_days}")

    eight_days = start + timedelta(days=MAX_TRIP_DAYS)  # one day over
    span_days_over = (eight_days - start).days
    _report("8-day span SHOULD exceed cap", span_days_over > MAX_TRIP_DAYS - 1, f"span={span_days_over}")


def test_guard_fires_for_long_trip():
    """A >7-day trip should call interrupt() with the fixed message,
    before any LLM call. interrupt() itself is patched here since it
    requires a real graph run context (get_config()) that a direct
    node call doesn't have -- we're only verifying OUR guard clause's
    behavior, not LangGraph's interrupt machinery.
    """
    print("\n--- test_guard_fires_for_long_trip ---")

    start = date(2026, 10, 1)
    end = start + timedelta(days=10)  # 10-day span, well over cap
    state = _base_state(start, end)

    captured_calls = []

    def _fake_interrupt(message):
        captured_calls.append(message)
        raise _LLMNotCalled("interrupt() called -- stopping test here on purpose")

    with patch("agents.concierge.interrupt", side_effect=_fake_interrupt), \
         patch("agents.concierge.get_structured_llm", side_effect=_LLMNotCalled("LLM should not be called")):
        try:
            concierge_node(state)
            _report("guard should have called interrupt()", False, "no exception raised")
        except _LLMNotCalled:
            called_correctly = (
                len(captured_calls) == 1
                and captured_calls[0] == TRIP_LENGTH_MESSAGE
            )
            _report(
                "interrupt() called once with correct message before LLM",
                called_correctly,
                f"calls={captured_calls}",
            )
        except Exception as e:
            _report("unexpected exception type", False, f"{type(e).__name__}: {e}")


def test_guard_allows_valid_trip():
    """A <=7-day trip should NOT raise GraphInterrupt — it should fall through
    to the LLM path. We patch get_structured_llm to raise a sentinel instead
    of actually calling Groq, so reaching that point (and only that point)
    proves the guard clause correctly let a valid trip through at zero cost.
    """
    print("\n--- test_guard_allows_valid_trip ---")

    start = date(2026, 10, 1)
    end = start + timedelta(days=MAX_TRIP_DAYS - 1)  # exactly 7 days, should pass
    state = _base_state(start, end)

    with patch("agents.concierge.get_structured_llm", side_effect=_LLMNotCalled("reached LLM path")):
        try:
            concierge_node(state)
            _report("expected sentinel exception, got clean return", False)
        except _LLMNotCalled:
            _report("valid trip correctly bypassed guard and reached LLM path", True)
        except GraphInterrupt:
            _report("valid trip incorrectly triggered guard", False, "GraphInterrupt raised for a 7-day trip")
        except Exception as e:
            _report("unexpected exception type", False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    test_boundary_arithmetic()
    test_guard_fires_for_long_trip()
    test_guard_allows_valid_trip()