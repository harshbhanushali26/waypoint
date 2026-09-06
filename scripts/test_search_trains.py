# """
# scripts/test_search_trains.py

# Standalone test script for search_trains (RailRadar two-endpoint stage).
# Three cases are zero-cost (no live API calls). One case makes a real
# live one-way search: 1 trains-between call + up to 4 fare calls = 5
# RailRadar requests total (out of 1,000/month).
# """

# from datetime import date, timedelta
# from core.config import settings
# from tools.search_trains import search_trains


# def _base_state(transport_modes=None, origin_city="Vapi", destination="Mumbai", days_out=5) -> dict:
#     start = date.today() + timedelta(days=days_out)
#     return {
#         "origin_city": origin_city,
#         "destination": destination,
#         "start_date": start.isoformat(),
#         "end_date": start.isoformat(),  # one-way: skips return leg
#         "currency": "INR",
#         "search_plan": {"transport_modes": transport_modes if transport_modes is not None else ["trains"]},
#     }


# def _report(case_name: str, result: dict):
#     has_note = "trains_note" in result
#     train_count = len(result.get("trains", []))
#     status = "NOTE PRESENT (degraded/failed)" if has_note else "NO NOTE (success)"
#     print(f"[{case_name}] {status} — trains entries: {train_count}")
#     if has_note:
#         print(f"    note: {result['trains_note']}")
#     print()


# def test_mode_not_selected():
#     """Zero cost — trains not in transport_modes, should short-circuit."""
#     state = _base_state(transport_modes=["flights"])
#     result = search_trains(state)
#     _report("mode_not_selected", result)


# def test_missing_api_key():
#     """Zero cost — temporarily blank the RailRadar key, restore after."""
#     original_key = settings.railradar_api_key
#     settings.railradar_api_key = ""
#     try:
#         state = _base_state()
#         result = search_trains(state)
#         _report("missing_api_key", result)
#     finally:
#         settings.railradar_api_key = original_key


# def test_missing_origin_city():
#     """Zero cost — empty origin_city should fail the 'missing fields' check before any request."""
#     state = _base_state(origin_city="")
#     result = search_trains(state)
#     _report("missing_origin_city", result)


# def test_happy_path_one_way():
#     """LIVE — burns up to 5 RailRadar requests (1 between-stations + up to 4 fare lookups)."""
#     print("[happy_path_one_way] LIVE CALL — burning up to 5 RailRadar requests...")
#     state = _base_state()
#     result = search_trains(state)
#     _report("happy_path_one_way", result)

#     # ── DEBUG: print the raw API response to see actual field names ──
#     from tools.search_trains import resolve_station, _fetch_trains_between
#     from_code = resolve_station("Vapi")
#     to_code = resolve_station("Mumbai")
#     print(f"  resolved: Vapi → {from_code}, Mumbai → {to_code}")
#     raw_trains = _fetch_trains_between(from_code, to_code, state["start_date"])
#     print(f"  raw train count: {len(raw_trains)}")
#     print(f"  raw train[0] keys: {list(raw_trains[0].keys())}")
#     print(f"  raw train[0]: {raw_trains[0]}")
#     # ── END DEBUG ──

#     # Extra check specific to this node: confirm at least one train actually
#     # got a real fare, not just a silent price=0 fallback.
#     trains = result.get("trains", [])
#     priced = [t for t in trains if t.get("price", 0) > 0]
#     print(f"    trains with nonzero price: {len(priced)} / {len(trains)}")
#     if trains:
#         # print(f"    sample train: {trains[0]}")
#         print(trains)
#         print(priced)


# if __name__ == "__main__":
#     test_mode_not_selected()
#     test_missing_api_key()
#     test_missing_origin_city()
#     test_happy_path_one_way()

"""
scripts/test_search_trains.py

Minimal-quota test script for search_trains.
3 zero-cost tests + 1 live test (up to 7 API calls, ~42s due to throttling).

Run: uv run python -m scripts.test_search_trains
"""

import json
import logging
from datetime import date, timedelta

from core.config import settings
from tools.search_trains import search_trains

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_trains")


def _base_state(
    origin_city="Vapi",
    destination="Mumbai",
    days_out=5,
    transport_modes=None,
) -> dict:
    start = date.today() + timedelta(days=days_out)
    return {
        "origin_city": origin_city,
        "destination": destination,
        "start_date": start.isoformat(),
        "end_date": start.isoformat(),  # one-way
        "currency": "INR",
        "search_plan": {
            "transport_modes": transport_modes if transport_modes is not None else ["trains"],
        },
    }


def _report(name: str, result: dict):
    note = result.get("trains_note")
    count = len(result.get("trains", []))
    status = f"NOTE ({note})" if note else "OK"
    print(f"[{name}] {status} — {count} trains\n")


# ── Zero-cost tests ──────────────────────────────────────────────────────────

def test_mode_not_selected():
    log.info("test_mode_not_selected")
    result = search_trains(_base_state(transport_modes=["flights"]))
    _report("mode_not_selected", result)


def test_missing_api_key():
    log.info("test_missing_api_key")
    original = settings.railradar_api_key
    settings.railradar_api_key = ""
    try:
        result = search_trains(_base_state())
        _report("missing_api_key", result)
    finally:
        settings.railradar_api_key = original


def test_missing_fields():
    log.info("test_missing_fields")
    result = search_trains(_base_state(origin_city=""))
    _report("missing_fields", result)


# ── Live test (up to 7 API calls, throttled to ~6s apart) ────────────────────

def test_live_one_way():
    """
    LIVE — 1 between-stations + up to (3 trains × 2 classes) = up to 7 calls.
    Throttled at 6s/call, so this can take up to ~42s. That's expected.

    Calls search_trains() once, prints a detailed breakdown.
    Does NOT call internal functions separately (avoids duplicate API calls).
    """
    log.info("test_live_one_way — up to 7 API calls, ~6s apart (expect up to ~42s)")

    state = _base_state()
    result = search_trains(state)

    _report("live_one_way", result)

    trains = result.get("trains", [])
    if not trains:
        print("  No trains returned.\n")
        return

    priced = [t for t in trains if t.get("price", 0) > 0]
    unpriced = [t for t in trains if t.get("price", 0) == 0]

    print(f"  Total:     {len(trains)} trains")
    print(f"  Priced:    {len(priced)}")
    print(f"  Unpriced:  {len(unpriced)}")

    # Show each train compactly
    print(f"\n  {'Train':<12} {'Name':<30} {'Dep':>5} {'Arr':>5} {'Dur':>4}min {'From→To':<12} {'Class':>5} {'Price':>8}")
    print(f"  {'─'*12} {'─'*30} {'─'*5} {'─'*5} {'─'*7} {'─'*12} {'─'*5} {'─'*8}")

    for t in trains:
        name = t["train_name"][:28] if t["train_name"] else "?"
        dep = t["departure_time"] or "?"
        arr = t["arrival_time"] or "?"
        dur = str(t["duration_minutes"])
        route = f"{t['departure_station']}→{t['arrival_station']}"
        cls = t["class_code"] or "?"
        price = f"₹{t['price']:.0f}" if t["price"] else "—"
        print(f"  {t['train_number']:<12} {name:<30} {dep:>5} {arr:>5} {dur:>7} {route:<12} {cls:>5} {price:>8}")

    # Show full JSON of first priced train (if any)
    if priced:
        print(f"\n  First priced train (full JSON):")
        print(f"  {json.dumps(priced[0], indent=2)}")
    else:
        print(f"\n  ⚠ No trains got fares.")
        print(f"  First train (full JSON):")
        print(f"  {json.dumps(trains[0], indent=2)}")


if __name__ == "__main__":
    print("=" * 72)
    print("  Waypoint — search_trains test suite")
    print("  RailRadar API (free sandbox: 1,000 requests/month, 10/minute)")
    print("=" * 72)

    test_mode_not_selected()
    test_missing_api_key()
    test_missing_fields()

    print()
    print("=" * 72)
    print("  LIVE TEST — up to 7 API calls, throttled ~6s apart")
    print("=" * 72)
    test_live_one_way()

    print()
    print("=" * 72)
    print("  Done.")
    print("=" * 72)