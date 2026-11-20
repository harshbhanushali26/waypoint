"""
graph/validator.py

Deterministic guardrail between itinerary_builder and human_review. Zero API calls.

The LLM proposes activities and picks a hotel and transport legs by id.
Python owns everything that has to be true:
  - hotel and transport details come from the search results, not the model's copy
  - check-in, check-out and transport events are rebuilt from those records
  - activities that are physically impossible (before arrival, after departure) are dropped
  - every trip date has a day, events are sorted, costs and budget flags are recomputed
"""

import copy
import logging
import re
from datetime import date, timedelta

from core.logging import get_trip_logger
from graph.state import TripState

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap]m)?", re.I)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_NOISE = {"the", "of", "and", "in", "at", "a", "an", "to", "for",
          "visit", "explore", "enjoy", "tour", "see", "walk", "trip"}
_ORDER = {"hotel_checkout": 0, "transport": 1, "hotel_checkin": 2, "activity": 3}

_ARRIVAL_TO_HOTEL_MIN = 60
_CHECKOUT_BEFORE_DEPARTURE_MIN = 180
_AIRPORT_BUFFER_MIN = 90


# ── Small helpers ────────────────────────────────────────────────────────────

def _minutes(value) -> int | None:
    """'9:30', '09:30', '2:00 PM' or '2026-12-10 11:10' -> minutes since midnight."""
    m = _TIME_RE.search(str(value or ""))
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def _hhmm(minutes: int) -> str:
    minutes = max(0, min(int(minutes), 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _date_of(value) -> str | None:
    m = _DATE_RE.search(str(value or ""))
    return m.group(1) if m else None


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tokens(text: str) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9\s]", " ", str(text).lower()).split() if t and t not in _NOISE}


def _sort_key(ev: dict):
    m = _minutes(ev.get("time"))
    return (m if m is not None else 24 * 60, _ORDER.get(ev.get("type"), 4))


def _trip_dates(ni: dict, days) -> list[str]:
    try:
        start = date.fromisoformat(str(ni.get("start_date")))
        end = date.fromisoformat(str(ni.get("end_date")))
        n = (end - start).days + 1
        if 1 <= n <= 31:
            return [(start + timedelta(days=i)).isoformat() for i in range(n)]
    except (TypeError, ValueError):
        pass
    return [d["date"] for d in (days or []) if isinstance(d, dict) and d.get("date")]


# ── Resolve model picks against the real search results ──────────────────────

def _resolve_hotel(chosen, catalog: list[dict], gaps: list[str]) -> dict:
    chosen = chosen if isinstance(chosen, dict) else {}
    hid = chosen.get("hotel_id")
    name = str(chosen.get("name") or "").strip().lower()

    for h in catalog:
        if hid and h.get("hotel_id") == hid:
            return dict(h)
    for h in catalog:
        if name and str(h.get("name") or "").strip().lower() == name:
            return dict(h)

    if chosen.get("name"):
        gaps.append("The selected hotel could not be matched to a search result, so its details are unverified.")
    return dict(chosen)


def _direction(leg: dict, index: int) -> str:
    label = str(leg.get("leg") or leg.get("direction") or "").lower()
    if "return" in label:
        return "return"
    if "outbound" in label:
        return "outbound"
    return "outbound" if index == 0 else "return"


def _resolve_legs(chosen, flights: list[dict], trains: list[dict], gaps: list[str]) -> list[dict]:
    resolved = []
    for i, leg in enumerate(chosen or []):
        if not isinstance(leg, dict):
            continue
        out = dict(leg)
        rec = None
        if leg.get("flight_id"):
            rec = next((f for f in flights if f.get("flight_id") == leg["flight_id"]), None)
            out["mode"] = "flight"
        elif leg.get("train_id"):
            rec = next((t for t in trains if t.get("train_id") == leg["train_id"]), None)
            out["mode"] = "train"

        if rec:
            out.update(rec)    # price, times and codes come from the search result
        else:
            gaps.append("A selected transport option could not be matched to a search result, so its details are unverified.")
        out["leg"] = _direction(out if "direction" in out else leg, i)
        resolved.append(out)
    return resolved


# ── Rebuilt events ───────────────────────────────────────────────────────────

def _transport_event(leg: dict, dest_city: str, origin_city: str, dates: list[str]):
    dep = leg.get("departure_time")
    m = _minutes(dep)
    if m is None:
        return None, None

    direction = leg.get("leg", "outbound")
    day = _date_of(dep)
    if day not in dates:
        day = dates[0] if direction == "outbound" else dates[-1]

    word = "Train" if leg.get("mode") == "train" else "Flight"
    target = dest_city if direction == "outbound" else origin_city

    number = leg.get("flight_number") or leg.get("train_number") or ""
    carrier = leg.get("airline") or leg.get("train_name") or ""
    who = " ".join(p for p in (carrier, str(number)) if p)
    frm = leg.get("departure_airport_name") or leg.get("departure_station_name") or leg.get("departure_city") or ""
    to = leg.get("arrival_airport_name") or leg.get("arrival_station_name") or leg.get("arrival_city") or ""
    route = f"{frm} to {to}" if frm and to else ""
    details = ": ".join(p for p in (who, route) if p)

    return {"type": "transport", "time": _hhmm(m), "title": f"{word} to {target}", "details": details}, day


def _hotel_times(hotel, dates, arrive_day, arrive_min, depart_day, depart_min):
    ci = _minutes(hotel.get("check_in_time"))
    ci = 14 * 60 if ci is None else ci
    co = _minutes(hotel.get("check_out_time"))
    co = 11 * 60 if co is None else co

    ci_day = arrive_day if arrive_day in dates else dates[0]
    if arrive_min is not None and ci_day == arrive_day:
        ci = max(ci, arrive_min + _ARRIVAL_TO_HOTEL_MIN)

    co_day = dates[-1]
    if depart_min is not None and depart_day == co_day:
        co = min(co, max(depart_min - _CHECKOUT_BEFORE_DEPARTURE_MIN, 0))
    return ci_day, ci, co_day, co


# ── Pricing ──────────────────────────────────────────────────────────────────

def _price_index(activities: list[dict]) -> list[tuple[set[str], float]]:
    index = []
    for a in activities:
        if a.get("name"):
            index.append((_tokens(a["name"]), _num(a.get("est_price_inr"))))
    return index


def _match_price(title: str, index) -> float:
    t = _tokens(title)
    if not t:
        return 0.0
    best_score, best_price = 0.0, 0.0
    for toks, price in index:
        if not toks:
            continue
        score = len(t & toks) / len(t | toks)
        if score > best_score:
            best_score, best_price = score, price
    return best_price if best_score >= 0.5 else 0.0


# ── Node ─────────────────────────────────────────────────────────────────────

def validator_node(state: TripState) -> dict:
    trip_id = state.get("trip_id", "-")
    log = get_trip_logger(logger, trip_id)
    log.info("Validator: rebuilding facts, ordering events, recomputing costs")

    itinerary = state.get("itinerary")
    if not itinerary or not isinstance(itinerary, dict):
        log.warning("Validator: no valid itinerary in state; skipping.")
        return {}

    it = copy.deepcopy(itinerary)
    ni = state.get("normalized_input", {}) or {}
    num_travelers = max(int(ni.get("num_travelers") or 1), 1)
    gaps: list[str] = []

    dates = _trip_dates(ni, it.get("days"))
    if not dates:
        log.error("Validator: could not determine trip dates; leaving itinerary unchanged.")
        return {"status": "awaiting_review"}

    dest_city = str(ni.get("destination") or "").split(",")[0].strip() or "your destination"
    origin_city = str(ni.get("origin_city") or "").split(",")[0].strip() or "home"

    # 1. Hotel and transport: model picks, search results supply the facts
    hotel = _resolve_hotel(it.get("chosen_hotel"), state.get("hotels") or [], gaps)
    legs = _resolve_legs(it.get("chosen_transport"), state.get("flights") or [], state.get("trains") or [], gaps)
    it["chosen_hotel"] = hotel
    it["chosen_transport"] = legs

    outbound = next((l for l in legs if l.get("leg") == "outbound"), None)
    ret = next((l for l in legs if l.get("leg") == "return"), None)

    arrive_day = arrive_min = depart_day = depart_min = None
    if outbound:
        arrive_day = _date_of(outbound.get("arrival_time")) or dates[0]
        arrive_min = _minutes(outbound.get("arrival_time"))
    if ret:
        depart_day = _date_of(ret.get("departure_time")) or dates[-1]
        depart_min = _minutes(ret.get("departure_time"))

    # 2. Keep only activities, and only the possible ones. Everything else is rebuilt below.
    buckets: dict[str, list[dict]] = {d: [] for d in dates}
    seen_titles: set[frozenset] = set()
    dropped = 0

    for day in it.get("days") or []:
        d = day.get("date") if isinstance(day, dict) else None
        if d not in buckets:
            log.warning("Validator: dropping events dated %s (outside the trip)", d)
            continue
        for ev in day.get("events") or []:
            if not isinstance(ev, dict) or ev.get("type") != "activity":
                continue
            m = _minutes(ev.get("time"))
            if m is not None:
                if d == arrive_day and arrive_min is not None and m < arrive_min:
                    dropped += 1
                    continue
                if d == depart_day and depart_min is not None and m >= depart_min - _AIRPORT_BUFFER_MIN:
                    dropped += 1
                    continue
                ev["time"] = _hhmm(m)
            key = frozenset(_tokens(ev.get("title", "")))
            if key and key in seen_titles:
                dropped += 1
                continue
            seen_titles.add(key)
            buckets[d].append(ev)

    if dropped:
        log.info("Validator: dropped %d impossible or duplicate activities", dropped)

    # 3. Rebuild transport and hotel events from the resolved records
    for leg in legs:
        ev, d = _transport_event(leg, dest_city, origin_city, dates)
        if ev:
            buckets[d].append(ev)
        else:
            gaps.append("A transport leg has no usable departure time, so it was left off the schedule.")

    if hotel.get("name"):
        ci_day, ci_min, co_day, co_min = _hotel_times(hotel, dates, arrive_day, arrive_min, depart_day, depart_min)
        ci_note = f"Check-in from {hotel['check_in_time']}." if hotel.get("check_in_time") else ""
        co_note = f"Check-out by {hotel['check_out_time']}." if hotel.get("check_out_time") else ""
        buckets[ci_day].append({"type": "hotel_checkin", "time": _hhmm(ci_min),
                                "title": f"Check in at {hotel['name']}", "details": ci_note})
        buckets[co_day].append({"type": "hotel_checkout", "time": _hhmm(co_min),
                                "title": f"Check out of {hotel['name']}", "details": co_note})

    # 4. One day per trip date, events in order
    it["days"] = [{"date": d, "events": sorted(buckets[d], key=_sort_key)} for d in dates]

    # 5. Exact costs
    transport_cost = round(sum(_num(l.get("price")) for l in legs), 2)
    lodging_cost = round(_num(hotel.get("total_price")), 2)

    index = _price_index(state.get("activities") or [])
    activities_cost, unpriced = 0.0, 0
    for day in it["days"]:
        for ev in day["events"]:
            if ev.get("type") == "activity":
                price = _match_price(ev.get("title", ""), index)
                if price <= 0:
                    unpriced += 1
                activities_cost += price * num_travelers
    activities_cost = round(activities_cost, 2)

    total = round(transport_cost + lodging_cost + activities_cost, 2)
    it["total_cost"] = total
    it["cost_breakdown"] = {
        "transport": transport_cost,
        "lodging": lodging_cost,
        "activities": activities_cost,
        "total": total,
    }

    existing_gaps = it.get("data_gaps") or []
    it["data_gaps"] = list(dict.fromkeys([*existing_gaps, *gaps]))

    # 6. Keep the budget verdict consistent with the exact total
    update: dict = {"itinerary": it, "status": "awaiting_review"}
    ba = dict(state.get("budget_analysis") or {})
    budget = _num(ni.get("budget")) or _num(ba.get("budget"))
    if budget > 0:
        over = total > budget
        ba.update({
            "budget": budget,
            "estimated_total": total,
            "over_budget": over,
            "overage_amount": round(max(total - budget, 0), 2),
        })
        if not over:
            ba["suggestions"] = []
        update["budget_analysis"] = ba

    log.info(
        "Validator done: %d days, total=%.2f (transport=%.2f, lodging=%.2f, activities=%.2f, %d unpriced)",
        len(it["days"]), total, transport_cost, lodging_cost, activities_cost, unpriced,
    )
    return update